import json

from fastapi.testclient import TestClient

from config import Config
from database import Database
from service import CareerPathAIService


class _FakeRedis:
    def __init__(self):
        self.data = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        self.data.pop(key, None)

    def eval(self, _script, _numkeys, key, value):
        if self.data.get(key) == value:
            self.delete(key)
            return 1
        return 0


def test_agent_resume_job_defaults_to_agentic_native_responses(monkeypatch):
    from backend import jobs
    import backend.agents.orchestrator as orchestrator_module
    import backend.agents.langgraph_orchestrator as langgraph_module

    calls = []

    class _PipelineOrchestrator:
        async def run_orchestration(self, **kwargs):
            calls.append(("pipeline", kwargs))

    class _LangGraphAgenticOrchestrator:
        async def run_orchestration(self, **kwargs):
            calls.append(("langgraph_agentic", kwargs))

    monkeypatch.setattr(orchestrator_module, "Orchestrator", lambda: _PipelineOrchestrator())
    monkeypatch.setattr(langgraph_module, "LangGraphAgenticOrchestrator", lambda: _LangGraphAgenticOrchestrator())
    monkeypatch.setattr(jobs, "get_redis_connection", lambda: _FakeRedis())
    monkeypatch.setattr(jobs, "log_event", lambda **_kwargs: None)

    jobs.run_agent_resume_orchestration_job(
        task_id="tatest-api-key",
        user_id=7,
        config_id="cfg-1",
        is_co_pilot=False,
    )

    assert calls == [
        (
            "langgraph_agentic",
            {
                "task_id": "tatest-api-key",
                "user_id": 7,
                "config_id": "cfg-1",
                "is_co_pilot": False,
                "tool_calling_mode": "native_responses",
            },
        )
    ]


def test_agent_resume_job_routes_explicit_pipeline_mode(monkeypatch):
    from backend import jobs
    import backend.agents.langgraph_orchestrator as langgraph_module

    calls = []

    class _LangGraphPipelineOrchestrator:
        async def run_orchestration(self, **kwargs):
            calls.append(("langgraph_pipeline", kwargs))

    class _LangGraphAgenticOrchestrator:
        async def run_orchestration(self, **kwargs):
            calls.append(("langgraph_agentic", kwargs))

    monkeypatch.setattr(langgraph_module, "LangGraphPipelineOrchestrator", lambda: _LangGraphPipelineOrchestrator())
    monkeypatch.setattr(langgraph_module, "LangGraphAgenticOrchestrator", lambda: _LangGraphAgenticOrchestrator())
    monkeypatch.setattr(jobs, "get_redis_connection", lambda: _FakeRedis())
    monkeypatch.setattr(jobs, "log_event", lambda **_kwargs: None)

    jobs.run_agent_resume_orchestration_job(
        task_id="task-pipeline",
        user_id=7,
        config_id="cfg-1",
        is_co_pilot=False,
        execution_mode="pipeline",
        tool_calling_mode="auto",
    )

    assert calls == [
        (
            "langgraph_pipeline",
            {
                "task_id": "task-pipeline",
                "user_id": 7,
                "config_id": "cfg-1",
                "is_co_pilot": False,
            },
        )
    ]


def test_agent_resume_job_routes_agentic_mode(monkeypatch):
    from backend import jobs
    import backend.agents.orchestrator as orchestrator_module
    import backend.agents.langgraph_orchestrator as langgraph_module

    calls = []

    class _PipelineOrchestrator:
        async def run_orchestration(self, **kwargs):
            calls.append(("pipeline", kwargs))

    class _LangGraphAgenticOrchestrator:
        async def run_orchestration(self, **kwargs):
            calls.append(("langgraph_agentic", kwargs))

    monkeypatch.setattr(orchestrator_module, "Orchestrator", lambda: _PipelineOrchestrator())
    monkeypatch.setattr(langgraph_module, "LangGraphAgenticOrchestrator", lambda: _LangGraphAgenticOrchestrator())
    monkeypatch.setattr(jobs, "get_redis_connection", lambda: _FakeRedis())
    monkeypatch.setattr(jobs, "log_event", lambda **_kwargs: None)

    jobs.run_agent_resume_orchestration_job(
        task_id="task-agentic",
        user_id=7,
        config_id="cfg-1",
        is_co_pilot=True,
        execution_mode="agentic",
        tool_calling_mode="json_action",
    )

    assert calls == [
        (
            "langgraph_agentic",
            {
                "task_id": "task-agentic",
                "user_id": 7,
                "config_id": "cfg-1",
                "is_co_pilot": True,
                "tool_calling_mode": "json_action",
            },
        )
    ]


