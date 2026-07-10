import json
import pytest
import asyncio
from unittest.mock import MagicMock, patch
from pathlib import Path

from config import Config
from database import Database
from backend.agent_planner import AgentPlanner
from backend.agents.base import BaseAgent
from backend.agents.job_decoder import JobDecoder
from backend.agents.resume_copywriter import ResumeCopywriter
from backend.agents.hr_critic import HRCritic
from backend.agents.tools.hitl_tool import ask_human_question, HumanInteractionRequired
from backend.agents.orchestrator import Orchestrator
from backend.agent_resume import tool_extract_resume_sections, get_safe_workspace_path

# 模拟简历数据
MOCK_RESUME = """李四
电话：13911112222
邮箱：lisi@example.com

工作经历
2022.01 - 至今  某大厂 - 后端开发工程师
负责实现核心数据传输模块，通过高并发优化提升系统吞吐量。
"""

# 模拟岗位描述 JD
MOCK_JD = """高级后端开发工程师
岗位职责：
1. 负责核心系统设计开发，提升大流量下的高并发处理能力。
任职要求：
1. 精通 Go/Python，有 3 年以上后端开发经验。
2. 具有微服务、高并发系统调优背景者优先。
"""

class MockChoice:
    def __init__(self, content):
        self.message = MagicMock()
        self.message.content = content

class MockResponse:
    def __init__(self, content):
        self.choices = [MockChoice(content)]

def test_agent_planner_generate_plan():
    """
    测试 AgentPlanner 能否正常生成并解析结构化执行计划 JSON。
    """
    planner = AgentPlanner()

    # 动态获取当前简历提取出来的段落名称，以防由于别名格式导致匹配失败
    sections = json.loads(tool_extract_resume_sections(MOCK_RESUME))
    target_sec_name = next(s["section_name"] for s in sections if s["section_name"] != "其他")

    # 模拟大模型返回的计划书
    mock_json_response = f"""
    {{
      "steps": [
        {{
          "step_index": 1,
          "section_index": {next(s["index"] for s in sections if s["section_name"] == target_sec_name)},
          "section_name": "{target_sec_name}",
          "original_content": "负责实现核心数据传输模块...",
          "improvement_goal": "突出微服务以及高并发调优经验",
          "requires_human_input": false,
          "human_question": "",
          "status": "PENDING"
        }}
      ]
    }}
    """

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MockResponse(mock_json_response)

    # 运行测试
    loop = asyncio.get_event_loop()
    plan = loop.run_until_complete(
        planner.generate_plan(
            resume_text=MOCK_RESUME,
            jd_text=MOCK_JD,
            openai_client=mock_client,
            model_id="mock-model"
        )
    )

    assert "steps" in plan
    assert len(plan["steps"]) == 1
    assert plan["steps"][0]["section_name"] == target_sec_name
    assert plan["steps"][0]["requires_human_input"] is False
    assert plan["steps"][0]["human_question"] == ""
    assert plan["steps"][0]["status"] == "PENDING"


def test_agent_planner_uses_responses_api_when_configured():
    planner = AgentPlanner()
    sections = json.loads(tool_extract_resume_sections(MOCK_RESUME))
    target_sec_name = next(s["section_name"] for s in sections if s["section_name"] != "其他")
    target_sec_index = next(s["index"] for s in sections if s["section_name"] == target_sec_name)
    mock_json_response = f"""
    {{
      "steps": [
        {{
          "step_index": 1,
          "section_index": {target_sec_index},
          "section_name": "{target_sec_name}",
          "original_content": "负责实现核心数据传输模块...",
          "improvement_goal": "突出微服务以及高并发调优经验",
          "requires_human_input": false,
          "human_question": "",
          "status": "PENDING"
        }}
      ]
    }}
    """

    mock_client = MagicMock()
    mock_client._internpath_stream_api_mode = "responses"
    mock_client._internpath_prompt_cache_key = "planner-cache-key"
    mock_client._internpath_prompt_cache_retention = "24h"
    mock_client.responses.create.return_value = {"output_text": mock_json_response}

    loop = asyncio.get_event_loop()
    plan = loop.run_until_complete(
        planner.generate_plan(
            resume_text=MOCK_RESUME,
            jd_text=MOCK_JD,
            openai_client=mock_client,
            model_id="mock-model"
        )
    )

    assert len(plan["steps"]) == 1
    assert plan["steps"][0]["section_name"] == target_sec_name
    assert "input" in mock_client.responses.create.call_args.kwargs
    assert mock_client.responses.create.call_args.kwargs["stream"] is True
    assert mock_client.responses.create.call_args.kwargs["prompt_cache_key"] == "planner-cache-key"
    assert mock_client.responses.create.call_args.kwargs["prompt_cache_retention"] == "24h"
    mock_client.chat.completions.create.assert_not_called()


