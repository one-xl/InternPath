from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from config import Config
from ai_service_client import AiServiceClient
from backend.resume_rag import SECTION_IMPORTANCE

from .verification import (
    HRCriticInvalidOutputError,
    HRCriticReviewError,
    QualityReviewResult,
    draft_resume_suggestion,
    decode_jd_requirements,
    review_rag_evidence,
    review_suggestion_quality,
    review_with_hr_critic,
    SuggestionDraft,
    verify_suggestion_facts,
)
from .tool_runtime import ResumeAdvisorToolRuntime
from .context import build_advisor_context_snapshot


_KEYWORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]{1,}|[\u4e00-\u9fff]{2,}")
_STOP_WORDS = {"负责", "要求", "需要", "相关", "岗位", "经验", "能力", "优先", "我们", "你将", "以及", "进行"}
_FOLLOW_UP_PREFIXES = ("为什么", "为何", "怎么", "如何", "能否", "可以", "解释", "这条", "这个")
_REVISION_HINTS = ("改短", "精简", "精炼", "更克制", "换个说法", "改写", "重写", "语气")
_EDITABLE_BLOCK_KINDS = {"bullet", "paragraph", "table_cell"}
_NON_EDITABLE_SECTION_IDS = {"contact", "objective"}
_AUTO_REWRITE_SECTION_IDS = {"project_experience", "work_experience", "research", "skills", "coursework"}
_ADVISOR_SECTION_BONUSES = {
    "project_experience": 0.40,
    "work_experience": 0.34,
    "research": 0.28,
    "coursework": 0.24,
    "skills": 0.18,
    "education": 0.12,
    "self_introduction": 0.10,
    "generic_section": -0.36,
}
_PERSONAL_FIELD_RE = re.compile(
    r"(?:姓名|性别|年龄|生日|出生(?:日期|年月)?|电话|手机|邮箱|邮件|地址|现居|籍贯|微信|身份证|"
    r"name|gender|age|birth(?:day| date)?|phone|mobile|email|address)\s*[:：]",
    flags=re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)")
_DATE_OF_BIRTH_RE = re.compile(r"(?:19|20)\d{2}[./-年]\d{1,2}[./-月]\d{1,2}日?")
_NAME_LIKE_RE = re.compile(r"^[\u4e00-\u9fff]{2,4}$")
_GENERIC_REQUIREMENTS = {
    "负责", "要求", "需要", "相关", "岗位", "经验", "能力", "优先", "我们", "你将", "以及", "进行",
    "熟悉", "掌握", "具备", "良好", "优秀", "开发", "实习", "本科", "学历", "专业", "工作", "团队",
    "实现", "支持", "推动", "参与", "完成", "进行", "负责", "相关经验", "能力要求",
}


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _elapsed_ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


def _public_error_summary(exc: Exception) -> dict[str, Any]:
    return {"errorType": exc.__class__.__name__}


class _ModelUnavailableError(RuntimeError):
    """Raised when an advisor turn needs a configured model but none is available."""


def _verify_with_holder(
    holder: dict[str, Any],
    *,
    original_text: str,
    proposed_text: str,
    resume_evidence_texts: list[str],
    confirmed_facts: list[dict[str, Any]],
    jd_text: str,
) -> dict[str, Any]:
    value = verify_suggestion_facts(
        original_text=original_text,
        proposed_text=proposed_text,
        resume_evidence_texts=resume_evidence_texts,
        confirmed_facts=confirmed_facts,
        jd_text=jd_text,
    )
    holder["value"] = value
    return {"status": value.status, "issueCount": len(value.fact_issues)}