def test_agent_resume_job_resumes_langgraph_checkpoint(monkeypatch):
    from backend import jobs
    import backend.agents.langgraph_orchestrator as langgraph_module

    calls = []
    resume_payload = {
        "answer": "接口 P95 延迟降低 30%。",
        "answer_type": "evidence",
        "remember": False,
        "evidence_scope": "current_step",
        "step_index": 1,
    }

    class _FakeDB:
        def get_agent_resume_task(self, _user_id, _task_id):
            return None

    class _LangGraphAgenticOrchestrator:
        async def run_orchestration(self, **kwargs):
            calls.append(("start", kwargs))

        async def resume_orchestration(self, **kwargs):
            calls.append(("resume", kwargs))

    monkeypatch.setattr(jobs, "Database", lambda: _FakeDB())
    monkeypatch.setattr(langgraph_module, "LangGraphAgenticOrchestrator", lambda: _LangGraphAgenticOrchestrator())
    monkeypatch.setattr(jobs, "get_redis_connection", lambda: _FakeRedis())
    monkeypatch.setattr(jobs, "log_event", lambda **_kwargs: None)

    jobs.run_agent_resume_orchestration_job(
        task_id="tatest-api-key",
        user_id=7,
        config_id="cfg-1",
        is_co_pilot=False,
        execution_mode="agentic",
        tool_calling_mode="native_responses",
        resume_payload=resume_payload,
    )

    assert calls == [
        (
            "resume",
            {
                "task_id": "tatest-api-key",
                "user_id": 7,
                "resume_payload": resume_payload,
            },
        )
    ]


def test_agent_resume_job_resumes_pipeline_langgraph_checkpoint(monkeypatch):
    from backend import jobs
    import backend.agents.langgraph_orchestrator as langgraph_module

    calls = []
    resume_payload = {"answer": "确认项目数据。", "answer_type": "evidence"}

    class _FakeDB:
        def get_agent_resume_task(self, _user_id, _task_id):
            return None

    class _LangGraphPipelineOrchestrator:
        async def run_orchestration(self, **kwargs):
            calls.append(("start", kwargs))

        async def resume_orchestration(self, **kwargs):
            calls.append(("resume", kwargs))

    monkeypatch.setattr(jobs, "Database", lambda: _FakeDB())
    monkeypatch.setattr(langgraph_module, "LangGraphPipelineOrchestrator", lambda: _LangGraphPipelineOrchestrator())
    monkeypatch.setattr(jobs, "get_redis_connection", lambda: _FakeRedis())
    monkeypatch.setattr(jobs, "log_event", lambda **_kwargs: None)

    jobs.run_agent_resume_orchestration_job(
        task_id="tatest-api-key",
        user_id=7,
        config_id="cfg-1",
        is_co_pilot=False,
        execution_mode="pipeline",
        tool_calling_mode="auto",
        resume_payload=resume_payload,
    )

    assert calls == [
        (
            "resume",
            {
                "task_id": "tatest-api-key",
                "user_id": 7,
                "resume_payload": resume_payload,
            },
        )
    ]


def test_agentic_orchestrator_auto_uses_native_responses(tmp_path, monkeypatch):
    import asyncio
    import backend.agents.agentic_orchestrator as agentic_module
    from backend.agents.tool_loop import ToolLoopResult

    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    calls = []
    updates = []

    class _FakeDB:
        def get_agent_resume_task(self, _user_id, task_id):
            return {
                "task_id": task_id,
                "trace_id": "tr-auto",
                "resume_id": "resume-1",
                "jd_text": "Backend internship requiring FastAPI.",
                "execution_plan": "{}",
                "logs": "[]",
            }

        def get_user_resume(self, _user_id, _resume_id):
            return {
                "cleanedText": "Projects\nBuilt APIs.",
                "rawText": "Projects\nBuilt APIs.",
            }

        def update_agent_resume_task_status(self, **kwargs):
            updates.append(kwargs)

    class _FakeAnalyzer:
        def _client(self, *_args, **_kwargs):
            return object(), "cfg-auto", "openai", "gpt-5.5"

    class _FakeLoop:
        def __init__(self, _registry):
            pass

        def run_native_responses_loop(self, _ctx, model_turn, **_kwargs):
            calls.append(("native", model_turn.namespace))
            return ToolLoopResult(
                status="completed",
                final_text="done",
                turns=1,
                events=[{"type": "tool_result", "tool_name": "finalize_resume_artifacts", "ok": True}],
            )

        def run_json_action_loop(self, *_args, **_kwargs):
            calls.append(("json", "agentic_resume_json_action"))
            return ToolLoopResult(status="completed", final_text="wrong", turns=1, events=[])

    monkeypatch.setattr(agentic_module, "AIAnalyzer", lambda: _FakeAnalyzer())
    monkeypatch.setattr(agentic_module, "AgenticToolLoop", _FakeLoop)
    monkeypatch.setattr(agentic_module, "materialize_original_resume_file", lambda *_args, **_kwargs: None)

    orchestrator = agentic_module.AgenticOrchestrator()
    orchestrator.db = _FakeDB()

    asyncio.run(
        orchestrator.run_orchestration(
            task_id="task-auto",
            user_id="user-auto",
            config_id=None,
            is_co_pilot=True,
            tool_calling_mode="auto",
        )
    )

    assert calls == [("native", "agentic_resume_native_tools")]
    saved_plans = [
        json.loads(update["execution_plan"])
        for update in updates
        if update.get("execution_plan")
    ]
    assert saved_plans
    assert saved_plans[-1]["effective_tool_calling_mode"] == "native_responses"


