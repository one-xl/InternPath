import json

from fastapi.testclient import TestClient

from backend.main import create_app
from config import Config
from database import Database
from service import CareerPathAIService


def _register(client: TestClient, username: str) -> tuple[str, str]:
    reg = client.post("/api/auth/register", json={"username": username, "password": "password123"})
    assert reg.status_code == 200
    return reg.json()["token"], str(reg.json()["user"]["id"])


def _save_resume(db: Database, user_id: str, resume_id: str) -> None:
    db.save_user_resume(
        user_id=user_id,
        resume_id=resume_id,
        file_name="resume.docx",
        file_size=128,
        file_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        parsed_resume={
            "file": {"id": resume_id, "name": "resume.docx", "size": 128, "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            "cleanedText": "项目经历\n负责开发 InternPath 简历优化工作台。",
            "rawText": "项目经历\n负责开发 InternPath 简历优化工作台。",
            "chunks": [],
        },
    )


def test_agent_resume_mock_api_e2e_auto_dialog_cache_and_download(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    token, user_id = _register(client, "mock-e2e@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    resume_id = "resume_mock_e2e"
    _save_resume(db, user_id, resume_id)

    enqueue_calls: list[dict] = []

    def fake_enqueue(_job_func, **kwargs):
        enqueue_calls.append(kwargs)
        task_id = kwargs["task_id"]
        is_co_pilot = bool(kwargs.get("is_co_pilot"))
        task = db.get_agent_resume_task(user_id, task_id)
        if is_co_pilot and task and task.get("status") == "PENDING":
            db.update_agent_resume_task_status(
                task_id=task_id,
                user_id=user_id,
                status="WAITING_FOR_HUMAN",
                pending_question="请补充项目量化数据？",
                    execution_plan=json.dumps({
                        "config_id": kwargs.get("config_id"),
                        "is_co_pilot": True,
                        "execution_mode": kwargs.get("execution_mode"),
                        "tool_calling_mode": kwargs.get("tool_calling_mode"),
                        "steps": [
                        {
                            "step_index": 1,
                            "section_index": 0,
                            "section_name": "项目经历",
                            "original_content": "项目经历\n负责开发 InternPath 简历优化工作台。",
                            "improvement_goal": "突出工程结果",
                            "status": "PENDING",
                        }
                    ],
                    "cache_stats": {"hits": 0, "misses": 1, "saved_model_calls": 0, "items": []},
                }, ensure_ascii=False),
            )
            db.add_agent_resume_turn(
                task_id=task_id,
                user_id=user_id,
                step_index=1,
                role="assistant",
                content="请补充项目量化数据？",
            )
            return {"id": task_id}

        db.update_agent_resume_task_status(
            task_id=task_id,
            user_id=user_id,
            status="COMPLETED",
            optimized_resume_md="# 优化后的简历\n\n项目经历\n- 负责开发 InternPath 简历优化工作台。",
            pending_question="",
            human_answer="",
                execution_plan=json.dumps({
                    "config_id": kwargs.get("config_id"),
                    "is_co_pilot": is_co_pilot,
                    "execution_mode": kwargs.get("execution_mode"),
                    "tool_calling_mode": kwargs.get("tool_calling_mode"),
                    "steps": [],
                "cache_stats": {
                    "hits": 1,
                    "misses": 1,
                    "saved_model_calls": 2,
                    "items": [
                        {
                            "namespace": "job_decode_v2",
                            "label": "JD 解码",
                            "hit": True,
                            "saved_model_calls": 1,
                            "timestamp": "2026-07-05T00:00:00",
                        }
                    ],
                },
            }, ensure_ascii=False),
        )
        return {"id": task_id}

    monkeypatch.setattr("backend.main.enqueue_job", fake_enqueue)

    auto_resp = client.post(
        "/api/agent/resume/optimize",
        headers=headers,
        json={
            "resume_id": resume_id,
            "jd_text": "招聘 Python 后端实习生，要求熟悉 FastAPI。",
            "config_id": None,
            "is_co_pilot": False,
        },
    )
    assert auto_resp.status_code == 200
    auto_task_id = auto_resp.json()["taskId"]

    auto_detail = client.get(f"/api/agent/resume/tasks/{auto_task_id}", headers=headers)
    assert auto_detail.status_code == 200
    assert auto_detail.json()["status"] == "COMPLETED"
    assert auto_detail.json()["cacheStats"]["hits"] == 1

    cache_resp = client.post(
        "/api/agent/resume/optimize",
        headers=headers,
        json={
            "resume_id": resume_id,
            "jd_text": "招聘 Python 后端实习生，\n要求熟悉 FastAPI。",
            "config_id": None,
            "is_co_pilot": False,
        },
    )
    assert cache_resp.status_code == 200
    assert cache_resp.json()["cacheHit"] is True
    assert cache_resp.json()["taskId"] == auto_task_id

    download_resp = client.get(f"/api/agent/resume/tasks/{auto_task_id}/download", headers=headers)
    assert download_resp.status_code == 200
    assert "优化后的简历" in download_resp.text

    dialog_resp = client.post(
        "/api/agent/resume/optimize",
        headers=headers,
        json={
            "resume_id": resume_id,
            "jd_text": "招聘 Agent 平台工程师，要求能解释项目结果。",
            "config_id": None,
            "is_co_pilot": True,
        },
    )
    assert dialog_resp.status_code == 200
    dialog_task_id = dialog_resp.json()["taskId"]

    waiting_detail = client.get(f"/api/agent/resume/tasks/{dialog_task_id}", headers=headers).json()
    assert waiting_detail["status"] == "WAITING_FOR_HUMAN"
    assert waiting_detail["conversationTurns"][0]["role"] == "assistant"

    answer_resp = client.post(
        f"/api/agent/resume/tasks/{dialog_task_id}/answer",
        headers=headers,
        json={
            "answer_text": "将人工整理时间减少 50%",
            "answer_type": "evidence",
            "remember": False,
            "evidence_scope": "current_step",
        },
    )
    assert answer_resp.status_code == 200

    final_detail = client.get(f"/api/agent/resume/tasks/{dialog_task_id}", headers=headers).json()
    assert final_detail["status"] == "COMPLETED"
    assert any(turn["role"] == "user" and turn["answerType"] == "evidence" for turn in final_detail["conversationTurns"])
    assert len(enqueue_calls) >= 3
