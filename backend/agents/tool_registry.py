from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

from backend.agents.tools.docx_tools import update_docx_resume_from_log
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


JsonDict = dict[str, Any]
ToolHandler = Callable[["AgentToolContext", JsonDict], Any]


@dataclass(frozen=True)
class AgentToolContext:
    user_id: Any
    task_id: str
    resume_text: str = ""
    jd_text: str = ""
    is_co_pilot: bool = True


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

    def to_responses_tool(self) -> JsonDict:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema,
        }


class AgentToolValidationError(ValueError):
    pass


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
    return _json_result(True, {
        "docx_updated": docx_updated,
        "docx_error": docx_error,
        "markdown_file": "optimized_resume.md",
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

    def list_tools(self, *, is_co_pilot: bool = True) -> list[AgentToolSpec]:
        tools = []
        for tool in self._tools.values():
            if is_co_pilot and not tool.available_in_copilot:
                continue
            if not is_co_pilot and not tool.available_in_auto:
                continue
            tools.append(tool)
        return tools

    def responses_tools(self, *, is_co_pilot: bool = True) -> list[JsonDict]:
        return [tool.to_responses_tool() for tool in self.list_tools(is_co_pilot=is_co_pilot)]

    def execute(self, name: str, arguments: JsonDict, ctx: AgentToolContext) -> JsonDict:
        tool = self.get(name)
        if ctx.is_co_pilot and not tool.available_in_copilot:
            raise PermissionError(f"Tool is not available in copilot mode: {name}")
        if not ctx.is_co_pilot and not tool.available_in_auto:
            raise PermissionError(f"Tool is not available in auto mode: {name}")
        started_at = time.perf_counter()
        try:
            _validate_args(tool.parameters_schema, arguments)
            result = tool.handler(ctx, arguments)
            ok = True
            error = ""
        except Exception as exc:
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
            "preview": _short_preview(result if ok else error, tool.result_preview_chars),
            "read_only": tool.read_only,
            "requires_confirmation": tool.requires_confirmation,
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
    ]


DEFAULT_AGENT_TOOL_REGISTRY = AgentToolRegistry()