def test_langgraph_agentic_orchestrator_runs_minimal_graph(tmp_path, monkeypatch):
    import asyncio
    import backend.agents.langgraph_orchestrator as langgraph_module
    import backend.agents.orchestrator as orchestrator_module
    from backend.agents.tool_loop import ToolLoopResult

    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "LANGGRAPH_CHECKPOINTER", "memory")
    updates = []
    calls = []

    class _FakeDB:
        def __init__(self):
            self.task = {
                "task_id": "task-langgraph",
                "trace_id": "tr-langgraph",
                "resume_id": "resume-1",
                "jd_text": "Backend internship requiring FastAPI and workflow automation.",
                "execution_plan": "{}",
                "logs": "[]",
                "status": "PENDING",
            }

        def get_agent_resume_task(self, _user_id, _task_id):
            return dict(self.task)

        def get_user_resume(self, _user_id, _resume_id):
            return {
                "cleanedText": "Projects\nBuilt APIs.",
                "rawText": "Projects\nBuilt APIs.",
            }

        def update_agent_resume_task_status(self, **kwargs):
            updates.append(dict(kwargs))
            for key in ("status", "execution_plan", "logs", "optimized_resume_md", "error_message"):
                if key in kwargs:
                    self.task[key] = kwargs[key]

    class _FakeAnalyzer:
        def _client(self, *_args, **_kwargs):
            return object(), "cfg-langgraph", "openai", "gpt-5.5"

    class _FakeLoop:
        def __init__(self, _registry):
            pass

        def run_native_responses_loop(self, _ctx, model_turn, **kwargs):
            calls.append(("native", model_turn.namespace))
            event_sink = kwargs.get("event_sink")
            if event_sink:
                event_sink({"type": "model_turn_start", "turn": 1})
                event_sink({
                    "type": "tool_result",
                    "tool_name": "finalize_resume_artifacts",
                    "ok": True,
                    "duration_ms": 7,
                })
            return ToolLoopResult(
                status="completed",
                final_text="done",
                turns=1,
                events=[
                    {"type": "model_turn_start", "turn": 1},
                    {"type": "tool_result", "tool_name": "finalize_resume_artifacts", "ok": True, "duration_ms": 7},
                ],
            )

        def run_json_action_loop(self, *_args, **_kwargs):
            calls.append(("json", "agentic_resume_json_action"))
            return ToolLoopResult(status="completed", final_text="wrong", turns=1, events=[])

    fake_db = _FakeDB()
    monkeypatch.setattr(orchestrator_module, "Database", lambda: fake_db)
    monkeypatch.setattr(langgraph_module, "AIAnalyzer", lambda: _FakeAnalyzer())
    monkeypatch.setattr(langgraph_module, "AgenticToolLoop", _FakeLoop)
    monkeypatch.setattr(langgraph_module, "materialize_original_resume_file", lambda *_args, **_kwargs: None)

    orchestrator = langgraph_module.LangGraphAgenticOrchestrator()
    asyncio.run(
        orchestrator.run_orchestration(
            task_id="task-langgraph",
            user_id="user-langgraph",
            config_id=None,
            is_co_pilot=True,
            tool_calling_mode="native_responses",
        )
    )

    assert calls == [("native", "agentic_resume_native_tools")]
    assert fake_db.task["status"] == "COMPLETED"
    assert fake_db.task["optimized_resume_md"] == "Projects\nBuilt APIs."
    saved_plans = [
        json.loads(update["execution_plan"])
        for update in updates
        if update.get("execution_plan")
    ]
    assert saved_plans
    assert saved_plans[-1]["orchestrator_backend"] == "langgraph"
    assert saved_plans[-1]["effective_tool_calling_mode"] == "native_responses"
    assert saved_plans[-1]["langgraph"]["nodes"] == [
        "load_task",
        "prepare_workspace",
        "run_agent_loop",
        "wait_for_human",
        "finalize_task",
    ]


