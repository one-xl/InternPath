from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from config import Config

from .graph import ResumeAdvisorGraph


class ResumeAdvisorGraphState(TypedDict, total=False):
    user_id: Any
    session_id: str
    run_id: str
    result: dict[str, Any]
    resume_payload: dict[str, Any]


class LangGraphResumeAdvisor:
    """Durable LangGraph shell around one evidence-first Advisor turn.

    The domain graph remains in :class:`ResumeAdvisorGraph`; this module owns the
    resumable seam and only pauses after a user-visible question or suggestion.
    """

    def __init__(
        self,
        repository: Any,
        *,
        checkpointer: Any | None = None,
        model_provider: Any | None = None,
    ):
        self.repository = repository
        self.engine = ResumeAdvisorGraph(repository, model_provider=model_provider)
        self._provided_checkpointer = checkpointer
        self._checkpointer_context = None
        self._graph = None

    def _build_checkpointer(self) -> Any:
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

    def _build_graph(self, checkpointer: Any):
        graph = StateGraph(ResumeAdvisorGraphState)
        graph.add_node("execute_turn", self._execute_turn)
        graph.add_node("wait_for_user", self._wait_for_user)
        graph.add_edge(START, "execute_turn")
        graph.add_conditional_edges(
            "execute_turn",
            self._route_after_turn,
            {"wait_for_user": "wait_for_user", "done": END},
        )
        graph.add_edge("wait_for_user", "execute_turn")
        return graph.compile(checkpointer=checkpointer, name="internpath_resume_advisor")

    def _ensure_graph(self):
        if self._graph is None:
            self._graph = self._build_graph(self._build_checkpointer())
        return self._graph

    @staticmethod
    def _config(user_id: Any, session_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": f"resume-advisor:{user_id}:{session_id}"}}

    def _execute_turn(self, state: ResumeAdvisorGraphState) -> ResumeAdvisorGraphState:
        result = self.engine.run(
            user_id=state["user_id"],
            session_id=state["session_id"],
            run_id=state["run_id"],
        )
        return {**state, "result": result}

    @staticmethod
    def _route_after_turn(state: ResumeAdvisorGraphState) -> str:
        status = str((state.get("result") or {}).get("status") or "")
        return "wait_for_user" if status in {"WAITING_FOR_USER", "READY_FOR_CONFIRMATION"} else "done"

    def _wait_for_user(self, state: ResumeAdvisorGraphState) -> ResumeAdvisorGraphState:
        result = state.get("result") or {}
        resume_payload = interrupt(
            {
                "sessionId": state["session_id"],
                "runId": state["run_id"],
                "status": result.get("status"),
                "message": result.get("message"),
                "suggestion": result.get("suggestion"),
            }
        )
        return {**state, "resume_payload": dict(resume_payload or {})}

    def run(self, *, user_id: Any, session_id: str, run_id: str) -> dict[str, Any]:
        try:
            result = self._ensure_graph().invoke(
                {"user_id": user_id, "session_id": session_id, "run_id": run_id},
                config=self._config(user_id, session_id),
            )
            return dict(result.get("result") or {"status": "PAUSED"})
        finally:
            self._close_checkpointer()

    def resume(self, *, user_id: Any, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._ensure_graph().invoke(
                Command(resume=payload),
                config=self._config(user_id, session_id),
            )
            return dict(result.get("result") or {"status": "PAUSED"})
        finally:
            self._close_checkpointer()

    def _close_checkpointer(self) -> None:
        if self._checkpointer_context is None:
            return
        try:
            self._checkpointer_context.__exit__(None, None, None)
        finally:
            self._checkpointer_context = None
            self._graph = None
