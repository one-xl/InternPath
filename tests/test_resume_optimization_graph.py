from __future__ import annotations

import json

from backend.resume_optimization.graph import build_optimization_graph


def test_langgraph_runs_all_four_agents_with_grounded_diff():
    responses = iter([
        json.dumps({"requirements": [{"id": "r1", "text": "Python", "priority": "high"}]}),
        json.dumps({"diffs": [{"targetBlockId": "b1", "originalText": "做开发", "replacementText": "使用 Python 开发接口", "reason": "对应 Python 要求", "evidenceIds": ["b1"]}]}),
        json.dumps({"matched": False, "summary": "有待补充", "strengths": [], "risks": [{"targetBlockId": "b1", "reason": "缺少关键词"}]}),
        "请确认并修改该条项目经历。",
    ])
    graph = build_optimization_graph(lambda _query, resume, _projects: [{"chunkId": resume[0]["id"], "text": resume[0]["text"], "score": 0.9}])
    result = graph.invoke({"jd_text": "需要 Python", "resume_blocks": [{"id": "b1", "text": "做开发", "location": {}, "section": "项目经历"}], "project_chunks": [], "model_call": lambda _system, _content: next(responses), "events": []})

    assert result["diffs"][0]["targetBlockId"] == "b1"
    assert result["hr"]["matched"] is False
    assert [event["agent"] for event in result["events"]] == ["jd_analyst", "hybrid_rag", "resume_editor", "hr_analyst", "orchestrator"]