def test_langgraph_pipeline_orchestrator_replaces_legacy_runtime(tmp_path, monkeypatch):
    import asyncio

    from langgraph.checkpoint.memory import InMemorySaver

    import backend.agents.langgraph_orchestrator as langgraph_module
    import backend.agents.orchestrator as orchestrator_module
    from backend.agents.tool_loop import ToolLoopResult

    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "LANGGRAPH_CHECKPOINTER", "memory")
    calls = []

    class _FakeDB:
        def __init__(self):
            self.task = {
                "task_id": "tatest-api-key",
                "trace_id": "tr-langgraph-pipeline",
                "resume_id": "resume-1",
                "jd_text": "Backend internship requiring FastAPI.",
                "execution_plan": json.dumps({"execution_mode": "pipeline"}),
                "logs": "[]",
                "status": "PENDING",
            }

        def get_agent_resume_task(self, _user_id, _task_id):
            return dict(self.task)

        def get_user_resume(self, _user_id, _resume_id):
            return {
                "cleanedText": "Projects\nBuilt APIs.",
                "rawText": "Projects\nBuilt APIs.",
            }

        def update_agent_resume_task_status(self, **kwargs):
            for key in (
                "status",
                "execution_plan",
                "logs",
                "optimized_resume_md",
                "error_message",
                "pending_question",
            ):
                if key in kwargs:
                    self.task[key] = kwargs[key]

    class _FakeAnalyzer:
        def _client(self, *_args, **_kwargs):
            return object(), "cfg-pipeline", "openai", "gpt-5.5"

    class _FakeLoop:
        def __init__(self, _registry):
            pass

        def run_native_responses_loop(self, *_args, **_kwargs):
            raise AssertionError("pipeline compatibility mode must use json_action")

        def run_json_action_loop(self, _ctx, model_turn, **_kwargs):
            calls.append(("json", model_turn.namespace))
            return ToolLoopResult(
                status="completed",
                final_text="done",
                turns=1,
                events=[
                    {
                        "type": "tool_result",
                        "tool_name": "finalize_resume_artifacts",
                        "ok": True,
                    }
                ],
            )

    async def fail_legacy_runtime(*_args, **_kwargs):
        raise AssertionError("legacy Orchestrator.run_orchestration must not be called")

    fake_db = _FakeDB()
    monkeypatch.setattr(orchestrator_module, "Database", lambda: fake_db)
    monkeypatch.setattr(orchestrator_module.Orchestrator, "run_orchestration", fail_legacy_runtime)
    monkeypatch.setattr(langgraph_module, "AIAnalyzer", lambda: _FakeAnalyzer())
    monkeypatch.setattr(langgraph_module, "AgenticToolLoop", _FakeLoop)
    monkeypatch.setattr(langgraph_module, "materialize_original_resume_file", lambda *_args, **_kwargs: None)

    orchestrator = langgraph_module.LangGraphPipelineOrchestrator(checkpointer=InMemorySaver())
    asyncio.run(
        orchestrator.run_orchestration(
            task_id="tatest-api-key",
            user_id="user-langgraph-pipeline",
            config_id=None,
            is_co_pilot=False,
        )
    )

    assert calls == [("json", "agentic_resume_json_action")]
    assert fake_db.task["status"] == "COMPLETED"
    plan = json.loads(fake_db.task["execution_plan"])
    assert plan["execution_mode"] == "pipeline"
    assert plan["effective_tool_calling_mode"] == "json_action"
    assert plan["orchestrator_backend"] == "langgraph"
    assert "wrapped_runtime" not in plan["langgraph"]