def test_agent_planner_fails_when_model_call_fails():
    """
    AgentPlanner 不允许在模型调用失败时生成本地启发式计划。
    """
    planner = AgentPlanner()
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = RuntimeError("model down")

    loop = asyncio.get_event_loop()
    with pytest.raises(RuntimeError, match="生成简历优化计划失败"):
        loop.run_until_complete(
            planner.generate_plan(
                resume_text=MOCK_RESUME,
                jd_text=MOCK_JD,
                openai_client=mock_client,
                model_id="mock-model"
            )
        )


def test_agent_planner_fails_on_invalid_json_plan():
    """
    AgentPlanner 不允许在模型返回非法 JSON 时生成本地启发式计划。
    """
    planner = AgentPlanner()
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MockResponse("not json")

    loop = asyncio.get_event_loop()
    with pytest.raises(ValueError, match="不是合法 JSON"):
        loop.run_until_complete(
            planner.generate_plan(
                resume_text=MOCK_RESUME,
                jd_text=MOCK_JD,
                openai_client=mock_client,
                model_id="mock-model"
            )
        )


def test_agent_planner_fails_on_missing_required_plan_field():
    planner = AgentPlanner()
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MockResponse(
        '{"steps":[{"step_index":1,"section_name":"工作经历","original_content":"x","improvement_goal":"y","status":"PENDING"}]}'
    )

    loop = asyncio.get_event_loop()
    with pytest.raises(ValueError, match="Schema"):
        loop.run_until_complete(
            planner.generate_plan(
                resume_text=MOCK_RESUME,
                jd_text=MOCK_JD,
                openai_client=mock_client,
                model_id="mock-model"
            )
        )


def test_agent_planner_accepts_model_empty_steps():
    """
    空 steps 是模型明确输出的合法计划，不属于本地兜底。
    """
    planner = AgentPlanner()
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MockResponse('{"steps": []}')

    loop = asyncio.get_event_loop()
    plan = loop.run_until_complete(
        planner.generate_plan(
            resume_text=MOCK_RESUME,
            jd_text=MOCK_JD,
            openai_client=mock_client,
            model_id="mock-model"
        )
    )

    assert plan == {"steps": []}


def test_job_decoder_decode_job():
    """
    测试 JobDecoder 是否能深度解析 JD，提取结构化岗位画像。
    """
    mock_client = MagicMock()
    mock_json_response = """
    {
      "hard_requirements": {
        "technical_stack": ["Python", "Go"],
        "education": "本科以上",
        "experience_years": "3年以上"
      },
      "soft_requirements": {
        "industry_background": ["大流量系统"],
        "project_attributes": ["微服务", "高并发调优"],
        "soft_skills": ["良好的沟通能力"]
      },
      "core_duties": ["负责核心系统设计开发"]
    }
    """
    mock_client.chat.completions.create.return_value = MockResponse(mock_json_response)

    decoder = JobDecoder(model="mock-model", openai_client=mock_client)

    loop = asyncio.get_event_loop()
    decoded = loop.run_until_complete(decoder.decode_job(MOCK_JD))

    assert "hard_requirements" in decoded
    assert "technical_stack" in decoded["hard_requirements"]
    assert "Python" in decoded["hard_requirements"]["technical_stack"]
    assert "core_duties" in decoded
    assert len(decoded["core_duties"]) == 1


