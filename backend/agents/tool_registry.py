from __future__ import annotations

import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.agents.tools.docx_tools import convert_docx_to_pdf, update_docx_resume_from_log
from backend.agents.tools.hitl_tool import ask_human_question
from backend.agents.tools.resume_section_tools import (
    tool_extract_resume_sections,
    tool_generate_modification_diff,
    tool_replace_resume_section,
)
from backend.agents.tools.workspace_tools import (
    get_safe_workspace_path,
    get_workspace_dir,
    tool_read_file,
    tool_write_file,
)
from backend.resume_advisor.verification import (
    FactVerificationResult,
    QualityReviewResult,
    review_suggestion_quality,
    verify_suggestion_facts,
)


JsonDict = dict[str, Any]
ToolHandler = Callable[["AgentToolContext", JsonDict], Any]


class AgentToolProfile(str, Enum):
    ARTIFACT_LEGACY = "artifact_legacy"
    RESUME_ADVISOR = "resume_advisor"


class AgentToolSideEffect(str, Enum):
    READ = "read"
    APPEND = "append"
    TRANSITION = "transition"


@dataclass(frozen=True)
class AgentToolContext:
    user_id: Any
    task_id: str
    resume_text: str = ""
    jd_text: str = ""
    is_co_pilot: bool = True
    human_context: str = ""
    profile: AgentToolProfile = AgentToolProfile.ARTIFACT_LEGACY
    advisor_module: Any | None = None
    user_confirmation: bool = False
    trace_id: str = ""


@dataclass(frozen=True)
class AgentToolSpec:
    name: str
    description: str
    parameters_schema: JsonDict
    handler: ToolHandler
    read_only: bool = False
    requires_confirmation: bool = False
    available_in_auto: bool = True
    available_in_copilot: bool = True
    timeout_seconds: int = 30
    result_preview_chars: int = 1200
    version: str = "1.0.0"
    side_effect: AgentToolSideEffect = AgentToolSideEffect.READ
    profiles: frozenset[AgentToolProfile] = frozenset({AgentToolProfile.ARTIFACT_LEGACY})
    input_model: type[BaseModel] | None = None
    output_model: type[BaseModel] | None = None
    retry_attempts: int = 0
    redact_log_payload: bool = True

    def to_responses_tool(self) -> JsonDict:
        parameters = self.parameters_schema
        if self.input_model is not None:
            parameters = self.input_model.model_json_schema()
            parameters.pop("title", None)
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": parameters,
        }


class AgentToolValidationError(ValueError):
    pass


def _tool_idempotency_key(name: str, arguments: JsonDict, ctx: AgentToolContext) -> str:
    payload = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(f"{ctx.user_id}:{ctx.task_id}:{name}:{payload}".encode("utf-8")).hexdigest()
    return f"tool-{digest[:24]}"


def _tool_trace_id(ctx: AgentToolContext) -> str:
    if ctx.trace_id:
        return ctx.trace_id
    if ctx.advisor_module is not None:
        try:
            run = ctx.advisor_module.repository.get_active_run(ctx.user_id, ctx.task_id)
            trace_id = str((run or {}).get("traceId") or "")
            if trace_id:
                return trace_id
        except Exception:
            pass
    return ""


def _tool_evidence_refs(arguments: JsonDict) -> list[str]:
    refs = arguments.get("evidence_block_ids") or arguments.get("block_ids") or []
    return [str(value) for value in refs if str(value)] if isinstance(refs, list) else []


def _tool_error_code(error: str) -> str:
    lowered = error.lower()
    if "confirmation" in lowered:
        return "user_confirmation_required"
    if "unknown" in lowered or "missing" in lowered or "validation" in lowered:
        return "invalid_arguments"
    if "timeout" in lowered:
        return "tool_timeout"
    return "tool_execution_failed"


class _NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _FactLookupResult(BaseModel):
    facts: list[dict[str, Any]]


class _VerifySuggestionFactsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_text: str = Field(min_length=1, max_length=12000)
    proposed_text: str = Field(min_length=1, max_length=12000)
    evidence_block_ids: list[str] = Field(min_length=1, max_length=20)


class _ReviewSuggestionQualityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_text: str = Field(min_length=1, max_length=12000)
    proposed_text: str = Field(min_length=1, max_length=12000)
    evidence_block_ids: list[str] = Field(min_length=1, max_length=20)
    fact_status: str = Field(pattern=r"^(supported|needs_user|unsupported)$")


class _BlockIdsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_ids: list[str] = Field(min_length=1, max_length=30)


class _EvidenceQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class _DraftSuggestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_block_id: str = Field(min_length=1, max_length=255)
    proposed_text: str = Field(min_length=1, max_length=12000)
    issue: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=1, max_length=3000)
    expected_impact: str = Field(min_length=1, max_length=1000)
    priority: Literal["high", "medium", "low"] = "medium"
    jd_requirement_ids: list[str] = Field(default_factory=list, max_length=20)


class _ReviseSuggestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestion_id: str = Field(min_length=1, max_length=255)
    proposed_text: str = Field(min_length=1, max_length=12000)
    rationale: str = Field(min_length=1, max_length=3000)


class _RecordFactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_key: str = Field(min_length=1, max_length=255)
    claim_value: str = Field(min_length=1, max_length=4000)
    status: Literal["confirmed", "denied", "uncertain"]
    scope: Literal["session", "resume", "global"] = "session"