def test_langgraph_agentic_orchestrator_resumes_native_human_interrupt(tmp_path, monkeypatch):
    import asyncio

    from langgraph.checkpoint.memory import InMemorySaver

    import backend.agents.langgraph_orchestrator as langgraph_module
    import backend.agents.orchestrator as orchestrator_module
    from backend.agents.tool_loop import ToolLoopResult

    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "LANGGRAPH_CHECKPOINTER", "memory")

    calls = []
    human_contexts = []
    materialize_calls = []

    class _FakeDB:
        def __init__(self):
            self.task = {
                "task_id": "tatest-api-key",
                "trace_id": "tr-langgraph-hitl",
                "resume_id": "resume-1",
                "jd_text": "Backend internship requiring measurable API outcomes.",
                "execution_plan": "{}",
                "logs": "[]",
                "status": "PENDING",
                "pending_question": "",
                "human_answer": "",
            }

        def get_agent_resume_task(self, _user_id, _task_id):
            return dict(self.task)

        def get_user_resume(self, _user_id, _resume_id):
            return {
                "cleanedText": "Projects\nBuilt APIs.",
                "rawText": "Projects\nBuilt APIs.",
            }

        def update_agent_resume_task_status(self, **kwargs):
            for key in (
                "status",
                "execution_plan",
                "logs",
                "optimized_resume_md",
                "error_message",
                "pending_question",
                "human_answer",
            ):
                if key in kwargs:
                    self.task[key] = kwargs[key]

    class _FakeAnalyzer:
        def _client(self, *_args, **_kwargs):
            return object(), "cfg-langgraph", "openai", "gpt-5.5"

    class _FakeLoop:
        def __init__(self, _registry):
            pass

        def run_native_responses_loop(self, _ctx, _model_turn, **_kwargs):
            calls.append("agent_loop")
            human_contexts.append(_ctx.human_context)
            if len(calls) == 1:
                return ToolLoopResult(
                    status="needs_human",
                    final_text="请补充 API 性能提升的量化结果。",
                    turns=1,
                    events=[
                        {
                            "type": "tool_call",
                            "tool_name": "ask_user_for_fact",
                            "arguments": {"question": "请补充 API 性能提升的量化结果。"},
                        }
                    ],
                )
            return ToolLoopResult(
                status="completed",
                final_text="done",
                turns=1,
                events=[
                    {
                        "type": "tool_result",
                        "tool_name": "finalize_resume_artifacts",
                        "ok": True,
                    }
                ],
            )

        def run_json_action_loop(self, *_args, **_kwargs):
            raise AssertionError("native resume test must not use json_action")

    fake_db = _FakeDB()
    checkpointer = InMemorySaver()
    monkeypatch.setattr(orchestrator_module, "Database", lambda: fake_db)
    monkeypatch.setattr(langgraph_module, "AIAnalyzer", lambda: _FakeAnalyzer())
    monkeypatch.setattr(langgraph_module, "AgenticToolLoop", _FakeLoop)
    monkeypatch.setattr(
        langgraph_module,
        "materialize_original_resume_file",
        lambda *_args, **_kwargs: materialize_calls.append("materialized"),
    )

    first_run = langgraph_module.LangGraphAgenticOrchestrator(checkpointer=checkpointer)
    asyncio.run(
        first_run.run_orchestration(
            task_id="tatest-api-key",
            user_id="user-langgraph-hitl",
            config_id=None,
            is_co_pilot=True,
            tool_calling_mode="native_responses",
        )
    )

    assert fake_db.task["status"] == "WAITING_FOR_HUMAN"
    assert fake_db.task["pending_question"] == "请补充 API 性能提升的量化结果。"

    resumed = langgraph_module.LangGraphAgenticOrchestrator(checkpointer=checkpointer)
    asyncio.run(
        resumed.resume_orchestration(
            task_id="tatest-api-key",
            user_id="user-langgraph-hitl",
            resume_payload={
                "answer": "接口 P95 延迟降低 30%。",
                "answer_type": "evidence",
            },
        )
    )

    assert calls == ["agent_loop", "agent_loop"]
    assert human_contexts == ["", "接口 P95 延迟降低 30%。"]
    assert materialize_calls == ["materialized"]
    assert fake_db.task["status"] == "COMPLETED"
    assert fake_db.task["pending_question"] == ""


def test_langgraph_postgres_checkpointer_resumes_across_instances(monkeypatch):
    import asyncio
    from uuid import uuid4

    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    import backend.agents.langgraph_orchestrator as langgraph_module
    import backend.agents.orchestrator as orchestrator_module

    suffix = uuid4().hex
    task_id = f"tatest-api-key{suffix}"
    user_id = f"user-postgres-probe-{suffix}"
    thread_id = f"agent-resume:{user_id}:{task_id}"
    resumed_answers = []

    class _FakeDB:
        def get_agent_resume_task(self, _user_id, _task_id):
            return None

        def update_agent_resume_task_status(self, **_kwargs):
            pass

    class _ProbeOrchestrator(langgraph_module.LangGraphAgenticOrchestrator):
        def _build_graph(self, checkpointer):
            graph = StateGraph(langgraph_module.ResumeAgentGraphState)

            def wait_for_answer(state):
                answer = interrupt({"question": "checkpoint probe"})
                resumed_answers.append(str(answer))
                return {"status": "COMPLETED"}

            graph.add_node("wait_for_answer", wait_for_answer)
            graph.add_edge(START, "wait_for_answer")
            graph.add_edge("wait_for_answer", END)
            return graph.compile(checkpointer=checkpointer, name="internpath_postgres_resume_probe")

        async def start(self):
            await self._invoke_graph(
                {"task_id": task_id, "user_id": user_id, "status": "RUNNING"},
                task_id=task_id,
                user_id=user_id,
            )

    monkeypatch.setattr(Config, "LANGGRAPH_CHECKPOINTER", "postgres")
    monkeypatch.setattr(Config, "LANGGRAPH_POSTGRES_SETUP", True)
    monkeypatch.setattr(orchestrator_module, "Database", lambda: _FakeDB())

    try:
        first = _ProbeOrchestrator()
        asyncio.run(first.start())
        assert first.current_status == "WAITING_FOR_HUMAN"

        second = _ProbeOrchestrator()
        asyncio.run(
            second.resume_orchestration(
                task_id=task_id,
                user_id=user_id,
                resume_payload={"answer": "restored"},
            )
        )
        assert second.current_status == "COMPLETED"
        assert resumed_answers == ["{'answer': 'restored'}"]
    finally:
        with PostgresSaver.from_conn_string(Config.DATABASE_URL) as saver:
            saver.delete_thread(thread_id)