def test_job_decoder_rejects_missing_schema_fields():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MockResponse('{"hard_requirements": {"technical_stack": []}}')
    decoder = JobDecoder(model="mock-model", openai_client=mock_client)

    loop = asyncio.get_event_loop()
    with pytest.raises(ValueError, match="岗位解码结果未通过结构化 Schema 校验"):
        loop.run_until_complete(decoder.decode_job(MOCK_JD))


def test_hr_critic_rejects_score_out_of_range():
    critic = HRCritic()
    with pytest.raises(ValueError, match="HR 审计结果未通过结构化 Schema 校验"):
        critic._parse_evaluation_result(
            json.dumps({
                "score": 101,
                "is_passed": True,
                "critique": "too high",
                "suggestions": "",
            })
        )


def test_resume_copywriter_rewrite_section():
    """
    测试 ResumeCopywriter 能否正常优化段落及进行审计不通过时的重试改写。
    """
    mock_client = MagicMock()
    # 模拟大模型返回的改写和重试内容
    mock_client.chat.completions.create.side_effect = [
        MockResponse("改写后的段落一"),
        MockResponse("针对HR反馈重试修改后的完美段落")
    ]

    copywriter = ResumeCopywriter(model="mock-model", openai_client=mock_client)

    loop = asyncio.get_event_loop()
    # 1. 正常改写
    res1 = loop.run_until_complete(
        copywriter.rewrite_section(
            section_name="工作经历",
            original_content="原始工作经历文本",
            decoded_job={"hard_requirements": {"technical_stack": ["Python"]}},
            goal="突出高并发经验"
        )
    )
    assert res1 == "改写后的段落一"

    # 2. 审计不通过时重试
    res2 = loop.run_until_complete(
        copywriter.rewrite_section_retry(
            section_name="工作经历",
            original_content="原始工作经历文本",
            previous_optimized="改写后的段落一",
            critique="未体现具体性能提升",
            suggestions="请补充如性能提升50%的数据说明",
            decoded_job={"hard_requirements": {"technical_stack": ["Python"]}},
            goal="突出高并发经验"
        )
    )
    assert res2 == "针对HR反馈重试修改后的完美段落"


def test_resume_copywriter_streams_rewrite_deltas():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = [
        {"choices": [{"delta": {"content": "流式"}}]},
        {"choices": [{"delta": {"content": "段落"}}]},
    ]
    copywriter = ResumeCopywriter(model="mock-model", openai_client=mock_client)
    deltas: list[str] = []

    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(
        copywriter.rewrite_section(
            section_name="工作经历",
            original_content="原始工作经历文本",
            decoded_job={"hard_requirements": {"technical_stack": ["Python"]}},
            goal="突出高并发经验",
            on_delta=deltas.append,
        )
    )

    assert deltas == ["流式", "段落"]
    assert result == "流式段落"
    assert mock_client.chat.completions.create.call_args.kwargs["stream"] is True


