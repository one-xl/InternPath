import json

from fastapi.testclient import TestClient

import backend.main as main_module
from backend.agent_resume import check_resume_fact_integrity
from backend.agents.cache import (
    FileAgentCacheStore,
    PostgresAgentCacheStore,
    RedisAgentCacheStore,
    build_cache_key,
    get_agent_cache,
    set_agent_cache,
)
from backend.agents.tools.workspace_tools import tool_write_file
from backend.main import create_app
from config import Config
from database import Database
from service import CareerPathAIService


def test_agent_cache_key_normalizes_whitespace(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))

    key_a = build_cache_key("jd", "  Python\n后端  开发 ")
    key_b = build_cache_key("jd", "Python 后端 开发")
    assert key_a == key_b

    set_agent_cache("unit", key_a, {"ok": True})
    assert get_agent_cache("unit", key_b) == {"ok": True}


def test_agent_cache_key_changes_when_prompt_hash_changes(tmp_path):
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("version one", encoding="utf-8")
    key_one = build_cache_key("job_decode_v2", "same jd", prompt_files=[str(prompt_file)])

    prompt_file.write_text("version two", encoding="utf-8")
    key_two = build_cache_key("job_decode_v2", "same jd", prompt_files=[str(prompt_file)])

    assert key_one != key_two


def test_agent_cache_key_ignores_prompt_absolute_location(tmp_path):
    first_dir = tmp_path / "first-install"
    second_dir = tmp_path / "second-install"
    first_dir.mkdir()
    second_dir.mkdir()
    first_prompt = first_dir / "resume_copywriter.md"
    second_prompt = second_dir / "resume_copywriter.md"
    first_prompt.write_text("same prompt content", encoding="utf-8")
    second_prompt.write_text("same prompt content", encoding="utf-8")

    key_one = build_cache_key("resume_advisor_draft_v1", "same input", prompt_files=[str(first_prompt)])
    key_two = build_cache_key("resume_advisor_draft_v1", "same input", prompt_files=[str(second_prompt)])

    assert key_one == key_two


def test_file_agent_cache_store_respects_ttl(tmp_path):
    store = FileAgentCacheStore(base_dir=str(tmp_path / "cache"), ttl_seconds=0)
    store.set("ttl-unit", "key", {"ok": True})
    assert store.get("ttl-unit", "key") == {"ok": True}

    expiring_store = FileAgentCacheStore(base_dir=str(tmp_path / "cache-expiring"), ttl_seconds=1)
    expiring_store.set("ttl-unit", "key", {"ok": True})
    cache_file = tmp_path / "cache-expiring" / "ttl-unit.json"
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    payload["key"]["created_at"] = "2000-01-01T00:00:00"
    cache_file.write_text(json.dumps(payload), encoding="utf-8")

    assert expiring_store.get("ttl-unit", "key") is None


def test_redis_agent_cache_store_roundtrip_and_clear():
    class FakeRedis:
        def __init__(self):
            self.data = {}
            self.ttls = {}
            self.setex_calls = []

        def get(self, key):
            return self.data.get(key)

        def set(self, key, value):
            self.data[key] = value

        def setex(self, key, ttl, value):
            self.ttls[key] = ttl
            self.setex_calls.append((key, ttl))
            self.data[key] = value

        def scan_iter(self, match):
            import fnmatch

            return [key for key in self.data if fnmatch.fnmatch(key, match)]

        def delete(self, *keys):
            for key in keys:
                self.data.pop(key, None)

    fake = FakeRedis()
    store = RedisAgentCacheStore(redis_client=fake, ttl_seconds=60)
    store.set("agent unit", "key-1", {"ok": True})

    assert store.get("agent unit", "key-1") == {"ok": True}
    assert [ttl for _, ttl in fake.setex_calls] == [60, 60]

    store.clear_namespace("agent unit")
    assert store.get("agent unit", "key-1") is None


def test_postgres_agent_cache_store_roundtrip_and_clear(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))
    db = Database(str(tmp_path / "agent-cache.db"))
    store = PostgresAgentCacheStore(db=db, ttl_seconds=0)

    store.set("postgres-unit", "key-1", {"ok": True})

    assert store.get("postgres-unit", "key-1") == {"ok": True}
    store.clear_namespace("postgres-unit")
    assert store.get("postgres-unit", "key-1") is None


def test_fact_integrity_blocks_new_hard_facts_and_accepts_evidence():
    original = "项目经历\n负责开发数据看板，优化页面交互。"
    optimized = "项目经历\n负责开发数据看板，将首屏耗时降低 40%。"

    blocked = check_resume_fact_integrity(original, optimized)
    assert blocked["ok"] is False
    assert "新增量化指标" in blocked["message"]

    accepted = check_resume_fact_integrity(original, optimized, evidence_text="首屏耗时降低 40%")
    assert accepted["ok"] is True


