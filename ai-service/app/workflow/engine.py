from __future__ import annotations

import time
from typing import Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from app.workflow.logs import make_workflow_log
from app.workflow.state import WorkflowState


class WorkflowExecutionError(RuntimeError):
    """Raised when a critical workflow node fails."""


class WorkflowNode(Protocol):
    node_name: str
    critical: bool

    def input_summary(self, state: WorkflowState) -> str: ...

    def run(self, state: WorkflowState) -> WorkflowState: ...

    def output_summary(self, state: WorkflowState) -> str: ...


class _WorkflowGraphState(TypedDict):
    workflow_state: WorkflowState


class WorkflowEngine:
    def __init__(self, nodes: list[WorkflowNode]):
        self.nodes = nodes
        self.backend = "langgraph"
        self._graph = self._build_graph(nodes) if nodes else None

    def run(self, state: WorkflowState) -> WorkflowState:
        if self._graph is None:
            return state
        result = self._graph.invoke({"workflow_state": state})
        return result["workflow_state"]

    def _build_graph(self, nodes: list[WorkflowNode]):
        graph = StateGraph(_WorkflowGraphState)
        previous = START
        for index, node in enumerate(nodes):
            graph_node_name = f"{index:02d}_{node.node_name}"
            graph.add_node(graph_node_name, self._runner_for(node))
            graph.add_edge(previous, graph_node_name)
            previous = graph_node_name
        graph.add_edge(previous, END)
        return graph.compile(name="internpath_ai_service_workflow")

    @staticmethod
    def _runner_for(node: WorkflowNode):
        def run_node(graph_state: _WorkflowGraphState) -> _WorkflowGraphState:
            state = graph_state["workflow_state"]
            started = time.perf_counter()
            input_summary = safe_summary(lambda: node.input_summary(state))
            try:
                state = node.run(state)
                duration_ms = int((time.perf_counter() - started) * 1000)
                state.workflow_logs.append(
                    make_workflow_log(
                        node_name=node.node_name,
                        status="SUCCESS",
                        duration_ms=duration_ms,
                        input_summary=input_summary,
                        output_summary=safe_summary(lambda: node.output_summary(state)),
                    )
                )
            except Exception as exc:
                duration_ms = int((time.perf_counter() - started) * 1000)
                is_critical = getattr(node, "critical", True)
                status = "FAILED" if is_critical else "WARNING"
                state.workflow_logs.append(
                    make_workflow_log(
                        node_name=node.node_name,
                        status=status,
                        duration_ms=duration_ms,
                        input_summary=input_summary,
                        output_summary="",
                        error=str(exc),
                    )
                )
                if is_critical:
                    state.failed = True
                    state.error = str(exc)
                    raise WorkflowExecutionError(str(exc)) from exc
            return {"workflow_state": state}

        return run_node


def safe_summary(fn) -> str:
    try:
        return str(fn())
    except Exception as exc:  # noqa: BLE001
        return f"summary unavailable: {exc}"