class _SavePreferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_name: str = Field(min_length=1, max_length=255)
    preference_text: str = Field(min_length=1, max_length=2000)


class _RequestUserInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=3000)
    question_key: str = Field(min_length=1, max_length=255)
    why: str = Field(min_length=1, max_length=1000)
    target: str = Field(min_length=1, max_length=1000)
    evidence_types: list[str] = Field(default_factory=list, max_length=8)


def _schema(properties: JsonDict | None = None, required: list[str] | None = None) -> JsonDict:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }


def _short_preview(value: Any, limit: int) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    text = text.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _validate_args(schema: JsonDict, arguments: JsonDict) -> None:
    if not isinstance(arguments, dict):
        raise AgentToolValidationError("Tool arguments must be a JSON object.")
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    for key in required:
        if key not in arguments:
            raise AgentToolValidationError(f"Missing required tool argument: {key}")
    if schema.get("additionalProperties") is False:
        extra = sorted(set(arguments) - set(properties))
        if extra:
            raise AgentToolValidationError(f"Unknown tool argument(s): {', '.join(extra)}")
    for key, value in arguments.items():
        expected = (properties.get(key) or {}).get("type")
        if expected == "string" and not isinstance(value, str):
            raise AgentToolValidationError(f"Tool argument '{key}' must be a string.")
        if expected == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            raise AgentToolValidationError(f"Tool argument '{key}' must be an integer.")
        if expected == "boolean" and not isinstance(value, bool):
            raise AgentToolValidationError(f"Tool argument '{key}' must be a boolean.")


def _json_result(ok: bool, data: Any = None, error: str = "") -> JsonDict:
    return {
        "ok": ok,
        "data": data,
        "error": error,
    }


def _list_workspace_files(ctx: AgentToolContext, _arguments: JsonDict) -> JsonDict:
    workspace_dir = get_workspace_dir(ctx.user_id, ctx.task_id)
    files: list[str] = []
    for root, _dirs, names in os.walk(workspace_dir):
        for name in names:
            path = os.path.join(root, name)
            files.append(os.path.relpath(path, workspace_dir).replace("\\", "/"))
    return _json_result(True, {"files": sorted(files)})


def _read_workspace_file(ctx: AgentToolContext, arguments: JsonDict) -> JsonDict:
    filename = arguments["filename"]
    # Validate first so unsafe paths raise instead of being hidden in legacy text.
    get_safe_workspace_path(ctx.user_id, ctx.task_id, filename)
    content = tool_read_file(ctx.user_id, ctx.task_id, filename)
    return _json_result(True, {"filename": filename, "content": content})


