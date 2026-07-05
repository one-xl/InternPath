import json

from fastapi.testclient import TestClient

from backend.agent_resume import check_resume_fact_integrity
from backend.agents.cache import (
    FileAgentCacheStore,
    PostgresAgentCacheStore,
    RedisAgentCacheStore,
    build_cache_key,
    get_agent_cache,
    set_agent_cache,
)
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
            "jd_text": "招聘 Python 后端实习生，\n要求熟悉 FastAPI。",
            "config_id": None,
            "is_co_pilot": False,
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["cacheHit"] is True
    assert data["taskId"] == task_id


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
            "jd_text": "Backend intern role requiring\nFastAPI and SQL.",
            "config_id": None,
            "is_co_pilot": False,
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
            "jd_text": jd_text,
            "config_id": "cfg-1",
            "is_co_pilot": True,
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
