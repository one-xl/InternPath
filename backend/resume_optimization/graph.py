from __future__ import annotations

import json
import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .prompts import HR_ANALYST_PROMPT, JD_ANALYST_PROMPT, ORCHESTRATOR_PROMPT, RESUME_EDITOR_PROMPT


class OptimizationState(TypedDict, total=False):
    jd_text: str
    resume_blocks: list[dict[str, Any]]
    project_chunks: list[dict[str, Any]]
    model_call: Any
    requirements: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    diffs: list[dict[str, Any]]
    hr: dict[str, Any]
    summary: str
    events: list[dict[str, Any]]


def _json(value: str, fallback: Any) -> Any:
    match = re.search(r"\{.*\}|\[.*\]", value or "", flags=re.S)
    if not match:
        return fallback
    try:
        return json.loads(match.group(0))
    except ValueError:
        return fallback


def build_optimization_graph(retrieve: Any):
    def jd_analyst(state: OptimizationState) -> dict[str, Any]:
        raw = state["model_call"](JD_ANALYST_PROMPT, state["jd_text"])
        parsed = _json(raw, {"requirements": []})
        return {"requirements": list(parsed.get("requirements") or []), "events": [*state.get("events", []), {"agent": "jd_analyst", "status": "completed"}]}

    def rag(state: OptimizationState) -> dict[str, Any]:
        query = "\n".join([state["jd_text"], *[str(item.get("text") or "") for item in state.get("requirements", [])]])
        return {"evidence": retrieve(query, state["resume_blocks"], state.get("project_chunks", [])), "events": [*state.get("events", []), {"agent": "hybrid_rag", "status": "completed"}]}

    def editor(state: OptimizationState) -> dict[str, Any]:
        payload = {"jd": state["jd_text"], "requirements": state.get("requirements", []), "resumeBlocks": state["resume_blocks"], "evidence": state.get("evidence", [])}
        parsed = _json(state["model_call"](RESUME_EDITOR_PROMPT, json.dumps(payload, ensure_ascii=False)), {"diffs": []})
        return {"diffs": list(parsed.get("diffs") or []), "events": [*state.get("events", []), {"agent": "resume_editor", "status": "completed"}]}

    def hr(state: OptimizationState) -> dict[str, Any]:
        payload = {"jd": state["jd_text"], "requirements": state.get("requirements", []), "resumeBlocks": state["resume_blocks"], "evidence": state.get("evidence", []), "diffs": state.get("diffs", [])}
        result = _json(state["model_call"](HR_ANALYST_PROMPT, json.dumps(payload, ensure_ascii=False)), {"matched": False, "summary": "未得到 HR 审查结果", "strengths": [], "risks": []})
        return {"hr": result, "events": [*state.get("events", []), {"agent": "hr_analyst", "status": "completed"}]}

    def orchestrator(state: OptimizationState) -> dict[str, Any]:
        payload = {"hr": state.get("hr", {}), "diffs": state.get("diffs", []), "evidence": state.get("evidence", [])}
        return {"summary": state["model_call"](ORCHESTRATOR_PROMPT, json.dumps(payload, ensure_ascii=False)), "events": [*state.get("events", []), {"agent": "orchestrator", "status": "completed"}]}

    graph = StateGraph(OptimizationState)
    graph.add_node("jd_analyst", jd_analyst)
    graph.add_node("hybrid_rag", rag)
    graph.add_node("resume_editor", editor)
    graph.add_node("hr_analyst", hr)
    graph.add_node("orchestrator", orchestrator)
    graph.add_edge(START, "jd_analyst")
    graph.add_edge("jd_analyst", "hybrid_rag")
    graph.add_edge("hybrid_rag", "resume_editor")
    graph.add_edge("resume_editor", "hr_analyst")
    graph.add_edge("hr_analyst", "orchestrator")
    graph.add_edge("orchestrator", END)
    return graph.compile()
