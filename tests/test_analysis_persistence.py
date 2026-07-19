from pathlib import Path
from uuid import uuid4

import pytest

from config import Config
from database import Database
from document_parser import DocumentParseError, extract_text_from_md_bytes, extract_text_from_txt_bytes
from models import JobAnalysis, PersonalDecision
from service import CareerPathAIService


TEST_DB_DIR = Path(__file__).resolve().parent.parent / ".test_dbs" / "analysis_persistence"


@pytest.fixture
def local_tmp_dir():
    path = TEST_DB_DIR / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    yield path
    for candidate in sorted(path.rglob("*"), reverse=True):
        if candidate.is_file():
            candidate.unlink()
        else:
            candidate.rmdir()
    path.rmdir()


def test_database_analysis_report_roundtrip(local_tmp_dir):
    db = Database(str(local_tmp_dir / "analysis.db"))
    user_id = 1
    task_id = "task-db-1"

    task_row_id = db.create_analysis_task(user_id=user_id, task_id=task_id)
    assert task_row_id > 0

    db.update_analysis_task_status(user_id, task_id, "PROCESSING")
    report_id = db.save_analysis_report(
        user_id=user_id,
        task_id=task_id,
        jd_text="Python backend JD",
        resume_text="Python project",
        knowledge_texts=["FastAPI notes"],
        original_analysis={"skills": ["Python"], "difficulty": "中等", "job_summary": "backend"},
        final_report={"matchScore": {"overall": 80}},
        evidence_summary={"evidenceCoverage": 0.75, "totalClaims": 2},
        hallucination_control={"riskLevel": "LOW"},
        citations=[{"claimId": "claim-1", "evidenceText": "Python project"}],
    )
    db.save_claim_check_results(
        user_id,
        task_id,
        [
            {
                "claimId": "claim-1",
                "claimText": "Candidate has Python experience.",
                "claimType": "GENERAL",
                "status": "supported",
                "confidenceScore": 0.8,
                "reason": "matched evidence",
                "evidenceChunks": [{"text": "Python project"}],
            }
        ],
    )

    report = db.get_analysis_report(user_id, report_id=report_id)
    assert report is not None
    assert report["knowledge_texts"] == ["FastAPI notes"]
    assert report["final_report"]["matchScore"]["overall"] == 80
    assert report["evidence_coverage"] == 0.75

    reports = db.list_analysis_reports(user_id)
    assert [item["id"] for item in reports] == [report_id]

    claims = db.get_claim_check_results(user_id, task_id)
    assert len(claims) == 1
    assert claims[0]["claim_text"] == "Candidate has Python experience."
    assert claims[0]["check_status"] == "supported"
    assert claims[0]["evidence_count"] == 1


def test_database_knowledge_document_roundtrip(local_tmp_dir):
    db = Database(str(local_tmp_dir / "knowledge.db"))
    doc_id = db.create_knowledge_document(
        user_id=1,
        title="Resume",
        file_name="resume.md",
        file_type="md",
        source_type="resume",
        raw_text="Python project experience",
    )
    chunks = [
        {
            "chunkIndex": 0,
            "text": "Python project experience",
            "tokenCount": 25,
            "metadata": {"fileName": "resume.md", "sourceType": "resume"},
        }
    ]
    db.save_knowledge_chunks(1, doc_id, chunks)
    db.update_knowledge_document_status(1, doc_id, "READY", chunk_count=1)

    docs = db.list_knowledge_documents(1)
    assert len(docs) == 1
    assert docs[0]["chunk_count"] == 1
    assert docs[0]["status"] == "READY"

    saved_chunks = db.get_knowledge_chunks(1, [doc_id])
    assert len(saved_chunks) == 1
    assert saved_chunks[0]["chunk_text"] == "Python project experience"
    assert saved_chunks[0]["metadata"]["fileName"] == "resume.md"

    assert db.delete_knowledge_document(doc_id, 1) is True
    assert db.get_knowledge_chunks(1, [doc_id]) == []