def test_resume_copywriter_streams_rewrite_deltas_with_responses_api():
    mock_client = MagicMock()
    mock_client._internpath_stream_api_mode = "responses"
    mock_client._internpath_prompt_cache_key = "copywriter-cache-key"
    mock_client._internpath_prompt_cache_retention = "24h"
    mock_client.responses.create.return_value = [
        {"type": "response.output_text.delta", "delta": "streamed"},
        {"type": "response.output_text.delta", "delta": " text"},
        {
            "type": "response.completed",
            "response": {
                "usage": {
                    "input_tokens": 1200,
                    "output_tokens": 10,
                    "input_tokens_details": {"cached_tokens": 1024},
                }
            },
        },
    ]
    copywriter = ResumeCopywriter(model="mock-model", openai_client=mock_client)
    deltas: list[str] = []
    fake_pref_db = MagicMock()
    fake_pref_db.get_preferences.return_value = []

    loop = asyncio.get_event_loop()
    with patch("backend.memory.preference_db.PreferenceDB", return_value=fake_pref_db):
        result = loop.run_until_complete(
            copywriter.rewrite_section(
                section_name="work",
                original_content="original",
                decoded_job={"hard_requirements": {"technical_stack": ["Python"]}},
                goal="improve",
                on_delta=deltas.append,
            )
        )

    assert deltas == ["streamed", " text"]
    assert result == "streamed text"
    assert mock_client.responses.create.call_args.kwargs["stream"] is True
    assert "input" in mock_client.responses.create.call_args.kwargs
    assert mock_client.responses.create.call_args.kwargs["prompt_cache_key"] == "copywriter-cache-key"
    assert mock_client.responses.create.call_args.kwargs["prompt_cache_retention"] == "24h"
    stats = BaseAgent.pop_provider_cache_usage(mock_client)
    assert stats["providerCacheHit"] is True
    assert stats["providerCachedTokens"] == 1024
    mock_client.chat.completions.create.assert_not_called()


def test_resume_copywriter_responses_completed_event_can_carry_full_text():
    mock_client = MagicMock()
    mock_client._internpath_stream_api_mode = "responses"
    mock_client.responses.create.return_value = [
        {"type": "response.completed", "response": {"output_text": "completed text"}},
    ]
    copywriter = ResumeCopywriter(model="mock-model", openai_client=mock_client)
    deltas: list[str] = []

    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(
        copywriter.rewrite_section(
            section_name="work",
            original_content="original",
            decoded_job={"hard_requirements": {"technical_stack": ["Python"]}},
            goal="improve",
            on_delta=deltas.append,
        )
    )

    assert deltas == ["completed text"]
    assert result == "completed text"
    assert mock_client.responses.create.call_count == 1
    assert mock_client.responses.create.call_args.kwargs["stream"] is True
    mock_client.chat.completions.create.assert_not_called()


def test_base_agent_non_stream_uses_responses_api_when_configured():
    mock_client = MagicMock()
    mock_client._internpath_stream_api_mode = "responses"
    mock_client._internpath_prompt_cache_key = "base-cache-key"
    mock_client._internpath_prompt_cache_retention = "24h"
    mock_client.responses.create.return_value = {"output_text": "review text"}
    copywriter = ResumeCopywriter(model="mock-model", openai_client=mock_client)

    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(copywriter._call_llm("system", "user"))

    assert result == "review text"
    assert "input" in mock_client.responses.create.call_args.kwargs
    assert mock_client.responses.create.call_args.kwargs["stream"] is True
    assert mock_client.responses.create.call_args.kwargs["prompt_cache_key"] == "base-cache-key"
    assert mock_client.responses.create.call_args.kwargs["prompt_cache_retention"] == "24h"
    mock_client.chat.completions.create.assert_not_called()


def test_hitl_tool_ask_human_question(tmp_path, monkeypatch):
    """
    测试 ask_human_question 能否正常更新数据库状态，并抛出指定异常挂起任务。
    """
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    db = Database(str(tmp_path / "auth.db"))

    with patch("backend.agents.tools.hitl_tool.Database", return_value=db):
        task_id = "test_hitl_task"
        user_id = 99

        # 写入一条测试任务
        db.create_agent_resume_task(
            task_id=task_id,
            user_id=user_id,
            resume_id="fake_resume",
            original_resume_name="resume.pdf",
            jd_text=MOCK_JD
        )

        # 调用提问方法，应当抛出 HumanInteractionRequired
        with pytest.raises(HumanInteractionRequired) as exc_info:
            ask_human_question(task_id, user_id, "请补充高并发调优的细节？")

        assert exc_info.value.question == "请补充高并发调优的细节？"

        # 检查数据库状态是否更新为 WAITING_FOR_HUMAN
        task = db.get_agent_resume_task(user_id, task_id)
        assert task["status"] == "WAITING_FOR_HUMAN"
        assert task["pending_question"] == "请补充高并发调优的细节？"


