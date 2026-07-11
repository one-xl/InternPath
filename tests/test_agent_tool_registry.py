import json

import pytest

from backend.agents.tool_registry import AgentToolContext, AgentToolProfile, AgentToolRegistry, AgentToolSideEffect, AgentToolSpec
from backend.agents.tools.workspace_tools import get_workspace_dir, tool_read_file, tool_write_file
from config import Config


def test_registry_exports_responses_function_tools():
    registry = AgentToolRegistry()

    tools = registry.responses_tools()
    names = {tool["name"] for tool in tools}

    assert "extract_resume_sections" in names
    assert "replace_resume_section" in names
    assert "finalize_resume_artifacts" in names
    assert all(tool["type"] == "function" for tool in tools)
    assert all(tool["parameters"]["type"] == "object" for tool in tools)


def test_registry_executes_workspace_read_write(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path))
    registry = AgentToolRegistry()
    ctx = AgentToolContext(user_id="u1", task_id="t1")

    write_result = registry.execute(
        "write_workspace_file",
        {"filename": "notes/plan.txt", "content": "hello"},
        ctx,
    )
    read_result = registry.execute(
        "read_workspace_file",
        {"filename": "notes/plan.txt"},
        ctx,
    )

    assert write_result["ok"] is True
    assert read_result["ok"] is True
    assert read_result["result"]["data"]["content"] == "hello"


def test_resume_advisor_profile_hides_and_rejects_legacy_artifact_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path))
    registry = AgentToolRegistry()
    advisor_tools = registry.responses_tools(profile=AgentToolProfile.RESUME_ADVISOR)
    advisor_names = {tool["name"] for tool in advisor_tools}

    assert {"get_resume_snapshot", "get_resume_outline", "list_confirmed_facts"} <= advisor_names
    assert "write_workspace_file" not in advisor_names
    assert "replace_resume_section" not in advisor_names
    assert "finalize_resume_artifacts" not in advisor_names

    result = registry.execute(
        "write_workspace_file",
        {"filename": "resume.md", "content": "unsafe"},
        AgentToolContext(user_id="u1", task_id="advisor", profile=AgentToolProfile.RESUME_ADVISOR),
    )

    assert result["ok"] is False
    assert "not available" in result["error"]


def test_resume_advisor_verification_tools_use_structured_evidence_only(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path))

    class _Repository:
        def list_confirmed_facts(self, _user_id, _session_id):
            return []

    class _AdvisorModule:
        repository = _Repository()

        def get_resume_view(self, *, user_id, session_id):
            return {
                "blocks": [{"id": "block-1", "text": "负责 FastAPI 接口开发"}],
            }

    registry = AgentToolRegistry()
    ctx = AgentToolContext(
        user_id="u1",
        task_id="advisor-1",
        jd_text="需要 FastAPI 和 Redis 经验",
        profile=AgentToolProfile.RESUME_ADVISOR,
        advisor_module=_AdvisorModule(),
    )
    names = {tool["name"] for tool in registry.responses_tools(profile=AgentToolProfile.RESUME_ADVISOR)}
    assert {
        "get_resume_snapshot", "get_resume_outline", "locate_resume_blocks", "get_analysis_context",
        "parse_jd_requirements", "retrieve_resume_evidence", "list_confirmed_facts", "list_resume_preferences",
        "analyze_gap_queue", "draft_resume_suggestion", "verify_suggestion_facts", "review_suggestion_quality",
        "revise_resume_suggestion", "record_user_fact", "save_user_preference", "request_user_input",
        "evaluate_session_completion",
    } <= names

    verified = registry.execute_profiled(
        "verify_suggestion_facts",
        {
            "original_text": "负责 FastAPI 接口开发",
            "proposed_text": "负责 FastAPI 与 Redis 接口开发",
            "evidence_block_ids": ["block-1"],
        },
        ctx,
    )

    assert verified["ok"] is True
    assert verified["data"]["status"] == "needs_user"
    assert verified["meta"]["tool"] == "verify_suggestion_facts"
    assert verified["meta"]["evidenceRefs"] == ["block-1"]
    assert verified["meta"]["idempotencyKey"].startswith("tool-")

    raw = registry.execute(
        "verify_suggestion_facts",
        {
            "original_text": "负责 FastAPI 接口开发",
            "proposed_text": "负责 FastAPI 接口开发",
            "evidence_block_ids": ["block-1"],
        },
        ctx,
    )
    assert raw["preview"] == "[advisor payload redacted]"


