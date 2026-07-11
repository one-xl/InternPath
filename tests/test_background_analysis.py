import json
import sys
import pytest
from pathlib import Path
from uuid import uuid4
from unittest.mock import MagicMock

# Add backend directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from config import Config
from database import Database

TEST_DB_DIR = Path(__file__).resolve().parent.parent / ".test_dbs" / "background_analysis"


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


class MockChatCompletions:
    def __init__(self, fail_mode=False):
        self.fail_mode = fail_mode
        self.call_count = 0

    def create(self, *args, **kwargs):
        if self.fail_mode:
            raise RuntimeError("LLM API timeout")

        self.call_count += 1
        messages = kwargs.get("messages", [])
        prompt = messages[0]["content"] if messages else ""

        # 1. Parse JD prompt
        if "structural requirements and constraints" in prompt or "JD Text to parse" in prompt:
            data = {
                "job_title": "Python Developer",
                "company": "Tech Corp",
                "location": "Beijing",
                "requirements": [
                    {
                        "id": "req_001",
                        "text": "Must have 3+ years of Python experience",
                        "category": "technical",
                        "priority": "must_have",
                        "is_hard_requirement": True,
                        "keywords": ["Python"],
                        "reason": "Backend logic"
                    }
                ],
                "hard_constraints": [
                    {
                        "type": "experience",
                        "text": "3+ years Python",
                        "blocking_level": "blocking"
                    }
                ]
            }
            return self._make_response(json.dumps(data))

        # 2. Hard constraints check prompt
        elif "audit the candidate's resume against the hard constraints" in prompt:
            data = {
                "hard_risks": [
                    {
                        "constraint": "3+ years Python",
                        "type": "experience",
                        "status": "pass",
                        "severity": "minor",
                        "reason": "Candidate has 5 years of Python",
                        "evidence": ["Python developer for 5 years"]
                    }
                ],
                "has_blocking_risk": False
            }
            return self._make_response(json.dumps(data))

        # 3. Main analysis prompt
        else:
            data = {
                "requirement_assessments": [
                    {
                        "requirement_id": "req_001",
                        "requirement_text": "Must have 3+ years of Python experience",
                        "status": "matched",
                        "confidence": "high",
                        "evidence_used": ["chunk-1"],
                        "reason": "Candidate has extensive Python background",
                        "gap": "None",
                        "fixable_by_resume_rewrite": False
                    }
                ],
                "decision": {
                    "decision": "strong_apply",
                    "confidence": "high",
                    "overall_score": 90,
                    "summary": "Excellent match for python backend",
                    "why_this_decision": ["Matches all core requirements"],
                    "main_risks": [],
                    "main_opportunities": ["Strong python background"]
                },
                "matchBreakdown": {
                    "techStack": 95,
                    "projectExperience": 90,
                    "educationBackground": 80,
                    "keywordCoverage": 90,
                    "seniorityFit": 90,
                    "competitionLevel": 70,
                    "evidenceStrength": 90,
                    "resumeImprovementPotential": 80
                },
                "resume_rewrite_suggestions": [
                    {
                        "target_requirement_id": "req_001",
                        "resume_section": "项目经历",
                        "current_problem": "Expressing Python as just a language without scale",
                        "rewrite_strategy": "Highlight Django/FastAPI high concurrency projects",
                        "example_rewrite": "Scaled python FastAPI backend to 10k QPS",
                        "risk": "safe_to_rewrite"
                    }
                ],
                "learning_plan": [
                    {
                        "gap": "Lack of Go experience",
                        "topic": "Go syntax and concurrency",
                        "priority": "medium",
                        "reason": "JD lists Go as nice to have",
                        "suggested_action": "Read Tour of Go",
                        "estimated_effort": "5天"
                    }
                ],
                "interview_prep": [
                    {
                        "topic": "Python GIL and asyncio",
                        "question_type": "技术问答",
                        "reason": "Core python performance concept"
                    }
                ]
            }
            return self._make_response(json.dumps(data))

    def _make_response(self, content):
        mock_choice = MagicMock()
        mock_choice.message.content = content
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response


