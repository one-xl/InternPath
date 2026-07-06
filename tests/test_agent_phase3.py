import os
import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from backend.memory.preference_db import PreferenceDB
from backend.agents.tools.layout_tools import check_layout_dependencies, render_docx_to_images
from backend.agents.layout_auditor import LayoutAuditor
from backend.agents.resume_copywriter import ResumeCopywriter
from backend.agents.orchestrator import Orchestrator
from backend.main import create_app
from database import Database
from config import Config
from service import CareerPathAIService

# 模拟 Choice 和 Response 结构用于 Mock LLM 响应
class MockChoice:
    def __init__(self, content):
        self.message = MagicMock()
        self.message.content = content

class MockResponse:
    def __init__(self, content):
        self.choices = [MockChoice(content)]

def test_preference_db_postgres_roundtrip(tmp_path):
    db = Database(str(tmp_path / "preferences.db"))
    preferences = PreferenceDB(db)

    preferences.save_preference(
        user_id="test_user",
        section_name="work_experience",
        preference_text="突出微服务架构设计",
    )
    preferences.save_preference(
        user_id="test_user",
        section_name="work_experience",
        preference_text="使用STAR法则进行数据量化描述",
    )
    preferences.save_preference(
        user_id="test_user",
        section_name="work_experience",
        preference_text="突出微服务架构设计",
    )

    prefs = preferences.get_preferences(user_id="test_user", section_name="work_experience")
    assert prefs == ["突出微服务架构设计", "使用STAR法则进行数据量化描述"]


def test_preference_db_uses_postgres_schema_across_instances(tmp_path):
    db = Database(str(tmp_path / "preferences.db"))
    PreferenceDB(db).save_preference("user_file", "Projects", "Prefer concise impact bullets")

    assert PreferenceDB(db).get_preferences("user_file", "Projects") == ["Prefer concise impact bullets"]


def test_agent_answer_remember_saves_section_preference(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "memory@example.com", "password": "password123"})
    token = reg.json()["token"]
    user_id = reg.json()["user"]["id"]

    task_id = "agent-resume-memory-answer"
    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id="resume_memory",
        original_resume_name="resume.docx",
        jd_text="Backend intern role.",
    )
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="WAITING_FOR_HUMAN",
        pending_question="Any verified project details?",
        execution_plan=json.dumps({
            "config_id": None,
            "is_co_pilot": True,
            "steps": [
                {
                    "section_name": "Projects",
                    "status": "PENDING",
                }
            ],
        }),
    )

    with patch("backend.agents.orchestrator.Orchestrator.run_orchestration", new_callable=MagicMock):
        resp = client.post(
            f"/api/agent/resume/tasks/{task_id}/answer",
            headers={"Authorization": f"Bearer {token}"},
            json={"answer": "Led a FastAPI migration for an internal matching service.", "remember": True},
        )

        assert resp.status_code == 200
        prefs = PreferenceDB(db).get_preferences(str(user_id), "Projects")
        assert any("FastAPI migration" in pref for pref in prefs)


def test_agent_answer_skip_does_not_save_preference_but_records_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "skip-memory@example.com", "password": "password123"})
    token = reg.json()["token"]
    user_id = reg.json()["user"]["id"]

    task_id = "agent-resume-skip-answer"
    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id="resume_memory_skip",
        original_resume_name="resume.docx",
        jd_text="Backend intern role.",
    )
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="WAITING_FOR_HUMAN",
        pending_question="Any verified project details?",
        execution_plan=json.dumps({
            "config_id": None,
            "is_co_pilot": True,
            "steps": [
                {
                    "step_index": 1,
                    "section_name": "Projects",
                    "status": "PENDING",
                }
            ],
        }),
    )

    with patch("backend.agents.orchestrator.Orchestrator.run_orchestration", new_callable=MagicMock):
        resp = client.post(
            f"/api/agent/resume/tasks/{task_id}/answer",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "answer_text": "",
                "answer_type": "skip",
                "remember": True,
                "evidence_scope": "current_step",
            },
        )

    assert resp.status_code == 200
    assert PreferenceDB(db).get_preferences(str(user_id), "Projects") == []
    turns = db.list_agent_resume_turns(user_id, task_id)
    assert turns[-1]["answer_type"] == "skip"
    assert "无补充" in turns[-1]["content"]