def test_agent_optimize_reuses_matching_completed_task(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "cache@example.com", "password": "password123"})
    token = reg.json()["token"]
    user_id = reg.json()["user"]["id"]

    resume_id = "resume_cache_1"
    db.save_user_resume(
        user_id=user_id,
        resume_id=resume_id,
        file_name="resume.docx",
        file_size=128,
        file_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        parsed_resume={
            "file": {"id": resume_id, "name": "resume.docx", "size": 128, "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            "cleanedText": "项目经历\n负责开发求职工作台。",
            "rawText": "项目经历\n负责开发求职工作台。",
            "chunks": [],
        },
    )

    task_id = "agent-resume-cache-hit"
    jd_text = "招聘 Python 后端实习生，要求熟悉 FastAPI。"
    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id=resume_id,
        original_resume_name="resume.docx",
        jd_text=jd_text,
    )
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="COMPLETED",
        optimized_resume_md="优化结果",
        execution_plan=json.dumps({"config_id": None, "is_co_pilot": False, "steps": []}, ensure_ascii=False),
    )

    resp = client.post(
        "/api/agent/resume/optimize",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "resume_id": resume_id,
            "legacy_mode": True,
            "jd_text": "招聘 Python 后端实习生，\n要求熟悉 FastAPI。",
            "config_id": None,
            "is_co_pilot": False,
            "executionMode": "pipeline",
            "toolCallingMode": "auto",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["cacheHit"] is True
    assert data["taskId"] == task_id


def test_agent_retry_failed_task_requeues_same_task_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    enqueued = []

    def fake_enqueue(func, *args, **kwargs):
        enqueued.append({"func": func, "args": args, "kwargs": kwargs})
        return object()

    monkeypatch.setattr(main_module, "enqueue_job", fake_enqueue)

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "retry@example.com", "password": "password123"})
    token = reg.json()["token"]
    user_id = reg.json()["user"]["id"]

    resume_id = "resume_retry_1"
    db.save_user_resume(
        user_id=user_id,
        resume_id=resume_id,
        file_name="resume.docx",
        file_size=128,
        file_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        parsed_resume={
            "file": {"id": resume_id, "name": "resume.docx", "size": 128, "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            "cleanedText": "Project: built an InternPath agent workflow.",
            "rawText": "Project: built an InternPath agent workflow.",
            "chunks": [],
        },
    )

    task_id = "agent-resume-retry-failed"
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
        error_message="upstream 503",
        logs=json.dumps([
            {
                "timestamp": "2026-07-05T20:32:50",
                "type": "error",
                "message": "调用大模型失败: upstream 503",
                "stage": "hr_critic",
                "agent": "HRCritic",
            }
        ], ensure_ascii=False),
        execution_plan=json.dumps({
            "config_id": "cfg-retry",
            "is_co_pilot": False,
            "steps": [
                {"step_index": 1, "status": "COMPLETED"},
                {"step_index": 2, "status": "PENDING"},
            ],
        }, ensure_ascii=False),
    )

    resp = client.post(
        f"/api/agent/resume/tasks/{task_id}/retry",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json()["taskId"] == task_id
    assert enqueued
    queued_kwargs = enqueued[0]["kwargs"]
    assert queued_kwargs["task_id"] == task_id
    assert queued_kwargs["user_id"] == user_id
    assert queued_kwargs["config_id"] == "cfg-retry"
    assert queued_kwargs["is_co_pilot"] is False
    assert queued_kwargs["job_id"].startswith(f"{task_id}:retry:")

    retried_task = db.get_agent_resume_task(user_id, task_id)
    assert retried_task["status"] == "RUNNING"
    assert retried_task["error_message"] == ""
    logs = json.loads(retried_task["logs"])
    assert logs[-1]["stage"] == "retry"
    assert "同一份简历" in logs[-1]["message"]


def test_agent_optimize_reuses_legacy_completed_task_without_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "legacy-cache@example.com", "password": "password123"})
    token = reg.json()["token"]
    user_id = reg.json()["user"]["id"]

    resume_id = "resume_legacy_cache"
    db.save_user_resume(
        user_id=user_id,
        resume_id=resume_id,
        file_name="resume.docx",
        file_size=128,
        file_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        parsed_resume={
            "file": {"id": resume_id, "name": "resume.docx", "size": 128, "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            "cleanedText": "Project: built a job matching dashboard.",
            "rawText": "Project: built a job matching dashboard.",
            "chunks": [],
        },
    )

    task_id = "agent-resume-legacy-cache-hit"
    jd_text = "Backend intern role requiring FastAPI and SQL."
    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id=resume_id,
        original_resume_name="resume.docx",
        jd_text=jd_text,
    )
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="COMPLETED",
        optimized_resume_md="Optimized result",
    )

    resp = client.post(
        "/api/agent/resume/optimize",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "resume_id": resume_id,
            "legacy_mode": True,
            "jd_text": "Backend intern role requiring\nFastAPI and SQL.",
            "config_id": None,
            "is_co_pilot": False,
            "executionMode": "pipeline",
            "toolCallingMode": "auto",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["cacheHit"] is True
    assert data["cacheHitSource"] == "legacy_completed_result"
    assert data["taskId"] == task_id


def test_agent_optimize_reuses_bootstrap_pending_task(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "bootstrap-cache@example.com", "password": "password123"})
    token = reg.json()["token"]
    user_id = reg.json()["user"]["id"]

    resume_id = "resume_bootstrap_cache"
    db.save_user_resume(
        user_id=user_id,
        resume_id=resume_id,
        file_name="resume.docx",
        file_size=128,
        file_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        parsed_resume={
            "file": {"id": resume_id, "name": "resume.docx", "size": 128, "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            "cleanedText": "Project: built a job matching dashboard.",
            "rawText": "Project: built a job matching dashboard.",
            "chunks": [],
        },
    )

    task_id = "agent-resume-bootstrap-cache-hit"
    jd_text = "Backend intern role requiring FastAPI and SQL."
    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id=resume_id,
        original_resume_name="resume.docx",
        jd_text=jd_text,
    )
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="PENDING",
        execution_plan=json.dumps({
            "bootstrap_only": True,
            "config_id": "cfg-1",
            "is_co_pilot": True,
            "steps": [],
        }, ensure_ascii=False),
    )

    resp = client.post(
        "/api/agent/resume/optimize",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "resume_id": resume_id,
            "legacy_mode": True,
            "jd_text": jd_text,
            "config_id": "cfg-1",
            "is_co_pilot": True,
            "executionMode": "pipeline",
            "toolCallingMode": "auto",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["cacheHit"] is True
    assert data["cacheHitSource"] == "matching_agent_task"
    assert data["taskId"] == task_id


def test_agent_task_status_returns_cache_stats(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "cache-stats@example.com", "password": "password123"})
    token = reg.json()["token"]
    user_id = reg.json()["user"]["id"]

    task_id = "agent-resume-cache-stats"
    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id="resume_stats",
        original_resume_name="resume.docx",
        jd_text="Backend intern role.",
    )
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="RUNNING",
        logs=json.dumps([
            {
                "timestamp": "2026-07-04T00:00:01",
                "type": "info",
                "message": "JD decode finished",
                "traceId": "trace-cache",
                "stage": "job_decode",
                "agent": "JobDecoder",
                "status": "completed",
                "durationMs": 123,
                "modelId": "mock-model",
            }
        ], ensure_ascii=False),
        execution_plan=json.dumps({
            "steps": [],
            "cache_stats": {
                "hits": 2,
                "misses": 1,
                "saved_model_calls": 4,
                "items": [
                    {
                        "namespace": "job_decode_v2",
                        "label": "JD decode",
                        "hit": True,
                        "saved_model_calls": 1,
                        "timestamp": "2026-07-04T00:00:00",
                    }
                ],
            },
        }, ensure_ascii=False),
    )

    resp = client.get(
        f"/api/agent/resume/tasks/{task_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert "cacheStats" in body
    assert "cache_stats" not in body
    assert "conversationTurns" in body
    assert "conversation_turns" not in body
    assert "optimizedResumeMd" in body
    assert "optimized_resume_md" not in body
    cache_stats = body["cacheStats"]
    assert cache_stats["hits"] == 2
    assert cache_stats["misses"] == 1
    assert cache_stats["hitRate"] == 67
    assert cache_stats["savedModelCalls"] == 4
    assert cache_stats["items"][0]["label"] == "JD decode"
    assert cache_stats["items"][0]["savedModelCalls"] == 1
    metrics = body["stageMetrics"]
    assert any(item["stage"] == "job_decode" and item["durationMs"] == 123 for item in metrics)
    assert any(item["cacheNamespace"] == "job_decode_v2" and item["cacheHits"] >= 1 for item in metrics)
    assert body["conversationState"] == {
        "summary": "",
        "globalPreferences": [],
        "factLedger": [],
        "updatedAt": "",
    }


def test_agent_task_events_stream_logs_and_cache_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "cache-stream@example.com", "password": "password123"})
    token = reg.json()["token"]
    user_id = reg.json()["user"]["id"]

    task_id = "agent-resume-cache-stream"
    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id="resume_stream",
        original_resume_name="resume.docx",
        jd_text="Backend intern role.",
    )
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="COMPLETED",
        logs=json.dumps([
            {
                "timestamp": "2026-07-04T00:00:01",
                "type": "info",
                "message": "JD decode cache hit",
                "stage": "cache",
                "agent": "Cache",
                "cacheNamespace": "job_decode_v2",
                "cacheHit": True,
            }
        ], ensure_ascii=False),
        optimized_resume_md="optimized",
        execution_plan=json.dumps({
            "steps": [],
            "cache_stats": {
                "hits": 1,
                "misses": 1,
                "saved_model_calls": 1,
                "items": [],
            },
        }, ensure_ascii=False),
    )
    tool_write_file(user_id, task_id, "stream_preview.md", "streaming preview")

    with client.stream(
        "GET",
        f"/api/agent/resume/tasks/{task_id}/events",
        headers={"Authorization": f"Bearer {token}"},
    ) as resp:
        body = "".join(resp.iter_text())

    assert resp.status_code == 200
    assert "event: connected" in body
    assert "event: agent_log" in body
    assert "event: snapshot" in body
    assert "event: done" in body
    assert '"streamPreviewMd": "streaming preview"' in body
    assert '"eventStreamMeta"' in body
    assert '"artifactMode": "full"' in body
    assert '"hitRate": 50' in body


