from pathlib import Path

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
            job_summary="后端实习岗位，需要接口开发和 Python 经验。",
        )


class _FailingAiServiceClient:
    def analyze_jd(self, **kwargs):
        raise RuntimeError("ai-service unavailable in test")


def _service_with_tmp_storage(tmp_path: Path, monkeypatch) -> CareerPathAIService:
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))
    service = object.__new__(CareerPathAIService)
    service.ai_analyzer = _FakeAnalyzer()
    service.ai_service_client = _FailingAiServiceClient()
    return service


def test_fastapi_auth_analyze_and_history_roundtrip(tmp_path, monkeypatch):
    service = _service_with_tmp_storage(tmp_path, monkeypatch)
    app = create_app(service=service, auth_db=Database(str(tmp_path / "auth.db")))
    client = TestClient(app)

    register_response = client.post(
        "/api/auth/register",
        json={"username": "demo", "password": "password123"},
    )
    assert register_response.status_code == 200
    token = register_response.json()["token"]

    analyze_response = client.post(
        "/api/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "jd_text": "Need Python FastAPI backend intern with API development experience.",
            "resume_text": "I built a Python service with FastAPI.",
            "knowledge_document_ids": [],
            "expert_options": {},
        },
    )
    assert analyze_response.status_code == 200
    body = analyze_response.json()
    assert body["record"]["id"] == 1
    assert body["personal_decision"]["recommendation"] in {"APPLY", "CONSIDER", "SKIP"}
    assert body["expert_report"]["status"] == "failed"

    history_response = client.get("/api/history", headers={"Authorization": f"Bearer {token}"})
    assert history_response.status_code == 200
    records = history_response.json()["records"]
    assert len(records) == 1
    assert records[0]["matchScore"] >= 0