def test_agent_answer_duplicate_running_task_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "dup-answer@example.com", "password": "password123"})
    token = reg.json()["token"]
    user_id = reg.json()["user"]["id"]
    task_id = "agent-resume-dup-answer"

    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id="resume_dup",
        original_resume_name="resume.docx",
        jd_text="Backend intern role.",
    )
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="RUNNING",
        execution_plan=json.dumps({
            "config_id": None,
            "is_co_pilot": True,
            "steps": [
                {
                    "step_index": 1,
                    "section_name": "Projects",
                    "status": "PENDING",
                }
            ],
        }),
    )

    enqueue_calls = []
    monkeypatch.setattr("backend.main.enqueue_job", lambda *args, **kwargs: enqueue_calls.append(kwargs))

    resp = client.post(
        f"/api/agent/resume/tasks/{task_id}/answer",
        headers={"Authorization": f"Bearer {token}"},
        json={"answer": "Duplicate click", "answer_type": "evidence"},
    )

    assert resp.status_code == 200
    assert resp.json()["recordedOnly"] is True
    assert resp.json()["status"] == "RUNNING"
    assert enqueue_calls == []
    turns = db.list_agent_resume_turns(user_id, task_id)
    assert len(turns) == 1
    assert turns[0]["content"] == "Duplicate click"


def test_agent_question_answer_explains_without_resuming(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "question-answer@example.com", "password": "password123"})
    token = reg.json()["token"]
    user_id = reg.json()["user"]["id"]
    task_id = "agent-resume-question-answer"

    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id="resume_question",
        original_resume_name="resume.docx",
        jd_text="Backend intern role.",
    )
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="WAITING_FOR_HUMAN",
        pending_question="Any verified project details?",
        execution_plan=json.dumps({
            "config_id": None,
            "is_co_pilot": True,
            "steps": [
                {
                    "step_index": 1,
                    "section_name": "Projects",
                    "original_content": "Built an internal matching service.",
                    "improvement_goal": "Explain backend impact",
                    "status": "PENDING",
                }
            ],
        }),
    )

    enqueue_calls = []
    monkeypatch.setattr("backend.main.enqueue_job", lambda *args, **kwargs: enqueue_calls.append(kwargs))

    resp = client.post(
        f"/api/agent/resume/tasks/{task_id}/answer",
        headers={"Authorization": f"Bearer {token}"},
        json={"answer": "为什么要改项目经历？", "answer_type": "question"},
    )

    assert resp.status_code == 200
    assert resp.json()["answeredQuestion"] is True
    assert enqueue_calls == []
    assert db.get_agent_resume_task(user_id, task_id)["status"] == "WAITING_FOR_HUMAN"
    turns = db.list_agent_resume_turns(user_id, task_id)
    assert turns[-1]["role"] == "assistant"
    assert "当前停在" in turns[-1]["content"]


def test_agent_completed_task_accepts_followup_question(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "completed-followup@example.com", "password": "password123"})
    token = reg.json()["token"]
    user_id = reg.json()["user"]["id"]
    task_id = "agent-resume-completed-followup"

    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id="resume_completed",
        original_resume_name="resume.docx",
        jd_text="Backend intern role.",
    )
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="COMPLETED",
        optimized_resume_md="### Optimized Resume",
        execution_plan=json.dumps({
            "config_id": "cfg-llm",
            "is_co_pilot": True,
            "steps": [
                {
                    "step_index": 1,
                    "section_name": "Projects",
                    "original_content": "Built an internal matching service.",
                    "improvement_goal": "Explain backend impact",
                    "status": "COMPLETED",
                }
            ],
        }),
    )

    enqueue_calls = []
    monkeypatch.setattr("backend.main.enqueue_job", lambda *args, **kwargs: enqueue_calls.append(kwargs))

    resp = client.post(
        f"/api/agent/resume/tasks/{task_id}/answer",
        headers={"Authorization": f"Bearer {token}"},
        json={"answer": "为什么这样改？", "answer_type": "question"},
    )

    assert resp.status_code == 200
    assert resp.json()["answeredQuestion"] is True
    assert resp.json()["recordedOnly"] is True
    assert resp.json()["status"] == "COMPLETED"
    assert enqueue_calls == []
    turns = db.list_agent_resume_turns(user_id, task_id)
    assert [turn["role"] for turn in turns] == ["user", "assistant"]
    assert "为什么这样改" in turns[0]["content"]


