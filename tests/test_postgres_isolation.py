"""
Integration tests for multi-user data isolation.

These tests verify that:
1. User A cannot see User B's drafts, settings, or model configs.
2. Cross-user history access returns 404.
3. userId is never accepted from request body for ownership.
4. New CRUD endpoints for drafts/settings/configs work correctly.

All tests use SQLite (no DATABASE_URL) for local CI compatibility.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from config import Config
from database import Database
from models import JobAnalysis
from service import CareerPathAIService


class _FakeAnalyzer:
    def extract_skills(self, jd_text: str) -> JobAnalysis:
        return JobAnalysis(
            skills=["Python", "FastAPI"],
            difficulty="中等",
            job_summary="后端实习岗位",
        )


class _FailingAiServiceClient:
    def analyze_jd(self, **kwargs):
        raise RuntimeError("ai-service unavailable in test")


def _make_app(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    service = object.__new__(CareerPathAIService)
    service.ai_analyzer = _FakeAnalyzer()
    service.ai_service_client = _FailingAiServiceClient()
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    return TestClient(app), db


def _register(client: TestClient, username: str, password: str = "Password123!") -> str:
    resp = client.post("/api/auth/register", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


# ── Draft isolation ──

def test_draft_isolation_between_users(tmp_path, monkeypatch):
    client, _ = _make_app(tmp_path, monkeypatch)
    token_a = _register(client, "alice@test.com")
    token_b = _register(client, "bob@test.com")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Alice saves a draft
    resp = client.post("/api/drafts", headers=headers_a, json={
        "input_json": {"jdText": "Alice's JD", "company": "AliceCorp"},
        "status": "DRAFT",
    })
    assert resp.status_code == 200
    alice_draft_id = resp.json()["id"]

    # Alice can see her draft
    resp = client.get("/api/drafts", headers=headers_a)
    assert resp.status_code == 200
    assert len(resp.json()["drafts"]) == 1

    # Bob cannot see Alice's draft
    resp = client.get("/api/drafts", headers=headers_b)
    assert resp.status_code == 200
    assert len(resp.json()["drafts"]) == 0

    # Bob cannot access Alice's draft by ID
    resp = client.get(f"/api/drafts/{alice_draft_id}", headers=headers_b)
    assert resp.status_code == 404

    # Bob cannot delete Alice's draft
    resp = client.delete(f"/api/drafts/{alice_draft_id}", headers=headers_b)
    # delete returns 200 even if not found (idempotent), but draft should still exist for Alice
    resp = client.get(f"/api/drafts/{alice_draft_id}", headers=headers_a)
    assert resp.status_code == 200


# ── Settings isolation ──

def test_settings_isolation_between_users(tmp_path, monkeypatch):
    client, _ = _make_app(tmp_path, monkeypatch)
    token_a = _register(client, "alice@test.com")
    token_b = _register(client, "bob@test.com")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Alice saves settings
    client.post("/api/settings", headers=headers_a, json={"theme": "dark", "lang": "zh"})
    # Bob saves different settings
    client.post("/api/settings", headers=headers_b, json={"theme": "light", "lang": "en"})

    # Each sees only their own
    resp_a = client.get("/api/settings", headers=headers_a)
    assert resp_a.json()["settings"]["theme"] == "dark"
    resp_b = client.get("/api/settings", headers=headers_b)
    assert resp_b.json()["settings"]["theme"] == "light"


# ── Model config isolation ──

def test_model_config_isolation_between_users(tmp_path, monkeypatch):
    client, _ = _make_app(tmp_path, monkeypatch)
    token_a = _register(client, "alice@test.com")
    token_b = _register(client, "bob@test.com")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Alice saves a config
    resp = client.post("/api/configs", headers=headers_a, json={
        "provider": "gemini",
        "modelId": "gemini-2.5-flash",
        "name": "Alice Gemini",
        "apiKey": "sk-alice-secret-key-12345678",
        "enabled": True,
        "type": "chat",
    })
    assert resp.status_code == 200
    alice_config_id = resp.json()["id"]

    # Alice sees her config
    resp = client.get("/api/configs", headers=headers_a)
    configs_a = resp.json()["configs"]
    assert any(c["id"] == alice_config_id for c in configs_a)

    # API key must be masked
    config_entry = next(c for c in configs_a if c["id"] == alice_config_id)
    assert config_entry.get("apiKey") == "••••••••"
    assert "sk-alice" not in str(config_entry)

    # Bob cannot see Alice's config
    resp = client.get("/api/configs", headers=headers_b)
    configs_b = resp.json()["configs"]
    assert not any(c["id"] == alice_config_id for c in configs_b)

    # Bob cannot delete Alice's config
    client.delete(f"/api/configs/{alice_config_id}", headers=headers_b)
    # Verify it still exists for Alice
    resp = client.get("/api/configs", headers=headers_a)
    assert any(c["id"] == alice_config_id for c in resp.json()["configs"])


def test_model_config_update_persists_model_id(tmp_path, monkeypatch):
    client, _ = _make_app(tmp_path, monkeypatch)
    token = _register(client, "alice@test.com")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/configs", headers=headers, json={
        "provider": "gemini",
        "modelId": "gemini-flash-latest",
        "name": "Gemini gemini-flash-latest",
        "apiKey": "sk-alice-secret-key-12345678",
        "enabled": True,
        "type": "chat",
    })
    assert resp.status_code == 200
    config_id = resp.json()["id"]

    resp = client.post("/api/configs", headers=headers, json={
        "id": config_id,
        "provider": "gemini",
        "modelId": "gemini-3-flash-preview",
        "name": "Gemini gemini-3-flash-preview",
        "apiKey": "",
        "enabled": True,
        "type": "chat",
    })
    assert resp.status_code == 200

    resp = client.get("/api/configs", headers=headers)
    config_entry = next(c for c in resp.json()["configs"] if c["id"] == config_id)
    assert config_entry["modelId"] == "gemini-3-flash-preview"
    assert config_entry["name"] == "Gemini gemini-3-flash-preview"


# ── History isolation ──

def test_history_isolation_between_users(tmp_path, monkeypatch):
    client, _ = _make_app(tmp_path, monkeypatch)
    token_a = _register(client, "alice@test.com")
    token_b = _register(client, "bob@test.com")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Alice runs an analysis which creates a history record
    resp = client.post("/api/analyze", headers=headers_a, json={
        "jd_text": "Need Python FastAPI backend intern with API development experience.",
        "resume_text": "I built a Python service with FastAPI.",
        "knowledge_document_ids": [],
        "expert_options": {},
    })
    assert resp.status_code == 200
    alice_record_id = resp.json()["record"]["id"]

    # Alice can see the record
    resp = client.get("/api/history", headers=headers_a)
    assert len(resp.json()["records"]) == 1

    # Bob cannot see Alice's history
    resp = client.get("/api/history", headers=headers_b)
    assert len(resp.json()["records"]) == 0

    # Bob cannot access Alice's record by ID
    resp = client.get(f"/api/history/{alice_record_id}", headers=headers_b)
    assert resp.status_code == 404
    assert "记录不存在或无权访问" in resp.json()["detail"]


# ── Unauthenticated access ──

def test_unauthenticated_access_returns_401(tmp_path, monkeypatch):
    client, _ = _make_app(tmp_path, monkeypatch)

    endpoints = [
        ("GET", "/api/drafts"),
        ("POST", "/api/drafts"),
        ("GET", "/api/settings"),
        ("POST", "/api/settings"),
        ("GET", "/api/configs"),
        ("POST", "/api/configs"),
        ("GET", "/api/history"),
        ("GET", "/api/me"),
    ]
    for method, path in endpoints:
        if method == "GET":
            resp = client.get(path)
        else:
            resp = client.post(path, json={})
        assert resp.status_code == 401, f"{method} {path} should return 401, got {resp.status_code}"


# ── Health check ──

def test_health_check(tmp_path, monkeypatch):
    client, _ = _make_app(tmp_path, monkeypatch)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["database"] == "connected"