def test_agent_optimize_accepts_agentic_mode_fields(tmp_path, monkeypatch):
    import backend.main as main_module

    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    enqueued = []

    def fake_enqueue(_func, *args, **kwargs):
        enqueued.append({"args": args, "kwargs": kwargs})
        return object()

    monkeypatch.setattr(main_module, "enqueue_job", fake_enqueue)

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = main_module.create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "agentic-mode@example.com", "password": "password123"})
    assert reg.status_code == 200
    token = reg.json()["token"]
    user_id = str(reg.json()["user"]["id"])

    resume_id = "resume-agentic-mode"
    db.save_user_resume(
        user_id=user_id,
        resume_id=resume_id,
        file_name="resume.docx",
        file_size=128,
        file_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        parsed_resume={
            "file": {"id": resume_id, "name": "resume.docx", "size": 128, "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            "cleanedText": "Projects\nBuilt an InternPath resume workflow.",
            "rawText": "Projects\nBuilt an InternPath resume workflow.",
            "chunks": [],
        },
    )

    response = client.post(
        "/api/agent/resume/optimize",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "resume_id": resume_id,
            "legacy_mode": True,
            "jd_text": "Backend internship requiring FastAPI, LLM workflow, and resume automation experience.",
            "config_id": None,
            "is_co_pilot": True,
            "executionMode": "agentic",
            "toolCallingMode": "json_action",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["executionMode"] == "agentic"
    assert data["toolCallingMode"] == "json_action"
    assert data["task"]["taskId"] == data["taskId"]
    assert data["task"]["streamPreviewMd"]
    response_log_stages = [item["stage"] for item in data["task"]["logs"]]
    assert "bootstrap" in response_log_stages
    assert "workspace_prewarm" in response_log_stages
    assert "queue" in response_log_stages
    assert enqueued
    queued_kwargs = enqueued[0]["kwargs"]
    assert queued_kwargs["execution_mode"] == "agentic"
    assert queued_kwargs["tool_calling_mode"] == "json_action"

    task = db.get_agent_resume_task(user_id, data["taskId"])
    plan = json.loads(task["execution_plan"])
    assert plan["execution_mode"] == "agentic"
    assert plan["tool_calling_mode"] == "json_action"
    logs = json.loads(task["logs"])
    assert any(item["stage"] == "workspace_prewarm" for item in logs)
    assert any(item["stage"] == "queue" for item in logs)

    detail = client.get(f"/api/agent/resume/tasks/{data['taskId']}", headers={"Authorization": f"Bearer {token}"})
    assert detail.status_code == 200
    assert detail.json()["executionMode"] == "agentic"
    assert detail.json()["toolCallingMode"] == "json_action"


def test_agent_optimize_defaults_to_agentic_native_responses(tmp_path, monkeypatch):
    import backend.main as main_module

    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    enqueued = []
    monkeypatch.setattr(
        main_module,
        "enqueue_job",
        lambda _func, *args, **kwargs: enqueued.append({"args": args, "kwargs": kwargs}) or object(),
    )

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = main_module.create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "agentic-default@example.com", "password": "password123"})
    assert reg.status_code == 200
    token = reg.json()["token"]
    user_id = str(reg.json()["user"]["id"])

    resume_id = "resume-agentic-default"
    db.save_user_resume(
        user_id=user_id,
        resume_id=resume_id,
        file_name="resume.docx",
        file_size=128,
        file_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        parsed_resume={
            "file": {"id": resume_id, "name": "resume.docx", "size": 128, "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            "cleanedText": "Projects\nBuilt an InternPath resume workflow.",
            "rawText": "Projects\nBuilt an InternPath resume workflow.",
            "chunks": [],
        },
    )

    response = client.post(
        "/api/agent/resume/optimize",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "resume_id": resume_id,
            "legacy_mode": True,
            "jd_text": "Backend internship requiring FastAPI, LLM workflow, and resume automation experience.",
            "is_co_pilot": True,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["executionMode"] == "agentic"
    assert data["toolCallingMode"] == "native_responses"
    assert enqueued
    queued_kwargs = enqueued[0]["kwargs"]
    assert queued_kwargs["execution_mode"] == "agentic"
    assert queued_kwargs["tool_calling_mode"] == "native_responses"

    task = db.get_agent_resume_task(user_id, data["taskId"])
    plan = json.loads(task["execution_plan"])
    assert plan["execution_mode"] == "agentic"
    assert plan["tool_calling_mode"] == "native_responses"


def test_agent_retry_preserves_agentic_mode_fields(tmp_path, monkeypatch):
    import backend.main as main_module

    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    enqueued = []
    monkeypatch.setattr(
        main_module,
        "enqueue_job",
        lambda _func, *args, **kwargs: enqueued.append({"args": args, "kwargs": kwargs}) or object(),
    )

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = main_module.create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "agentic-retry@example.com", "password": "password123"})
    assert reg.status_code == 200
    token = reg.json()["token"]
    user_id = str(reg.json()["user"]["id"])

    resume_id = "resume-agentic-retry"
    db.save_user_resume(
        user_id=user_id,
        resume_id=resume_id,
        file_name="resume.docx",
        file_size=128,
        file_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        parsed_resume={
            "file": {"id": resume_id, "name": "resume.docx", "size": 128, "type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            "cleanedText": "Projects\nBuilt an InternPath resume workflow.",
            "rawText": "Projects\nBuilt an InternPath resume workflow.",
            "chunks": [],
        },
    )
    task_id = "agentic-retry-task"
    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id=resume_id,
        original_resume_name="resume.docx",
        jd_text="Backend internship requiring FastAPI and LLM workflow experience.",
    )
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="FAILED",
        error_message="provider disconnected",
        execution_plan=json.dumps({
            "config_id": "cfg-agentic",
            "is_co_pilot": True,
            "execution_mode": "agentic",
            "tool_calling_mode": "json_action",
            "failure_point": {
                "failed_stage": "tool_result",
                "failed_tool_name": "replace_resume_section",
                "failed_tool_arguments": {
                    "section_index": 1,
                    "new_content": "same failed payload",
                    "reason": "retry test",
                },
                "failed_model_input_ref": "turn:3",
                "failed_model_input": {
                    "mode": "json_action",
                    "messages": [{"role": "user", "content": "same model input"}],
                },
                "last_successful_tool_result": {
                    "tool_name": "extract_resume_sections",
                    "ok": True,
                },
                "failed_sequence": 9,
                "retry_count": 1,
            },
            "steps": [],
        }, ensure_ascii=False),
    )

    response = client.post(
        f"/api/agent/resume/tasks/{task_id}/retry",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    queued_kwargs = enqueued[0]["kwargs"]
    assert queued_kwargs["config_id"] == "cfg-agentic"
    assert queued_kwargs["is_co_pilot"] is True
    assert queued_kwargs["execution_mode"] == "agentic"
    assert queued_kwargs["tool_calling_mode"] == "json_action"
    retried_task = db.get_agent_resume_task(user_id, task_id)
    retried_plan = json.loads(retried_task["execution_plan"])
    retry_request = retried_plan["retry_request"]
    assert retry_request["failed_tool_name"] == "replace_resume_section"
    assert retry_request["failed_tool_arguments"]["new_content"] == "same failed payload"
    assert retry_request["failed_sequence"] == 9
    assert retry_request["retry_count"] == 2
    assert retry_request["failed_model_input"]["messages"][0]["content"] == "same model input"
    assert retry_request["last_successful_tool_result"]["tool_name"] == "extract_resume_sections"


def test_agent_answer_preserves_agentic_mode_fields(tmp_path, monkeypatch):
    import backend.main as main_module

    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))

    enqueued = []
    monkeypatch.setattr(
        main_module,
        "enqueue_job",
        lambda _func, *args, **kwargs: enqueued.append({"args": args, "kwargs": kwargs}) or object(),
    )

    service = object.__new__(CareerPathAIService)
    db = Database(str(tmp_path / "auth.db"))
    app = main_module.create_app(service=service, auth_db=db)
    client = TestClient(app)

    reg = client.post("/api/auth/register", json={"username": "agentic-answer@example.com", "password": "password123"})
    assert reg.status_code == 200
    token = reg.json()["token"]
    user_id = str(reg.json()["user"]["id"])

    task_id = "agentic-answer-task"
    db.create_agent_resume_task(
        task_id=task_id,
        user_id=user_id,
        resume_id="resume-agentic-answer",
        original_resume_name="resume.docx",
        jd_text="Backend internship requiring FastAPI and LLM workflow experience.",
    )
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="WAITING_FOR_HUMAN",
        pending_question="Confirm verified FastAPI experience.",
        execution_plan=json.dumps({
            "config_id": "cfg-agentic-answer",
            "is_co_pilot": False,
            "execution_mode": "agentic",
            "tool_calling_mode": "json_action",
            "steps": [
                {
                    "step_index": 1,
                    "section_index": 0,
                    "section_name": "Projects",
                    "status": "RUNNING",
                }
            ],
        }, ensure_ascii=False),
    )

    response = client.post(
        f"/api/agent/resume/tasks/{task_id}/answer",
        headers={"Authorization": f"Bearer {token}"},
        json={"answer": "Verified FastAPI and SSE project work.", "answer_type": "evidence"},
    )

    assert response.status_code == 200
    queued_kwargs = enqueued[0]["kwargs"]
    assert queued_kwargs["config_id"] == "cfg-agentic-answer"
    assert queued_kwargs["is_co_pilot"] is False
    assert queued_kwargs["execution_mode"] == "agentic"
    assert queued_kwargs["tool_calling_mode"] == "json_action"
    assert queued_kwargs["resume_payload"] == {
        "answer": "Verified FastAPI and SSE project work.",
        "answer_type": "evidence",
        "remember": False,
        "evidence_scope": "current_step",
        "step_index": 1,
    }