def test_agent_instruction_updates_conversation_state(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "instruction-state@example.com", "password": "password123"})
    token = reg.json()["token"]
    user_id = reg.json()["user"]["id"]
    task_id = "agent-resume-instruction-state"

    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id="resume_instruction",
        original_resume_name="resume.docx",
        jd_text="Backend intern role.",
    )
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="WAITING_FOR_HUMAN",
        pending_question="Any verified project details?",
        execution_plan=json.dumps({
            "config_id": None,
            "is_co_pilot": True,
            "steps": [
                {
                    "step_index": 1,
                    "section_name": "Projects",
                    "status": "PENDING",
                }
            ],
        }),
    )

    enqueue_calls = []
    monkeypatch.setattr("backend.main.enqueue_job", lambda *args, **kwargs: enqueue_calls.append(kwargs))

    resp = client.post(
        f"/api/agent/resume/tasks/{task_id}/answer",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "answer": "后续都用更简洁的风格，不要改教育经历。",
            "answer_type": "instruction",
            "remember": True,
            "evidence_scope": "global",
        },
    )

    assert resp.status_code == 200
    state = db.get_agent_resume_conversation_state(user_id, task_id)
    assert "更简洁" in state["summary"]
    assert state["global_preferences"] == ["后续都用更简洁的风格，不要改教育经历。"]
    assert state["fact_ledger"] == ["后续都用更简洁的风格，不要改教育经历。"]
    assert enqueue_calls
    assert enqueue_calls[0]["config_id"] is None


def test_check_layout_dependencies():
    """
    测试 check_layout_dependencies 依赖检测。
    """
    # 1. 模拟组件全存在
    with patch("shutil.which", side_effect=lambda cmd: f"/usr/bin/{cmd}"):
        ok, missing = check_layout_dependencies()
        assert ok is True
        assert missing == ""

    # 2. 模拟 LibreOffice 缺失
    with patch("shutil.which", side_effect=lambda cmd: None if cmd in ["soffice", "libreoffice"] else f"/usr/bin/{cmd}"):
        ok, missing = check_layout_dependencies()
        assert ok is False
        assert "LibreOffice" in missing

    # 3. 模拟 Poppler 缺失
    with patch("shutil.which", side_effect=lambda cmd: None if cmd in ["pdftoppm"] else f"/usr/bin/{cmd}"):
        ok, missing = check_layout_dependencies()
        assert ok is False
        assert "Poppler" in missing

def test_render_docx_to_images(tmp_path, monkeypatch):
    """
    测试 render_docx_to_images PDF 渲染多图逻辑。
    """
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path))
    # 准备假 docx 路径
    docx_file = tmp_path / "optimized_resume.docx"
    docx_file.write_text("dummy docx content")

    mock_image1 = MagicMock()
    mock_image2 = MagicMock()

    # 模拟 convert_docx_to_pdf 并创建物理假 PDF，避免 Mock os.path.exists 引起 os.makedirs 失败
    def side_effect_convert(user_id, task_id, docx_path, pdf_dir):
        os.makedirs(pdf_dir, exist_ok=True)
        pdf_path = os.path.join(pdf_dir, "optimized_resume.pdf")
        with open(pdf_path, "w", encoding="utf-8") as f:
            f.write("fake pdf")
        return True

    with patch("backend.agents.tools.layout_tools.convert_docx_to_pdf", side_effect=side_effect_convert), \
         patch("pdf2image.convert_from_path", return_value=[mock_image1, mock_image2]) as mock_convert:

        img_paths = render_docx_to_images(user_id="user1", task_id="task1", docx_path=str(docx_file))

        assert len(img_paths) == 2
        mock_image1.save.assert_called_once()
        mock_image2.save.assert_called_once()
        assert "page_user1_task1_0.png" in img_paths[0]
        assert "page_user1_task1_1.png" in img_paths[1]

@pytest.mark.asyncio
async def test_layout_auditor_audit():
    """
    测试 LayoutAuditor 版面审计专家的多模态 JSON 结果解析。
    """
    mock_json_response = """
    ```json
    {
      "score": 90,
      "is_passed": true,
      "issues": ["排版整洁，字距适中"]
    }
    ```
    """
    # 初始化 LayoutAuditor，Mock _call_llm_multimodal 方法
    auditor = LayoutAuditor()

    # 模拟文件读取，避免 MagicMock 被 base64 读取时类型报错
    mock_file = MagicMock()
    mock_file.read.return_value = b"fake image bytes"

    with patch.object(auditor, "_call_llm_multimodal", return_value=mock_json_response) as mock_call, \
         patch("os.path.exists", return_value=True), \
         patch("builtins.open", MagicMock(return_value=mock_file)):

        res = await auditor.audit_layout(page_image_paths=["/path/to/page0.png"])
        assert res["score"] == 90
        assert res["is_passed"] is True
        assert "排版整洁，字距适中" in res["issues"]
        mock_call.assert_called_once()


@pytest.mark.asyncio
async def test_layout_auditor_rejects_score_out_of_range():
    auditor = LayoutAuditor()
    mock_file = MagicMock()
    mock_file.read.return_value = b"fake image bytes"

    with patch.object(auditor, "_call_llm_multimodal", return_value='{"score": 120, "is_passed": true, "issues": []}'), \
         patch("os.path.exists", return_value=True), \
         patch("builtins.open", MagicMock(return_value=mock_file)):
        with pytest.raises(RuntimeError, match="版面审计"):
            await auditor.audit_layout(page_image_paths=["/path/to/page0.png"])

