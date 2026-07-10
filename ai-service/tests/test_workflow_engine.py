import pytest

from app.workflow.engine import WorkflowEngine, WorkflowExecutionError
from app.workflow.state import WorkflowState


class _AppendNode:
    node_name = "AppendNode"
    critical = True

    def __init__(self, value):
        self.value = value

    def input_summary(self, state):
        return f"before={state.data.get('items', [])}"

    def run(self, state):
        state.data.setdefault("items", []).append(self.value)
        return state

    def output_summary(self, state):
        return f"after={state.data.get('items', [])}"


class _FailingNode:
    node_name = "FailingNode"

    def __init__(self, critical):
        self.critical = critical

    def input_summary(self, state):
        return "will fail"

    def run(self, state):
        raise RuntimeError("node failed")

    def output_summary(self, state):
        return "unreachable"


def test_workflow_engine_runs_nodes_in_order():
    state = WorkflowState(request={})
    engine = WorkflowEngine([_AppendNode("a"), _AppendNode("b")])

    result = engine.run(state)

    assert engine.backend == "langgraph"
    assert engine._graph is not None
    assert result.data["items"] == ["a", "b"]
    assert [log["status"] for log in result.workflow_logs] == ["SUCCESS", "SUCCESS"]


def test_workflow_engine_records_failed_critical_node():
    state = WorkflowState(request={})
    engine = WorkflowEngine([_AppendNode("a"), _FailingNode(critical=True), _AppendNode("b")])

    with pytest.raises(WorkflowExecutionError):
        engine.run(state)

    assert state.failed is True
    assert state.data["items"] == ["a"]
    assert state.workflow_logs[-1]["nodeName"] == "FailingNode"
    assert state.workflow_logs[-1]["status"] == "FAILED"


def test_workflow_engine_warns_and_continues_for_noncritical_node():
    state = WorkflowState(request={})
    engine = WorkflowEngine([_AppendNode("a"), _FailingNode(critical=False), _AppendNode("b")])

    result = engine.run(state)

    assert result.data["items"] == ["a", "b"]
    assert [log["status"] for log in result.workflow_logs] == ["SUCCESS", "WARNING", "SUCCESS"]