def test_agent_task_events_stream_emits_retry_available(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "retry-stream@example.com", "password": "password123"})
    token = reg.json()["token"]
    user_id = reg.json()["user"]["id"]

    task_id = "agent-resume-retry-stream"
    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id="resume_retry_stream",
        original_resume_name="resume.docx",
        jd_text="Backend intern role.",
    )
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="FAILED",
        error_message="provider disconnected",
        logs=json.dumps([
            {
                "timestamp": "2026-07-04T00:00:01",
                "type": "error",
                "message": "Tool failed",
                "stage": "tool_result",
                "agent": "AgenticToolLoop",
                "traceId": task_id,
                "status": "failed",
            }
        ], ensure_ascii=False),
        execution_plan=json.dumps({
            "failure_point": {
                "failed_stage": "tool_result",
                "failed_tool_name": "replace_resume_section",
                "failed_tool_arguments": {"section_index": 2, "new_content": "same data"},
                "failed_model_input_ref": "turn:3",
                "failed_sequence": 7,
                "retry_count": 1,
                "error": "provider disconnected",
            }
        }, ensure_ascii=False),
    )

    with client.stream(
        "GET",
        f"/api/agent/resume/tasks/{task_id}/events",
        headers={"Authorization": f"Bearer {token}"},
    ) as resp:
        body = "".join(resp.iter_text())

    assert resp.status_code == 200
    assert "event: retry_available" in body
    assert '"failedToolName": "replace_resume_section"' in body
    assert '"section_index": 2' in body
    assert '"sequence": 7' in body