def _review_with_holder(holder: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    try:
        value = review_with_hr_critic(**kwargs)
        if value.reviewer != "hr_critic" or not value.hr_review:
            raise HRCriticInvalidOutputError("HRCritic did not return an independent structured decision")
    except Exception as exc:
        holder["error"] = exc
        raise
    holder["value"] = value
    return {
        "isPassed": value.is_passed,
        "score": value.score,
        "issueCount": len(value.issues),
        "reviewer": value.reviewer,
    }


def _review_rag_evidence_with_holder(holder: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    try:
        value = review_rag_evidence(**kwargs)
    except Exception as exc:
        holder["error"] = exc
        raise
    holder["value"] = value
    return {
        "selectedChunkIds": value.selected_chunk_ids,
        "uncoveredRequirementCount": len(value.uncovered_requirements),
    }


def _jd_requirements(jd_text: str) -> list[str]:
    values: list[str] = []
    for token in _KEYWORD_RE.findall(jd_text):
        normalized = token.strip()
        if (
            len(_normalized_match_text(normalized)) < 2
            or normalized in _STOP_WORDS
            or normalized.lower() in {item.lower() for item in _STOP_WORDS}
            or _normalized_match_text(normalized) in _GENERIC_REQUIREMENTS
        ):
            continue
        if normalized not in values:
            values.append(normalized)
    return values[:12]


def _normalized_match_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _effective_section_id(block: dict[str, Any]) -> str:
    section_id = str(block.get("sectionId") or "generic_section").strip() or "generic_section"
    section_name = str(block.get("sectionName") or "")
    if "求职意向" in section_name or "职业目标" in section_name or "意向岗位" in section_name:
        return "objective"
    if "课程" in section_name:
        return "coursework"
    return section_id


def _is_personal_identity_block(block: dict[str, Any]) -> bool:
    section_id = _effective_section_id(block)
    section_name = str(block.get("sectionName") or "")
    text = str(block.get("text") or "").strip()
    if section_id in _NON_EDITABLE_SECTION_IDS:
        return True
    if any(label in section_name for label in ("基本信息", "个人信息", "联系方式", "求职意向", "职业目标")):
        return True
    if _PERSONAL_FIELD_RE.search(text) or _EMAIL_RE.search(text) or _PHONE_RE.search(text) or _DATE_OF_BIRTH_RE.search(text):
        return True
    # DOCX textboxes can be read after an unrelated heading. A bare short Chinese name
    # under a misclassified self-introduction block must still never become rewrite input.
    return section_id in {"self_introduction", "generic_section"} and bool(_NAME_LIKE_RE.fullmatch(text))


def _is_editable_candidate(block: dict[str, Any]) -> bool:
    return (
        str(block.get("kind") or "") in _EDITABLE_BLOCK_KINDS
        and bool(str(block.get("text") or "").strip())
        and not _is_personal_identity_block(block)
    )


def _is_automatic_rewrite_candidate(block: dict[str, Any]) -> bool:
    """Keep automatic revisions inside high-value resume evidence only."""
    return _is_editable_candidate(block) and _effective_section_id(block) in _AUTO_REWRITE_SECTION_IDS


def _section_priority(block: dict[str, Any]) -> int:
    section_id = _effective_section_id(block)
    baseline = float(SECTION_IMPORTANCE.get(section_id, SECTION_IMPORTANCE.get("generic_section", 0.0)))
    return int(round((baseline + _ADVISOR_SECTION_BONUSES.get(section_id, 0.0)) * 100))


def _requirement_matches_text(requirement: str, text: Any) -> bool:
    normalized_requirement = _normalized_match_text(requirement)
    return bool(normalized_requirement) and normalized_requirement in _normalized_match_text(text)


def _block_requirement_matches(block: dict[str, Any], requirements: list[str]) -> int:
    text = str(block.get("text") or "")
    return sum(1 for requirement in requirements if _requirement_matches_text(requirement, text))


def _is_actionable_requirement(requirement: str) -> bool:
    normalized = _normalized_match_text(requirement)
    return len(normalized) >= 2 and normalized not in _GENERIC_REQUIREMENTS


class ResumeAdvisorGraph:
    """One-run graph for the evidence-first advisor mode.

    The graph deliberately stops after one question or one suggestion. It does not write the
    original file and it never treats JD text as candidate evidence.
    """

    def __init__(
        self,
        repository: Any,
        *,
        model_client: Any | None = None,
        model_id: str = "",
        model_provider: Any | None = None,
        ai_service_client: AiServiceClient | None = None,
    ):
        self.repository = repository
        self.model_client = model_client
        self.model_id = model_id
        self.model_provider = model_provider
        self.ai_service_client = ai_service_client or AiServiceClient(timeout=8.0)
        self.tool_runtime = ResumeAdvisorToolRuntime()

    def _list_session_facts(self, *, user_id: Any, session_id: str) -> list[dict[str, Any]]:
        list_session_facts = getattr(self.repository, "list_session_facts", None)
        if callable(list_session_facts):
            facts = list_session_facts(user_id, session_id)
        else:
            # Older repository fakes only expose the original confirmed-facts method.
            facts = self.repository.list_confirmed_facts(user_id, session_id)
        return [fact for fact in facts if isinstance(fact, dict)]

    @staticmethod
    def _rank_candidate_blocks(blocks: list[dict[str, Any]], requirements: list[str]) -> list[dict[str, Any]]:
        return sorted(
            blocks,
            key=lambda block: (
                -_block_requirement_matches(block, requirements),
                -_section_priority(block),
                int(block.get("order") or 0),
            ),
        )

    @staticmethod
    def _supporting_evidence_blocks(
        *,
        current_block: dict[str, Any],
        all_blocks: list[dict[str, Any]],
        requirements: list[str],
    ) -> list[dict[str, Any]]:
        """Keep the target first and attach a few JD-relevant, non-PII resume facts."""
        selected = [current_block]
        matches = [
            block
            for block in all_blocks
            if block.get("id") != current_block.get("id")
            and _is_editable_candidate(block)
            and _block_requirement_matches(block, requirements)
        ]
        for block in ResumeAdvisorGraph._rank_candidate_blocks(matches, requirements):
            if len(selected) >= 4:
                break
            selected.append(block)
        return selected

    @staticmethod
    def _resume_chunks_for_retrieval(
        resume_view: dict[str, Any],
        blocks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Use canonical parsed chunks and retain a block-backed fallback for old snapshots."""
        chunks = [chunk for chunk in resume_view.get("chunks", []) if isinstance(chunk, dict) and str(chunk.get("content") or "").strip()]
        if chunks:
            return chunks
        return [
            {
                "id": f"evidence-{block.get('id')}",
                "content": str(block.get("text") or ""),
                "section": str(block.get("sectionName") or "其他"),
                "sourceBlockIds": [str(block.get("id") or "")],
            }
            for block in blocks
            if str(block.get("text") or "").strip()
        ]

    @staticmethod
    def _rag_evidence_block_ids(chunks: list[dict[str, Any]]) -> list[str]:
        ids: list[str] = []
        for chunk in chunks:
            metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            source_block_ids = chunk.get("sourceBlockIds") or metadata.get("sourceBlockIds") or []
            for block_id in source_block_ids:
                value = str(block_id or "")
                if value and value not in ids:
                    ids.append(value)
        return ids

    @staticmethod
    def _project_selection_from_messages(messages: list[dict[str, Any]]) -> tuple[str, list[int]]:
        for message in messages:
            payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
            scope = str(payload.get("projectKnowledgeScope") or "none")
            if scope not in {"all", "selected"}:
                continue
            document_ids: list[int] = []
            for value in payload.get("projectKnowledgeDocumentIds") or []:
                try:
                    document_ids.append(int(value))
                except (TypeError, ValueError):
                    continue
            return scope, list(dict.fromkeys(document_ids))
        return "none", []

    @staticmethod
    def _project_chunks_for_retrieval(
        *,
        user_id: Any,
        scope: str,
        document_ids: list[int],
    ) -> list[dict[str, Any]]:
        if scope not in {"all", "selected"}:
            return []
        try:
            from service import CareerPathAIService

            documents = CareerPathAIService().get_project_knowledge_chunks_for_analysis(
                user_id,
                document_ids,
                scope=scope,
            )
        except Exception:
            return []

        chunks: list[dict[str, Any]] = []
        for document in documents:
            metadata = dict(document.get("metadata") or {}) if isinstance(document.get("metadata"), dict) else {}
            document_id = str(document.get("documentId") or "")
            chunk_id = str(document.get("chunkId") or "")
            content = str(document.get("content") or "").strip()
            if not document_id or not chunk_id or not content:
                continue
            metadata.update({"sourceType": "project", "documentId": document_id})
            chunks.append(
                {
                    "id": f"project:{document_id}:{chunk_id}",
                    "documentId": document_id,
                    "chunkId": chunk_id,
                    "content": content,
                    "section": document.get("sectionTitle") or metadata.get("documentTitle") or "项目知识库",
                    "sectionId": document.get("sectionId"),
                    "sectionType": document.get("sectionType") or "project_experience",
                    "sectionTitle": document.get("sectionTitle") or metadata.get("documentTitle") or "项目知识库",
                    "hierarchy": document.get("hierarchy") or [],
                    "semanticType": document.get("semanticType") or "experience",
                    "importance": document.get("importance") or 0.9,
                    "keywords": document.get("keywords") or [],
                    "embeddingText": document.get("embeddingText") or content,
                    "embedding": document.get("embedding"),
                    "sourceType": "project",
                    "sourceBlockIds": [],
                    "metadata": metadata,
                }
            )
        return chunks

    @staticmethod
    def _ai_service_documents(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Map parsed resume chunks to the AI service contract without model credentials."""
        documents: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            content = str(chunk.get("content") or chunk.get("text") or "").strip()
            if not content:
                continue
            metadata = dict(chunk.get("metadata") or {}) if isinstance(chunk.get("metadata"), dict) else {}
            source_block_ids = chunk.get("sourceBlockIds") or metadata.get("sourceBlockIds") or []
            metadata["sourceBlockIds"] = list(dict.fromkeys(
                str(value) for value in source_block_ids if str(value)
            ))
            if chunk.get("blockIds") and "blockIds" not in metadata:
                metadata["blockIds"] = list(chunk.get("blockIds") or [])
            embedding = chunk.get("embedding") or metadata.get("embedding")
            documents.append(
                {
                    "documentId": str(
                        chunk.get("documentId")
                        or chunk.get("resumeFileId")
                        or metadata.get("documentId")
                        or "resume"
                    ),
                    "chunkId": str(chunk.get("chunkId") or chunk.get("id") or f"resume-{index}"),
                    "content": content,
                    "sectionId": chunk.get("sectionId") or metadata.get("sectionId"),
                    "sectionType": chunk.get("sectionType") or metadata.get("sectionType"),
                    "sectionTitle": chunk.get("sectionTitle") or chunk.get("section") or metadata.get("sectionTitle"),
                    "hierarchy": chunk.get("hierarchy") or metadata.get("hierarchy") or [],
                    "semanticType": chunk.get("semanticType") or metadata.get("semanticType"),
                    "importance": chunk.get("importance") if chunk.get("importance") is not None else metadata.get("importance"),
                    "keywords": chunk.get("keywords") or metadata.get("keywords") or [],
                    "embeddingText": chunk.get("embeddingText") or metadata.get("embeddingText") or content,
                    "embedding": embedding if isinstance(embedding, list) else None,
                    "metadata": metadata,
                }
            )
        return documents

    @staticmethod
    def _advisor_chunks_from_ai_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Restore the local Advisor evidence shape after an AI-service retrieval."""
        chunks: list[dict[str, Any]] = []
        for result in results:
            if not isinstance(result, dict):
                continue
            content = str(result.get("text") or result.get("content") or "").strip()
            chunk_id = str(result.get("chunkId") or result.get("id") or "")
            if not content or not chunk_id:
                continue
            metadata = dict(result.get("metadata") or {}) if isinstance(result.get("metadata"), dict) else {}
            source_block_ids = result.get("sourceBlockIds") or metadata.get("sourceBlockIds") or []
            metadata["sourceBlockIds"] = list(dict.fromkeys(
                str(value) for value in source_block_ids if str(value)
            ))
            chunks.append(
                {
                    **result,
                    "id": chunk_id,
                    "content": content,
                    "section": result.get("sectionTitle") or result.get("section") or "",
                    "sourceBlockIds": metadata["sourceBlockIds"],
                    "metadata": metadata,
                }
            )
        return chunks

    @staticmethod
    def _supporting_user_fact_ids(facts: list[dict[str, Any]], proposed_text: str) -> list[str]:
        proposed = _normalized_match_text(proposed_text)
        if not proposed:
            return []
        fact_ids: list[str] = []
        for fact in facts:
            if fact.get("status") != "confirmed":
                continue
            fact_id = str(fact.get("id") or "")
            if not fact_id:
                continue
            claim_key = str(fact.get("claimKey") or "")
            claim_value = str(fact.get("claimValue") or "")
            if claim_key.startswith("requirement:"):
                if _requirement_matches_text(claim_key.removeprefix("requirement:"), proposed):
                    fact_ids.append(fact_id)
                continue
            terms = [term for term in _KEYWORD_RE.findall(f"{claim_key} {claim_value}") if len(term) >= 2]
            if any(_requirement_matches_text(term, proposed) for term in terms):
                fact_ids.append(fact_id)
        return list(dict.fromkeys(fact_ids))

    @staticmethod
    def _resume_scan_key(session: dict[str, Any], resume_view: dict[str, Any]) -> str:
        content_hash = str(
            resume_view.get("contentHash")
            or session.get("resumeContentHash")
            or session.get("resumeId")
            or "resume"
        )
        return f"resume-scan:{content_hash}"

    @staticmethod
    def _has_resume_scan(messages: list[dict[str, Any]], scan_key: str) -> bool:
        return any(
            message.get("messageKind") == "resume_scan"
            and isinstance(message.get("payload"), dict)
            and message["payload"].get("scanKey") == scan_key
            for message in messages
        )

    @staticmethod
    def _resume_scan_payload(
        *,
        resume_view: dict[str, Any],
        blocks: list[dict[str, Any]],
        requirements: list[str],
        scan_key: str,
    ) -> dict[str, Any]:
        """Summarise the canonical resume and JD coverage without copying resume text."""
        cleaning = resume_view.get("cleaning") if isinstance(resume_view.get("cleaning"), dict) else {}
        resume_text = "\n".join(str(block.get("text") or "") for block in blocks)
        matched_requirements = [
            requirement
            for requirement in requirements
            if _requirement_matches_text(requirement, resume_text)
        ]
        missing_requirements = [
            requirement
            for requirement in requirements
            if requirement not in matched_requirements and _is_actionable_requirement(requirement)
        ]
        sections: dict[str, int] = {}
        for block in blocks:
            section_name = str(block.get("sectionName") or "其他")
            sections[section_name] = sections.get(section_name, 0) + 1
        return {
            "scanKey": scan_key,
            "status": "completed",
            "contentHash": str(resume_view.get("contentHash") or cleaning.get("contentHash") or ""),
            "cleaning": {
                "schemaVersion": str(cleaning.get("schemaVersion") or "resume-cleaning-v1"),
                "sourceFormat": str(cleaning.get("sourceFormat") or ""),
                "extractedRecordCount": int(cleaning.get("extractedRecordCount") or len(blocks)),
                "canonicalRecordCount": int(cleaning.get("canonicalRecordCount") or len(blocks)),
                "duplicateSourceCount": int(cleaning.get("duplicateSourceCount") or 0),
                "blockCount": int(cleaning.get("blockCount") or len(blocks)),
                "editableBlockCount": int(cleaning.get("editableBlockCount") or sum(1 for block in blocks if _is_editable_candidate(block))),
                "sectionCount": int(cleaning.get("sectionCount") or len(sections)),
                "lowConfidenceLocationCount": int(cleaning.get("lowConfidenceLocationCount") or sum(1 for block in blocks if block.get("locatorConfidence") == "approximate")),
                "warnings": [str(item) for item in cleaning.get("warnings", []) if str(item).strip()],
            },
            "sections": [
                {"name": name, "blockCount": count}
                for name, count in sorted(sections.items(), key=lambda item: (-item[1], item[0]))
            ],
            "jdCoverage": {
                "requirementCount": len(requirements),
                "matchedRequirements": matched_requirements,
                "missingRequirements": missing_requirements,
            },
        }

    def _append_resume_scan(
        self,
        *,
        user_id: Any,
        session_id: str,
        run_id: str,
        session: dict[str, Any],
        resume_view: dict[str, Any],
        blocks: list[dict[str, Any]],
        requirements: list[str],
        messages: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        scan_key = self._resume_scan_key(session, resume_view)
        if self._has_resume_scan(messages, scan_key):
            return None
        payload = self._resume_scan_payload(
            resume_view=resume_view,
            blocks=blocks,
            requirements=requirements,
            scan_key=scan_key,
        )
        message = self.repository.append_turn(
            user_id=user_id,
            session_id=session_id,
            role="assistant",
            content="",
            message_kind="resume_scan",
            run_id=run_id,
            payload=payload,
        )
        self.repository.append_event(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            message_id=message["id"],
            event_type="resume_scan",
            payload={
                "blockCount": payload["cleaning"]["blockCount"],
                "requirementCount": payload["jdCoverage"]["requirementCount"],
            },
        )
        return message

    def _draft_suggestion(
        self,
        text: str,
        *,
        section_name: str,
        jd_requirements: list[str],
        model_client: Any | None,
        model_id: str,
        revision_feedback: str = "",
        context_snapshot: str = "",
        user_id: Any = "default",
        on_delta: Callable[[str], None] | None = None,
        on_cache_event: Callable[[str, bool], None] | None = None,
        on_provider_usage: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> SuggestionDraft:
        if model_client is None or not str(model_id).strip():
            raise _ModelUnavailableError("resume advisor model is not configured")
        draft = draft_resume_suggestion(
            original_text=text,
            section_name=section_name,
            jd_requirements=jd_requirements,
            model_client=model_client,
            model_id=model_id,
            revision_feedback=revision_feedback,
            context_snapshot=context_snapshot,
            user_id=user_id,
            on_delta=on_delta,
            on_cache_event=on_cache_event,
            on_provider_usage=on_provider_usage,
        )
        if draft.outcome == "revision" and not str(draft.proposed_text or "").strip():
            raise RuntimeError("resume advisor model returned an empty suggestion")
        return draft

    def _request_evidence_clarification(
        self,
        *,
        user_id: Any,
        location: str,
        original_text: str,
        proposed_text: str,
        fact_issues: list[Any],
        retrieved_evidence: list[str],
        model_client: Any | None,
        model_id: str,
    ) -> tuple[str | None, str, Exception | None]:
        """Delegate user-facing fact questions to ResumeCopywriter, never to a rule script."""
        if model_client is None or not str(model_id).strip():
            return None, "unavailable", None
        try:
            from backend.agents.resume_copywriter import ResumeCopywriter
            from .verification import _run_async

            question = _run_async(
                ResumeCopywriter(model=model_id, openai_client=model_client).request_advisor_evidence(
                    location=location,
                    original_content=original_text,
                    proposed_content=proposed_text,
                    unsupported_claims=[str(getattr(issue, "claim", "") or "") for issue in fact_issues],
                    retrieved_evidence=retrieved_evidence,
                    user_id=str(user_id),
                )
            )
        except Exception as exc:
            return None, "failed", exc
        content = str(question or "").strip()
        if not content:
            return None, "failed", RuntimeError("ResumeCopywriter returned an empty evidence clarification")
        return content, "ok", None

    def _get_run_snapshot(self, *, user_id: Any, run_id: str) -> dict[str, Any]:
        get_run = getattr(self.repository, "get_run", None)
        if not callable(get_run):
            return {}
        try:
            value = get_run(user_id=user_id, run_id=run_id)
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    def _merge_run_telemetry(self, *, user_id: Any, run_id: str, telemetry: dict[str, Any]) -> None:
        merge = getattr(self.repository, "merge_run_telemetry", None)
        if not callable(merge):
            return
        try:
            merge(user_id=user_id, run_id=run_id, telemetry=telemetry)
        except Exception:
            pass

    def _is_cancelled(self, *, user_id: Any, run_id: str) -> bool:
        checker = getattr(self.repository, "is_run_cancelled", None)
        if not callable(checker):
            return False
        return bool(checker(user_id=user_id, run_id=run_id))

    def _cancelled_result(self, *, user_id: Any, session_id: str, run_id: str) -> dict[str, Any]:
        run = self._get_run_snapshot(user_id=user_id, run_id=run_id)
        if str(run.get("status") or "") != "CANCELLED":
            self.repository.update_run(user_id=user_id, run_id=run_id, status="CANCELLED")
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                event_type="run_cancelled",
                payload={"stage": "run_control"},
            )
        return {"status": "CANCELLED"}

    def _pause_for_model_issue(
        self,
        *,
        user_id: Any,
        session_id: str,
        run_id: str,
        stage: str,
        model_status: str,
        error: Exception | None = None,
        target: dict[str, Any] | None = None,
        reply_to_message_id: Any = None,
        suggestion_id: Any = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "mode": stage,
            "modelStatus": model_status,
            "errorCode": f"resume_advisor_{stage}_{model_status}",
        }
        if target:
            payload["target"] = target
        if reply_to_message_id is not None:
            payload["replyToMessageId"] = reply_to_message_id
        if suggestion_id is not None:
            payload["suggestionId"] = suggestion_id
        message = self.repository.append_turn(
            user_id=user_id,
            session_id=session_id,
            role="assistant",
            content="",
            message_kind="error",
            run_id=run_id,
            payload=payload,
        )
        event_payload: dict[str, Any] = {
            "stage": stage,
            "modelStatus": model_status,
        }
        if error is not None:
            event_payload.update(_public_error_summary(error))
        self.repository.update_session(
            user_id,
            session_id,
            session_status="WAITING_FOR_USER",
            active_run_id=run_id,
        )
        self.repository.append_event(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            message_id=message["id"],
            event_type="model_failure",
            payload=event_payload,
        )
        self.repository.update_run(user_id=user_id, run_id=run_id, status="PAUSED")
        return {"status": "WAITING_FOR_USER", "message": message}

    def _pause_for_quality_rejection(
        self,
        *,
        user_id: Any,
        session_id: str,
        run_id: str,
        quality: QualityReviewResult,
        target: dict[str, Any],
        issue: str,
    ) -> dict[str, Any]:
        """Pause without releasing a suggestion when a safety or HR gate rejects it."""
        hr_review = quality.hr_review if isinstance(quality.hr_review, dict) else {}
        agent_feedback = str(hr_review.get("critique") or "").strip() if quality.reviewer == "hr_critic" else ""
        message = self.repository.append_turn(
            user_id=user_id,
            session_id=session_id,
            role="assistant",
            content=agent_feedback,
            message_kind="error",
            run_id=run_id,
            payload={
                "errorCode": "quality_gate_failed",
                "qualityStatus": "rejected",
                "quality": quality.model_dump(),
                "target": target,
                "issue": issue,
            },
        )
        self.repository.update_session(
            user_id,
            session_id,
            session_status="WAITING_FOR_USER",
            active_run_id=run_id,
        )
        self.repository.append_event(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            message_id=message["id"],
            event_type="message",
            payload={
                "messageKind": "error",
                "qualityPassed": False,
                "reviewer": quality.reviewer,
            },
        )
        self.repository.update_run(user_id=user_id, run_id=run_id, status="PAUSED")
        return {"status": "WAITING_FOR_USER", "message": message}

    def run(self, *, user_id: Any, session_id: str, run_id: str) -> dict[str, Any]:
        session = self.repository.get_session(user_id, session_id)
        if not session:
            raise LookupError("未找到简历优化会话。")

        if self._is_cancelled(user_id=user_id, run_id=run_id):
            return self._cancelled_result(user_id=user_id, session_id=session_id, run_id=run_id)

        self.repository.update_run(user_id=user_id, run_id=run_id, status="RUNNING")
        run_snapshot = self._get_run_snapshot(user_id=user_id, run_id=run_id)
        run_created_at = _parse_timestamp(run_snapshot.get("createdAt"))
        run_started_at = _parse_timestamp(run_snapshot.get("startedAt"))
        queue_ms = _elapsed_ms(run_created_at, run_started_at)
        self.repository.append_event(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            event_type="progress",
            payload={"stage": "refresh_context", "summary": "正在校验简历快照与岗位要求。"},
        )

        model_client, model_id = self._resolve_model(user_id)
        retrieval_view = getattr(self.repository, "get_resume_retrieval_view", None)
        resume_view = (
            retrieval_view(user_id, session_id)
            if callable(retrieval_view)
            else self.repository.get_resume_view(user_id, session_id)
        )
        blocks = [block for block in resume_view.get("blocks", []) if isinstance(block, dict)]
        suggestions = self.repository.list_suggestions(user_id, session_id)
        session_facts = self._list_session_facts(user_id=user_id, session_id=session_id)
        confirmed_facts = [fact for fact in session_facts if fact.get("status") == "confirmed"]
        denied_facts = [fact for fact in session_facts if fact.get("status") == "denied"]
        messages = self.repository.list_turns(user_id, session_id)
        project_scope, project_document_ids = self._project_selection_from_messages(messages)
        ranking_requirements = _jd_requirements(str(session.get("jdText") or ""))
        scan_message = self._append_resume_scan(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            session=session,
            resume_view=resume_view,
            blocks=blocks,
            requirements=ranking_requirements,
            messages=messages,
        )
        if scan_message:
            messages = [*messages, scan_message]
        follow_up = next(
            (
                message
                for message in reversed(messages)
                if self._is_suggestion_follow_up(message)
            ),
            None,
        )
        active_suggestion = next(
            (
                suggestion
                for suggestion in reversed(suggestions)
                if suggestion.get("status") in {"proposed", "accepted"}
            ),
            None,
        )
        if follow_up and active_suggestion:
            return self._reply_to_suggestion_follow_up(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                user_message=follow_up,
                suggestion=active_suggestion,
            )
        latest_user_message = next(
            (message for message in reversed(messages) if message.get("role") == "user"),
            None,
        )
        implicit_revision = active_suggestion if self._is_suggestion_revision_request(latest_user_message) else None
        if implicit_revision:
            self.repository.update_suggestion_status(user_id, str(implicit_revision["id"]), "needs_revision")
        revision_request = implicit_revision or next(
            (suggestion for suggestion in reversed(suggestions) if suggestion.get("status") == "needs_revision"),
            None,
        )
        rejected_blocks = {
            str(suggestion.get("target", {}).get("blockId") or "")
            for suggestion in suggestions
            if suggestion.get("status") == "rejected"
        }
        denied_question_keys = {
            str(fact.get("claimKey") or "")
            for fact in denied_facts
        }
        denied_blocks = {
            question_key.split(":", 2)[1]
            for question_key in denied_question_keys
            if question_key.startswith("fact:") and len(question_key.split(":", 2)) == 3
        }
        completed_blocks = {
            str(suggestion.get("target", {}).get("blockId") or "")
            for suggestion in suggestions
            if suggestion.get("status") in {"proposed", "accepted", "applied"}
        }

        def block_reference_ids(block: dict[str, Any]) -> set[str]:
            return {
                str(value)
                for value in [block.get("id"), *(block.get("legacyBlockIds") or [])]
                if str(value or "")
            }

        candidates = [
            block
            for block in blocks
            if _is_automatic_rewrite_candidate(block)
            and _block_requirement_matches(block, ranking_requirements) > 0
            and block_reference_ids(block).isdisjoint(rejected_blocks)
            and block_reference_ids(block).isdisjoint(denied_blocks)
            and block_reference_ids(block).isdisjoint(completed_blocks)
        ]

        if revision_request:
            requested_block_id = str(revision_request.get("target", {}).get("blockId") or "")
            candidates = [block for block in blocks if requested_block_id in block_reference_ids(block)]
        else:
            candidates = self._rank_candidate_blocks(candidates, ranking_requirements)
        revision_feedback = str(latest_user_message.get("content") or "") if implicit_revision and latest_user_message else next(
            (
                str(message.get("content") or "")
                for message in reversed(messages)
                if isinstance(message.get("payload"), dict)
                and message["payload"].get("suggestionId") == (revision_request or {}).get("id")
                and message["payload"].get("action") == "needs_revision"
            ),
            "",
        )
        if not candidates:
            message = self.repository.append_turn(
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                content="",
                message_kind="completion",
                run_id=run_id,
                payload={"status": "READY_FOR_CONFIRMATION"},
            )
            self.repository.update_session(
                user_id,
                session_id,
                session_status="READY_FOR_CONFIRMATION",
                active_run_id=run_id,
            )
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                message_id=message["id"],
                event_type="message",
                payload={"messageKind": "completion"},
            )
            self.repository.update_run(user_id=user_id, run_id=run_id, status="COMPLETED")
            return {"status": "READY_FOR_CONFIRMATION", "message": message}

        block = candidates[0]
        original_text = str(block.get("text") or "").strip()
        supporting_blocks = self._supporting_evidence_blocks(
            current_block=block,
            all_blocks=blocks,
            requirements=ranking_requirements,
        )
        supporting_evidence_block_ids = [
            str(item.get("id") or "")
            for item in supporting_blocks
            if str(item.get("id") or "")
        ]
        preferences: list[str] = []
        try:
            from backend.memory.preference_db import PreferenceDB

            preference_db = PreferenceDB(db=getattr(self.repository, "db", None))
            preferences = list(dict.fromkeys([
                *preference_db.get_preferences(user_id, "resume_advisor"),
                *preference_db.get_preferences(user_id, str(block.get("sectionId") or "resume_advisor")),
            ]))
        except Exception:
            preferences = []
        context_snapshot = build_advisor_context_snapshot(
            current_block=block,
            jd_requirements=_jd_requirements(str(session.get("jdText") or "")),
            messages=messages,
            facts=confirmed_facts,
            preferences=preferences,
            max_chars=Config.ADVISOR_CONTEXT_MAX_CHARS,
            recent_turn_limit=Config.ADVISOR_CONTEXT_RECENT_TURNS,
        )
        self._merge_run_telemetry(
            user_id=user_id,
            run_id=run_id,
            telemetry={
                "contextVersion": context_snapshot["version"],
                "contextHash": context_snapshot["hash"],
                "contextChars": context_snapshot["characterCount"],
                "compactedMessageCount": context_snapshot["compactedMessageCount"],
            },
        )
        supplementary_evidence = "\n".join(
            f"- {str(item.get('locationLabel') or item.get('sectionName') or '简历内容')}: {str(item.get('text') or '').strip()}"
            for item in supporting_blocks[1:]
            if str(item.get("text") or "").strip()
        )
        context_prompt = str(context_snapshot["promptText"])
        if supplementary_evidence:
            context_prompt = (
                f"{context_prompt}\n\n[同份简历中可核验的补充证据]\n"
                f"{supplementary_evidence[:1200]}"
            )

        def record_cache_event(namespace: str, hit: bool) -> None:
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                event_type="cache",
                payload={
                    "namespace": namespace,
                    "hit": hit,
                    "stage": "cache_lookup",
                    "modelId": model_id,
                },
            )

        def record_provider_usage(agent: str, usage: dict[str, Any]) -> None:
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                event_type="provider_usage",
                payload={
                    "agent": agent,
                    "modelId": model_id,
                    **(usage if isinstance(usage, dict) else {}),
                },
            )

        def emit_tool_call(tool_name: str, stage: str) -> tuple[str, float]:
            call_id = f"tool-{uuid4().hex}"
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                event_type="tool_call",
                payload={
                    "callId": call_id,
                    "toolName": tool_name,
                    "stage": stage,
                    "agent": {
                        "extract_jd_requirements": "job_decoder",
                        "retrieve_resume_evidence": "resume_rag_retriever",
                        "review_rag_evidence": "resume_rag_reviewer",
                        "verify_suggestion_facts": "fact_verifier",
                        "hr_quality_review": "hr_critic",
                    }.get(tool_name, "resume_advisor"),
                    "blockId": block.get("id"),
                },
            )
            return call_id, time.monotonic()

        def emit_tool_result(
            *,
            call_id: str,
            tool_name: str,
            stage: str,
            started_at: float,
            ok: bool,
            summary: dict[str, Any],
        ) -> None:
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                event_type="tool_result",
                payload={
                    "callId": call_id,
                    "toolName": tool_name,
                    "stage": stage,
                    "agent": {
                        "extract_jd_requirements": "job_decoder",
                        "retrieve_resume_evidence": "resume_rag_retriever",
                        "review_rag_evidence": "resume_rag_reviewer",
                        "verify_suggestion_facts": "fact_verifier",
                        "hr_quality_review": "hr_critic",
                    }.get(tool_name, "resume_advisor"),
                    "blockId": block.get("id"),
                    "ok": ok,
                    "durationMs": max(0, int((time.monotonic() - started_at) * 1000)),
                    "summary": summary,
                },
            )

        def execute_operation(
            *,
            tool_name: str,
            stage: str,
            arguments: dict[str, Any],
            handler: Callable[[], dict[str, Any]],
        ) -> dict[str, Any]:
            call_id, started_at = emit_tool_call(tool_name, stage)
            outcome = self.tool_runtime.execute(
                name=tool_name,
                user_id=user_id,
                session_id=session_id,
                trace_id=str(run_snapshot.get("traceId") or session.get("traceId") or ""),
                arguments=arguments,
                handler=handler,
            )
            if outcome.get("ok"):
                data = outcome.get("data") if isinstance(outcome.get("data"), dict) else {}
                public_data = (
                    {"requirementCount": len(data.get("requirements", []))}
                    if tool_name == "extract_jd_requirements"
                    else {
                        "evidenceCount": data.get("evidenceCount", 0),
                        "chunkCount": len(data.get("chunkIds", [])),
                        "retrievalMode": data.get("retrievalMode"),
                        "semanticMode": data.get("semanticMode"),
                    }
                    if tool_name == "retrieve_resume_evidence"
                    else {key: value for key, value in data.items() if key != "raw"}
                )
                emit_tool_result(
                    call_id=call_id,
                    tool_name=tool_name,
                    stage=stage,
                    started_at=started_at,
                    ok=True,
                    summary={"meta": outcome.get("meta", {}), **public_data},
                )
                return data
            error = outcome.get("error") if isinstance(outcome.get("error"), dict) else {}
            emit_tool_result(
                call_id=call_id,
                tool_name=tool_name,
                stage=stage,
                started_at=started_at,
                ok=False,
                summary={"code": str(error.get("code") or "tool_execution_failed")},
            )
            raise RuntimeError(str(error.get("message") or f"Advisor tool failed: {tool_name}"))

        if self._is_cancelled(user_id=user_id, run_id=run_id):
            return self._cancelled_result(user_id=user_id, session_id=session_id, run_id=run_id)
        self.repository.append_event(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            event_type="progress",
            payload={"stage": "jd_requirements", "summary": "岗位解码 Agent 正在提炼职位要求。", "agent": "job_decoder", "modelId": model_id},
        )
        try:
            requirements_result = execute_operation(
                tool_name="extract_jd_requirements",
                stage="jd_requirements",
                arguments={"jdText": str(session.get("jdText") or "")},
                handler=lambda: {
                    "requirements": decode_jd_requirements(
                        jd_text=str(session.get("jdText") or ""),
                        fallback_requirements=_jd_requirements(str(session.get("jdText") or "")),
                        model_client=model_client,
                        model_id=model_id,
                        allow_model_call=True,
                        # JD terms are deterministic routing input, not a
                        # user-facing generation. Keep the run moving with
                        # the local parser when the decoder provider fails.
                        require_model=False,
                        on_cache_event=record_cache_event,
                    )
                },
            )
        except Exception as exc:
            return self._pause_for_model_issue(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                stage="jd_requirements",
                model_status="unavailable" if model_client is None or not model_id else "failed",
                error=exc,
                target={"locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文"},
            )
        requirements = [str(item) for item in requirements_result.get("requirements", [])]
        retrieval_holder: dict[str, Any] = {}
        retrieval_chunks = self._resume_chunks_for_retrieval(resume_view, blocks)
        project_chunks = self._project_chunks_for_retrieval(
            user_id=user_id,
            scope=project_scope,
            document_ids=project_document_ids,
        )
        retrieval_chunks = [*retrieval_chunks, *project_chunks]

        def retrieve_resume_evidence() -> dict[str, Any]:
            jd_text = str(session.get("jdText") or "")
            try:
                response = self.ai_service_client.rag_search(
                    query=jd_text,
                    documents=self._ai_service_documents(retrieval_chunks),
                    top_k=6,
                    strategy="hybrid",
                )
            except Exception as exc:
                raise RuntimeError("AI Service 混合检索不可用") from exc

            if not isinstance(response, dict):
                raise RuntimeError("AI Service 返回了无效的混合检索结果")
            semantic_mode = str(response.get("semanticMode") or "")
            results = response.get("results") if isinstance(response.get("results"), list) else []
            if response.get("strategy") != "hybrid" or semantic_mode != "embedding":
                raise RuntimeError("混合检索未使用可用的 embedding 语义召回")

            top_chunks = self._advisor_chunks_from_ai_results(results)
            retrieval_holder["chunks"] = top_chunks
            retrieval_holder["retrievalMode"] = "ai_service_hybrid"
            retrieval_holder["semanticMode"] = semantic_mode
            self._merge_run_telemetry(
                user_id=user_id,
                run_id=run_id,
                telemetry={
                    "resumeRetrieval": {
                        "mode": "ai_service_hybrid",
                        "semanticMode": semantic_mode,
                        "evidenceCount": len(top_chunks),
                    }
                },
            )
            return {
                "evidenceCount": len(top_chunks),
                "chunkIds": [str(chunk.get("id") or chunk.get("chunkId") or "") for chunk in top_chunks if str(chunk.get("id") or chunk.get("chunkId") or "")],
                "retrievalMode": "ai_service_hybrid",
                "semanticMode": semantic_mode,
            }

        self.repository.append_event(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            event_type="progress",
            payload={"stage": "resume_retrieval", "summary": "简历检索 Agent 正在定位与岗位相关的证据。", "agent": "resume_rag_retriever"},
        )
        try:
            execute_operation(
                tool_name="retrieve_resume_evidence",
                stage="resume_retrieval",
                arguments={"jdText": str(session.get("jdText") or "")},
                handler=retrieve_resume_evidence,
            )
        except Exception as exc:
            return self._pause_for_model_issue(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                stage="resume_retrieval",
                model_status="unavailable",
                error=exc,
                target={"locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文"},
            )
        rag_chunks = retrieval_holder.get("chunks", [])
        if not rag_chunks:
            return self._pause_for_model_issue(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                stage="rag_evidence_review",
                model_status="invalid_output",
                target={"locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文"},
            )
        self.repository.append_event(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            event_type="progress",
            payload={
                "stage": "rag_evidence_review",
                "summary": "RAG 证据审阅 Agent 正在筛选可归因的简历证据。",
                "agent": "resume_rag_reviewer",
                "modelId": model_id,
            },
        )
        rag_review_holder: dict[str, Any] = {}
        try:
            execute_operation(
                tool_name="review_rag_evidence",
                stage="rag_evidence_review",
                arguments={"candidateChunkIds": [str(chunk.get("id") or chunk.get("chunkId") or "") for chunk in rag_chunks]},
                handler=lambda: _review_rag_evidence_with_holder(
                    rag_review_holder,
                    jd_text=str(session.get("jdText") or ""),
                    jd_requirements=requirements,
                    candidates=rag_chunks,
                    model_client=model_client,
                    model_id=model_id,
                    user_id=user_id,
                    on_cache_event=record_cache_event,
                    on_provider_usage=record_provider_usage,
                ),
            )
        except Exception as exc:
            review_error = rag_review_holder.get("error")
            return self._pause_for_model_issue(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                stage="rag_evidence_review",
                model_status=str(getattr(review_error, "model_status", "failed")),
                error=review_error if isinstance(review_error, Exception) else exc,
                target={"locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文"},
            )
        rag_review = rag_review_holder["value"]
        selected_chunk_ids = set(rag_review.selected_chunk_ids)
        rag_chunks = [
            chunk for chunk in rag_chunks
            if str(chunk.get("id") or chunk.get("chunkId") or "") in selected_chunk_ids
        ]
        if not rag_chunks:
            missing = "、".join(rag_review.uncovered_requirements[:6]) or "当前 JD 的关键要求"
            message = self.repository.append_turn(
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                content=f"RAG 证据审阅未找到可支撑“{missing}”的真实简历片段；请补充相关事实后再继续优化。",
                message_kind="text",
                run_id=run_id,
                payload={
                    "mode": "rag_evidence_insufficient",
                    "uncoveredRequirements": rag_review.uncovered_requirements,
                    "target": {"locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文"},
                },
            )
            self.repository.update_session(user_id, session_id, session_status="WAITING_FOR_USER", active_run_id=run_id)
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                message_id=message["id"],
                event_type="message",
                payload={"messageKind": "text", "mode": "rag_evidence_insufficient", "agent": "resume_rag_reviewer"},
            )
            self.repository.update_run(user_id=user_id, run_id=run_id, status="PAUSED")
            return {"status": "WAITING_FOR_USER", "message": message}
        rag_evidence_texts = [
            f"{str(chunk.get('section') or chunk.get('sectionTitle') or '简历内容')}: {str(chunk.get('content') or '').strip()}"
            for chunk in rag_chunks
            if str(chunk.get("content") or "").strip()
        ]
        rag_evidence_block_ids = self._rag_evidence_block_ids(rag_chunks)
        supporting_evidence_block_ids = list(dict.fromkeys([*supporting_evidence_block_ids, *rag_evidence_block_ids]))
        evidence_texts = list(dict.fromkeys([
            *[str(item.get("text") or "") for item in supporting_blocks if str(item.get("text") or "").strip()],
            *rag_evidence_texts,
        ]))
        if rag_evidence_texts:
            rag_context = "\n".join(f"- {item}" for item in rag_evidence_texts)
            context_prompt = (
                f"{context_prompt}\n\n[RAG 检索到的简历证据]\n"
                f"{rag_context[:1800]}"
            )
        self.repository.append_event(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            event_type="progress",
            payload={
                "stage": "draft_suggestion",
                "summary": "模型正在生成本段建议。",
                "agent": "resume_copywriter",
                "modelId": model_id,
                "blockId": block.get("id"),
            },
        )

        def on_model_delta(_delta: str) -> None:
            # The proposal may contain unsupported candidate claims. Hold it until
            # fact verification and the independent HRCritic gate both approve it.
            return

        if self._is_cancelled(user_id=user_id, run_id=run_id):
            return self._cancelled_result(user_id=user_id, session_id=session_id, run_id=run_id)
        draft: SuggestionDraft | None = None
        model_issue: tuple[str, Exception] | None = None
        try:
            draft = self._draft_suggestion(
                original_text,
                section_name=str(block.get("sectionId") or ""),
                jd_requirements=requirements,
                model_client=model_client,
                model_id=model_id,
                revision_feedback=revision_feedback,
                context_snapshot=context_prompt,
                user_id=user_id,
                on_delta=on_model_delta,
                on_cache_event=record_cache_event,
                on_provider_usage=record_provider_usage,
            )
        except _ModelUnavailableError as exc:
            model_issue = ("unavailable", exc)
        except Exception as exc:
            model_issue = ("failed", exc)
        if model_issue is not None:
            model_status, model_error = model_issue
            return self._pause_for_model_issue(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                stage="suggestion_generation",
                model_status=model_status,
                error=model_error,
                target={
                    "blockId": block["id"],
                    "locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文",
                },
            )
        assert draft is not None
        if self._is_cancelled(user_id=user_id, run_id=run_id):
            return self._cancelled_result(user_id=user_id, session_id=session_id, run_id=run_id)
        if draft.outcome == "affirmation":
            affirmation_holder: dict[str, Any] = {}
            execute_operation(
                tool_name="verify_suggestion_facts",
                stage="affirmation_verification",
                arguments={"blockId": str(block.get("id") or "")},
                handler=lambda: _verify_with_holder(
                    affirmation_holder,
                    original_text=original_text,
                    proposed_text=draft.affirmation,
                    confirmed_facts=confirmed_facts,
                    jd_text=str(session.get("jdText") or ""),
                    resume_evidence_texts=evidence_texts,
                ),
            )
            affirmation_verification = affirmation_holder["value"]
            if affirmation_verification.status != "supported":
                return self._pause_for_model_issue(
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_id,
                    stage="alignment_assessment",
                    model_status="unsafe_output",
                    target={"locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文"},
                )
            affirmation_quality_holder: dict[str, Any] = {}
            try:
                execute_operation(
                    tool_name="hr_quality_review",
                    stage="affirmation_quality_review",
                    arguments={"blockId": str(block.get("id") or "")},
                    handler=lambda: _review_with_holder(
                        affirmation_quality_holder,
                        original_text=original_text,
                        proposed_text=draft.affirmation,
                        section_name=str(block.get("sectionName") or "其他"),
                        jd_text=str(session.get("jdText") or ""),
                        resume_evidence_texts=evidence_texts,
                        confirmed_facts=confirmed_facts,
                        model_client=model_client,
                        model_id=model_id,
                        on_cache_event=record_cache_event,
                        on_provider_usage=record_provider_usage,
                    ),
                )
            except Exception as exc:
                review_error = affirmation_quality_holder.get("error")
                return self._pause_for_model_issue(
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_id,
                    stage="affirmation_quality_review",
                    model_status=str(getattr(review_error, "model_status", "failed")),
                    error=review_error if isinstance(review_error, Exception) else exc,
                    target={"locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文"},
                )
            affirmation_quality = affirmation_quality_holder["value"]
            if not affirmation_quality.is_passed:
                return self._pause_for_quality_rejection(
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_id,
                    quality=affirmation_quality,
                    target={
                        "blockId": block["id"],
                        "locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文",
                    },
                    issue="匹配肯定结论",
                )
            message = self.repository.append_turn(
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                content=draft.affirmation,
                message_kind="text",
                run_id=run_id,
                payload={
                    "mode": "alignment_assessment",
                    "highlightLocations": draft.highlight_locations,
                    "target": {"locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文"},
                },
            )
            self.repository.update_session(
                user_id,
                session_id,
                session_status="READY_FOR_CONFIRMATION",
                active_run_id=run_id,
            )
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                message_id=message["id"],
                event_type="message",
                payload={"messageKind": "text", "mode": "alignment_assessment", "agent": "resume_copywriter"},
            )
            self.repository.update_run(user_id=user_id, run_id=run_id, status="COMPLETED")
            return {"status": "READY_FOR_CONFIRMATION", "message": message}
        copy_text = draft.proposed_text
        if self._is_cancelled(user_id=user_id, run_id=run_id):
            return self._cancelled_result(user_id=user_id, session_id=session_id, run_id=run_id)
        verification_holder: dict[str, Any] = {}
        execute_operation(
            tool_name="verify_suggestion_facts",
            stage="fact_verification",
            arguments={"blockId": str(block.get("id") or "")},
            handler=lambda: _verify_with_holder(
                verification_holder,
                original_text=original_text,
                proposed_text=copy_text,
                confirmed_facts=confirmed_facts,
                jd_text=str(session.get("jdText") or ""),
                resume_evidence_texts=evidence_texts,
            ),
        )
        verification = verification_holder["value"]
        if self._is_cancelled(user_id=user_id, run_id=run_id):
            return self._cancelled_result(user_id=user_id, session_id=session_id, run_id=run_id)
        if verification.status != "supported":
            clarification, clarification_status, clarification_error = self._request_evidence_clarification(
                user_id=user_id,
                location=str(block.get("locationLabel") or block.get("sectionName") or "简历正文"),
                original_text=original_text,
                proposed_text=copy_text,
                fact_issues=verification.fact_issues,
                retrieved_evidence=evidence_texts,
                model_client=model_client,
                model_id=model_id,
            )
            if clarification is None:
                return self._pause_for_model_issue(
                    user_id=user_id,
                    session_id=session_id,
                    run_id=run_id,
                    stage="fact_clarification",
                    model_status=clarification_status,
                    error=clarification_error,
                    target={"locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文"},
                )
            message = self.repository.append_turn(
                user_id=user_id,
                session_id=session_id,
                role="assistant",
                content=clarification,
                message_kind="text",
                run_id=run_id,
                payload={
                    "mode": "evidence_clarification",
                    "factStatus": verification.status,
                    "resumeEvidenceBlockIds": supporting_evidence_block_ids,
                    "target": {"locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文"},
                },
            )
            self.repository.update_session(
                user_id,
                session_id,
                session_status="WAITING_FOR_USER",
                active_run_id=run_id,
            )
            self.repository.append_event(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                message_id=message["id"],
                event_type="message",
                payload={"messageKind": "text", "mode": "evidence_clarification", "factStatus": verification.status},
            )
            self.repository.update_run(user_id=user_id, run_id=run_id, status="PAUSED")
            return {"status": "WAITING_FOR_USER", "message": message}

        local_quality = review_suggestion_quality(
            original_text=original_text,
            proposed_text=copy_text,
            evidence_block_ids=supporting_evidence_block_ids,
            fact_status=verification.status,
        )
        if not local_quality.is_passed:
            return self._pause_for_quality_rejection(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                quality=local_quality,
                target={
                    "blockId": block["id"],
                    "locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文",
                },
                issue=draft.issue,
            )

        if self._is_cancelled(user_id=user_id, run_id=run_id):
            return self._cancelled_result(user_id=user_id, session_id=session_id, run_id=run_id)
        quality_holder: dict[str, Any] = {}
        try:
            execute_operation(
                tool_name="hr_quality_review",
                stage="quality_review",
                arguments={"blockId": str(block.get("id") or "")},
                handler=lambda: _review_with_holder(
                    quality_holder,
                    original_text=original_text,
                    proposed_text=copy_text,
                    section_name=str(block.get("sectionName") or "其他"),
                    jd_text=str(session.get("jdText") or ""),
                    resume_evidence_texts=evidence_texts,
                    confirmed_facts=confirmed_facts,
                    model_client=model_client,
                    model_id=model_id,
                    on_cache_event=record_cache_event,
                    on_provider_usage=record_provider_usage,
                ),
            )
        except Exception as exc:
            review_error = quality_holder.get("error")
            if isinstance(review_error, HRCriticReviewError):
                model_status = review_error.model_status
                model_error = review_error
            else:
                model_status = "failed"
                model_error = exc
            return self._pause_for_model_issue(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                stage="hr_quality_review",
                model_status=model_status,
                error=model_error,
                target={
                    "blockId": block["id"],
                    "locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文",
                },
            )
        quality = quality_holder["value"]
        if not quality.is_passed:
            return self._pause_for_quality_rejection(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                quality=quality,
                target={
                    "blockId": block["id"],
                    "locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文",
                },
                issue=draft.issue,
            )

        if self._is_cancelled(user_id=user_id, run_id=run_id):
            return self._cancelled_result(user_id=user_id, session_id=session_id, run_id=run_id)
        location = {
            "blockId": block["id"],
            "sectionId": block.get("sectionId") or "generic_section",
            "sectionName": block.get("sectionName") or "其他",
            "itemLabel": block.get("itemLabel"),
            "sourceFormat": (block.get("locator") or {}).get("sourceFormat", "txt"),
            "pageNumber": (block.get("locator") or {}).get("pageNumber"),
            "locationLabel": block.get("locationLabel") or block.get("sectionName") or "简历正文",
            "locatorConfidence": block.get("locatorConfidence") or "approximate",
            "bbox": (block.get("locator") or {}).get("bbox"),
        }
        suggestion = self.repository.create_suggestion(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            data={
                "parentSuggestionId": revision_request.get("id") if revision_request else None,
                "target": location,
                "originalTextHash": block.get("textHash") or "",
                "priority": draft.priority,
                "issue": draft.issue,
                "originalText": original_text,
                "proposedText": copy_text,
                "copyText": copy_text,
                "rationale": draft.rationale,
                "expectedImpact": draft.expected_impact,
                "jdRequirementIds": requirements,
                "resumeEvidenceBlockIds": supporting_evidence_block_ids,
                "userFactIds": self._supporting_user_fact_ids(confirmed_facts, copy_text),
                "factStatus": verification.status,
                "factIssues": [issue.message for issue in verification.fact_issues],
                "status": "proposed",
            },
        )
        message = self.repository.append_turn(
            user_id=user_id,
            session_id=session_id,
            role="assistant",
            content=(
                f"简历改写 Agent 已为“{location['locationLabel']}”准备一条建议；"
                "事实核验与 HR 审查均已通过。请在右侧“修改建议工作区”查看并决定是否采用。"
            ),
            message_kind="text",
            run_id=run_id,
            payload={"suggestionId": suggestion["id"], "agent": "resume_copywriter", "qualityPassed": True},
        )
        self.repository.update_session(
            user_id,
            session_id,
            session_status="WAITING_FOR_USER",
            active_run_id=run_id,
        )
        self.repository.append_event(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            message_id=message["id"],
            suggestion_id=suggestion["id"],
            event_type="suggestion",
            payload={"factStatus": suggestion["factStatus"]},
        )
        self.repository.update_run(user_id=user_id, run_id=run_id, status="PAUSED")
        return {"status": "WAITING_FOR_USER", "suggestion": suggestion, "message": message}

    def _resolve_model(self, user_id: Any) -> tuple[Any | None, str]:
        if self.model_provider is not None:
            try:
                resolved = self.model_provider(user_id)
                if resolved:
                    return resolved
            except Exception:
                pass
        return self.model_client, self.model_id

    @staticmethod
    def _is_suggestion_follow_up(message: dict[str, Any]) -> bool:
        if message.get("role") != "user":
            return False
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
        if payload.get("action") or payload.get("suggestionId"):
            return False
        content = str(message.get("content") or "").strip()
        return bool(content) and (
            content.endswith(("?", "？"))
            or content.startswith(_FOLLOW_UP_PREFIXES)
        )

    @staticmethod
    def _is_suggestion_revision_request(message: dict[str, Any] | None) -> bool:
        if not message or message.get("role") != "user":
            return False
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
        if payload.get("action") or payload.get("suggestionId"):
            return False
        content = str(message.get("content") or "").strip()
        return any(hint in content for hint in _REVISION_HINTS)

    def _reply_to_suggestion_follow_up(
        self,
        *,
        user_id: Any,
        session_id: str,
        run_id: str,
        user_message: dict[str, Any],
        suggestion: dict[str, Any],
    ) -> dict[str, Any]:
        target = suggestion.get("target") if isinstance(suggestion.get("target"), dict) else {}
        location = str(target.get("locationLabel") or "当前段落")
        original = str(suggestion.get("originalText") or "原文内容")
        proposed = str(suggestion.get("proposedText") or suggestion.get("copyText") or "建议文本")
        confirmed_facts = [
            fact
            for fact in self._list_session_facts(user_id=user_id, session_id=session_id)
            if fact.get("status") == "confirmed"
        ]
        explanation, model_status, model_error = self._generate_suggestion_explanation(
            user_id=user_id,
            user_question=str(user_message.get("content") or ""),
            location=location,
            original=original,
            proposed=proposed,
            confirmed_facts=confirmed_facts,
        )
        if explanation is None:
            return self._pause_for_model_issue(
                user_id=user_id,
                session_id=session_id,
                run_id=run_id,
                stage="suggestion_follow_up",
                model_status=model_status,
                error=model_error,
                target={
                    "blockId": target.get("blockId"),
                    "locationLabel": location,
                },
                reply_to_message_id=user_message.get("id"),
                suggestion_id=suggestion.get("id"),
            )
        message = self.repository.append_turn(
            user_id=user_id,
            session_id=session_id,
            role="assistant",
            content=explanation,
            message_kind="text",
            run_id=run_id,
            payload={
                "replyToMessageId": user_message.get("id"),
                "suggestionId": suggestion.get("id"),
                "mode": "suggestion_follow_up",
            },
        )
        self.repository.update_session(
            user_id,
            session_id,
            session_status="WAITING_FOR_USER",
            active_run_id=run_id,
        )
        self.repository.append_event(
            user_id=user_id,
            session_id=session_id,
            run_id=run_id,
            message_id=message["id"],
            event_type="message",
            payload={"messageKind": "text", "mode": "suggestion_follow_up"},
        )
        self.repository.update_run(user_id=user_id, run_id=run_id, status="PAUSED")
        return {"status": "WAITING_FOR_USER", "message": message}

    def _generate_suggestion_explanation(
        self,
        *,
        user_id: Any,
        user_question: str,
        location: str,
        original: str,
        proposed: str,
        confirmed_facts: list[dict[str, Any]],
    ) -> tuple[str | None, str, Exception | None]:
        """Request one follow-up from ResumeCopywriter, then apply the evidence gate."""
        model_client, model_id = self._resolve_model(user_id)
        if model_client is None or not str(model_id).strip():
            return None, "unavailable", None
        try:
            from backend.agents.resume_copywriter import ResumeCopywriter
            from .verification import _run_async

            copywriter = ResumeCopywriter(model=model_id, openai_client=model_client)
            content = _run_async(
                copywriter.explain_advisor_suggestion(
                    user_question=user_question,
                    location=location,
                    original_content=original,
                    proposed_content=proposed,
                    confirmed_facts=[
                        str(fact.get("claimValue") or "")
                        for fact in confirmed_facts
                        if str(fact.get("claimValue") or "").strip()
                    ],
                    user_id=str(user_id),
                )
            )
        except Exception as exc:
            return None, "failed", exc

        explanation = str(content or "").strip()
        if not explanation:
            return None, "failed", RuntimeError("resume advisor model returned an empty explanation")
        try:
            verification = verify_suggestion_facts(
                original_text=original,
                proposed_text=explanation,
                resume_evidence_texts=[proposed],
                confirmed_facts=confirmed_facts,
                jd_text="",
            )
        except Exception as exc:
            return None, "failed", exc
        if verification.status != "supported":
            return None, "unsafe_output", None
        return explanation, "ok", None