def _write_workspace_file(ctx: AgentToolContext, arguments: JsonDict) -> JsonDict:
    filename = arguments["filename"]
    content = arguments["content"]
    path = get_safe_workspace_path(ctx.user_id, ctx.task_id, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    status = tool_write_file(ctx.user_id, ctx.task_id, filename, content)
    return _json_result(True, {"filename": filename, "status": status})


def _extract_resume_sections(ctx: AgentToolContext, arguments: JsonDict) -> JsonDict:
    resume_text = str(arguments.get("resume_text") or "").strip()
    if not resume_text:
        resume_text = ctx.resume_text.strip()
    if not resume_text:
        resume_text = tool_read_file(ctx.user_id, ctx.task_id, "original_resume.txt")
    sections_json = tool_extract_resume_sections(resume_text)
    sections = json.loads(sections_json)
    tool_write_file(ctx.user_id, ctx.task_id, "resume_sections.json", json.dumps(sections, ensure_ascii=False))
    return _json_result(True, {"sections": sections})


def _replace_resume_section(ctx: AgentToolContext, arguments: JsonDict) -> JsonDict:
    section_index = arguments["section_index"]
    section_name = str(arguments.get("section_name") or "").strip()
    new_content = arguments["new_content"]
    reason = str(arguments.get("reason") or "").strip() or "agentic tool edit"
    raw_sections = tool_read_file(ctx.user_id, ctx.task_id, "resume_sections.json")
    try:
        sections = json.loads(raw_sections)
        actual = str(sections[section_index].get("section_name") or "")
        original_content = str(sections[section_index].get("content") or "")
    except Exception as exc:
        raise AgentToolValidationError(f"Cannot read resume section before replacement: {exc}") from exc
    if section_name:
        if actual and actual != section_name:
            raise AgentToolValidationError(
                f"section_name does not match section_index: expected '{actual}', got '{section_name}'."
            )
    else:
        section_name = actual
    status = tool_replace_resume_section(ctx.user_id, ctx.task_id, section_index, new_content, reason)
    assembled = tool_read_file(ctx.user_id, ctx.task_id, "assembled_resume.txt")
    preview_updated = not assembled.startswith("错误：") and not assembled.startswith("读取文件失败：")
    return _json_result(True, {
        "status": status,
        "section_index": section_index,
        "section_name": section_name,
        "reason": reason,
        "original_preview": _short_preview(original_content, 360),
        "new_preview": _short_preview(new_content, 420),
        "stream_preview_file": "stream_preview.md" if preview_updated else "",
        "assembled_preview": _short_preview(assembled, 900) if preview_updated else "",
    })


def _generate_modification_diff(ctx: AgentToolContext, _arguments: JsonDict) -> JsonDict:
    diff = tool_generate_modification_diff(ctx.user_id, ctx.task_id)
    return _json_result(True, {"filename": "modification_diff.md", "content": diff})


def _ask_user_for_fact(ctx: AgentToolContext, arguments: JsonDict) -> JsonDict:
    question = arguments["question"]
    step_index = arguments.get("step_index")
    ask_human_question(ctx.task_id, ctx.user_id, question, step_index=step_index)
    return _json_result(True, {"status": "waiting_for_human"})


def _finalize_resume_artifacts(ctx: AgentToolContext, _arguments: JsonDict) -> JsonDict:
    mod_log_path = get_safe_workspace_path(ctx.user_id, ctx.task_id, "modification_log.json")
    if not os.path.exists(mod_log_path):
        return _json_result(False, {
            "docx_updated": False,
            "pdf_updated": False,
            "markdown_file": "",
        }, "No modification_log.json exists; the agent has not applied any section replacement.")

    try:
        with open(mod_log_path, "r", encoding="utf-8") as f:
            modification_log = json.load(f)
    except Exception as exc:
        return _json_result(False, {
            "docx_updated": False,
            "pdf_updated": False,
            "markdown_file": "",
        }, f"Cannot read modification_log.json: {exc}")
    if not isinstance(modification_log, list) or not modification_log:
        return _json_result(False, {
            "docx_updated": False,
            "pdf_updated": False,
            "markdown_file": "",
        }, "modification_log.json is empty; no resume edits were applied.")

    docx_updated = False
    docx_error = ""
    try:
        docx_updated = bool(update_docx_resume_from_log(ctx.user_id, ctx.task_id))
    except Exception as exc:
        docx_error = str(exc)
    if not docx_updated and not docx_error:
        guard_path = get_safe_workspace_path(ctx.user_id, ctx.task_id, "docx_template_guard.json")
        if os.path.exists(guard_path):
            try:
                with open(guard_path, "r", encoding="utf-8") as f:
                    guard_report = json.load(f)
                docx_error = str(guard_report.get("reason") or "")
                if not docx_error and guard_report.get("issues"):
                    docx_error = str(guard_report["issues"][0].get("message") or "")
            except Exception as exc:
                docx_error = f"Failed to read DOCX template guard report: {exc}"

    assembled_path = get_safe_workspace_path(ctx.user_id, ctx.task_id, "assembled_resume.txt")
    assembled = tool_read_file(ctx.user_id, ctx.task_id, "assembled_resume.txt") if os.path.exists(assembled_path) else ""
    if assembled:
        tool_write_file(ctx.user_id, ctx.task_id, "optimized_resume.md", assembled)
    try:
        tool_generate_modification_diff(ctx.user_id, ctx.task_id)
    except Exception:
        pass

    if not docx_updated:
        return _json_result(False, {
            "docx_updated": False,
            "pdf_updated": False,
            "markdown_file": "optimized_resume.md" if assembled else "",
            "docx_error": docx_error,
        }, docx_error or "High-fidelity DOCX was not generated.")

    docx_path = get_safe_workspace_path(ctx.user_id, ctx.task_id, "optimized_resume.docx")
    workspace_dir = os.path.dirname(docx_path)
    pdf_path = os.path.join(workspace_dir, "optimized_resume.pdf")
    pdf_updated = os.path.exists(pdf_path)
    pdf_error = ""
    if not pdf_updated:
        try:
            pdf_updated = bool(convert_docx_to_pdf(ctx.user_id, ctx.task_id, docx_path, workspace_dir))
        except Exception as exc:
            pdf_error = str(exc)
    if not pdf_updated and not pdf_error:
        pdf_error = "PDF conversion did not produce optimized_resume.pdf."

    return _json_result(True, {
        "docx_updated": docx_updated,
        "pdf_updated": pdf_updated,
        "docx_error": docx_error,
        "pdf_error": pdf_error,
        "markdown_file": "optimized_resume.md",
        "docx_file": "optimized_resume.docx",
        "pdf_file": "optimized_resume.pdf" if pdf_updated else "",
    })


def _advisor_module(ctx: AgentToolContext) -> Any:
    if ctx.advisor_module is None:
        raise AgentToolValidationError("resume_advisor tools require a ResumeAdvisorModule context.")
    return ctx.advisor_module


def _get_resume_snapshot(ctx: AgentToolContext, _arguments: JsonDict) -> JsonDict:
    return _json_result(True, _advisor_module(ctx).get_snapshot(user_id=ctx.user_id, session_id=ctx.task_id))


def _get_resume_outline(ctx: AgentToolContext, _arguments: JsonDict) -> JsonDict:
    return _json_result(True, _advisor_module(ctx).get_resume_view(user_id=ctx.user_id, session_id=ctx.task_id))


def _list_confirmed_facts(ctx: AgentToolContext, _arguments: JsonDict) -> JsonDict:
    facts = _advisor_module(ctx).repository.list_confirmed_facts(ctx.user_id, ctx.task_id)
    return _json_result(True, {"facts": facts})


def _advisor_evidence_texts(ctx: AgentToolContext, block_ids: list[str]) -> list[str]:
    view = _advisor_module(ctx).get_resume_view(user_id=ctx.user_id, session_id=ctx.task_id)
    blocks = {
        str(block.get("id") or ""): block
        for block in view.get("blocks", [])
        if isinstance(block, dict)
    }
    missing = [block_id for block_id in block_ids if block_id not in blocks]
    if missing:
        raise AgentToolValidationError(f"Unknown resume evidence block(s): {', '.join(missing)}")
    return [str(blocks[block_id].get("text") or "") for block_id in block_ids]


def _verify_suggestion_facts(ctx: AgentToolContext, arguments: JsonDict) -> JsonDict:
    evidence_texts = _advisor_evidence_texts(ctx, arguments["evidence_block_ids"])
    facts = _advisor_module(ctx).repository.list_confirmed_facts(ctx.user_id, ctx.task_id)
    result = verify_suggestion_facts(
        original_text=arguments["original_text"],
        proposed_text=arguments["proposed_text"],
        resume_evidence_texts=evidence_texts,
        confirmed_facts=facts,
        jd_text=ctx.jd_text,
    )
    return _json_result(True, result.model_dump())


def _review_suggestion_quality(ctx: AgentToolContext, arguments: JsonDict) -> JsonDict:
    _advisor_evidence_texts(ctx, arguments["evidence_block_ids"])
    result = review_suggestion_quality(
        original_text=arguments["original_text"],
        proposed_text=arguments["proposed_text"],
        evidence_block_ids=arguments["evidence_block_ids"],
        fact_status=arguments["fact_status"],
    )
    return _json_result(True, result.model_dump())


def _advisor_blocks(ctx: AgentToolContext) -> dict[str, dict[str, Any]]:
    view = _advisor_module(ctx).get_resume_view(user_id=ctx.user_id, session_id=ctx.task_id)
    return {
        str(block.get("id") or ""): block
        for block in view.get("blocks", [])
        if isinstance(block, dict) and str(block.get("id") or "")
    }


def _locate_resume_blocks(ctx: AgentToolContext, arguments: JsonDict) -> JsonDict:
    blocks = _advisor_blocks(ctx)
    missing = [block_id for block_id in arguments["block_ids"] if block_id not in blocks]
    if missing:
        raise AgentToolValidationError(f"Unknown resume block(s): {', '.join(missing)}")
    return _json_result(True, {"blocks": [blocks[block_id] for block_id in arguments["block_ids"]]})


def _get_analysis_context(ctx: AgentToolContext, _arguments: JsonDict) -> JsonDict:
    session = _advisor_module(ctx).repository.get_session(ctx.user_id, ctx.task_id)
    record_id = str((session or {}).get("analysisRecordId") or "")
    record = _advisor_module(ctx).repository.db.get_analysis_record(ctx.user_id, record_id) if record_id else None
    return _json_result(True, {"analysisRecordId": record_id or None, "analysis": record or {}})


def _jd_requirement_terms(jd_text: str) -> list[str]:
    stop_words = {"负责", "要求", "需要", "相关", "岗位", "经验", "能力", "优先", "我们", "你将", "以及", "进行"}
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9+#./-]{1,}|[\u4e00-\u9fff]{2,}", jd_text):
        normalized = token.strip()
        if normalized and normalized.casefold() not in {word.casefold() for word in stop_words} and normalized not in terms:
            terms.append(normalized)
    return terms[:20]


def _parse_jd_requirements(ctx: AgentToolContext, _arguments: JsonDict) -> JsonDict:
    requirements = [
        {"id": f"jd-{index + 1}-{hashlib.sha1(term.encode('utf-8')).hexdigest()[:8]}", "text": term}
        for index, term in enumerate(_jd_requirement_terms(ctx.jd_text))
    ]
    return _json_result(True, {"requirements": requirements})


def _retrieve_resume_evidence(ctx: AgentToolContext, arguments: JsonDict) -> JsonDict:
    query_terms = _jd_requirement_terms(arguments["requirement"])
    ranked: list[tuple[int, dict[str, Any]]] = []
    for block in _advisor_blocks(ctx).values():
        text = str(block.get("text") or "")
        score = sum(1 for term in query_terms if term.casefold() in text.casefold())
        if score:
            ranked.append((score, block))
    ranked.sort(key=lambda item: (-item[0], int(item[1].get("order") or 0)))
    return _json_result(True, {
        "evidence": [
            {"blockId": block["id"], "text": block.get("text") or "", "score": score}
            for score, block in ranked[:arguments["limit"]]
        ],
    })


def _list_resume_preferences(ctx: AgentToolContext, _arguments: JsonDict) -> JsonDict:
    from backend.memory.preference_db import PreferenceDB

    preferences = PreferenceDB(db=_advisor_module(ctx).repository.db).get_preferences(ctx.user_id, "resume_advisor")
    return _json_result(True, {"preferences": preferences})


def _analyze_gap_queue(ctx: AgentToolContext, _arguments: JsonDict) -> JsonDict:
    resume_text = "\n".join(str(block.get("text") or "") for block in _advisor_blocks(ctx).values())
    gaps = [
        {"requirement": term, "status": "needs_evidence", "reason": "简历快照中没有可检索的对应证据。"}
        for term in _jd_requirement_terms(ctx.jd_text)
        if term.casefold() not in resume_text.casefold()
    ]
    return _json_result(True, {"gaps": gaps[:12]})


def _suggestion_location(block: dict[str, Any]) -> dict[str, Any]:
    locator = block.get("locator") if isinstance(block.get("locator"), dict) else {}
    return {
        "blockId": block["id"],
        "sectionId": block.get("sectionId") or "generic_section",
        "sectionName": block.get("sectionName") or "其他",
        "itemLabel": block.get("itemLabel"),
        "sourceFormat": locator.get("sourceFormat") or "txt",
        "pageNumber": locator.get("pageNumber"),
        "locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文",
        "locatorConfidence": block.get("locatorConfidence") or "approximate",
        "bbox": locator.get("bbox"),
    }


def _active_run_id(ctx: AgentToolContext) -> str:
    run = _advisor_module(ctx).repository.get_active_run(ctx.user_id, ctx.task_id)
    return str((run or {}).get("id") or "tool-draft")


def _draft_resume_suggestion(ctx: AgentToolContext, arguments: JsonDict) -> JsonDict:
    blocks = _advisor_blocks(ctx)
    block = blocks.get(arguments["target_block_id"])
    if block is None:
        raise AgentToolValidationError("Unknown target resume block.")
    facts = _advisor_module(ctx).repository.list_confirmed_facts(ctx.user_id, ctx.task_id)
    verification = verify_suggestion_facts(
        original_text=str(block.get("text") or ""),
        proposed_text=arguments["proposed_text"],
        resume_evidence_texts=[str(block.get("text") or "")],
        confirmed_facts=facts,
        jd_text=ctx.jd_text,
    )
    quality = review_suggestion_quality(
        original_text=str(block.get("text") or ""),
        proposed_text=arguments["proposed_text"],
        evidence_block_ids=[str(block["id"])],
        fact_status=verification.status,
    )
    if not verification.is_supported or not quality.is_passed:
        return _json_result(False, {"verification": verification.model_dump(), "quality": quality.model_dump()}, "Suggestion did not pass fact or quality gates.")
    suggestion = _advisor_module(ctx).repository.create_suggestion(
        user_id=ctx.user_id,
        session_id=ctx.task_id,
        run_id=_active_run_id(ctx),
        data={
            "parentSuggestionId": arguments.get("_parent_suggestion_id"),
            "target": _suggestion_location(block),
            "originalTextHash": str(block.get("textHash") or ""),
            "priority": arguments["priority"],
            "issue": arguments["issue"],
            "originalText": str(block.get("text") or ""),
            "proposedText": arguments["proposed_text"],
            "copyText": arguments["proposed_text"],
            "rationale": arguments["rationale"],
            "expectedImpact": arguments["expected_impact"],
            "jdRequirementIds": arguments["jd_requirement_ids"],
            "resumeEvidenceBlockIds": [str(block["id"])],
            "userFactIds": [str(fact["id"]) for fact in facts if fact.get("status") == "confirmed"],
            "factStatus": verification.status,
            "factIssues": [],
            "status": "proposed",
        },
    )
    return _json_result(True, {"suggestion": suggestion})


def _revise_resume_suggestion(ctx: AgentToolContext, arguments: JsonDict) -> JsonDict:
    source = _advisor_module(ctx).repository.get_suggestion(ctx.user_id, arguments["suggestion_id"])
    if source is None:
        raise LookupError("未找到要修订的建议。")
    draft = _draft_resume_suggestion(
        ctx,
        {
            "target_block_id": source["target"]["blockId"],
            "proposed_text": arguments["proposed_text"],
            "issue": f"修订建议：{source['issue']}",
            "rationale": arguments["rationale"],
            "expected_impact": source["expectedImpact"],
            "priority": source["priority"],
            "jd_requirement_ids": source["jdRequirementIds"],
            "_parent_suggestion_id": source["id"],
        },
    )
    if not draft.get("ok"):
        return draft
    suggestion = draft["data"]["suggestion"]
    return _json_result(True, {"suggestion": suggestion, "parentSuggestionId": source["id"]})


def _record_user_fact(ctx: AgentToolContext, arguments: JsonDict) -> JsonDict:
    fact_id = _advisor_module(ctx).repository.record_fact(
        user_id=ctx.user_id,
        session_id=ctx.task_id,
        claim_key=arguments["claim_key"],
        claim_value=arguments["claim_value"],
        source_type="user_message",
        source_id="tool-record-user-fact",
        status=arguments["status"],
        scope=arguments["scope"],
    )
    return _json_result(True, {"factId": fact_id})


def _save_user_preference(ctx: AgentToolContext, arguments: JsonDict) -> JsonDict:
    from backend.memory.preference_db import PreferenceDB

    PreferenceDB(db=_advisor_module(ctx).repository.db).save_preference(
        user_id=ctx.user_id,
        section_name=arguments["section_name"],
        preference_text=arguments["preference_text"],
        source_task_id=ctx.task_id,
    )
    return _json_result(True, {"saved": True})


def _request_user_input(ctx: AgentToolContext, arguments: JsonDict) -> JsonDict:
    message = _advisor_module(ctx).repository.append_turn(
        user_id=ctx.user_id,
        session_id=ctx.task_id,
        role="assistant",
        content=arguments["question"],
        message_kind="question",
        run_id=_active_run_id(ctx),
        payload={
            "questionKey": arguments["question_key"],
            "why": arguments["why"],
            "target": arguments["target"],
            "evidenceTypes": arguments["evidence_types"],
        },
    )
    _advisor_module(ctx).repository.update_session(ctx.user_id, ctx.task_id, session_status="WAITING_FOR_USER")
    return _json_result(True, {"message": message, "status": "WAITING_FOR_USER"})


def _evaluate_session_completion(ctx: AgentToolContext, _arguments: JsonDict) -> JsonDict:
    suggestions = _advisor_module(ctx).repository.list_suggestions(ctx.user_id, ctx.task_id)
    unresolved = [item["id"] for item in suggestions if item.get("status") in {"proposed", "needs_revision"}]
    unsupported = [item["id"] for item in suggestions if item.get("factStatus") != "supported"]
    return _json_result(True, {
        "readyForConfirmation": not unresolved and not unsupported,
        "unresolvedSuggestionIds": unresolved,
        "unverifiedSuggestionIds": unsupported,
    })


class AgentToolRegistry:
    def __init__(self, tools: list[AgentToolSpec] | None = None):
        self._tools: dict[str, AgentToolSpec] = {}
        for tool in tools or default_agent_tools():
            self.register(tool)

    def register(self, tool: AgentToolSpec) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate agent tool: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> AgentToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown agent tool: {name}") from exc

    def list_tools(
        self,
        *,
        is_co_pilot: bool = True,
        profile: AgentToolProfile = AgentToolProfile.ARTIFACT_LEGACY,
    ) -> list[AgentToolSpec]:
        tools = []
        for tool in self._tools.values():
            if profile not in tool.profiles:
                continue
            if is_co_pilot and not tool.available_in_copilot:
                continue
            if not is_co_pilot and not tool.available_in_auto:
                continue
            tools.append(tool)
        return tools

    def responses_tools(
        self,
        *,
        is_co_pilot: bool = True,
        profile: AgentToolProfile = AgentToolProfile.ARTIFACT_LEGACY,
    ) -> list[JsonDict]:
        return [
            tool.to_responses_tool()
            for tool in self.list_tools(is_co_pilot=is_co_pilot, profile=profile)
        ]

    def execute(self, name: str, arguments: JsonDict, ctx: AgentToolContext) -> JsonDict:
        tool = self.get(name)
        started_at = time.perf_counter()
        idempotency_key = _tool_idempotency_key(name, arguments, ctx)
        attempts = 0
        try:
            if ctx.profile not in tool.profiles:
                raise PermissionError(f"Tool is not available in {ctx.profile} profile: {name}")
            if ctx.is_co_pilot and not tool.available_in_copilot:
                raise PermissionError(f"Tool is not available in copilot mode: {name}")
            if not ctx.is_co_pilot and not tool.available_in_auto:
                raise PermissionError(f"Tool is not available in auto mode: {name}")
            if tool.requires_confirmation and not ctx.user_confirmation:
                raise PermissionError(f"Tool requires explicit user confirmation: {name}")
            if tool.input_model is not None:
                arguments = tool.input_model.model_validate(arguments).model_dump()
            else:
                _validate_args(tool.parameters_schema, arguments)
            max_attempts = 1 + (tool.retry_attempts if tool.side_effect == AgentToolSideEffect.READ else 0)
            result = None
            error = ""
            ok = False
            for attempts in range(1, max_attempts + 1):
                attempt_started_at = time.perf_counter()
                try:
                    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"internpath-tool-{name}")
                    future = executor.submit(tool.handler, ctx, arguments)
                    try:
                        result = future.result(timeout=max(0.001, float(tool.timeout_seconds)))
                    except FutureTimeout as exc:
                        future.cancel()
                        raise TimeoutError(f"Tool exceeded its {tool.timeout_seconds}s timeout: {name}") from exc
                    finally:
                        # Never wait for an uncooperative blocking handler after its deadline.
                        executor.shutdown(wait=False, cancel_futures=True)
                    attempt_duration_ms = int((time.perf_counter() - attempt_started_at) * 1000)
                    if tool.output_model is not None and isinstance(result, dict) and result.get("ok") is not False:
                        data = result.get("data", result)
                        result = {
                            **result,
                            "data": tool.output_model.model_validate(data).model_dump(),
                        }
                    if isinstance(result, dict) and result.get("ok") is False:
                        error = str(result.get("error") or "")
                        if attempts < max_attempts:
                            continue
                        break
                    ok = True
                    error = ""
                    break
                except Exception as exc:
                    result = None
                    error = str(exc)
                    if attempts >= max_attempts:
                        break
        except (ValidationError, Exception) as exc:
            result = None
            ok = False
            error = str(exc)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        return {
            "tool_name": name,
            "ok": ok,
            "result": result,
            "error": error,
            "duration_ms": duration_ms,
            "preview": (
                "[advisor payload redacted]"
                if ctx.profile == AgentToolProfile.RESUME_ADVISOR and tool.redact_log_payload
                else _short_preview(result if ok else error, tool.result_preview_chars)
            ),
            "read_only": tool.read_only,
            "requires_confirmation": tool.requires_confirmation,
            "idempotency_key": idempotency_key,
            "attempts": attempts,
        }

    def execute_profiled(self, name: str, arguments: JsonDict, ctx: AgentToolContext) -> JsonDict:
        """Execute a profile-scoped tool using the structured advisor result contract."""
        result = self.execute(name, arguments, ctx)
        payload = result.get("result") if isinstance(result.get("result"), dict) else {}
        return {
            "ok": result["ok"],
            "data": payload.get("data") if result["ok"] else {},
            "error": None if result["ok"] else {
                "code": _tool_error_code(result["error"]),
                "message": result["error"],
                "retryable": self.get(name).side_effect == AgentToolSideEffect.READ,
            },
            "meta": {
                "tool": name,
                "version": self.get(name).version,
                "traceId": _tool_trace_id(ctx),
                "durationMs": result["duration_ms"],
                "attempts": result["attempts"],
                "sideEffect": self.get(name).side_effect,
                "evidenceRefs": _tool_evidence_refs(arguments),
                "idempotencyKey": result["idempotency_key"],
            },
        }


