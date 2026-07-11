import os
import io
import json
import time
import zipfile
import pytest
import requests
import http.server
import threading
from pathlib import Path
from xml.sax.saxutils import escape
from backend.agent_resume import (
    tool_extract_resume_sections,
    tool_replace_resume_section,
    tool_generate_modification_diff,
    get_safe_workspace_path
)

def create_minimal_docx(text: str) -> bytes:
    """Helper to create a minimal valid docx structure in memory."""
    xml_header = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        '<w:body>\n'
    )
    xml_footer = (
        '</w:body>\n'
        '</w:document>'
    )
    paragraphs = []
    for line in text.splitlines():
        if line.strip():
            # Minimal XML paragraph with text element
            p_xml = f'<w:p><w:r><w:t>{escape(line.strip())}</w:t></w:r></w:p>'
            paragraphs.append(p_xml)
    doc_xml = xml_header + "\n".join(paragraphs) + xml_footer

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
        )
        z.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
        )
        z.writestr(
            "word/_rels/document.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>""",
        )
        z.writestr("word/document.xml", doc_xml.encode("utf-8"))
    return buf.getvalue()

# Mock OpenAI Server Handler
class MockOpenAIHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_POST(self):
        if self.path in ("/v1/chat/completions", "/chat/completions"):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            payload = json.loads(body)

            has_tools = "tools" in payload
            messages = payload.get("messages", [])

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            if not has_tools:
                # Helper tool calls
                system_prompt = ""
                for msg in messages:
                    if msg.get("role") == "system":
                        system_prompt = msg.get("content", "")

                content = "Mocked Completion Response"
                if "GAP" in system_prompt or "GAP" in body:
                    content = (
                        "### GAP 分析报告\n\n"
                        "| 段落名 | 修改紧迫度(高/中/低) | 修改方向 | 预期效果 |\n"
                        "| 项目经历 | 高 | 突出React | 提高匹配度 |"
                    )
                elif "润色" in system_prompt or "改写" in system_prompt or "STAR" in body:
                    content = "项目经历\n- 负责实现基于 React 的前端看板项目，适配大模型接口。"
                elif "幻觉" in system_prompt or "幻觉" in body:
                    content = "是否存在幻觉风险？否\n通过验证。"

                response_data = {
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": content
                            },
                            "finish_reason": "stop"
                        }
                    ]
                }
                self.wfile.write(json.dumps(response_data).encode("utf-8"))
            else:
                # Agent REACT loop
                tool_calls = []
                content = None
                finish_reason = "tool_calls"

                msg_count = len(messages)
                if msg_count <= 3:
                    # Turn 1: extract_resume_sections
                    tool_calls = [
                        {
                            "id": "call_extract",
                            "type": "function",
                            "function": {
                                "name": "extract_resume_sections",
                                "arguments": "{}"
                            }
                        }
                    ]
                elif msg_count in (4, 5):
                    # Turn 2: analyze_resume_gap
                    tool_calls = [
                        {
                            "id": "call_gap",
                            "type": "function",
                            "function": {
                                "name": "analyze_resume_gap",
                                "arguments": "{}"
                            }
                        }
                    ]
                elif msg_count in (6, 7):
                    # Turn 3: rewrite, verify, replace
                    tool_calls = [
                        {
                            "id": "call_rewrite",
                            "type": "function",
                            "function": {
                                "name": "rewrite_resume_section",
                                "arguments": json.dumps({
                                    "section_name": "项目经历",
                                    "original_content": "项目A：个人求职看板 InternPath\n负责实现 AI Agent 简历优化链",
                                    "improvement_goal": "突出React"
                                })
                            }
                        },
                        {
                            "id": "call_verify",
                            "type": "function",
                            "function": {
                                "name": "verify_anti_hallucination",
                                "arguments": json.dumps({
                                    "original_content": "项目A：个人求职看板 InternPath\n负责实现 AI Agent 简历优化链",
                                    "optimized_content": "项目经历\n- 负责实现基于 React 的前端看板项目，适配大模型接口。"
                                })
                            }
                        },
                        {
                            "id": "call_replace",
                            "type": "function",
                            "function": {
                                "name": "replace_resume_section",
                                "arguments": json.dumps({
                                    "section_index": 2,
                                    "new_content": "项目经历\n- 负责实现基于 React 的前端看板项目，适配大模型接口。",
                                    "reason": "突出React"
                                })
                            }
                        }
                    ]
                elif msg_count >= 8 and msg_count <= 12:
                    # Turn 4: generate_modification_diff, write optimized_resume.md
                    tool_calls = [
                        {
                            "id": "call_diff",
                            "type": "function",
                            "function": {
                                "name": "generate_modification_diff",
                                "arguments": "{}"
                            }
                        },
                        {
                            "id": "call_write",
                            "type": "function",
                            "function": {
                                "name": "write_workspace_file",
                                "arguments": json.dumps({
                                    "filename": "optimized_resume.md",
                                    "content": (
                                        "# 优化后的简历\n\n"
                                        "## 基本信息\n姓名：张三\n\n"
                                        "## 教育经历\n北京大学\n\n"
                                        "## 项目经历\n- 负责实现基于 React 的前端看板项目，适配大模型接口。"
                                    )
                                })
                            }
                        }
                    ]
                else:
                    # Final turn: completed
                    content = "优化任务已全部成功完成！"
                    finish_reason = "stop"

                response_data = {
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": content,
                                "tool_calls": tool_calls if tool_calls else None
                            },
                            "finish_reason": finish_reason
                        }
                    ]
                }
                self.wfile.write(json.dumps(response_data).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

@pytest.fixture(scope="module", autouse=True)
def run_mock_openai_server():
    server = http.server.HTTPServer(("127.0.0.1", 9099), MockOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    yield
    server.shutdown()

def test_agent_resume_e2e():
    """
    E2E test for Agent Resume Optimization Workflow.
    It calls the running backend server on port 8787.
    """
    if os.getenv("INTERNPATH_RUN_LIVE_E2E") != "1":
        pytest.skip("Set INTERNPATH_RUN_LIVE_E2E=1 to run live backend/worker E2E.")

    base_url = "http://127.0.0.1:8787"

    # 1. Login
    login_payload = {
        "username": "admin@example.com",
        "password": "ChangeMe123!"
    }

    session = requests.Session()
    try:
        resp = session.post(f"{base_url}/api/auth/login", json=login_payload, timeout=5)
    except requests.exceptions.ConnectionError:
        pytest.skip("Backend server is not running on port 8787. Skipping E2E test.")

    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Upload Resume as .docx
    resume_text = (
        "基本信息\n"
        "姓名：张三\n"
        "联系电话：13800000000\n\n"
        "教育经历\n"
        "北京大学 - 计算机科学与技术 - 本科 - 2020-2024\n\n"
        "项目经历\n"
        "项目A：个人求职看板 InternPath\n"
        "负责实现 AI Agent 简历优化链，重构了大模型交互逻辑。\n\n"
        "技能\n"
        "Python, React, Docker"
    )

    docx_bytes = create_minimal_docx(resume_text)
    resume_file_name = f"test_resume_e2e_{int(time.time() * 1000)}.docx"
    files = {
        "file": (resume_file_name, docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    }

    resp = session.post(f"{base_url}/api/resumes/upload", files=files, headers=headers, timeout=5)
    assert resp.status_code == 200, f"Upload failed: {resp.text}"
    resume_id = resp.json()["parsedResume"]["file"]["id"]
    assert resume_id is not None

    # 3. Trigger Optimize Task
    optimize_payload = {
        "resume_id": resume_id,
        "legacy_mode": True,
        "jd_text": "招聘 React 前端开发工程师，熟悉 AI Agent 看板。",
        "config_id": None,
        "is_co_pilot": False,
    }

    resp = session.post(f"{base_url}/api/agent/resume/optimize", json=optimize_payload, headers=headers, timeout=5)
    assert resp.status_code == 200, f"Optimize trigger failed: {resp.text}"
    task_id = resp.json()["taskId"]
    assert task_id is not None

    # 4. Poll task status
    completed = False
    poll_interval_seconds = 3
    max_wait_seconds = int(os.getenv("INTERNPATH_AGENT_E2E_TIMEOUT_SECONDS", "300"))
    for _ in range(max_wait_seconds // poll_interval_seconds):
        time.sleep(poll_interval_seconds)
        resp = session.get(f"{base_url}/api/agent/resume/tasks/{task_id}", headers=headers, timeout=5)
        assert resp.status_code == 200
        data = resp.json()

        status = data["status"]
        if status == "COMPLETED":
            completed = True
            break
        elif status == "FAILED":
            pytest.fail(f"Agent optimization task failed: {data.get('errorMessage')}")

    assert completed, f"Task did not complete within {max_wait_seconds} seconds."

    # 5. Verify assertions
    resp = session.get(f"{base_url}/api/agent/resume/tasks/{task_id}", headers=headers, timeout=5)
    data = resp.json()

    # Assert status
    assert data["status"] == "COMPLETED"

    # Assert logs contain the observable optimization stages.
    logs_str = json.dumps(data["logs"], ensure_ascii=False)
    required_log_markers = [
        "已成功提取原始简历",
        "岗位画像解码完成",
        "防幻觉审查完成",
        "物理替换更新已落盘",
        "优化流水线执行全部完成",
    ]
    for marker in required_log_markers:
        assert marker in logs_str, f"Required stage '{marker}' was not logged."

    # Assert optimizedResumeMd contains basic info and education titles
    opt_md = data["optimizedResumeMd"]
    assert opt_md is not None and opt_md.strip() != ""
    assert "基本信息" in opt_md
    assert "教育经历" in opt_md

    # Assert download works
    download_resp = session.get(f"{base_url}/api/agent/resume/tasks/{task_id}/download", headers=headers, timeout=5)
    assert download_resp.status_code == 200
    assert download_resp.text == opt_md


def test_agent_resume_tools_unit(tmp_path, monkeypatch):
    """
    Unit test fallback to directly verify the three core tool functions:
    tool_extract_resume_sections, tool_replace_resume_section, and tool_generate_modification_diff.
    """
    # Override user db directory
    monkeypatch.setattr("config.Config.USER_DB_DIR", str(tmp_path / "user_data"))

    user_id = 999
    task_id = "test_unit_task"

    sample_text = (
        "基本信息\n"
        "姓名：张三\n"
        "电话：13800000000\n\n"
        "教育经历\n"
        "清华大学 - 计算机 - 本科\n\n"
        "项目经历\n"
        "项目A：求职平台\n"
        "负责开发后端功能。\n\n"
        "技能\n"
        "Python, SQL"
    )

    # 1. Test tool_extract_resume_sections
    sections_json = tool_extract_resume_sections(sample_text)
    sections = json.loads(sections_json)

    assert len(sections) >= 4
    # First section should contain basic info
    assert "基本信息" in sections[0]["content"] or "张三" in sections[0]["content"]

    # 2. Setup workspace directory for replacement test
    workspace_dir = Path(get_safe_workspace_path(user_id, task_id, "temp.txt")).parent
    with open(workspace_dir / "resume_sections.json", "w", encoding="utf-8") as f:
        f.write(sections_json)

    # 3. Test tool_replace_resume_section
    # Find "项目经历" section index
    proj_idx = next(s["index"] for s in sections if "项目经历" in s["content"] or s["section_name"] == "项目经历")

    replacement_content = "项目经历\n- 负责开发高并发求职平台后端服务，使用 FastAPI 和 Redis 优化性能。"
    res = tool_replace_resume_section(
        user_id=user_id,
        task_id=task_id,
        section_index=proj_idx,
        new_content=replacement_content,
        reason="突出高并发与FastAPI"
    )

    assert "成功" in res

    # Verify assembled_resume.txt exists and only modified the target section
    with open(workspace_dir / "assembled_resume.txt", "r", encoding="utf-8") as f:
        assembled = f.read()
    assert "FastAPI 和 Redis" in assembled
    assert "清华大学" in assembled # education remains unchanged

    # 4. Test tool_generate_modification_diff (which creates modification_diff.md)
    diff = tool_generate_modification_diff(user_id, task_id)
    assert "突出高并发与FastAPI" in diff
    assert "负责开发后端功能" in diff
    assert "FastAPI 和 Redis" in diff

    # Verify modification_diff.md was generated
    diff_file_path = workspace_dir / "modification_diff.md"
    assert diff_file_path.exists()
    assert diff_file_path.read_text(encoding="utf-8") == diff