@pytest.fixture
def test_env(local_tmp_dir, monkeypatch):
    db_path = str(local_tmp_dir / "career_path.db")
    monkeypatch.setattr(Config, "DB_PATH", db_path)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(local_tmp_dir / "user_data"))

    # Instantiate Database in test context
    test_db = Database(db_path)

    # Mock the module-level instances in background_analyzer
    from backend import background_analyzer
    monkeypatch.setattr(background_analyzer, "db", test_db)

    mock_analyzer = MagicMock()
    mock_service = MagicMock()
    monkeypatch.setattr(background_analyzer, "analyzer", mock_analyzer)
    monkeypatch.setattr(background_analyzer, "service", mock_service)

    return {
        "db": test_db,
        "analyzer": mock_analyzer,
        "service": mock_service,
        "background_analyzer": background_analyzer
    }


def test_background_analysis_success(test_env):
    db = test_env["db"]
    mock_analyzer = test_env["analyzer"]
    mock_service = test_env["service"]
    bg_analyzer_module = test_env["background_analyzer"]

    # 1. Create a standard user with limit 5
    user_id = db.create_user(username="test_user", password="secure_password123")

    # Update generation limit to 5 (create_user defaults to 5 anyway, but let's be explicit)
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET generation_limit = 5, role = 'user' WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    # Verify user
    user = db.get_user_by_id(user_id)
    assert user is not None
    assert user.role == "user"
    assert user.generation_limit == 5

    # 2. Save a mock parsed resume
    resume_file_id = "mock-resume-file-id"
    parsed_resume = {
        "file": {
            "name": "resume.pdf",
            "size": 1234,
            "type": "application/pdf",
            "uploadedAt": "2026-06-07T12:00:00"
        },
        "cleanedText": "Python backend developer. Experienced in FastAPI, MySQL and Redis.",
        "extractedProfile": {
            "name": "Test Candidate",
            "education": "Bachelor of Software Engineering"
        },
        "chunks": [
            {
                "id": "chunk-1",
                "content": "Experienced python developer using FastAPI and Django.",
                "section": "experience"
            }
        ]
    }
    db.save_user_resume(
        user_id=user_id,
        resume_id=resume_file_id,
        file_name="resume.pdf",
        file_size=1234,
        file_type="application/pdf",
        parsed_resume=parsed_resume
    )

    # 3. Setup mocks
    mock_chat_client = MagicMock()
    mock_chat_client.chat = MagicMock()
    mock_chat_client.chat.completions = MockChatCompletions()

    mock_analyzer._client.return_value = (
        mock_chat_client,
        "resolved-chat-config-id",
        "mock-provider",
        "mock-model"
    )
    mock_service._resolve_embedding_config.return_value = (
        "mock-emb-provider",
        "mock-emb-model",
        None,
        None
    )
    mock_service.get_embedding_for_text.return_value = [0.1] * 128

    # 4. Insert placeholder record in DB
    record_id = "test-record-id-success"
    draft_data = {
        "jdText": "Python backend software engineer. Must have 3+ years of Python experience. Location Beijing.",
        "candidateMaterial": "None"
    }

    initial_result = {
        "id": record_id,
        "createdAt": "2026-06-07T16:00:00",
        "draft": draft_data,
        "status": "pending",
        "progressStep": 0
    }
    db.save_analysis_record(
        user_id=user_id,
        status="pending",
        result_json=initial_result,
        input_json=draft_data,
        record_id=record_id
    )

    # 5. Run the background analysis task
    bg_analyzer_module.run_background_resume_analysis(
        user_id=user_id,
        record_id=record_id,
        draft_data=draft_data,
        resume_file_id=resume_file_id,
        embedding_config_id="emb-cfg-1",
        chat_config_id=None
    )

    # 6. Assertions
    # Check that record is updated to 'watching' (success)
    record = db.get_analysis_record(user_id, record_id)
    assert record is not None
    assert record.get("status") == "watching"

    # Assert JSON result structures
    assert record.get("matchScore") == 88
    assert record.get("decision") == "strong_yes"
    assert record.get("oneLineReason") == "Excellent match for python backend"
    assert len(record.get("resumeAdvice", [])) == 1
    assert record.get("resumeAdvice")[0]["target_requirement_id"] == "req_001"
    assert record.get("resumeAdvice")[0]["priority"] == "high"
    mock_service._resolve_embedding_config.assert_called_with(user_id, "emb-cfg-1")
    assert mock_service.get_embedding_for_text.call_args_list
    assert all(call.args[2] == "emb-cfg-1" for call in mock_service.get_embedding_for_text.call_args_list)

    # Assert step progression
    steps = record.get("steps", [])
    assert len(steps) == 6
    for step in steps:
        assert step["status"] == "success"

    # Verify user generation limit was decremented
    updated_user = db.get_user_by_id(user_id)
    assert updated_user.generation_limit == 4


