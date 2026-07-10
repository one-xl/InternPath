from __future__ import annotations

import asyncio
import json
import time
import traceback
from typing import Any, Optional, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from ai_analyzer import AIAnalyzer
from backend.agents.agentic_orchestrator import AgenticOrchestrator
from backend.agents.tool_loop import (
    AgenticToolLoop,
    ResponsesJsonActionModelTurn,
    ResponsesNativeToolModelTurn,
)
from backend.agents.tool_registry import AgentToolContext, DEFAULT_AGENT_TOOL_REGISTRY
from backend.agents.tools.docx_tools import materialize_original_resume_file
from backend.agents.tools.hitl_tool import HumanInteractionRequired
from backend.agents.tools.workspace_tools import tool_read_file, tool_write_file
from config import Config


LANGGRAPH_AGENTIC_GRAPH_VERSION = "2026-07-10.langgraph-resume-v2"


class ResumeAgentGraphState(TypedDict, total=False):
    task_id: str
    user_id: Any
    config_id: Optional[str]
    is_co_pilot: bool
    tool_calling_mode: str
    effective_tool_calling_mode: str
    status: str
    task: dict[str, Any]
    plan_data: dict[str, Any]
    resume_id: Any
    resume_text: str
    jd_text: str
    provider: str
    model_id: str
    resolved_config_id: Optional[str]
    loop_result: dict[str, Any]
    loop_metrics: dict[str, Any]
    loop_duration_ms: int
    final_resume_md: str
    pending_question: str
    resume_payload: dict[str, Any]


