import json

from fastapi.testclient import TestClient

from backend.main import create_app
from config import Config
from database import Database
from service import CareerPathAIService


class _FakeRedis:
    def __init__(self):
        self.data = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        self.data.pop(key, None)

    def eval(self, _script, _numkeys, key, value):
        if self.data.get(key) == value:
            self.delete(key)
            return 1
        return 0


def test_agent_resume_job_defaults_to_pipeline(monkeypatch):
    from backend import jobs
    import backend.agents.orchestrator as orchestrator_module
    import backend.agents.agentic_orchestrator as agentic_module

    calls = []

    class _PipelineOrchestrator:
        async def run_orchestration(self, **kwargs):
            calls.append(("pipeline", kwargs))

    class _AgenticOrchestrator:
        async def run_orchestration(self, **kwargs):
            calls.append(("agentic", kwargs))

    monkeypatch.setattr(orchestrator_module, "Orchestrator", lambda: _PipelineOrchestrator())
    monkeypatch.setattr(agentic_module, "AgenticOrchestrator", lambda: _AgenticOrchestrator())
    monkeypatch.setattr(jobs, "get_redis_connection", lambda: _FakeRedis())
    monkeypatch.setattr(jobs, "log_event", lambda **_kwargs: None)

    jobs.run_agent_resume_orchestration_job(
        task_id="task-pipeline",
        user_id=7,
        config_id="cfg-1",
        is_co_pilot=False,
    )

    assert calls == [
        (
            "pipeline",
            {
                "task_id": "task-pipeline",
                "user_id": 7,
                "config_id": "cfg-1",
                "is_co_pilot": False,
            },
        )
    ]


def test_agent_resume_job_routes_agentic_mode(monkeypatch):
    from backend import jobs
    import backend.agents.orchestrator as orchestrator_module
    import backend.agents.agentic_orchestrator as agentic_module

    calls = []

    class _PipelineOrchestrator:
        async def run_orchestration(self, **kwargs):
            calls.append(("pipeline", kwargs))

    class _AgenticOrchestrator:
        async def run_orchestration(self, **kwargs):
            calls.append(("agentic", kwargs))

    monkeypatch.setattr(orchestrator_module, "Orchestrator", lambda: _PipelineOrchestrator())
    monkeypatch.setattr(agentic_module, "AgenticOrchestrator", lambda: _AgenticOrchestrator())
    monkeypatch.setattr(jobs, "get_redis_connection", lambda: _FakeRedis())
    monkeypatch.setattr(jobs, "log_event", lambda **_kwargs: None)

    jobs.run_agent_resume_orchestration_job(
        task_id="task-agentic",
        user_id=7,
        config_id="cfg-1",
        is_co_pilot=True,
        execution_mode="agentic",
        tool_calling_mode="json_action",
    )

    assert calls == [
        (
            "agentic",
            {
                "task_id": "task-agentic",
                "user_id": 7,
                "config_id": "cfg-1",
                "is_co_pilot": True,
                "tool_calling_mode": "json_action",
            },
        )
    ]