def test_agent_resume_turns_are_step_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))
    db = Database(str(tmp_path / "turns.db"))

    task_id = "turn-scope-task"
    user_id = "turn-user"
    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id="resume_turn",
        original_resume_name="resume.docx",
        jd_text=MOCK_JD,
    )
    turn_1 = db.add_agent_resume_turn(
        task_id=task_id,
        user_id=user_id,
        step_index=1,
        role="user",
        content="第一步补充事实",
        answer_type="evidence",
    )
    db.add_agent_resume_turn(
        task_id=task_id,
        user_id=user_id,
        step_index=2,
        role="user",
        content="第二步偏好",
        answer_type="preference",
    )

    step_1_answers = db.list_unconsumed_agent_answer_turns(user_id, task_id, 1)
    assert [item["content"] for item in step_1_answers] == ["第一步补充事实"]

    db.mark_agent_resume_turns_consumed([turn_1])
    assert db.list_unconsumed_agent_answer_turns(user_id, task_id, 1) == []
    assert [item["content"] for item in db.list_unconsumed_agent_answer_turns(user_id, task_id, 2)] == ["第二步偏好"]


def test_agent_resume_job_pauses_on_hitl(monkeypatch):
    from backend import jobs
    import backend.agents.langgraph_orchestrator as langgraph_module
    from backend.agents.tools.hitl_tool import HumanInteractionRequired

    class _FakeLangGraphPipelineOrchestrator:
        async def run_orchestration(self, **kwargs):
            raise HumanInteractionRequired("请补充项目量化结果？")

    class _FakeDatabase:
        def update_agent_resume_task_status(self, **kwargs):
            updates.append(kwargs)

    class _FakeRedis:
        def __init__(self):
            self.data = {}
            self.ttls = {}

        def set(self, key, value, nx=False, ex=None):
            if nx and key in self.data:
                return False
            self.data[key] = value
            self.ttls[key] = ex
            return True

        def get(self, key):
            return self.data.get(key)

        def delete(self, key):
            self.data.pop(key, None)

        def eval(self, script, numkeys, key, value):
            if self.data.get(key) == value:
                self.delete(key)
                return 1
            return 0

    updates = []
    fake_redis = _FakeRedis()
    monkeypatch.setattr(langgraph_module, "LangGraphPipelineOrchestrator", lambda: _FakeLangGraphPipelineOrchestrator())
    monkeypatch.setattr(jobs, "Database", lambda: _FakeDatabase())
    monkeypatch.setattr(jobs, "get_redis_connection", lambda: fake_redis)
    monkeypatch.setattr(jobs, "log_event", lambda **kwargs: None)

    jobs.run_agent_resume_orchestration_job(
        task_id="task-hitl",
        user_id=99,
        config_id=None,
        is_co_pilot=True,
        execution_mode="pipeline",
        tool_calling_mode="auto",
    )

    assert updates == [
        {
            "task_id": "task-hitl",
            "user_id": 99,
            "status": "WAITING_FOR_HUMAN",
            "pending_question": "请补充项目量化结果？",
        }
    ]
    assert fake_redis.data == {}


def test_agent_resume_job_single_flight_skips_duplicate(monkeypatch):
    from backend import jobs
    import backend.agents.orchestrator as orchestrator_module

    class _FakeOrchestrator:
        async def run_orchestration(self, **kwargs):
            calls.append(kwargs)

    class _FakeRedis:
        def __init__(self):
            self.data = {"agent:task-lock:task-dup": "other-worker"}
            self.ttls = {"agent:task-lock:task-dup": 1860}

        def set(self, key, value, nx=False, ex=None):
            if nx and key in self.data:
                return False
            self.data[key] = value
            self.ttls[key] = ex
            return True

        def get(self, key):
            return self.data.get(key)

        def delete(self, key):
            self.data.pop(key, None)

        def eval(self, script, numkeys, key, value):
            if self.data.get(key) == value:
                self.delete(key)
                return 1
            return 0

    calls = []
    events = []
    fake_redis = _FakeRedis()
    monkeypatch.setattr(orchestrator_module, "Orchestrator", lambda: _FakeOrchestrator())
    monkeypatch.setattr(jobs, "get_redis_connection", lambda: fake_redis)
    monkeypatch.setattr(jobs, "log_event", lambda **kwargs: events.append(kwargs))

    jobs.run_agent_resume_orchestration_job(
        task_id="task-dup",
        user_id=99,
        config_id=None,
        is_co_pilot=True,
    )

    assert calls == []
    assert fake_redis.data["agent:task-lock:task-dup"] == "other-worker"
    assert events[-1]["event"] == "agent_resume_lock_skipped"


