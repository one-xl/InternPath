import os
import json
import pytest
from pathlib import Path
from backend.agent_resume import (
    tool_extract_resume_sections,
    tool_replace_resume_section,
    tool_generate_modification_diff,
    get_safe_workspace_path
)
from backend.agents.tools.docx_tools import generate_docx_from_markdown
from backend.main import create_app
from config import Config
from database import Database
from service import CareerPathAIService
from fastapi.testclient import TestClient

# Mock sample resume
SAMPLE_RESUME = """张三
联系电话：13800000000
邮箱：zhangsan@example.com

教育经历
北京大学 - 计算机科学与技术 - 本科 - 2020.09-2024.07

技能
Python, FastAPI, React, Docker

项目经历
项目A：个人求职看板 InternPath
负责实现 AI Agent 简历优化链，重构了大模型交互逻辑。
"""

def test_tool_extract_resume_sections():
    sections_json = tool_extract_resume_sections(SAMPLE_RESUME)
    sections = json.loads(sections_json)

    assert len(sections) > 0
    # First section should be '其他' containing contact info
    assert sections[0]["section_name"] == "其他"
    assert "张三" in sections[0]["content"]
    assert sections[0]["index"] == 0

    # Verify '教育经历' is parsed
    edu_section = next((s for s in sections if s["section_name"] == "教育经历"), None)
    assert edu_section is not None
    assert "北京大学" in edu_section["content"]

    # Verify '项目经历' is parsed
    proj_section = next((s for s in sections if s["section_name"] == "项目经历"), None)
    assert proj_section is not None
    assert "InternPath" in proj_section["content"]


def test_tool_replace_and_diff(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    user_id = 42
    task_id = "test_task"

    # Setup workspace by writing resume_sections.json
    workspace_dir = Path(get_safe_workspace_path(user_id, task_id, "temp.txt")).parent
    sections_json = tool_extract_resume_sections(SAMPLE_RESUME)

    with open(workspace_dir / "resume_sections.json", "w", encoding="utf-8") as f:
        f.write(sections_json)

    # Perform replacement
    res = tool_replace_resume_section(
        user_id=user_id,
        task_id=task_id,
        section_index=2, # index 2 is '技能' (0 is 其他, 1 is 教育经历, 2 is 技能)
        new_content="技能\nPython, Go, Kubernetes, Terraform",
        reason="突出容器化和云原生运维能力"
    )

    assert "成功" in res

    # Read assembled resume
    with open(workspace_dir / "assembled_resume.txt", "r", encoding="utf-8") as f:
        assembled = f.read()
    assert "Go, Kubernetes" in assembled
    assert "北京大学" in assembled # unchanged parts must remain

    # Generate diff
    diff = tool_generate_modification_diff(user_id, task_id)
    assert "突出容器化和云原生运维能力" in diff
    assert "Python, FastAPI" in diff # original text
    assert "Go, Kubernetes" in diff # new text


def test_workspace_path_rejects_traversal_and_absolute_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    user_id = 42
    task_id = "safe-path-task"

    safe_path = Path(get_safe_workspace_path(user_id, task_id, "resume_sections.json"))
    assert safe_path.parent.name == f"task_{task_id}"

    with pytest.raises(PermissionError):
        get_safe_workspace_path(user_id, task_id, "../escape.txt")

    prefix_sibling = f"../task_{task_id}_evil/escape.txt"
    with pytest.raises(PermissionError):
        get_safe_workspace_path(user_id, task_id, prefix_sibling)

    with pytest.raises(PermissionError):
        get_safe_workspace_path(user_id, task_id, str(tmp_path / "absolute.txt"))


def test_docx_tool_generates_docx_from_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    user_id = 42
    task_id = "docx-tool-task"
    docx_path = get_safe_workspace_path(user_id, task_id, "optimized_resume.docx")

    generate_docx_from_markdown(
        user_id=user_id,
        task_id=task_id,
        markdown_content="# 简历\n\n- 负责开发 InternPath。",
        docx_path=docx_path,
    )

    assert Path(docx_path).exists()
    assert Path(docx_path).stat().st_size > 0


def test_api_download_docx_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    # Setup service/app
    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    # Register and create task
    reg = client.post("/api/auth/register", json={"username": "demo@example.com", "password": "password123"})
    token = reg.json()["token"]
    user_id = reg.json()["user"]["id"]
    task_id = "test_api_task"

    # Create the task in DB first
    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id="fake_resume_id",
        original_resume_name="my_resume.md",
        jd_text="fake jd text"
    )

    # Write a fake completed agent task to DB
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="COMPLETED",
        logs="[]",
        optimized_resume_md="### Optimized Resume"
    )
    # Also update original_resume_name
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE agent_resume_tasks SET original_resume_name = ? WHERE task_id = ?",
        ("my_resume.md", task_id)
    )
    conn.commit()

    # Test MD download
    resp = client.get(f"/api/agent/resume/tasks/{task_id}/download", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/markdown; charset=utf-8"
    assert "optimized_my_resume.md" in resp.headers["content-disposition"]

    # Test DOCX download generation (when .docx does not exist in workspace)
    resp_docx_fallback = client.get(
        f"/api/agent/resume/tasks/{task_id}/download?format=docx",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp_docx_fallback.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in resp_docx_fallback.headers["content-type"]
    assert "optimized_my_resume.docx" in resp_docx_fallback.headers["content-disposition"]

    # Now simulate docx creation in workspace
    workspace_dir = Path(get_safe_workspace_path(user_id, task_id, "optimized_resume.docx")).parent
    with open(workspace_dir / "optimized_resume.docx", "w") as f:
        f.write("fake docx content")

    resp_docx_success = client.get(
        f"/api/agent/resume/tasks/{task_id}/download?format=docx",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp_docx_success.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in resp_docx_success.headers["content-type"]
    assert "optimized_my_resume.docx" in resp_docx_success.headers["content-disposition"]