def default_agent_tools() -> list[AgentToolSpec]:
    string_schema = {"type": "string"}
    return [
        AgentToolSpec(
            name="list_workspace_files",
            description="List files in the current task workspace.",
            parameters_schema=_schema(),
            handler=_list_workspace_files,
            read_only=True,
        ),
        AgentToolSpec(
            name="read_workspace_file",
            description="Read a UTF-8 text file from the current task workspace.",
            parameters_schema=_schema({"filename": string_schema}, ["filename"]),
            handler=_read_workspace_file,
            read_only=True,
        ),
        AgentToolSpec(
            name="write_workspace_file",
            description="Write a UTF-8 text file inside the current task workspace.",
            parameters_schema=_schema({"filename": string_schema, "content": string_schema}, ["filename", "content"]),
            handler=_write_workspace_file,
        ),
        AgentToolSpec(
            name="extract_resume_sections",
            description="Extract resume sections and persist resume_sections.json for later patching.",
            parameters_schema=_schema({"resume_text": string_schema}),
            handler=_extract_resume_sections,
        ),
        AgentToolSpec(
            name="replace_resume_section",
            description="Replace one extracted resume section and append modification_log.json.",
            parameters_schema=_schema(
                {
                    "section_index": {"type": "integer"},
                    "section_name": string_schema,
                    "new_content": string_schema,
                    "reason": string_schema,
                },
                ["section_index", "new_content"],
            ),
            handler=_replace_resume_section,
        ),
        AgentToolSpec(
            name="generate_modification_diff",
            description="Generate modification_diff.md from modification_log.json.",
            parameters_schema=_schema(),
            handler=_generate_modification_diff,
            read_only=True,
        ),
        AgentToolSpec(
            name="ask_user_for_fact",
            description="Pause the task and ask the user for missing factual information.",
            parameters_schema=_schema(
                {
                    "question": string_schema,
                    "step_index": {"type": "integer"},
                },
                ["question"],
            ),
            handler=_ask_user_for_fact,
            available_in_auto=True,
            available_in_copilot=True,
            requires_confirmation=True,
        ),
        AgentToolSpec(
            name="finalize_resume_artifacts",
            description="Finalize markdown and try to update the original DOCX template without lossy fallback.",
            parameters_schema=_schema(),
            handler=_finalize_resume_artifacts,
            timeout_seconds=120,
        ),
        AgentToolSpec(
            name="get_resume_snapshot",
            description="Read the immutable resume snapshot bound to the current advisor session.",
            parameters_schema=_schema(),
            handler=_get_resume_snapshot,
            read_only=True,
            side_effect=AgentToolSideEffect.READ,
            profiles=frozenset({AgentToolProfile.RESUME_ADVISOR}),
            input_model=_NoArguments,
        ),
        AgentToolSpec(
            name="get_resume_outline",
            description="Read resume blocks, context, and locator confidence for the advisor session.",
            parameters_schema=_schema(),
            handler=_get_resume_outline,
            read_only=True,
            side_effect=AgentToolSideEffect.READ,
            profiles=frozenset({AgentToolProfile.RESUME_ADVISOR}),
            input_model=_NoArguments,
        ),
        AgentToolSpec(
            name="locate_resume_blocks",
            description="Return immutable resume-block locators, page data, and confidence for explicit block IDs.",
            parameters_schema=_schema(),
            handler=_locate_resume_blocks,
            read_only=True,
            side_effect=AgentToolSideEffect.READ,
            profiles=frozenset({AgentToolProfile.RESUME_ADVISOR}),
            input_model=_BlockIdsInput,
        ),
        AgentToolSpec(
            name="get_analysis_context",
            description="Read the analysis record bound to the advisor session, if one exists.",
            parameters_schema=_schema(),
            handler=_get_analysis_context,
            read_only=True,
            side_effect=AgentToolSideEffect.READ,
            profiles=frozenset({AgentToolProfile.RESUME_ADVISOR}),
            input_model=_NoArguments,
        ),
        AgentToolSpec(
            name="parse_jd_requirements",
            description="Parse the bound JD into stable requirement identifiers. These are job requirements, not candidate facts.",
            parameters_schema=_schema(),
            handler=_parse_jd_requirements,
            read_only=True,
            side_effect=AgentToolSideEffect.READ,
            profiles=frozenset({AgentToolProfile.RESUME_ADVISOR}),
            input_model=_NoArguments,
        ),
        AgentToolSpec(
            name="retrieve_resume_evidence",
            description="Retrieve immutable resume blocks relevant to one JD requirement without using JD as evidence.",
            parameters_schema=_schema(),
            handler=_retrieve_resume_evidence,
            read_only=True,
            side_effect=AgentToolSideEffect.READ,
            profiles=frozenset({AgentToolProfile.RESUME_ADVISOR}),
            input_model=_EvidenceQueryInput,
        ),
        AgentToolSpec(
            name="list_confirmed_facts",
            description="Read confirmed and denied candidate facts without treating JD text as evidence.",
            parameters_schema=_schema(),
            handler=_list_confirmed_facts,
            read_only=True,
            side_effect=AgentToolSideEffect.READ,
            profiles=frozenset({AgentToolProfile.RESUME_ADVISOR}),
            input_model=_NoArguments,
            output_model=_FactLookupResult,
        ),
        AgentToolSpec(
            name="list_resume_preferences",
            description="Read user preferences explicitly saved for resume-advisor writing style.",
            parameters_schema=_schema(),
            handler=_list_resume_preferences,
            read_only=True,
            side_effect=AgentToolSideEffect.READ,
            profiles=frozenset({AgentToolProfile.RESUME_ADVISOR}),
            input_model=_NoArguments,
        ),
        AgentToolSpec(
            name="analyze_gap_queue",
            description="List JD requirements that have no retrievable evidence in the immutable resume snapshot.",
            parameters_schema=_schema(),
            handler=_analyze_gap_queue,
            read_only=True,
            side_effect=AgentToolSideEffect.READ,
            profiles=frozenset({AgentToolProfile.RESUME_ADVISOR}),
            input_model=_NoArguments,
        ),
        AgentToolSpec(
            name="draft_resume_suggestion",
            description="Append one fact-verified, quality-checked suggestion tied to exactly one immutable resume block.",
            parameters_schema=_schema(),
            handler=_draft_resume_suggestion,
            side_effect=AgentToolSideEffect.APPEND,
            profiles=frozenset({AgentToolProfile.RESUME_ADVISOR}),
            input_model=_DraftSuggestionInput,
        ),
        AgentToolSpec(
            name="verify_suggestion_facts",
            description="Verify proposed claims against immutable resume blocks and confirmed facts. JD text is never candidate evidence.",
            parameters_schema=_schema(),
            handler=_verify_suggestion_facts,
            read_only=True,
            side_effect=AgentToolSideEffect.READ,
            profiles=frozenset({AgentToolProfile.RESUME_ADVISOR}),
            input_model=_VerifySuggestionFactsInput,
            output_model=FactVerificationResult,
        ),
        AgentToolSpec(
            name="review_suggestion_quality",
            description="Run the deterministic quality gate for a fact-verified, copyable suggestion.",
            parameters_schema=_schema(),
            handler=_review_suggestion_quality,
            read_only=True,
            side_effect=AgentToolSideEffect.READ,
            profiles=frozenset({AgentToolProfile.RESUME_ADVISOR}),
            input_model=_ReviewSuggestionQualityInput,
            output_model=QualityReviewResult,
        ),
        AgentToolSpec(
            name="revise_resume_suggestion",
            description="Append a new immutable child version after fact and quality gates; never overwrites history.",
            parameters_schema=_schema(),
            handler=_revise_resume_suggestion,
            side_effect=AgentToolSideEffect.APPEND,
            profiles=frozenset({AgentToolProfile.RESUME_ADVISOR}),
            input_model=_ReviseSuggestionInput,
        ),
        AgentToolSpec(
            name="record_user_fact",
            description="Append a user-confirmed or user-denied fact to the session ledger after explicit confirmation.",
            parameters_schema=_schema(),
            handler=_record_user_fact,
            requires_confirmation=True,
            side_effect=AgentToolSideEffect.APPEND,
            profiles=frozenset({AgentToolProfile.RESUME_ADVISOR}),
            input_model=_RecordFactInput,
        ),
        AgentToolSpec(
            name="save_user_preference",
            description="Persist a writing preference only after the user explicitly asks to remember it.",
            parameters_schema=_schema(),
            handler=_save_user_preference,
            requires_confirmation=True,
            side_effect=AgentToolSideEffect.APPEND,
            profiles=frozenset({AgentToolProfile.RESUME_ADVISOR}),
            input_model=_SavePreferenceInput,
        ),
        AgentToolSpec(
            name="request_user_input",
            description="Create one structured evidence question and pause the current advisor interaction.",
            parameters_schema=_schema(),
            handler=_request_user_input,
            side_effect=AgentToolSideEffect.TRANSITION,
            profiles=frozenset({AgentToolProfile.RESUME_ADVISOR}),
            input_model=_RequestUserInput,
        ),
        AgentToolSpec(
            name="evaluate_session_completion",
            description="Report whether only explicit user satisfaction may close the advisor session.",
            parameters_schema=_schema(),
            handler=_evaluate_session_completion,
            read_only=True,
            side_effect=AgentToolSideEffect.READ,
            profiles=frozenset({AgentToolProfile.RESUME_ADVISOR}),
            input_model=_NoArguments,
        ),
    ]


DEFAULT_AGENT_TOOL_REGISTRY = AgentToolRegistry()