def test_database_jd_record_preserves_personal_decision(local_tmp_dir):
    db = Database(str(local_tmp_dir / "jd.db"))
    decision = PersonalDecision(
        recommendation="CONSIDER",
        match_score=62,
        decision_reasons=["技能有部分匹配"],
        critical_gaps=["缺少上线项目证据"],
        resume_rewrites=["用 FastAPI 项目经历证明后端能力"],
        evidence_needed=["补充接口性能或部署证据"],
        action_plan=["先改简历，再投递"],
        learning_plan=["补齐 SQL 查询练习"],
    )
    analysis = JobAnalysis(
        skills=["Python", "FastAPI"],
        difficulty="中等",
        job_summary="后端实习岗位",
        personal_decision=decision,
    )

    record_id = db.save_jd_record(1, "Need Python FastAPI", analysis)
    record = db.get_jd_record_by_id(1, record_id)

    assert record is not None
    assert record.analysis.personal_decision is not None
    assert record.analysis.personal_decision.recommendation == "CONSIDER"
    assert record.analysis.personal_decision.match_score == 62


def test_document_parser_text_and_markdown():
    assert extract_text_from_txt_bytes("hello 简历".encode("utf-8")) == "hello 简历"
    assert extract_text_from_md_bytes("# Title\n\ncontent".encode("utf-8")) == "# Title\n\ncontent"
    try:
        extract_text_from_txt_bytes(b"   ")
    except DocumentParseError as exc:
        assert "未提取到有效文本" in str(exc)
    else:
        raise AssertionError("empty text should fail")


class _FakeAiServiceClient:
    def __init__(self):
        self.last_kwargs = None

    def analyze_jd(self, **kwargs):
        self.last_kwargs = kwargs
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


class _FailingAiServiceClient:
    def analyze_jd(self, **kwargs):
        raise RuntimeError("service down")


class _FakeAnalyzer:
    def extract_skills(self, jd_text: str, *args, **kwargs) -> JobAnalysis:
        return JobAnalysis(skills=["Python"], difficulty="中等", job_summary="backend")


def _service_with_tmp_user_db(local_tmp_dir, monkeypatch, client):
    monkeypatch.setattr(Config, "USER_DB_DIR", str(local_tmp_dir / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(local_tmp_dir / "career_path.db"))
    service = object.__new__(CareerPathAIService)
    service.ai_service_client = client
    service.ai_analyzer = _FakeAnalyzer()
    return service


def test_service_analyze_jd_with_guardrails_saves_report(local_tmp_dir, monkeypatch):
    fake_client = _FakeAiServiceClient()
    service = _service_with_tmp_user_db(local_tmp_dir, monkeypatch, fake_client)

    result = service.analyze_jd_with_guardrails(
        user_id=1,
        jd_text="Need Python backend",
        resume_text="Python evidence",
        knowledge_texts=["Backend notes"],
    )

    assert result["saved"] is True
    reports = service.list_analysis_reports(1)
    assert len(reports) == 1
    assert reports[0]["final_report"]["matchScore"]["overall"] == 90
    claims = service.get_claim_check_results(1, result["taskId"])
    assert len(claims) == 1
    logs = service.get_workflow_logs(1, result["taskId"])
    assert len(logs) == 1
    assert logs[0]["nodeName"] == "JDParserNode"
    quality = service.get_quality_evaluation(1, result["taskId"])
    assert quality["qualityGrade"] == "A"
    assert quality["qualityGateStatus"] == "PASSED"


class _UploadedTextFile:
    name = "resume.txt"

    def getvalue(self):
        return b"Python backend project experience. FastAPI service."


def test_service_upload_knowledge_document_and_passes_chunks_to_ai_service(local_tmp_dir, monkeypatch):
    fake_client = _FakeAiServiceClient()
    service = _service_with_tmp_user_db(local_tmp_dir, monkeypatch, fake_client)
    doc = service.upload_knowledge_document(1, _UploadedTextFile(), "resume", title="My Resume")

    assert doc["status"] == "READY"
    assert doc["chunk_count"] >= 1

    service.analyze_jd_with_guardrails(
        user_id=1,
        jd_text="Need Python",
        selected_document_ids=[doc["id"]],
    )
    assert fake_client.last_kwargs is not None
    assert fake_client.last_kwargs["documents"]
    assert fake_client.last_kwargs["documents"][0]["metadata"]["fileName"] == "resume.txt"


def test_service_analyze_jd_with_guardrails_fails_when_ai_service_unavailable(local_tmp_dir, monkeypatch):
    service = _service_with_tmp_user_db(local_tmp_dir, monkeypatch, _FailingAiServiceClient())
    task_id = "tatest-api-key"

    with pytest.raises(RuntimeError, match="增强校验服务调用失败"):
        service.analyze_jd_with_guardrails(
            user_id=1,
            jd_text="Need Python backend",
            resume_text="Python evidence",
            task_id=task_id,
        )

    assert service.list_analysis_reports(1) == []
    db = service.user_db(1)
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT status, error_message FROM analysis_task WHERE user_id = ? AND task_id = ?",
        (1, task_id),
    )
    row = cursor.fetchone()
    conn.close()
    assert row[0] == "FAILED"
    assert "service down" in row[1]


