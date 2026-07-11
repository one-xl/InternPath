from __future__ import annotations

import base64
import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.main import create_app
from config import Config
from database import Database
from models import JobAnalysis
from service import CareerPathAIService
from backend.resume_advisor.repository import ResumeAdvisorRepository
from backend.resume_advisor.router import build_resume_advisor_router
from backend.resume_advisor.session_module import ResumeAdvisorModule


class _Analyzer:
    def extract_skills(self, _jd_text: str, *args, **kwargs) -> JobAnalysis:
        return JobAnalysis(skills=["Python"], difficulty="中等", job_summary="测试岗位")


def _service(tmp_path: Path, monkeypatch) -> CareerPathAIService:
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))
    service = object.__new__(CareerPathAIService)
    service.ai_analyzer = _Analyzer()
    service.ai_service_client = None
    return service


def _docx_bytes(document_xml: str) -> bytes:
    payload = io.BytesIO()
    with ZipFile(payload, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
    return payload.getvalue()


def test_resume_advisor_event_stream_waits_for_and_forwards_new_deltas(monkeypatch):
    class StreamingModule:
        def __init__(self):
            self.polls = 0

        def list_events(self, *, user_id, session_id, after_sequence=0):
            assert user_id == "u-stream"
            assert session_id == "session-stream"
            self.polls += 1
            if self.polls >= 2 and after_sequence < 1:
                return [
                    {
                        "id": "evt-stream", "sequence": 1, "runId": "run-stream", "type": "model_delta",
                        "messageId": None, "suggestionId": None,
                        "payload": {"delta": "真实 token", "stage": "draft_suggestion"},
                        "createdAt": "2026-07-11T12:00:00",
                    }
                ]
            return []

        def get_run_status(self, *, user_id, session_id):
            return "RUNNING" if self.polls < 2 else "PAUSED"

    monkeypatch.setattr("backend.resume_advisor.router.EVENT_POLL_INTERVAL_SECONDS", 0, raising=False)
    module = StreamingModule()
    app = FastAPI()
    app.include_router(build_resume_advisor_router(module, lambda: "u-stream"))

    response = TestClient(app).get("/api/agent/resume/sessions/session-stream/events?afterSequence=0")

    assert response.status_code == 200
    assert module.polls >= 2
    assert "event: model_delta" in response.text
    assert "真实 token" in response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"


def test_resume_advisor_slo_dashboard_is_scoped_to_current_user():
    class DashboardModule:
        def get_slo_dashboard(self, *, user_id, window_hours):
            assert user_id == "u-operations"
            assert window_hours == 12
            return {
                "windowHours": 12,
                "runCount": 3,
                "metrics": {"endToEndFirstTokenMs": {"p95Ms": 10_200, "thresholdMs": 10_000, "met": False}},
                "alerts": [{"code": "endToEndFirstTokenMs_p95_breach", "severity": "warning"}],
            }

    app = FastAPI()
    app.include_router(build_resume_advisor_router(DashboardModule(), lambda: "u-operations"))

    response = TestClient(app).get("/api/agent/resume/operations/slo?windowHours=12")

    assert response.status_code == 200
    assert response.json()["metrics"]["endToEndFirstTokenMs"]["p95Ms"] == 10_200
    assert response.json()["alerts"][0]["severity"] == "warning"


def test_resume_advisor_session_message_idempotency_and_explicit_finish(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    queued: list[dict] = []

    def fake_enqueue(_func, *args, **kwargs):
        queued.append(kwargs)
        return object()

    monkeypatch.setattr("backend.main.enqueue_job", fake_enqueue)
    auth_db = Database(str(tmp_path / "auth.db"))
    client = TestClient(create_app(service=_service(tmp_path, monkeypatch), auth_db=auth_db))

    register = client.post("/api/auth/register", json={"username": "advisor@example.com", "password": "password123"})
    token = register.json()["token"]
    user_id = register.json()["user"]["id"]
    parsed_resume = {
        "file": {"id": "resume-v1", "name": "resume.docx", "contentHash": "a" * 64, "b64_content": base64.b64encode(b"resume-bytes").decode("ascii")},
        "contentHash": "a" * 64,
        "cleanedText": "项目经历\n- 负责 FastAPI 接口开发",
        "blocks": [
            {
                "id": "block-1", "kind": "bullet", "sectionId": "project_experience",
                "sectionName": "项目经历", "itemLabel": "第 1 条", "text": "- 负责 FastAPI 接口开发",
                "textHash": "b" * 64, "locationLabel": "项目经历 > 第 1 条",
                "locatorConfidence": "approximate", "locator": {"sourceFormat": "docx", "lineStart": 2, "lineEnd": 2},
            }
        ],
    }
    auth_db.save_user_resume(user_id, "resume-v1", "resume.docx", 1, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", parsed_resume, content_hash="a" * 64)
    headers = {"Authorization": f"Bearer {token}"}

    retired = client.post(
        "/api/agent/resume/optimize",
        headers=headers,
        json={"resume_id": "resume-v1", "jd_text": "需要 FastAPI 实习经验"},
    )
    assert retired.status_code == 410

    started = client.post("/api/agent/resume/sessions", headers=headers, json={"resume_id": "resume-v1", "jd_text": "需要 FastAPI 实习经验"})
    assert started.status_code == 200
    session_id = started.json()["session"]["id"]
    assert queued[0]["queue_name"] == Config.RQ_ADVISOR_QUEUE_NAME
    repository = ResumeAdvisorRepository(auth_db)
    repository.update_run(user_id=user_id, run_id=started.json()["run"]["id"], status="PAUSED")
    initial_events = client.get(f"/api/agent/resume/sessions/{session_id}/events?afterSequence=0", headers=headers)
    assert initial_events.status_code == 200
    assert '"sequence": 1' in initial_events.text
    resumed_events = client.get(f"/api/agent/resume/sessions/{session_id}/events?afterSequence=1", headers=headers)
    assert resumed_events.status_code == 200
    assert '"sequence": 1' not in resumed_events.text
    paged_sessions = client.get("/api/agent/resume/sessions?limit=1&offset=0", headers=headers)
    assert paged_sessions.status_code == 200
    assert paged_sessions.json()["limit"] == 1
    assert paged_sessions.json()["offset"] == 0
    assert [item["id"] for item in paged_sessions.json()["sessions"]] == [session_id]

    resume_file = client.get(f"/api/agent/resume/sessions/{session_id}/resume-file", headers=headers)
    assert resume_file.status_code == 200
    assert resume_file.content == b"resume-bytes"
    resume_view = client.get(f"/api/agent/resume/sessions/{session_id}/resume-view", headers=headers)
    assert resume_view.json()["preview"]["sourceFormat"] == "docx"
    forbidden_save = client.post(
        f"/api/agent/resume/tasks/{session_id}/save",
        headers=headers,
        json={"section_index": 0, "new_text": "不应回写原简历"},
    )
    assert forbidden_save.status_code == 410
    forbidden_download = client.get(f"/api/agent/resume/tasks/{session_id}/download", headers=headers)
    assert forbidden_download.status_code == 410
    other = client.post("/api/auth/register", json={"username": "other-advisor@example.com", "password": "password123"})
    other_headers = {"Authorization": f"Bearer {other.json()['token']}"}
    assert client.get(f"/api/agent/resume/sessions/{session_id}/resume-file", headers=other_headers).status_code == 404

    source_suggestion = repository.create_suggestion(
        user_id=user_id,
        session_id=session_id,
        run_id="run-test",
        data={
            "target": {"blockId": "block-1", "sectionId": "project_experience", "sectionName": "项目经历", "sourceFormat": "docx", "locationLabel": "项目经历 > 第 1 条", "locatorConfidence": "approximate"},
            "originalTextHash": "b" * 64,
            "originalText": "- 负责 FastAPI 接口开发",
            "proposedText": "• 负责 FastAPI 接口开发",
            "copyText": "• 负责 FastAPI 接口开发",
            "issue": "统一项目符号",
            "rationale": "不引入新事实",
            "expectedImpact": "便于扫描",
            "priority": "high",
            "jdRequirementIds": [],
            "resumeEvidenceBlockIds": ["block-1"],
            "userFactIds": [],
            "factStatus": "supported",
            "factIssues": [],
            "status": "accepted",
        },
    )
    restored = client.post(
        f"/api/agent/resume/suggestions/{source_suggestion['id']}/actions",
        headers=headers,
        json={"action": "restore"},
    )
    assert restored.status_code == 200
    assert restored.json()["suggestion"]["version"] == 2
    assert restored.json()["suggestion"]["parentSuggestionId"] == source_suggestion["id"]

    unsupported = repository.create_suggestion(
        user_id=user_id,
        session_id=session_id,
        run_id="run-test",
        data={
            **{key: value for key, value in source_suggestion.items() if key not in {"id", "sessionId", "version"}},
            "factStatus": "needs_user",
            "factIssues": ["缺少 Redis 经验的可追溯证据"],
            "status": "proposed",
        },
    )
    blocked_accept = client.post(
        f"/api/agent/resume/suggestions/{unsupported['id']}/actions",
        headers=headers,
        json={"action": "accepted"},
    )
    assert blocked_accept.status_code == 409

    first_message = client.post(
        f"/api/agent/resume/sessions/{session_id}/messages",
        headers=headers,
        json={"content": "请说明为什么这样改", "client_message_id": "client-message-1"},
    )
    second_message = client.post(
        f"/api/agent/resume/sessions/{session_id}/messages",
        headers=headers,
        json={"content": "请说明为什么这样改", "client_message_id": "client-message-1"},
    )
    assert first_message.status_code == 200
    assert second_message.status_code == 200
    assert second_message.json()["duplicate"] is True
    assert len(queued) == 2
    repository.update_run(user_id=user_id, run_id=first_message.json()["run"]["id"], status="PAUSED")

    rejected = client.post(
        f"/api/agent/resume/suggestions/{source_suggestion['id']}/actions",
        headers=headers,
        json={"action": "rejected", "feedback": "这条保留原文，请继续检查其他不足"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["suggestion"]["status"] == "rejected"
    assert rejected.json()["run"] is not None
    repository.update_run(user_id=user_id, run_id=rejected.json()["run"]["id"], status="PAUSED")

    fact_answer = client.post(
        f"/api/agent/resume/sessions/{session_id}/messages",
        headers=headers,
        json={
            "content": "我实际使用 Redis 缓存过热点查询。",
            "client_message_id": "client-message-fact-1",
            "message_kind": "fact",
        },
    )
    assert fact_answer.status_code == 200

    conflict = client.post(
        f"/api/agent/resume/sessions/{session_id}/messages",
        headers=headers,
        json={"content": "第二条并发消息", "client_message_id": "client-message-conflict"},
    )
    assert conflict.status_code == 409

    snapshot = client.get(f"/api/agent/resume/sessions/{session_id}", headers=headers)
    assert snapshot.status_code == 200
    assert snapshot.json()["session"]["sessionStatus"] == "ACTIVE"
    assert snapshot.json()["facts"][-1]["claimValue"] == "我实际使用 Redis 缓存过热点查询。"
    assert snapshot.json()["facts"][-1]["status"] == "confirmed"

    global_fact_id = repository.record_fact(
        user_id=user_id,
        session_id=session_id,
        claim_key="preferred_style",
        claim_value="偏好简洁项目符号",
        source_type="user_message",
        source_id="turn-global",
        status="confirmed",
        scope="global",
    )
    next_session = repository.create_session(
        user_id=user_id,
        resume_id="resume-v1",
        resume_content_hash="a" * 64,
        jd_text="需要 Python 经验",
    )
    assert global_fact_id in {fact["id"] for fact in repository.list_confirmed_facts(user_id, next_session["id"])}

    finished = client.post(f"/api/agent/resume/sessions/{session_id}/finish", headers=headers, json={"confirmation": "satisfied"})
    assert finished.status_code == 200
    assert finished.json()["sessionStatus"] == "SATISFIED"

    deleted = client.delete("/api/resumes/resume-v1", headers=headers)
    assert deleted.status_code == 200
    assert "resume-v1" not in {resume["id"] for resume in client.get("/api/resumes", headers=headers).json()["resumes"]}
    assert client.get(f"/api/agent/resume/sessions/{session_id}/resume-view", headers=headers).status_code == 200
    assert client.get(f"/api/agent/resume/sessions/{session_id}/resume-file", headers=headers).content == b"resume-bytes"
    restored_resume = auth_db.restore_user_resume_by_content_hash(user_id, "a" * 64)
    assert restored_resume["file"]["id"] == "resume-v1"
    assert "resume-v1" in {resume["id"] for resume in client.get("/api/resumes", headers=headers).json()["resumes"]}


def test_same_name_different_resume_content_creates_an_immutable_new_version(tmp_path):
    db = Database(str(tmp_path / "versions.db"))
    user_id = db.create_user("versions@example.com", "password123")
    first = {"file": {"id": "resume-a", "name": "resume.docx", "contentHash": "1" * 64}, "contentHash": "1" * 64}
    second = {"file": {"id": "resume-b", "name": "resume.docx", "contentHash": "2" * 64}, "contentHash": "2" * 64}

    db.save_user_resume(user_id, "resume-a", "resume.docx", 10, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", first, content_hash="1" * 64)
    db.save_user_resume(user_id, "resume-b", "resume.docx", 11, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", second, content_hash="2" * 64)

    versions = {resume["id"]: resume for resume in db.list_user_resumes(user_id)}
    assert versions["resume-a"]["versionNo"] == 1
    assert versions["resume-a"]["isCurrent"] is False
    assert versions["resume-b"]["versionNo"] == 2
    assert versions["resume-b"]["isCurrent"] is True
    assert db.find_user_resume_by_content_hash(user_id, "1" * 64)["file"]["id"] == "resume-a"


def test_resume_advisor_view_repairs_legacy_generic_blocks_before_displaying_them(tmp_path):
    db = Database(str(tmp_path / "legacy-blocks.db"))
    user_id = db.create_user("legacy-blocks@example.com", "password123")
    parsed_resume = {
        "file": {"id": "resume-legacy", "name": "resume.docx", "size": 1, "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "contentHash": "c" * 64},
        "contentHash": "c" * 64,
        "cleanedText": "教育及培训\n浙江大学 计算机科学 本科\n项目/实践\nInternPath 负责接口开发",
        "chunks": [
            {"id": "chunk-1", "content": "教育及培训\n浙江大学 计算机科学 本科", "section": "教育经历", "sectionType": "education"},
            {"id": "chunk-2", "content": "项目/实践\nInternPath 负责接口开发", "section": "项目经历", "sectionType": "project_experience"},
        ],
        "blocks": [
            {"id": "legacy-1", "text": "教育及培训", "sectionName": "其他", "sectionId": "generic_section"},
            {"id": "legacy-2", "text": "InternPath 负责接口开发", "sectionName": "其他", "sectionId": "generic_section"},
        ],
    }
    db.save_user_resume(user_id, "resume-legacy", "resume.docx", 1, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", parsed_resume, content_hash="c" * 64)
    repository = ResumeAdvisorRepository(db)
    session = repository.create_session(user_id=user_id, resume_id="resume-legacy", resume_content_hash="c" * 64, jd_text="需要 FastAPI")

    view = repository.get_resume_view(user_id, session["id"])

    assert [block["sectionName"] for block in view["blocks"]] == ["教育经历", "教育经历", "项目经历", "项目经历"]
    assert [block["sectionName"] for block in db.get_user_resume(user_id, "resume-legacy")["blocks"]] == ["教育经历", "教育经历", "项目经历", "项目经历"]


def test_resume_advisor_view_hides_duplicate_blocks_but_keeps_their_legacy_target_ids(tmp_path):
    db = Database(str(tmp_path / "duplicate-blocks.db"))
    user_id = db.create_user("duplicate-blocks@example.com", "password123")
    parsed_resume = {
        "structureVersion": "resume-structure-v2",
        "file": {"id": "resume-duplicate", "name": "resume.docx", "contentHash": "e" * 64},
        "contentHash": "e" * 64,
        "cleanedText": "项目经历\n负责 FastAPI 接口开发",
        "chunks": [],
        "blocks": [
            {
                "id": "block-primary", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
                "text": "负责 FastAPI 接口开发", "textHash": "f" * 64, "locationLabel": "项目经历 > 第 1 条",
                "locatorConfidence": "high", "locator": {"sourceFormat": "docx", "paragraphIndex": 2},
            },
            {
                "id": "block-duplicate", "kind": "bullet", "sectionId": "project_experience", "sectionName": "项目经历",
                "text": "负责 FastAPI 接口开发", "textHash": "f" * 64, "locationLabel": "项目经历 > 第 2 条",
                "locatorConfidence": "high", "locator": {"sourceFormat": "docx", "paragraphIndex": 5},
            },
        ],
    }
    db.save_user_resume(user_id, "resume-duplicate", "resume.docx", 1, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", parsed_resume, content_hash="e" * 64)
    repository = ResumeAdvisorRepository(db)
    session = repository.create_session(user_id=user_id, resume_id="resume-duplicate", resume_content_hash="e" * 64, jd_text="需要 FastAPI")

    view = repository.get_resume_view(user_id, session["id"])

    assert [block["id"] for block in view["blocks"]] == ["block-primary"]
    assert view["blocks"][0]["legacyBlockIds"] == ["block-duplicate"]


def test_resume_advisor_view_lazily_reparses_and_persists_old_docx_textbox_snapshots(tmp_path):
    data = _docx_bytes(
        """<?xml version="1.0" encoding="UTF-8"?>
        <w:document
          xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
          xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
          xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
          xmlns:v="urn:schemas-microsoft-com:vml">
          <w:body><w:p><mc:AlternateContent>
            <mc:Choice Requires="wps"><w:drawing><wps:wsp><wps:txbx><w:txbxContent>
              <w:p><w:r><w:t>教育背景</w:t></w:r></w:p>
              <w:p><w:r><w:t>暨南大学 软件工程</w:t></w:r></w:p>
            </w:txbxContent></wps:txbx></wps:wsp></w:drawing></mc:Choice>
            <mc:Fallback><w:pict><v:shape><v:textbox><w:txbxContent>
              <w:p><w:r><w:t>教育背景</w:t></w:r></w:p>
              <w:p><w:r><w:t>暨南大学 软件工程</w:t></w:r></w:p>
            </w:txbxContent></v:textbox></v:shape></w:pict></mc:Fallback>
          </mc:AlternateContent></w:p></w:body>
        </w:document>""",
    )
    db = Database(str(tmp_path / "lazy-reparse.db"))
    user_id = db.create_user("lazy-reparse@example.com", "password123")
    parsed_resume = {
        "file": {
            "id": "resume-old-parser",
            "name": "resume.docx",
            "size": len(data),
            "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "contentHash": "9" * 64,
            "b64_content": base64.b64encode(data).decode("ascii"),
        },
        "contentHash": "9" * 64,
        "cleanedText": "教育背景教育背景 暨南大学 软件工程 暨南大学 软件工程",
        "chunks": [],
        "blocks": [{
            "id": "legacy-parent", "kind": "paragraph", "sectionId": "generic_section", "sectionName": "其他",
            "text": "教育背景教育背景 暨南大学 软件工程 暨南大学 软件工程", "textHash": "legacy",
            "locationLabel": "其他 > 第 1 条", "locatorConfidence": "approximate", "locator": {"sourceFormat": "docx"},
        }],
    }
    db.save_user_resume(
        user_id,
        "resume-old-parser",
        "resume.docx",
        len(data),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        parsed_resume,
        content_hash="9" * 64,
    )
    repository = ResumeAdvisorRepository(db)
    session = repository.create_session(
        user_id=user_id,
        resume_id="resume-old-parser",
        resume_content_hash="9" * 64,
        jd_text="需要软件工程背景",
    )

    view = repository.get_resume_view(user_id, session["id"])
    persisted = db.get_user_resume(user_id, "resume-old-parser")

    assert [block["text"] for block in view["blocks"]] == ["教育背景", "暨南大学 软件工程"]
    assert persisted["parser"]["version"] == "v2"
    assert persisted["file"]["id"] == "resume-old-parser"


def test_resume_advisor_treats_free_form_reply_to_an_open_fact_question_as_evidence(tmp_path):
    db = Database(str(tmp_path / "fact-reply.db"))
    user_id = db.create_user("fact-reply@example.com", "password123")
    repository = ResumeAdvisorRepository(db)
    session = repository.create_session(user_id=user_id, resume_id="resume-1", resume_content_hash="d" * 64, jd_text="需要 Redis")
    repository.append_turn(
        user_id=user_id,
        session_id=session["id"],
        role="assistant",
        content="你有 Redis 相关经验吗？",
        message_kind="question",
        payload={"questionKey": "requirement:redis"},
    )
    module = ResumeAdvisorModule(
        db,
        repository=repository,
        enqueue_run=lambda *_args, **_kwargs: None,
    )

    result = module.post_message(
        user_id=user_id,
        session_id=session["id"],
        content="我曾使用 Redis 缓存热点查询。",
        client_message_id="free-form-fact-1",
    )

    assert result["message"]["messageKind"] == "fact"
    facts = repository.list_confirmed_facts(user_id, session["id"])
    assert facts[-1]["claimKey"] == "requirement:redis"
    assert facts[-1]["claimValue"] == "我曾使用 Redis 缓存热点查询。"


def test_resume_advisor_migration_is_repeatable(tmp_path):
    first = Database(str(tmp_path / "migration.db"))
    second = Database(str(tmp_path / "migration.db"))

    conn = second.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = ?", ("20260710_resume_advisor_v1",))
    count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = ?", ("20260710_resume_advisor_v2_soft_delete",))
    soft_delete_count = cursor.fetchone()[0]
    conn.close()

    assert first.schema_name == second.schema_name
    assert count == 1
    assert soft_delete_count == 1