def test_agent_task_events_stream_emits_live_modification_patch(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "patch-stream@example.com", "password": "password123"})
    token = reg.json()["token"]
    user_id = reg.json()["user"]["id"]

    task_id = "agent-resume-live-patch"
    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id="resume_patch_stream",
        original_resume_name="resume.docx",
        jd_text="Backend intern role.",
    )
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="WAITING_FOR_HUMAN",
        logs=json.dumps([
            {
                "timestamp": "2026-07-04T00:00:01",
                "type": "tool_response",
                "message": "Tool replace_resume_section completed.",
                "stage": "tool_result",
                "agent": "AgenticToolLoop",
                "traceId": task_id,
                "status": "completed",
                "detail": {
                    "tool_name": "replace_resume_section",
                    "ok": True,
                },
            }
        ], ensure_ascii=False),
    )
    tool_write_file(user_id, task_id, "modification_log.json", json.dumps([
        {
            "section_name": "Work Experience",
            "section_index": 1,
            "original": "Built APIs",
            "new": "Built reliable FastAPI services",
            "reason": "match backend JD",
        }
    ], ensure_ascii=False))

    with client.stream(
        "GET",
        f"/api/agent/resume/tasks/{task_id}/events",
        headers={"Authorization": f"Bearer {token}"},
    ) as resp:
        body = "".join(resp.iter_text())

    assert resp.status_code == 200
    assert "event: modification_patch" in body
    assert '"section_name": "Work Experience"' in body
    assert '"new": "Built reliable FastAPI services"' in body
