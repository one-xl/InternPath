from __future__ import annotations

import time
from typing import Protocol

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


class WorkflowEngine:
    def __init__(self, nodes: list[WorkflowNode]):
        self.nodes = nodes

    def run(self, state: WorkflowState) -> WorkflowState:
        for node in self.nodes:
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
                status = "FAILED" if node.critical else "WARNING"
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
                if node.critical:
                    state.failed = True
                    state.error = str(exc)
                    raise WorkflowExecutionError(str(exc)) from exc
        return state


def safe_summary(fn) -> str:
    try:
        return str(fn())
    except Exception as exc:  # noqa: BLE001
        return f"summary unavailable: {exc}"