def test_registry_rejects_unsafe_workspace_path(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path))
    registry = AgentToolRegistry()
    ctx = AgentToolContext(user_id="u1", task_id="t1")

    result = registry.execute(
        "read_workspace_file",
        {"filename": "../secret.txt"},
        ctx,
    )

    assert result["ok"] is False
    assert "secret.txt" in result["error"]


def test_registry_validates_required_and_unknown_arguments(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path))
    registry = AgentToolRegistry()
    ctx = AgentToolContext(user_id="u1", task_id="t1")

    missing = registry.execute("read_workspace_file", {}, ctx)
    unknown = registry.execute(
        "read_workspace_file",
        {"filename": "a.txt", "extra": "nope"},
        ctx,
    )

    assert missing["ok"] is False
    assert "Missing required tool argument" in missing["error"]
    assert unknown["ok"] is False
    assert "Unknown tool argument" in unknown["error"]


def test_registry_retries_read_tools_and_enforces_confirmation():
    calls = {"retry": 0, "confirmed": 0}

    def retry_handler(_ctx, _arguments):
        calls["retry"] += 1
        return {"ok": calls["retry"] > 1, "data": {"attempt": calls["retry"]}, "error": "temporary"}

    def confirmed_handler(_ctx, _arguments):
        calls["confirmed"] += 1
        return {"ok": True, "data": {}}

    registry = AgentToolRegistry([
        AgentToolSpec(
            name="retry_read", description="retry", parameters_schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            handler=retry_handler, read_only=True, retry_attempts=1,
        ),
        AgentToolSpec(
            name="confirmed_append", description="confirm", parameters_schema={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            handler=confirmed_handler, requires_confirmation=True, side_effect=AgentToolSideEffect.APPEND,
        ),
    ])

    retried = registry.execute("retry_read", {}, AgentToolContext(user_id="u1", task_id="t1"))
    blocked = registry.execute("confirmed_append", {}, AgentToolContext(user_id="u1", task_id="t1"))
    approved = registry.execute(
        "confirmed_append", {}, AgentToolContext(user_id="u1", task_id="t1", user_confirmation=True),
    )

    assert retried["ok"] is True
    assert retried["attempts"] == 2
    assert blocked["ok"] is False
    assert calls["confirmed"] == 1
    assert approved["ok"] is True


def test_registry_extract_replace_and_diff(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path))
    registry = AgentToolRegistry()
    ctx = AgentToolContext(
        user_id="u1",
        task_id="t1",
        resume_text="Contact\nAda\n\nWork Experience\nBuilt APIs\n\nSkills\nPython",
    )
    get_workspace_dir(ctx.user_id, ctx.task_id)

    extracted = registry.execute("extract_resume_sections", {}, ctx)
    assert extracted["ok"] is True
    sections = extracted["result"]["data"]["sections"]
    assert sections

    section_index = next(
        (item["index"] for item in sections if "Experience" in item["section_name"]),
        sections[0]["index"],
    )
    section_name = sections[section_index]["section_name"]

    replaced = registry.execute(
        "replace_resume_section",
        {
            "section_index": section_index,
            "section_name": section_name,
            "new_content": "Work Experience\nBuilt resilient APIs",
            "reason": "Target backend role",
        },
        ctx,
    )
    diff = registry.execute("generate_modification_diff", {}, ctx)

    assert replaced["ok"] is True
    assert replaced["result"]["data"]["section_name"] == section_name
    assert replaced["result"]["data"]["stream_preview_file"] == "stream_preview.md"
    assert diff["ok"] is True
    assert "Built resilient APIs" in diff["result"]["data"]["content"]
    assert "Built resilient APIs" in tool_read_file(ctx.user_id, ctx.task_id, "stream_preview.md")

    raw_log = tool_write_file(ctx.user_id, ctx.task_id, "probe.json", json.dumps({"ok": True}))
    assert raw_log


def test_finalize_resume_artifacts_rejects_missing_modification_log(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path))
    registry = AgentToolRegistry()
    ctx = AgentToolContext(user_id="u1", task_id="no-edits", resume_text="Projects\nBuilt APIs", jd_text="Backend")

    result = registry.execute("finalize_resume_artifacts", {}, ctx)

    assert result["ok"] is False
    assert "modification_log.json" in result["error"]