def test_background_analysis_agent_resume_uses_langgraph(test_env, monkeypatch):
    db = test_env["db"]
    mock_analyzer = test_env["analyzer"]
    mock_service = test_env["service"]
    bg_analyzer_module = test_env["background_analyzer"]

    user_id = db.create_user(username="test_user_bg_langgraph", password="secure_password123")
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET generation_limit = 5, role = 'user' WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    resume_file_id = "mock-resume-langgraph"
    parsed_resume = {
        "file": {
            "id": resume_file_id,
            "name": "resume.pdf",
            "size": 1234,
            "type": "application/pdf",
        },
        "cleanedText": "Python backend developer. Experienced in FastAPI, MySQL and Redis.",
        "rawText": "Python backend developer. Experienced in FastAPI, MySQL and Redis.",
        "chunks": [
            {
                "id": "chunk-langgraph-1",
                "content": "Experienced python developer using FastAPI and Django.",
                "section": "experience",
            }
        ],
    }
    db.save_user_resume(
        user_id=user_id,
        resume_id=resume_file_id,
        file_name="resume.pdf",
        file_size=1234,
        file_type="application/pdf",
        parsed_resume=parsed_resume,
    )

    mock_chat_client = MagicMock()
    mock_chat_client.chat = MagicMock()
    mock_chat_client.chat.completions = MockChatCompletions()
    mock_analyzer._client.return_value = (
        mock_chat_client,
        "resolved-chat-config-id",
        "mock-provider",
        "mock-model",
    )
    mock_service._resolve_embedding_config.return_value = (
        "mock-emb-provider",
        "mock-emb-model",
        None,
        None,
    )
    mock_service.get_embedding_for_text.return_value = [0.1] * 128

    record_id = "test-record-bg-langgraph"
    draft_data = {
        "jdText": "Python backend software engineer. Must have 3+ years of Python experience. Location Beijing.",
        "candidateMaterial": "None",
    }
    db.save_analysis_record(
        user_id=user_id,
        status="pending",
        result_json={
            "id": record_id,
            "createdAt": "2026-06-07T16:00:00",
            "draft": draft_data,
            "status": "pending",
            "progressStep": 0,
            "enable_agent_resume": True,
            "legacy_artifact_mode": True,
        },
        input_json=draft_data,
        record_id=record_id,
    )

    calls = []

    class _FakeLangGraphAgenticOrchestrator:
        async def run_orchestration(self, **kwargs):
            calls.append(kwargs)
            from backend.agents.tools.workspace_tools import tool_write_file

            tool_write_file(kwargs["user_id"], kwargs["task_id"], "optimized_resume.md", "LangGraph optimized resume")
            db.update_agent_resume_task_status(
                task_id=kwargs["task_id"],
                user_id=kwargs["user_id"],
                status="COMPLETED",
                optimized_resume_md="LangGraph optimized resume",
            )

    import backend.agents.langgraph_orchestrator as langgraph_module

    monkeypatch.setattr(
        langgraph_module,
        "LangGraphAgenticOrchestrator",
        lambda: _FakeLangGraphAgenticOrchestrator(),
    )

    bg_analyzer_module.run_background_resume_analysis(
        user_id=user_id,
        record_id=record_id,
        draft_data=draft_data,
        resume_file_id=resume_file_id,
        embedding_config_id="emb-cfg-langgraph",
        chat_config_id="chat-cfg-langgraph",
        enable_agent_resume=True,
        legacy_artifact_mode=True,
    )

    assert calls == [
        {
            "task_id": record_id,
            "user_id": user_id,
            "config_id": "chat-cfg-langgraph",
            "is_co_pilot": False,
            "tool_calling_mode": "native_responses",
        }
    ]

    task = db.get_agent_resume_task(user_id, record_id)
    assert task["status"] == "COMPLETED"
    plan = json.loads(task["execution_plan"])
    assert plan["execution_mode"] == "agentic"
    assert plan["tool_calling_mode"] == "native_responses"

    record = db.get_analysis_record(user_id, record_id)
    assert record["status"] == "watching"
    assert record["optimized_resume_md"] == "LangGraph optimized resume"
    assert any(step["id"] == "agent_resume" and step["status"] == "success" for step in record["steps"])


