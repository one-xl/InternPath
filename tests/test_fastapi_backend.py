from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import create_app
from config import Config
from database import Database
from models import JobAnalysis
from service import CareerPathAIService


class _FakeAnalyzer:
    def extract_skills(self, jd_text: str, *args, **kwargs) -> JobAnalysis:
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
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    service = _service_with_tmp_storage(tmp_path, monkeypatch)
    app = create_app(service=service, auth_db=Database(str(tmp_path / "auth.db")))
    client = TestClient(app)

    register_response = client.post(
        "/api/auth/register",
        json={"username": "demo@example.com", "password": "password123"},
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


def test_register_requires_email_code_and_accepts_dev_code(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", True)
    monkeypatch.setattr(Config, "SMTP_HOST", "")
    service = _service_with_tmp_storage(tmp_path, monkeypatch)
    app = create_app(service=service, auth_db=Database(str(tmp_path / "auth.db")))
    client = TestClient(app)

    without_code = client.post(
        "/api/auth/register",
        json={"username": "verify@example.com", "password": "password123"},
    )
    assert without_code.status_code == 400

    code_response = client.post(
        "/api/auth/send-email-code",
        json={"username": "verify@example.com"},
    )
    assert code_response.status_code == 200
    code = code_response.json()["devCode"]

    register_response = client.post(
        "/api/auth/register",
        json={
            "username": "verify@example.com",
            "password": "password123",
            "verification_code": code,
        },
    )
    assert register_response.status_code == 200
    assert register_response.json()["user"]["username"] == "verify@example.com"


def test_star_api_payload_length_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    service = _service_with_tmp_storage(tmp_path, monkeypatch)
    app = create_app(service=service, auth_db=Database(str(tmp_path / "auth.db")))
    client = TestClient(app)

    # 1. Register & Auth
    register_response = client.post(
        "/api/auth/register",
        json={"username": "star_test@example.com", "password": "password123"},
    )
    assert register_response.status_code == 200
    token = register_response.json()["token"]

    # 2. Test Input text exceeding 4000 limit -> must be rejected with 422
    too_long_text = "A" * 4001
    bad_response = client.post(
        "/api/star/generate-segment",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "segment_type": "S",
            "input_text": too_long_text
        }
    )
    assert bad_response.status_code == 422

    # 3. Test Input text within 4000 limit -> must pass Pydantic validation (returns 500 because LLM_API_KEY is not configured in test env, but NOT 422)
    normal_text = "A" * 4000
    good_response = client.post(
        "/api/star/generate-segment",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "segment_type": "S",
            "input_text": normal_text
        }
    )
    assert good_response.status_code != 422

