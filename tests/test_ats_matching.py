import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from backend.main import create_app
from config import Config
from database import Database
from models import JobAnalysis
from service import CareerPathAIService
from backend.ats_simulator import simulate_ats_compatibility
from backend.job_import import parse_salary_range

class _FakeAnalyzerWithFunnel:
    def extract_skills(self, jd_text: str, *args, **kwargs) -> JobAnalysis:
        return JobAnalysis(
            skills=["Python", "FastAPI", "React"],
            difficulty="中等",
            job_summary="职位说明：需要 Python, FastAPI 和 React 开发能力。",
        )
        
    def stage2_llm_check(self, user_id, resume_text, jd_text):
        if "fail" in jd_text.lower() or "reject" in jd_text.lower():
            return False, "学历不符合要求"
        return True, ""


class _FailingAiServiceClient:
    def analyze_jd(self, **kwargs):
        raise RuntimeError("ai-service unavailable in test")


def _service_with_tmp_storage(tmp_path: Path, monkeypatch) -> CareerPathAIService:
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))
    service = object.__new__(CareerPathAIService)
    service.ai_analyzer = _FakeAnalyzerWithFunnel()
    service.ai_service_client = _FailingAiServiceClient()
    return service


def test_salary_range_parser():
    assert parse_salary_range("15k-25k") == 20.0
    assert parse_salary_range("200-300元/天") == 5.5
    assert parse_salary_range("3-5万/月") == 40.0
    assert parse_salary_range("30-50万/年") == 33.3
    assert parse_salary_range("") == 15.0


def test_ats_simulator():
    resume_text = "张三 的简历\n" * 5 + "教育经历\n清华大学 计算机硕士\n" + "工作经历\n谷歌 软件工程师\n" + "专业技能\nPython, C++, Java, React\n" * 3
    res = simulate_ats_compatibility(
        resume_text=resume_text,
        file_name="resume.pdf",
        jd_text="Need python and react engineer"
    )
    assert res["overall_score"] > 50
    assert res["parseability_score"] == 95.0
    
    # Scanned PDF test
    res_scanned = simulate_ats_compatibility(
        resume_text="Short",
        file_name="scanned.pdf",
        jd_text="Need python"
    )
    assert res_scanned["parseability_score"] == 20.0
    assert len(res_scanned["warnings"]) > 0


def test_job_import_endpoint_and_auto_matching(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    service = _service_with_tmp_storage(tmp_path, monkeypatch)
    app = create_app(service=service, auth_db=Database(str(tmp_path / "auth.db")))
    client = TestClient(app)

    # 1. Register a user
    register_response = client.post(
        "/api/auth/register",
        json={"username": "demo@example.com", "password": "password123"},
    )
    assert register_response.status_code == 200
    token = register_response.json()["token"]
    user_id = register_response.json()["user"]["id"]

    # 2. Upload a parsed resume dummy to allow screening
    db = service.user_db(user_id)
    parsed_resume_mock = {
        "file": {
            "id": "mock_resume_id",
            "name": "resume.pdf",
            "size": 1024,
            "type": "application/pdf"
        },
        "rawText": "My resume with Python and FastAPI skills.",
        "cleanedText": "My resume with Python and FastAPI skills.",
        "chunks": [
            {"chunkIndex": 0, "text": "My resume with Python and FastAPI skills."}
        ],
        "extractedProfile": {}
    }
    db.save_user_resume(
        user_id=user_id,
        resume_id="mock_resume_id",
        file_name="resume.pdf",
        file_size=1024,
        file_type="application/pdf",
        parsed_resume=parsed_resume_mock
    )

    # 3. Test import posting that passes both filters (Stage 1 & 2)
    import_payload = {
        "title": "Python Developer",
        "company": "FastAPI Corp",
        "location": "Beijing",
        "salary_range": "15k-25k",
        "jd_text": "We need a Python and FastAPI developer.",
        "source_url": "https://boss.zhipin.com/job/1"
    }
    response = client.post(
        "/api/jobs/import",
        headers={"Authorization": f"Bearer {token}"},
        json=import_payload
    )
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["jobId"] > 0
    assert res_data["matchResult"]["passed"] is True
    assert res_data["matchResult"]["stage1_score"] > 0.0

    # 4. Test import posting that fails Stage 1 (no keyword overlap)
    fail_payload = {
        "title": "C++ Embedded Engineer",
        "company": "Hardware Corp",
        "location": "Shanghai",
        "salary_range": "15k-25k",
        "jd_text": "We require extensive knowledge in rust, assembly, verilog, microcontrollers, and hardware kernel programming.",
        "source_url": "https://boss.zhipin.com/job/2"
    }
    response_fail = client.post(
        "/api/jobs/import",
        headers={"Authorization": f"Bearer {token}"},
        json=fail_payload
    )
    assert response_fail.status_code == 200
    res_data_fail = response_fail.json()
    assert res_data_fail["matchResult"]["passed"] is False
    assert "较低" in res_data_fail["matchResult"]["reason"]

    # 5. Test import posting that skips Stage 2 (LLM check is bypassed/skipped)
    reject_payload = {
        "title": "Senior Python Developer",
        "company": "FastAPI Corp",
        "location": "Beijing",
        "salary_range": "15k-25k",
        "jd_text": "We need python and fastapi skills. Otherwise we reject.",
        "source_url": "https://boss.zhipin.com/job/3"
    }
    response_reject = client.post(
        "/api/jobs/import",
        headers={"Authorization": f"Bearer {token}"},
        json=reject_payload
    )
    assert response_reject.status_code == 200
    res_data_reject = response_reject.json()
    assert res_data_reject["matchResult"]["passed"] is True

    # 6. Test ATS simulate API endpoint
    simulate_response = client.post(
        "/api/resumes/mock_resume_id/ats-simulate",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "jd_text": "Python FastAPI developer.",
            "jd_id": None
        }
    )
    assert simulate_response.status_code == 200
    sim_data = simulate_response.json()
    assert "overall_score" in sim_data
    assert "parseability_score" in sim_data

    # 7. Test vectorize resume API endpoint
    vectorize_response = client.post(
        "/api/resumes/mock_resume_id/vectorize",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert vectorize_response.status_code == 200
    vec_data = vectorize_response.json()
    assert vec_data["ok"] is True
    assert vec_data["vectorized"] is True
    
    # Verify in DB
    updated_resume = service.user_db(user_id).get_user_resume(user_id, "mock_resume_id")
    assert updated_resume.get("vectorized") is True
    assert len(updated_resume.get("chunks", [])) > 0
    assert "embedding" in updated_resume["chunks"][0]
