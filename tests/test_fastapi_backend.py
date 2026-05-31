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


def test_fastapi_async_analyze_task_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    service = _service_with_tmp_storage(tmp_path, monkeypatch)
    
    class _SuccessAiServiceClient:
        def analyze_jd(self, **kwargs):
            return {
                "taskId": kwargs["task_id"],
                "status": "success",
                "data": {
                    "finalReport": {"matchScore": {"overall": 90}},
                    "evidenceSummary": {"evidenceCoverage": 1.0, "totalClaims": 1},
                    "hallucinationControl": {"riskLevel": "LOW"},
                    "citations": [{"claimId": "claim-1", "evidenceText": "Python evidence"}],
                    "claims": [{"claim": "Candidate has Python experience."}],
                    "verificationResults": [
                        {
                            "claimId": "claim-1",
                            "claimText": "Candidate has Python experience.",
                            "claimType": "GENERAL",
                            "status": "supported",
                            "confidenceScore": 1.0,
                            "reason": "matched",
                            "evidenceChunks": [{"text": "Python evidence"}],
                        }
                    ],
                    "workflowLogs": [
                        {
                            "nodeName": "JDParserNode",
                            "status": "SUCCESS",
                            "durationMs": 1,
                            "inputSummary": "JD length: 19 chars",
                            "outputSummary": "Parsed 1 tech keywords",
                            "error": None,
                        }
                    ],
                    "qualityEvaluation": {
                        "finalQualityScore": 91,
                        "qualityGrade": "A",
                        "qualityGateStatus": "PASSED",
                        "scores": {
                            "evidenceCoverageScore": 100,
                            "hallucinationRiskScore": 90,
                            "citationCompletenessScore": 100,
                            "resumeHonestyScore": 100,
                            "matchScoreReasonableness": 90,
                        },
                        "issues": [],
                        "summary": "Quality score 91.0, gate PASSED.",
                    },
                },
            }
    service.ai_service_client = _SuccessAiServiceClient()
    
    app = create_app(service=service, auth_db=Database(str(tmp_path / "auth.db")))
    client = TestClient(app)

    register_response = client.post(
        "/api/auth/register",
        json={"username": "async_test@example.com", "password": "password123"},
    )
    token = register_response.json()["token"]

    analyze_response = client.post(
        "/api/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "jd_text": "Need Python FastAPI backend intern with API development experience.",
            "resume_text": "I built a Python service with FastAPI.",
            "knowledge_document_ids": [],
            "expert_options": {},
            "async_mode": True,
        },
    )
    assert analyze_response.status_code == 200
    body = analyze_response.json()
    assert "taskId" in body
    assert body["status"] == "PENDING"
    assert body["async"] is True
    
    task_id = body["taskId"]
    
    task_response = client.get(
        f"/api/analysis/tasks/{task_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert task_response.status_code == 200
    task_body = task_response.json()
    assert task_body["taskId"] == task_id
    assert task_body["status"] in {"SUCCESS", "PROCESSING", "PENDING"}
    if task_body["status"] == "SUCCESS":
        assert task_body["report"] is not None
        assert task_body["record"] is not None