def test_agent_resume_job_lock_has_ttl(monkeypatch):
    from backend import jobs
    import backend.agents.langgraph_orchestrator as langgraph_module

    class _FakeLangGraphPipelineOrchestrator:
        async def run_orchestration(self, **kwargs):
            calls.append(kwargs)

    class _FakeRedis:
        def __init__(self):
            self.data = {}
            self.ttls = {}

        def set(self, key, value, nx=False, ex=None):
            self.data[key] = value
            self.ttls[key] = ex
            return True

        def get(self, key):
            return self.data.get(key)

        def delete(self, key):
            self.data.pop(key, None)

        def eval(self, script, numkeys, key, value):
            if self.data.get(key) == value:
                self.delete(key)
                return 1
            return 0

    calls = []
    fake_redis = _FakeRedis()
    monkeypatch.setattr(langgraph_module, "LangGraphPipelineOrchestrator", lambda: _FakeLangGraphPipelineOrchestrator())
    monkeypatch.setattr(jobs, "get_redis_connection", lambda: fake_redis)
    monkeypatch.setattr(jobs, "log_event", lambda **kwargs: None)
    monkeypatch.setattr(Config, "RQ_JOB_TIMEOUT_SECONDS", 1800)

    jobs.run_agent_resume_orchestration_job(
        task_id="task-ttl",
        user_id=99,
        config_id=None,
        is_co_pilot=False,
        execution_mode="pipeline",
        tool_calling_mode="auto",
    )

    assert len(calls) == 1
    assert fake_redis.ttls["agent:task-lock:task-ttl"] == 1860
    assert fake_redis.data == {}