def test_background_analysis_repairs_legacy_generic_resume_chunks(test_env):
    db = test_env["db"]
    mock_analyzer = test_env["analyzer"]
    mock_service = test_env["service"]
    bg_analyzer_module = test_env["background_analyzer"]

    user_id = db.create_user(username="test_user_resume_repair", password="secure_password123")
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET generation_limit = 5, role = 'user' WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    resume_file_id = "legacy-generic-resume"
    parsed_resume = {
        "file": {
            "id": resume_file_id,
            "name": "resume.pdf",
            "size": 1234,
            "type": "application/pdf",
            "uploadedAt": "2026-06-07T12:00:00",
        },
        "cleanedText": (
            "赵六 13800000000 zhaoliu@example.com "
            "教育背景 复旦大学 软件工程 本科 "
            "专业技能 Python FastAPI Redis Docker "
            "项目经历 InternPath 分析平台 负责简历 RAG 召回与证据校验。 "
            "实习经历 后端开发实习 负责接口性能优化。"
        ),
        "extractedProfile": {},
        "chunks": [
            {
                "id": "legacy-chunk-0",
                "resumeFileId": resume_file_id,
                "index": 0,
                "content": "赵六 13800000000 zhaoliu@example.com 教育背景 复旦大学 软件工程 本科 专业技能 Python FastAPI Redis Docker 项目经历 InternPath 分析平台 负责简历 RAG 召回与证据校验。 实习经历 后端开发实习 负责接口性能优化。",
                "section": "其他",
                "sectionType": "generic_section",
                "semanticType": "general",
            }
        ],
    }
    db.save_user_resume(
        user_id=user_id,
        resume_id=resume_file_id,
        file_name="resume.pdf",
        file_size=1234,
        file_type="application/pdf",
        parsed_resume=parsed_resume,
    )

    mock_chat_client = MagicMock()
    mock_chat_client.chat = MagicMock()
    mock_chat_client.chat.completions = MockChatCompletions()
    mock_analyzer._client.return_value = (
        mock_chat_client,
        "resolved-chat-config-id",
        "mock-provider",
        "mock-model",
    )
    mock_service._resolve_embedding_config.return_value = (
        "mock-emb-provider",
        "mock-emb-model",
        None,
        None,
    )
    mock_service.get_embedding_for_text.return_value = [0.1] * 128

    record_id = "test-record-repair-generic-chunks"
    draft_data = {
        "jdText": "Python backend software engineer. Must have 3+ years of Python experience. FastAPI Redis Docker RAG platform experience required.",
        "candidateMaterial": "None",
    }
    db.save_analysis_record(
        user_id=user_id,
        status="pending",
        result_json={
            "id": record_id,
            "createdAt": "2026-06-07T16:00:00",
            "draft": draft_data,
            "status": "pending",
            "progressStep": 0,
        },
        input_json=draft_data,
        record_id=record_id,
    )

    bg_analyzer_module.run_background_resume_analysis(
        user_id=user_id,
        record_id=record_id,
        draft_data=draft_data,
        resume_file_id=resume_file_id,
        embedding_config_id="emb-cfg-legacy",
        chat_config_id=None,
    )

    record = db.get_analysis_record(user_id, record_id)
    assert record is not None
    assert record.get("status") == "watching"

    parsed_chunks = record["parsedResume"]["chunks"]
    parsed_sections = [chunk["section"] for chunk in parsed_chunks]
    assert parsed_sections == ["其他", "教育经历", "技能", "项目经历", "实习 / 工作经历"]
    assert {chunk["sectionType"] for chunk in record["retrievedResumeChunks"]} != {"generic_section"}
    assert {chunk["sectionType"] for chunk in parsed_chunks} != {"generic_section"}

    saved_resume = db.get_user_resume(user_id, resume_file_id)
    assert saved_resume is not None
    assert [chunk["section"] for chunk in saved_resume["chunks"]] == parsed_sections