def test_agent_optimize_accepts_agentic_mode_fields(tmp_path, monkeypatch):
    import backend.main as main_module

    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    enqueued = []

    def fake_enqueue(_func, *args, **kwargs):
        enqueued.append({"args": args, "kwargs": kwargs})
        return object()

    monkeypatch.setattr(main_module, "enqueue_job", fake_enqueue)

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "agentic-mode@example.com", "password": "password123"})
    assert reg.status_code == 200
    token = reg.json()["token"]
    user_id = str(reg.json()["user"]["id"])

    resume_id = "resume-agentic-mode"
    db.save_user_resume(
        user_id=user_id,
        resume_id=resume_id,
        file_name="resume.docx",
        file_size=128,
        file_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        parsed_resume={
            "file": {"id": resume_id, "name": "resume.docx", "size": 128, "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            "cleanedText": "Projects\nBuilt an InternPath resume workflow.",
            "rawText": "Projects\nBuilt an InternPath resume workflow.",
            "chunks": [],
        },
    )

    response = client.post(
        "/api/agent/resume/optimize",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "resume_id": resume_id,
            "jd_text": "Backend internship requiring FastAPI, LLM workflow, and resume automation experience.",
            "config_id": None,
            "is_co_pilot": True,
            "executionMode": "agentic",
            "toolCallingMode": "json_action",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["executionMode"] == "agentic"
    assert data["toolCallingMode"] == "json_action"
    assert data["task"]["taskId"] == data["taskId"]
    assert data["task"]["streamPreviewMd"]
    response_log_stages = [item["stage"] for item in data["task"]["logs"]]
    assert "bootstrap" in response_log_stages
    assert "workspace_prewarm" in response_log_stages
    assert "queue" in response_log_stages
    assert enqueued
    queued_kwargs = enqueued[0]["kwargs"]
    assert queued_kwargs["execution_mode"] == "agentic"
    assert queued_kwargs["tool_calling_mode"] == "json_action"

    task = db.get_agent_resume_task(user_id, data["taskId"])
    plan = json.loads(task["execution_plan"])
    assert plan["execution_mode"] == "agentic"
    assert plan["tool_calling_mode"] == "json_action"
    logs = json.loads(task["logs"])
    assert any(item["stage"] == "workspace_prewarm" for item in logs)
    assert any(item["stage"] == "queue" for item in logs)

    detail = client.get(f"/api/agent/resume/tasks/{data['taskId']}", headers={"Authorization": f"Bearer {token}"})
    assert detail.status_code == 200
    assert detail.json()["executionMode"] == "agentic"
    assert detail.json()["toolCallingMode"] == "json_action"


def test_agent_retry_preserves_agentic_mode_fields(tmp_path, monkeypatch):
    import backend.main as main_module

    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    enqueued = []
    monkeypatch.setattr(
        main_module,
        "enqueue_job",
        lambda _func, *args, **kwargs: enqueued.append({"args": args, "kwargs": kwargs}) or object(),
    )

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "agentic-retry@example.com", "password": "password123"})
    assert reg.status_code == 200
    token = reg.json()["token"]
    user_id = str(reg.json()["user"]["id"])

    resume_id = "resume-agentic-retry"
    db.save_user_resume(
        user_id=user_id,
        resume_id=resume_id,
        file_name="resume.docx",
        file_size=128,
        file_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        parsed_resume={
            "file": {"id": resume_id, "name": "resume.docx", "size": 128, "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            "cleanedText": "Projects\nBuilt an InternPath resume workflow.",
            "rawText": "Projects\nBuilt an InternPath resume workflow.",
            "chunks": [],
        },
    )
    task_id = "agentic-retry-task"
    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id=resume_id,
        original_resume_name="resume.docx",
        jd_text="Backend internship requiring FastAPI and LLM workflow experience.",
    )
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="FAILED",
        error_message="provider disconnected",
        execution_plan=json.dumps({
            "config_id": "cfg-agentic",
            "is_co_pilot": True,
            "execution_mode": "agentic",
            "tool_calling_mode": "json_action",
            "failure_point": {
                "failed_stage": "tool_result",
                "failed_tool_name": "replace_resume_section",
                "failed_tool_arguments": {
                    "section_index": 1,
                    "new_content": "same failed payload",
                    "reason": "retry test",
                },
                "failed_model_input_ref": "turn:3",
                "failed_model_input": {
                    "mode": "json_action",
                    "messages": [{"role": "user", "content": "same model input"}],
                },
                "last_successful_tool_result": {
                    "tool_name": "extract_resume_sections",
                    "ok": True,
                },
                "failed_sequence": 9,
                "retry_count": 1,
            },
            "steps": [],
        }, ensure_ascii=False),
    )

    response = client.post(
        f"/api/agent/resume/tasks/{task_id}/retry",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    queued_kwargs = enqueued[0]["kwargs"]
    assert queued_kwargs["config_id"] == "cfg-agentic"
    assert queued_kwargs["is_co_pilot"] is True
    assert queued_kwargs["execution_mode"] == "agentic"
    assert queued_kwargs["tool_calling_mode"] == "json_action"
    retried_task = db.get_agent_resume_task(user_id, task_id)
    retried_plan = json.loads(retried_task["execution_plan"])
    retry_request = retried_plan["retry_request"]
    assert retry_request["failed_tool_name"] == "replace_resume_section"
    assert retry_request["failed_tool_arguments"]["new_content"] == "same failed payload"
    assert retry_request["failed_sequence"] == 9
    assert retry_request["retry_count"] == 2
    assert retry_request["failed_model_input"]["messages"][0]["content"] == "same model input"
    assert retry_request["last_successful_tool_result"]["tool_name"] == "extract_resume_sections"


def test_agent_answer_preserves_agentic_mode_fields(tmp_path, monkeypatch):
    import backend.main as main_module

    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    enqueued = []
    monkeypatch.setattr(
        main_module,
        "enqueue_job",
        lambda _func, *args, **kwargs: enqueued.append({"args": args, "kwargs": kwargs}) or object(),
    )

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "agentic-answer@example.com", "password": "password123"})
    assert reg.status_code == 200
    token = reg.json()["token"]
    user_id = str(reg.json()["user"]["id"])

    task_id = "agentic-answer-task"
    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id="resume-agentic-answer",
        original_resume_name="resume.docx",
        jd_text="Backend internship requiring FastAPI and LLM workflow experience.",
    )
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="WAITING_FOR_HUMAN",
        pending_question="Confirm verified FastAPI experience.",
        execution_plan=json.dumps({
            "config_id": "cfg-agentic-answer",
            "is_co_pilot": False,
            "execution_mode": "agentic",
            "tool_calling_mode": "json_action",
            "steps": [
                {
                    "step_index": 1,
                    "section_index": 0,
                    "section_name": "Projects",
                    "status": "RUNNING",
                }
            ],
        }, ensure_ascii=False),
    )

    response = client.post(
        f"/api/agent/resume/tasks/{task_id}/answer",
        headers={"Authorization": f"Bearer {token}"},
        json={"answer": "Verified FastAPI and SSE project work.", "answer_type": "evidence"},
    )

    assert response.status_code == 200
    queued_kwargs = enqueued[0]["kwargs"]
    assert queued_kwargs["config_id"] == "cfg-agentic-answer"
    assert queued_kwargs["is_co_pilot"] is False
    assert queued_kwargs["execution_mode"] == "agentic"
    assert queued_kwargs["tool_calling_mode"] == "json_action"