def test_orchestrator_full_workflow(tmp_path, monkeypatch):
    """
    对 Orchestrator 核心调度官的工作流进行全流程覆盖测试：
    包括：初始化、生成执行计划、岗位解码、Co-Pilot 人机交互挂起、断点唤醒及最终合并替换。
    """
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    db = Database(str(tmp_path / "auth.db"))

    # 动态分析得到真实的简历段落名称，并在后续 mock 中使用它，确保 100% 匹配
    sections = json.loads(tool_extract_resume_sections(MOCK_RESUME))
    target_sec_name = next(s["section_name"] for s in sections if s["section_name"] != "其他")

    # 利用 db 实例化自动创建表，然后直接写入简历
    db.conn = db.get_connection()
    cursor = db.conn.cursor()

    # 直接向已创建的 resumes 表插入数据（Database 内部已经在实例化时自动创建了 resumes 表）
    cursor.execute(
        "INSERT INTO resumes (id, user_id, file_name, file_size, parsed_json) VALUES (?, ?, ?, ?, ?)",
        ("res_123", "user_abc", "test.docx", 1024, json.dumps({
            "cleanedText": MOCK_RESUME,
            "rawText": MOCK_RESUME,
            "name": "test.docx"
        }))
    )
    db.conn.commit()
    db.conn.close()

    # 创建任务
    task_id = "orch_task_1"
    user_id = "user_abc"
    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id="res_123",
        original_resume_name="test.docx",
        jd_text=MOCK_JD
    )

    # 模拟大模型客户端
    mock_client = MagicMock()

    # 模拟 AIAnalyzer 解析 client 的返回
    def mock_analyzer_client(self, u_id, cfg_id, use_fallback):
        return mock_client, cfg_id, "mock_provider", "mock_model"

    # 用 patch 将底层客户端注入
    # 模拟 LayoutAuditor
    mock_auditor = MagicMock()
    mock_auditor.audit_layout = MagicMock(return_value={"score": 95, "is_passed": True, "issues": ["排版非常整洁"]})

    with patch("backend.agents.orchestrator.Database", return_value=db), \
         patch("backend.agents.tools.hitl_tool.Database", return_value=db), \
         patch("ai_analyzer.AIAnalyzer._client", mock_analyzer_client), \
         patch("backend.agents.orchestrator.check_layout_dependencies", return_value=(True, "")), \
         patch("backend.agents.orchestrator.render_docx_to_images", return_value=["/fake/page_0.png"]), \
         patch("backend.agents.orchestrator.LayoutAuditor", return_value=mock_auditor):

        orchestrator = Orchestrator(model="mock_model", openai_client=mock_client)

        # 1. 模拟第一轮运行，期望生成计划并检测到关键模块（工作经历）触发人机交互挂起异常
        mock_plan_json = json.dumps({
            "steps": [
                {
                    "step_index": 1,
                    "section_index": next(s["index"] for s in sections if s["section_name"] == target_sec_name),
                    "section_name": target_sec_name,
                    "original_content": "负责实现核心数据传输模块...",
                    "improvement_goal": "突出微服务经验",
                    "requires_human_input": True,
                    "human_question": f"请补充「{target_sec_name}」中可量化的项目细节。",
                    "status": "PENDING"
                }
            ]
        })
        mock_job_json = json.dumps({
            "hard_requirements": {
                "technical_stack": ["Python"],
                "education": "未提及",
                "experience_years": "未提及",
            },
            "soft_requirements": {
                "industry_background": [],
                "project_attributes": ["高并发"],
                "soft_skills": []
            },
            "core_duties": []
        })
        # 审计打分合格
        mock_audit_json = json.dumps({
            "score": 95,
            "is_passed": True,
            "critique": "符合岗位要求",
            "suggestions": ""
        })

        mock_client.chat.completions.create.side_effect = [
            MockResponse(mock_plan_json), # Planner
            MockResponse(mock_job_json),  # JobDecoder
        ]

        loop = asyncio.get_event_loop()

        # 期望首次跑会抛出挂起异常
        with pytest.raises(HumanInteractionRequired):
            loop.run_until_complete(
                orchestrator.run_orchestration(task_id, user_id, "default_config")
            )

        # 校验数据库
        task = db.get_agent_resume_task(user_id, task_id)
        assert task["status"] == "WAITING_FOR_HUMAN"
        assert "execution_plan" in task and task["execution_plan"] is not None
        assert target_sec_name in task["pending_question"]

        # 2. 模拟用户提交反馈并唤醒任务，重新运行续跑
        db.update_agent_resume_task_status(
            task_id=task_id,
            user_id=user_id,
            status="RUNNING",
            human_answer="我在大厂开发了高并发的消息推送中间件，性能提升过两倍"
        )

        # 补充 mock 返回值以支持续跑轮次
        mock_client.chat.completions.create.side_effect = [
            MockResponse("工作经历\n2022.01 - 至今  某大厂 - 后端开发工程师\n这是合并了用户高并发推送中间件细节改写后的项目段落内容。"), # Copywriter
            MockResponse(mock_audit_json),     # HR Critic
            MockResponse("是否存在幻觉风险：否\n风险严重程度：无\n修改建议：无") # VerifyAntiHallucination
        ]

        # 运行续跑，应该顺利执行并跑通到 COMPLETED
        loop.run_until_complete(
            orchestrator.run_orchestration(task_id, user_id, "default_config")
        )

        # 最终检验
        task_final = db.get_agent_resume_task(user_id, task_id)
        assert task_final["status"] == "COMPLETED"
        assert "这是合并了用户高并发推送中间件" in task_final["optimized_resume_md"]
        # 校验提问和答案是否消费后已清空
        assert not task_final["human_answer"]
        assert not task_final["pending_question"]