def test_background_analysis_failure(test_env):
    db = test_env["db"]
    mock_analyzer = test_env["analyzer"]
    mock_service = test_env["service"]
    bg_analyzer_module = test_env["background_analyzer"]

    # 1. Create a user
    user_id = db.create_user(username="test_user_fail", password="secure_password123")

    # Set limit to 5
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET generation_limit = 5, role = 'user' WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    # 2. Save mock resume
    resume_file_id = "mock-resume-file-id"
    parsed_resume = {
        "file": {"name": "resume.pdf", "size": 1234, "type": "application/pdf"},
        "cleanedText": "Backend developer.",
        "chunks": [{"id": "chunk-1", "content": "Developer description"}]
    }
    db.save_user_resume(
        user_id=user_id,
        resume_id=resume_file_id,
        file_name="resume.pdf",
        file_size=1234,
        file_type="application/pdf",
        parsed_resume=parsed_resume
    )

    # 3. Setup failing mocks
    mock_chat_client = MagicMock()
    mock_chat_client.chat = MagicMock()
    mock_chat_client.chat.completions = MockChatCompletions(fail_mode=True)

    mock_analyzer._client.return_value = (
        mock_chat_client,
        "resolved-chat-config-id",
        "mock-provider",
        "mock-model"
    )
    mock_service._resolve_embedding_config.return_value = (
        "mock-emb-provider",
        "mock-emb-model",
        None,
        None
    )
    mock_service.get_embedding_for_text.return_value = [0.1] * 128

    # 4. Insert placeholder record in DB
    record_id = "test-record-id-failure"
    draft_data = {
        "jdText": "Python backend software engineer. Must have 3+ years of Python experience. Location Beijing. Strong communication skills.",
        "candidateMaterial": "None"
    }

    initial_result = {
        "id": record_id,
        "createdAt": "2026-06-07T16:00:00",
        "draft": draft_data,
        "status": "pending",
        "progressStep": 0,
        "steps": [
            { "id": "validate", "title": "检查输入与配置", "status": "running" },
            { "id": "resume_embedding", "title": "向量化简历片段", "status": "pending" },
            { "id": "jd_embedding", "title": "向量化岗位 JD", "status": "pending" },
            { "id": "retrieve_chunks", "title": "检索最相关片段", "status": "pending" },
            { "id": "gemini_analysis", "title": "调用 Gemini 分析", "status": "pending" },
            { "id": "save_history", "title": "保存分析记录", "status": "pending" }
        ]
    }
    db.save_analysis_record(
        user_id=user_id,
        status="pending",
        result_json=initial_result,
        input_json=draft_data,
        record_id=record_id
    )

    # 5. Run the background analysis task
    bg_analyzer_module.run_background_resume_analysis(
        user_id=user_id,
        record_id=record_id,
        draft_data=draft_data,
        resume_file_id=resume_file_id,
        embedding_config_id=None,
        chat_config_id=None
    )

    # 6. Assertions
    # Check that record is updated to 'failed'
    record = db.get_analysis_record(user_id, record_id)
    assert record is not None
    assert record.get("status") == "failed"
    assert "LLM API timeout" in record.get("errorMessage", "")
    assert record.get("is_failed") is True

    # Verify that steps mark the failure correctly
    steps = record.get("steps", [])
    # The failure occurs at Gemini analysis stage (step 5)
    # Let's inspect step 5 ("gemini_analysis")
    gemini_step = next((s for s in steps if s["id"] == "gemini_analysis"), None)
    assert gemini_step is not None
    assert gemini_step["status"] == "failed"
    assert "LLM API timeout" in gemini_step.get("errorMessage", "")

    # Verify user generation limit was NOT decremented (should remain 5)
    updated_user = db.get_user_by_id(user_id)
    assert updated_user.generation_limit == 5