class LangGraphAgenticOrchestrator(AgenticOrchestrator):
    """LangGraph-backed orchestration for the resume Agent workflow."""

    execution_mode = "agentic"

    def __init__(
        self,
        agent_id: str = "langgraph_agentic_orchestrator",
        role: str = "LangGraphAgenticOrchestrator",
        model: str = "gpt-4o-mini",
        openai_client: Optional[Any] = None,
        checkpointer: Optional[Any] = None,
    ):
        super().__init__(agent_id=agent_id, role=role, model=model, openai_client=openai_client)
        self._checkpointer_context = None
        self._provided_checkpointer = checkpointer
        self._graph = None

    def _build_graph(self, checkpointer: Any):
        graph = StateGraph(ResumeAgentGraphState)
        graph.add_node("load_task", self._load_task_node)
        graph.add_node("prepare_workspace", self._prepare_workspace_node)
        graph.add_node("run_agent_loop", self._run_agent_loop_node)
        graph.add_node("wait_for_human", self._wait_for_human_node)
        graph.add_node("finalize_task", self._finalize_task_node)
        graph.add_edge(START, "load_task")
        graph.add_edge("load_task", "prepare_workspace")
        graph.add_edge("prepare_workspace", "run_agent_loop")
        graph.add_conditional_edges(
            "run_agent_loop",
            self._route_after_agent_loop,
            {
                "finalize_task": "finalize_task",
                "wait_for_human": "wait_for_human",
            },
        )
        graph.add_edge("wait_for_human", "run_agent_loop")
        graph.add_edge("finalize_task", END)
        return graph.compile(
            checkpointer=checkpointer,
            name=f"internpath_{self.execution_mode}_resume_langgraph",
        )

    def _build_checkpointer(self):
        if self._provided_checkpointer is not None:
            return self._provided_checkpointer
        if Config.LANGGRAPH_CHECKPOINTER != "postgres":
            return InMemorySaver()
        if not Config.DATABASE_URL:
            raise RuntimeError("LANGGRAPH_CHECKPOINTER=postgres requires DATABASE_URL.")

        from langgraph.checkpoint.postgres import PostgresSaver

        self._checkpointer_context = PostgresSaver.from_conn_string(Config.DATABASE_URL)
        saver = self._checkpointer_context.__enter__()
        if Config.LANGGRAPH_POSTGRES_SETUP:
            saver.setup()
        return saver

    def _ensure_graph(self):
        if self._graph is None:
            self._graph = self._build_graph(self._build_checkpointer())
        return self._graph

    def _invoke_graph_blocking(
        self,
        graph_input: ResumeAgentGraphState | Command,
        *,
        task_id: str,
        user_id: Any,
    ) -> dict[str, Any]:
        try:
            return self._ensure_graph().invoke(
                graph_input,
                config=self._graph_config(task_id, user_id),
            )
        finally:
            self._close_checkpointer()

    async def run_orchestration(
        self,
        task_id: str,
        user_id: Any,
        config_id: Optional[str],
        is_co_pilot: bool = True,
        tool_calling_mode: str = "native_responses",
    ) -> None:
        self.logs = []
        self.current_status = "RUNNING"
        initial_state: ResumeAgentGraphState = {
            "task_id": task_id,
            "user_id": user_id,
            "config_id": config_id,
            "is_co_pilot": bool(is_co_pilot),
            "tool_calling_mode": str(tool_calling_mode or "native_responses"),
            "status": "RUNNING",
        }
        await self._invoke_graph(initial_state, task_id=task_id, user_id=user_id)

    async def resume_orchestration(
        self,
        task_id: str,
        user_id: Any,
        resume_payload: dict[str, Any],
    ) -> None:
        self.logs = []
        self.current_status = "RUNNING"
        await self._invoke_graph(
            Command(resume=dict(resume_payload or {})),
            task_id=task_id,
            user_id=user_id,
        )

    @staticmethod
    def _graph_config(task_id: str, user_id: Any) -> dict[str, Any]:
        return {
            "configurable": {
                "thread_id": f"agent-resume:{user_id}:{task_id}",
            }
        }

    async def _invoke_graph(
        self,
        graph_input: ResumeAgentGraphState | Command,
        *,
        task_id: str,
        user_id: Any,
    ) -> None:
        try:
            result = await asyncio.to_thread(
                self._invoke_graph_blocking,
                graph_input,
                task_id=task_id,
                user_id=user_id,
            )
            if isinstance(result, dict):
                if result.get("__interrupt__"):
                    self.current_status = "WAITING_FOR_HUMAN"
                elif result.get("status"):
                    self.current_status = str(result["status"])
        except HumanInteractionRequired:
            self.current_status = "WAITING_FOR_HUMAN"
            raise
        except Exception as exc:
            self.current_status = "FAILED"
            err_msg = str(exc)
            plan_data = {}
            try:
                task = self.db.get_agent_resume_task(user_id, task_id)
                plan_data = self._load_plan(task.get("execution_plan") if task else None)
            except Exception:
                plan_data = {}
            print(f"[LANGGRAPH_ORCHESTRATOR_ERROR] Task {task_id} failed: {err_msg}\n{traceback.format_exc()}")
            self.log_step(
                task_id,
                user_id,
                "error",
                f"LangGraph agentic workflow failed: {err_msg}",
                stage="langgraph_agentic",
                agent="LangGraphAgenticOrchestrator",
                status="failed",
                error_type=exc.__class__.__name__,
            )
            self.db.update_agent_resume_task_status(
                task_id=task_id,
                user_id=user_id,
                status="FAILED",
                error_message=err_msg,
                logs=json.dumps(self.logs, ensure_ascii=False),
                execution_plan=json.dumps(plan_data, ensure_ascii=False) if plan_data else None,
            )
            raise

    def _close_checkpointer(self) -> None:
        if self._checkpointer_context is None:
            return
        try:
            self._checkpointer_context.__exit__(None, None, None)
        finally:
            self._checkpointer_context = None
            self._graph = None

    def _load_task_node(self, state: ResumeAgentGraphState) -> ResumeAgentGraphState:
        task_id = state["task_id"]
        user_id = state["user_id"]
        task = self.db.get_agent_resume_task(user_id, task_id)
        if not task:
            raise ValueError(f"Agentic resume task does not exist: {task_id}")

        self.trace_id = str(task.get("trace_id") or task_id)
        plan_data = self._load_plan(task.get("execution_plan"))
        config_id = state.get("config_id")
        if config_id is None:
            config_id = plan_data.get("config_id")

        normalized_tool_mode = str(state.get("tool_calling_mode") or "native_responses").strip().lower().replace("-", "_")
        effective_tool_mode = "json_action" if normalized_tool_mode == "json_action" else "native_responses"
        plan_data["effective_tool_calling_mode"] = effective_tool_mode
        plan_data["orchestrator_backend"] = "langgraph"
        plan_data["langgraph"] = {
            "graph_version": LANGGRAPH_AGENTIC_GRAPH_VERSION,
            "nodes": [
                "load_task",
                "prepare_workspace",
                "run_agent_loop",
                "wait_for_human",
                "finalize_task",
            ],
            "state_source_of_truth": "agent_resume_tasks",
            "checkpointer": Config.LANGGRAPH_CHECKPOINTER,
            "native_interrupt_resume": True,
            "thread_id": f"agent-resume:{user_id}:{task_id}",
        }
        self._save_plan(task_id, user_id, plan_data, normalized_tool_mode, "RUNNING")
        self.log_step(
            task_id,
            user_id,
            "info",
            "LangGraph agentic workflow is starting.",
            {
                "execution_mode": self.execution_mode,
                "orchestrator_backend": "langgraph",
                "graph_version": LANGGRAPH_AGENTIC_GRAPH_VERSION,
                "tool_calling_mode": normalized_tool_mode,
                "effective_tool_calling_mode": effective_tool_mode,
            },
            stage="langgraph_bootstrap",
            agent="LangGraphAgenticOrchestrator",
            status="running",
        )
        state.update(
            {
                "task": task,
                "plan_data": plan_data,
                "config_id": config_id,
                "tool_calling_mode": normalized_tool_mode,
                "effective_tool_calling_mode": effective_tool_mode,
                "status": "RUNNING",
            }
        )
        return state
    def _prepare_workspace_node(self, state: ResumeAgentGraphState) -> ResumeAgentGraphState:
        task_id = state["task_id"]
        user_id = state["user_id"]
        task = state["task"]
        resume_id = task.get("resume_id")
        resume_data = self.db.get_user_resume(user_id, resume_id)
        if not resume_data:
            raise ValueError("Resume record was not found for this task.")

        resume_text = resume_data.get("cleanedText") or resume_data.get("rawText") or ""
        jd_text = task.get("jd_text") or ""
        if not str(resume_text).strip():
            raise ValueError("Resume text is empty.")
        if not str(jd_text).strip():
            raise ValueError("JD text is empty.")

        tool_write_file(user_id, task_id, "original_resume.txt", resume_text)
        tool_write_file(user_id, task_id, "job_description.txt", jd_text)
        tool_write_file(user_id, task_id, "stream_preview.md", "LangGraph agentic workflow started.")
        materialize_original_resume_file(user_id, task_id, resume_id, db=self.db)
        self.log_step(
            task_id,
            user_id,
            "info",
            "Workspace files are ready for the LangGraph agentic workflow.",
            {
                "resume_characters": len(resume_text),
                "jd_characters": len(jd_text),
            },
            stage="workspace",
            agent="LangGraphAgenticOrchestrator",
        )
        state.update(
            {
                "resume_id": resume_id,
                "resume_text": resume_text,
                "jd_text": jd_text,
            }
        )
        return state
    def _run_agent_loop_node(self, state: ResumeAgentGraphState) -> ResumeAgentGraphState:
        task_id = state["task_id"]
        user_id = state["user_id"]
        plan_data = state["plan_data"]
        config_id = state.get("config_id")
        is_co_pilot = bool(state.get("is_co_pilot", True))
        effective_tool_mode = str(state.get("effective_tool_calling_mode") or "native_responses")
        normalized_tool_mode = str(state.get("tool_calling_mode") or "native_responses")
        resume_text = str(state.get("resume_text") or "")
        jd_text = str(state.get("jd_text") or "")
        resume_payload = state.get("resume_payload") if isinstance(state.get("resume_payload"), dict) else {}
        human_context = str(resume_payload.get("answer") or "").strip()

        analyzer = AIAnalyzer()
        openai_client, resolved_cfg_id, provider, model_id = analyzer._client(user_id, config_id, True)
        self.openai_client = openai_client
        self.model = model_id
        plan_data["config_id"] = resolved_cfg_id or config_id
        plan_data["is_co_pilot"] = is_co_pilot
        self._save_plan(task_id, user_id, plan_data, normalized_tool_mode, "RUNNING")
        self.log_step(
            task_id,
            user_id,
            "info",
            "Resolved model configuration for LangGraph agentic mode.",
            {
                "provider": provider,
                "config_id": resolved_cfg_id or config_id,
                "model_id": model_id,
            },
            stage="model_config",
            agent="AIAnalyzer",
            model_id=model_id,
        )

        loop = AgenticToolLoop(DEFAULT_AGENT_TOOL_REGISTRY)
        ctx = AgentToolContext(
            user_id=user_id,
            task_id=task_id,
            resume_text=resume_text,
            jd_text=jd_text,
            is_co_pilot=is_co_pilot,
            human_context=human_context,
        )
        retry_failure_point = plan_data.get("retry_request") if isinstance(plan_data.get("retry_request"), dict) else None
        started_at = time.perf_counter()
        if effective_tool_mode == "native_responses":
            model_turn = ResponsesNativeToolModelTurn(
                openai_client,
                model_id,
                tools=DEFAULT_AGENT_TOOL_REGISTRY.responses_tools(is_co_pilot=is_co_pilot),
                namespace="agentic_resume_native_tools",
                temperature=0.1,
            )
            result = loop.run_native_responses_loop(
                ctx,
                model_turn,
                event_sink=self._event_sink(task_id, user_id, plan_data, normalized_tool_mode),
                retry_failure_point=retry_failure_point,
            )
        else:
            model_turn = ResponsesJsonActionModelTurn(
                openai_client,
                model_id,
                namespace="agentic_resume_json_action",
                temperature=0.1,
            )
            result = loop.run_json_action_loop(
                ctx,
                model_turn,
                event_sink=self._event_sink(task_id, user_id, plan_data, normalized_tool_mode),
                retry_failure_point=retry_failure_point,
            )
        duration_ms = int((time.perf_counter() - started_at) * 1000)

        if result.status == "needs_human":
            pending_question = self._pending_question_from_result(result)
            self.current_status = "WAITING_FOR_HUMAN"
            self._save_plan(task_id, user_id, plan_data, normalized_tool_mode, "WAITING_FOR_HUMAN")
            self.db.update_agent_resume_task_status(
                task_id=task_id,
                user_id=user_id,
                status="WAITING_FOR_HUMAN",
                pending_question=pending_question,
            )
            self.log_step(
                task_id,
                user_id,
                "info",
                "LangGraph agentic loop is waiting for user input.",
                stage="human_required",
                agent="LangGraphAgenticOrchestrator",
                duration_ms=duration_ms,
                status="waiting",
            )
            state.update(
                {
                    "status": "WAITING_FOR_HUMAN",
                    "plan_data": plan_data,
                    "pending_question": pending_question,
                    "loop_duration_ms": duration_ms,
                    "loop_result": {
                        "status": result.status,
                        "final_text": result.final_text,
                        "turns": result.turns,
                        "events": result.events,
                        "error": result.error,
                    },
                }
            )
            return state

        if result.status != "completed":
            raise RuntimeError(result.error or f"Agentic tool loop ended with status: {result.status}")

        state.update(
            {
                "status": "RUNNING",
                "plan_data": plan_data,
                "provider": provider,
                "model_id": model_id,
                "resolved_config_id": resolved_cfg_id,
                "loop_duration_ms": duration_ms,
                "loop_result": {
                    "status": result.status,
                    "final_text": result.final_text,
                    "turns": result.turns,
                    "events": result.events,
                    "error": result.error,
                },
            }
        )
        return state

    @staticmethod
    def _route_after_agent_loop(state: ResumeAgentGraphState) -> str:
        if state.get("status") == "WAITING_FOR_HUMAN":
            return "wait_for_human"
        return "finalize_task"

    @staticmethod
    def _pending_question_from_result(result: Any) -> str:
        events = result.events if isinstance(getattr(result, "events", None), list) else []
        for event in reversed(events):
            if event.get("tool_name") != "ask_user_for_fact":
                continue
            arguments = event.get("arguments")
            if isinstance(arguments, dict) and str(arguments.get("question") or "").strip():
                return str(arguments["question"]).strip()
            if str(event.get("error") or "").strip():
                return str(event["error"]).strip()
        return str(getattr(result, "final_text", "") or "请补充完成简历优化所需的事实信息。").strip()

    def _wait_for_human_node(self, state: ResumeAgentGraphState) -> ResumeAgentGraphState:
        pending_question = str(state.get("pending_question") or "请补充所需信息。").strip()
        resume_payload = interrupt(
            {
                "task_id": state["task_id"],
                "question": pending_question,
            }
        )
        payload = dict(resume_payload) if isinstance(resume_payload, dict) else {"answer": str(resume_payload or "")}
        answer = str(payload.get("answer") or "").strip()
        self.current_status = "RUNNING"
        self.db.update_agent_resume_task_status(
            task_id=state["task_id"],
            user_id=state["user_id"],
            status="RUNNING",
            pending_question="",
            human_answer=answer,
        )
        state.update(
            {
                "status": "RUNNING",
                "pending_question": "",
                "resume_payload": payload,
            }
        )
        return state

    def _finalize_task_node(self, state: ResumeAgentGraphState) -> ResumeAgentGraphState:
        task_id = state["task_id"]
        user_id = state["user_id"]
        resume_text = str(state.get("resume_text") or "")
        jd_text = str(state.get("jd_text") or "")
        is_co_pilot = bool(state.get("is_co_pilot", True))
        normalized_tool_mode = str(state.get("tool_calling_mode") or "native_responses")
        plan_data = state["plan_data"]
        loop_result = state["loop_result"]
        result_events = loop_result.get("events") if isinstance(loop_result.get("events"), list) else []
        loop_metrics = self._summarize_loop_events(result_events)
        ctx = AgentToolContext(
            user_id=user_id,
            task_id=task_id,
            resume_text=resume_text,
            jd_text=jd_text,
            is_co_pilot=is_co_pilot,
        )

        if self._has_successful_tool_result(result_events, "finalize_resume_artifacts"):
            loop_metrics["skipped_duplicate_finalize"] = True
            loop_metrics["forced_finalize"] = False
        else:
            finalize_started_at = time.perf_counter()
            finalize_result = DEFAULT_AGENT_TOOL_REGISTRY.execute("finalize_resume_artifacts", {}, ctx)
            loop_metrics["forced_finalize"] = True
            loop_metrics["skipped_duplicate_finalize"] = False
            loop_metrics["manual_finalize_ok"] = bool(finalize_result.get("ok"))
            loop_metrics["manual_finalize_duration_ms"] = int((time.perf_counter() - finalize_started_at) * 1000)
            self.log_step(
                task_id,
                user_id,
                "tool_response" if finalize_result.get("ok") else "error",
                "Forced finalize_resume_artifacts completed." if finalize_result.get("ok") else "Forced finalize_resume_artifacts failed.",
                finalize_result,
                stage="tool_result",
                agent="AgenticToolLoop",
                duration_ms=int(finalize_result.get("duration_ms") or 0),
                status="completed" if finalize_result.get("ok") else "failed",
                error_type="" if finalize_result.get("ok") else "ToolExecutionError",
            )
            if not finalize_result.get("ok"):
                raise RuntimeError(str(finalize_result.get("error") or "finalize_resume_artifacts failed."))

        plan_data["agentic_metrics"] = loop_metrics
        final_resume_md = self._read_final_markdown(user_id, task_id, resume_text)
        self.current_status = "COMPLETED"
        self._save_plan(task_id, user_id, plan_data, normalized_tool_mode, "COMPLETED")
        self.db.update_agent_resume_task_status(
            task_id=task_id,
            user_id=user_id,
            status="COMPLETED",
            logs=json.dumps(self.logs, ensure_ascii=False),
            optimized_resume_md=final_resume_md,
            execution_plan=json.dumps(plan_data, ensure_ascii=False),
            pending_question="",
        )
        self.log_step(
            task_id,
            user_id,
            "info",
            "LangGraph agentic workflow completed.",
            {
                "turns": int(loop_result.get("turns") or 0),
                "duration_ms": int(state.get("loop_duration_ms") or 0),
                "agentic_metrics": loop_metrics,
                "graph_version": LANGGRAPH_AGENTIC_GRAPH_VERSION,
            },
            stage="finalize",
            agent="LangGraphAgenticOrchestrator",
            duration_ms=int(state.get("loop_duration_ms") or 0),
        )
        state.update(
            {
                "status": "COMPLETED",
                "plan_data": plan_data,
                "loop_metrics": loop_metrics,
                "final_resume_md": final_resume_md,
            }
        )
        return state


class LangGraphPipelineOrchestrator(LangGraphAgenticOrchestrator):
    """Compatibility mode that runs the resume workflow entirely through LangGraph."""

    execution_mode = "pipeline"

    def __init__(
        self,
        agent_id: str = "langgraph_pipeline_orchestrator",
        role: str = "LangGraphPipelineOrchestrator",
        model: str = "gpt-4o-mini",
        openai_client: Optional[Any] = None,
        checkpointer: Optional[Any] = None,
    ):
        super().__init__(
            agent_id=agent_id,
            role=role,
            model=model,
            openai_client=openai_client,
            checkpointer=checkpointer,
        )

    async def run_orchestration(
        self,
        task_id: str,
        user_id: Any,
        config_id: Optional[str],
        is_co_pilot: bool = True,
    ) -> None:
        await super().run_orchestration(
            task_id=task_id,
            user_id=user_id,
            config_id=config_id,
            is_co_pilot=is_co_pilot,
            tool_calling_mode="json_action",
        )