@pytest.mark.asyncio
async def test_copywriter_few_shot_injection(tmp_path):
    """
    测试 ResumeCopywriter 是否能正确获取 Few-shot 偏好并注入到改写 Prompt 中。
    """
    db = Database(str(tmp_path / "copywriter-preferences.db"))
    PreferenceDB(db).save_preference(
        user_id="user_123",
        section_name="专业技能",
        preference_text="所有技术栈必须分类并用粗体显示",
    )

    copywriter = ResumeCopywriter()

    # 拦截大模型调用
    mock_response = "优化后的技能列表"
    with patch("backend.memory.preference_db.Database", return_value=db), \
         patch.object(copywriter, "_call_llm", return_value=mock_response) as mock_llm_call:
        res = await copywriter.rewrite_section(
            section_name="专业技能",
            original_content="Java, Python, C++",
            decoded_job={"hard_requirements": {}},
            goal="提升吸引力",
            user_id="user_123"
        )

        assert res == mock_response
        # 断言大模型的 prompt 里面确实包含了偏好规则
        called_args, called_kwargs = mock_llm_call.call_args
        user_prompt = called_kwargs.get("user_prompt", "")

        assert "所有技术栈必须分类并用粗体显示" in user_prompt
        assert "用户的历史偏好与 Few-shot 修改要求" in user_prompt

@pytest.mark.asyncio
async def test_orchestrator_dependency_failure(tmp_path, monkeypatch):
    """
    测试 Orchestrator 在版面审计依赖缺失时降级跳过视觉审计，而不是让已生成的简历任务失败。
    """
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    db = Database(str(tmp_path / "auth.db"))

    # Mock Database
    with patch("backend.agents.orchestrator.Database", return_value=db):
        task_id = "test_task_layout_fail"
        user_id = 100

        # 写入 resumes 记录
        db.conn = db.get_connection()
        cursor = db.conn.cursor()
        cursor.execute(
            "INSERT INTO resumes (id, user_id, file_name, file_size, parsed_json) VALUES (?, ?, ?, ?, ?)",
            ("fake_resume_id", 100, "resume.docx", 1024, json.dumps({
                "cleanedText": "简历内容",
                "rawText": "简历内容",
                "name": "resume.docx"
            }))
        )
        db.conn.commit()
        db.conn.close()

        # 写入一条测试任务
        db.create_agent_resume_task(
            task_id=task_id,
            user_id=user_id,
            resume_id="fake_resume_id",
            original_resume_name="resume.pdf",
            jd_text="随便一点岗位描述"
        )

        # 创建 Orchestrator 实例
        orchestrator = Orchestrator()

        # 模拟大模型客户端返回空的步骤计划
        mock_client = MagicMock()
        mock_plan_json = json.dumps({
            "steps": []
        })
        mock_job_json = json.dumps({
            "hard_requirements": {
                "technical_stack": [],
                "education": "未提及",
                "experience_years": "未提及",
            },
            "soft_requirements": {
                "industry_background": [],
                "project_attributes": [],
                "soft_skills": [],
            },
            "core_duties": [],
        })
        mock_client.chat.completions.create.side_effect = [
            MockResponse(mock_plan_json),
            MockResponse(mock_job_json),
        ]

        # 拦截大模型、文件读写、以及依赖检查（模拟缺失 LibreOffice 依赖）
        with patch("backend.agents.orchestrator.AIAnalyzer") as mock_analyzer_cls, \
             patch("backend.agents.orchestrator.tool_read_file", return_value="[]"), \
             patch("backend.agents.orchestrator.tool_write_file"), \
             patch("backend.agents.orchestrator.tool_generate_modification_diff"), \
             patch("backend.agents.orchestrator.update_docx_resume_from_log", return_value=True), \
             patch("backend.agents.orchestrator.check_layout_dependencies", return_value=(False, "LibreOffice (soffice/libreoffice)")):

             # 模拟 _client 返回
             mock_analyzer = MagicMock()
             mock_analyzer._client.return_value = (mock_client, "cfg_id", "provider", "model_id")
             mock_analyzer_cls.return_value = mock_analyzer

             await orchestrator.run_orchestration(
                 task_id=task_id,
                 user_id=user_id,
                 config_id="config1",
                 is_co_pilot=False
             )

             # 检查数据库状态，应为 COMPLETED，并记录依赖缺失 warning
             task = db.get_agent_resume_task(user_id, task_id)
             assert task["status"] == "COMPLETED"
             logs = json.loads(task["logs"])
             assert any("版面视觉审计依赖缺失" in item["message"] for item in logs)
