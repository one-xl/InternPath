import json

import pytest

from backend.agents.tool_registry import AgentToolContext, AgentToolRegistry
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