def test_agentic_loop_metrics_detect_successful_finalize():
    from backend.agents.agentic_orchestrator import AgenticOrchestrator

    events = [
        {"type": "model_turn_start", "turn": 1},
        {"type": "tool_call", "tool_name": "replace_resume_section"},
        {"type": "tool_result", "tool_name": "replace_resume_section", "ok": True, "duration_ms": 8},
        {"type": "tool_call", "tool_name": "finalize_resume_artifacts"},
        {"type": "tool_result", "tool_name": "finalize_resume_artifacts", "ok": True, "duration_ms": 15},
        {"type": "provider_usage", "providerCachedTokens": 512},
    ]

    metrics = AgenticOrchestrator._summarize_loop_events(events)

    assert metrics["model_turns"] == 1
    assert metrics["tool_calls"] == 2
    assert metrics["successful_tool_results"] == 2
    assert metrics["finalize_already_completed"] is True
    assert metrics["provider_usage_events"] == 1
    assert AgenticOrchestrator._has_successful_tool_result(events, "finalize_resume_artifacts") is True
    assert AgenticOrchestrator._has_successful_tool_result(
        [{"type": "tool_result", "tool_name": "finalize_resume_artifacts", "ok": False}],
        "finalize_resume_artifacts",
    ) is False


def test_agentic_event_sink_marks_bootstrap_tool_call(monkeypatch):
    from backend.agents.agentic_orchestrator import AgenticOrchestrator

    orchestrator = object.__new__(AgenticOrchestrator)
    logs = []

    def fake_log_step(*_args, **kwargs):
        logs.append({
            "message": _args[3],
            "detail": _args[4],
            "stage": kwargs.get("stage"),
        })

    orchestrator.log_step = fake_log_step
    sink = orchestrator._event_sink("task-1", "user-1", {}, "json_action")

    sink({
        "type": "tool_call",
        "turn": 0,
        "tool_name": "list_workspace_files",
        "arguments": {},
        "bootstrap": True,
        "bootstrap_index": 1,
    })

    assert logs[0]["message"] == "Bootstrap tool: list_workspace_files"
    assert logs[0]["detail"]["bootstrap"] is True
    assert logs[0]["detail"]["bootstrap_index"] == 1