def test_agentic_loop_metrics_detect_successful_finalize():
    from backend.agents.agentic_orchestrator import AgenticOrchestrator

    events = [
        {"type": "model_turn_start", "turn": 1},
        {"type": "tool_call", "tool_name": "replace_resume_section"},
        {"type": "tool_result", "tool_name": "replace_resume_section", "ok": True, "duration_ms": 8},
        {"type": "tool_call", "tool_name": "finalize_resume_artifacts"},
        {"type": "tool_result", "tool_name": "finalize_resume_artifacts", "ok": True, "duration_ms": 15},
        {"type": "provider_usage", "providerCachedTokens": 512},
    ]

    metrics = AgenticOrchestrator._summarize_loop_events(events)

    assert metrics["model_turns"] == 1
    assert metrics["tool_calls"] == 2
    assert metrics["successful_tool_results"] == 2
    assert metrics["finalize_already_completed"] is True
    assert metrics["provider_usage_events"] == 1
    assert AgenticOrchestrator._has_successful_tool_result(events, "finalize_resume_artifacts") is True
    assert AgenticOrchestrator._has_successful_tool_result(
        [{"type": "tool_result", "tool_name": "finalize_resume_artifacts", "ok": False}],
        "finalize_resume_artifacts",
    ) is False


def test_agentic_event_sink_marks_bootstrap_tool_call(monkeypatch):
    from backend.agents.agentic_orchestrator import AgenticOrchestrator

    orchestrator = object.__new__(AgenticOrchestrator)
    logs = []

    def fake_log_step(*_args, **kwargs):
        logs.append({
            "message": _args[3],
            "detail": _args[4],
            "stage": kwargs.get("stage"),
        })

    orchestrator.log_step = fake_log_step
    sink = orchestrator._event_sink("task-1", "user-1", {}, "json_action")

    sink({
        "type": "tool_call",
        "turn": 0,
        "tool_name": "list_workspace_files",
        "arguments": {},
        "bootstrap": True,
        "bootstrap_index": 1,
    })

    assert logs[0]["message"] == "Bootstrap tool: list_workspace_files"
    assert logs[0]["detail"]["bootstrap"] is True
    assert logs[0]["detail"]["bootstrap_index"] == 1


def test_agentic_event_sink_records_model_stream_delta(monkeypatch):
    from backend.agents.agentic_orchestrator import AgenticOrchestrator

    orchestrator = object.__new__(AgenticOrchestrator)
    logs = []

    def fake_log_step(*_args, **kwargs):
        logs.append({
            "message": _args[3],
            "detail": _args[4],
            "stage": kwargs.get("stage"),
            "status": kwargs.get("status"),
        })

    orchestrator.log_step = fake_log_step
    sink = orchestrator._event_sink("task-1", "user-1", {}, "json_action")

    sink({
        "type": "model_stream_delta",
        "turn": 1,
        "mode": "json_action",
        "content": '{"action":"call_tool"',
        "total_chars": 21,
    })

    assert logs[0]["stage"] == "model_stream_delta"
    assert logs[0]["status"] == "running"
    assert "21 public characters" in logs[0]["message"]
    assert logs[0]["detail"]["content"] == '{"action":"call_tool"'


def test_agentic_failure_point_preserves_failed_model_input(monkeypatch):
    from backend.agents.agentic_orchestrator import AgenticOrchestrator

    orchestrator = object.__new__(AgenticOrchestrator)
    saved = []
    orchestrator._save_plan = lambda task_id, user_id, plan_data, tool_calling_mode, status: saved.append(dict(plan_data))
    plan_data = {}
    failed_input = {
        "mode": "native_responses",
        "input_items": [{"role": "user", "content": "same failed input"}],
        "instructions": "same instructions",
        "previous_response_id": "resp_1",
    }

    orchestrator._record_failure_point(
        "task-1",
        "user-1",
        plan_data,
        {
            "failed_stage": "model_turn",
            "failed_model_input_ref": "turn:2",
            "failed_model_input": failed_input,
            "last_successful_tool_result": {"tool_name": "replace_resume_section", "ok": True},
            "failed_sequence": 6,
            "error": "provider disconnected",
        },
        tool_calling_mode="native_responses",
    )

    failure_point = plan_data["failure_point"]
    assert failure_point["failed_stage"] == "model_turn"
    assert failure_point["failed_model_input"] == failed_input
    assert failure_point["last_successful_tool_result"]["tool_name"] == "replace_resume_section"
    assert saved