def test_service_build_personal_decision_fails_without_model(local_tmp_dir, monkeypatch):
    service = _service_with_tmp_user_db(local_tmp_dir, monkeypatch, _FailingAiServiceClient())

    with pytest.raises(RuntimeError, match="大模型决策生成失败"):
        service.build_personal_decision(
            jd_text="Need Python FastAPI",
            analysis=JobAnalysis(
                skills=["Python", "FastAPI", "SQL"],
                difficulty="中等",
                job_summary="backend",
            ),
            resume_text="I built a Python backend service with FastAPI.",
        )


def test_database_workflow_logs_roundtrip(local_tmp_dir):
    db = Database(str(local_tmp_dir / "workflow.db"))
    db.save_workflow_logs(
        user_id=1,
        task_id="task-workflow",
        workflow_logs=[
            {
                "nodeName": "JDParserNode",
                "status": "SUCCESS",
                "durationMs": 7,
                "inputSummary": "JD length: 100 chars",
                "outputSummary": "Parsed 3 keywords",
                "error": None,
            },
            {
                "nodeName": "RewriteNode",
                "status": "WARNING",
                "durationMs": 2,
                "inputSummary": "enableRewrite=True",
                "outputSummary": "",
                "error": "rewrite skipped",
            },
        ],
    )

    logs = db.get_workflow_logs(1, "task-workflow")
    assert [log["nodeName"] for log in logs] == ["JDParserNode", "RewriteNode"]
    assert logs[0]["durationMs"] == 7
    assert logs[1]["status"] == "WARNING"
    assert logs[1]["error"] == "rewrite skipped"


def test_database_quality_evaluation_roundtrip(local_tmp_dir):
    db = Database(str(local_tmp_dir / "quality.db"))
    db.save_quality_evaluation(
        user_id=1,
        task_id="task-quality",
        quality_evaluation={
            "finalQualityScore": 52,
            "qualityGrade": "D",
            "qualityGateStatus": "FAILED",
            "scores": {
                "evidenceCoverageScore": 30,
                "hallucinationRiskScore": 30,
                "citationCompletenessScore": 20,
                "resumeHonestyScore": 80,
                "matchScoreReasonableness": 40,
            },
            "issues": [{"type": "SCORE_TOO_HIGH", "severity": "HIGH"}],
            "summary": "low quality",
        },
    )

    quality = db.get_quality_evaluation(1, "task-quality")
    assert quality["finalQualityScore"] == 52
    assert quality["qualityGateStatus"] == "FAILED"
    assert quality["scores"]["citationCompletenessScore"] == 20
    assert quality["issues"][0]["type"] == "SCORE_TOO_HIGH"

    low_quality = db.list_low_quality_reports(1)
    assert len(low_quality) == 1
    assert low_quality[0]["task_id"] == "task-quality"