def test_agentic_event_sink_records_model_stream_delta(monkeypatch):
    from backend.agents.agentic_orchestrator import AgenticOrchestrator

    orchestrator = object.__new__(AgenticOrchestrator)
    logs = []

    def fake_log_step(*_args, **kwargs):
        logs.append({
            "message": _args[3],
            "detail": _args[4],
            "stage": kwargs.get("stage"),
            "status": kwargs.get("status"),
        })

    orchestrator.log_step = fake_log_step
    sink = orchestrator._event_sink("task-1", "user-1", {}, "json_action")

    sink({
        "type": "model_stream_delta",
        "turn": 1,
        "mode": "json_action",
        "content": '{"action":"call_tool"',
        "total_chars": 21,
    })

    assert logs[0]["stage"] == "model_stream_delta"
    assert logs[0]["status"] == "running"
    assert "21 public characters" in logs[0]["message"]
    assert logs[0]["detail"]["content"] == '{"action":"call_tool"'


def test_agentic_failure_point_preserves_failed_model_input(monkeypatch):
    from backend.agents.agentic_orchestrator import AgenticOrchestrator

    orchestrator = object.__new__(AgenticOrchestrator)
    saved = []
    orchestrator._save_plan = lambda task_id, user_id, plan_data, tool_calling_mode, status: saved.append(dict(plan_data))
    plan_data = {}
    failed_input = {
        "mode": "native_responses",
        "input_items": [{"role": "user", "content": "same failed input"}],
        "instructions": "same instructions",
        "previous_response_id": "resp_1",
    }

    orchestrator._record_failure_point(
        "task-1",
        "user-1",
        plan_data,
        {
            "failed_stage": "model_turn",
            "failed_model_input_ref": "turn:2",
            "failed_model_input": failed_input,
            "last_successful_tool_result": {"tool_name": "replace_resume_section", "ok": True},
            "failed_sequence": 6,
            "error": "provider disconnected",
        },
        tool_calling_mode="native_responses",
    )

    failure_point = plan_data["failure_point"]
    assert failure_point["failed_stage"] == "model_turn"
    assert failure_point["failed_model_input"] == failed_input
    assert failure_point["last_successful_tool_result"]["tool_name"] == "replace_resume_section"
    assert saved
