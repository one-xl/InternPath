from __future__ import annotations

from app.api.schemas import AnalyzeJdRequest
from app.rag.project_reranker import rerank_projects
from app.workflow.nodes import build_analyze_jd_workflow, workflow_response
from app.workflow.state import WorkflowState


def _project_candidates() -> list[dict]:
    return [
        {
            "documentId": "payment-platform",
            "chunkId": "payment-1",
            "chunkText": "Built a FastAPI payment platform and reduced settlement latency by 40%.",
            "metadata": {"sourceType": "project", "documentTitle": "Payment platform"},
            "score": 0.92,
        },
        {
            "documentId": "mobile-game",
            "chunkId": "game-1",
            "chunkText": "Built a Unity mobile game with C# and in-app purchases.",
            "metadata": {"sourceType": "project", "documentTitle": "Mobile game"},
            "score": 0.41,
        },
    ]


def test_project_reranker_keeps_llm_recommendations_grounded_in_selected_evidence():
    result = rerank_projects(
        _project_candidates(),
        jd_text="Python FastAPI engineer needed for payment platform APIs.",
        resume_text="Current resume mentions Python backend work but omits payment latency results.",
        llm_answer={
            "recommendations": [
                {
                    "documentId": "payment-platform",
                    "chunkIds": ["payment-1"],
                    "summary": "FastAPI payment platform delivery.",
                    "matchReason": "Matches Python, FastAPI, payment APIs and latency work.",
                    "resumeSuggestion": "Add the 40% settlement-latency reduction to the FastAPI project bullet.",
                    "score": 96,
                }
            ]
        },
    )

    assert result["rerankMode"] == "llm"
    assert result["fallbackReason"] is None
    recommendation = result["recommendations"][0]
    assert recommendation["documentId"] == "payment-platform"
    assert recommendation["chunkIds"] == ["payment-1"]
    assert recommendation["evidence"] == [
        "Built a FastAPI payment platform and reduced settlement latency by 40%."
    ]
    assert "40%" in recommendation["resumeSuggestion"]


def test_project_reranker_marks_deterministic_fallback_when_llm_fails():
    result = rerank_projects(
        _project_candidates(),
        jd_text="Python FastAPI engineer needed for payment platform APIs.",
        resume_text="Current resume contains Python backend experience.",
        llm_answer=RuntimeError("LLM unavailable"),
    )

    assert result["rerankMode"] == "fallback"
    assert "LLM unavailable" in result["fallbackReason"]
    recommendation = result["recommendations"][0]
    assert recommendation["documentId"] == "payment-platform"
    assert recommendation["chunkIds"] == ["payment-1"]
    assert recommendation["evidence"]
    assert recommendation["summary"]
    assert recommendation["matchReason"]
    assert recommendation["resumeSuggestion"]


def test_analysis_workflow_exposes_selected_project_recommendations_and_resume_suggestions(monkeypatch):
    monkeypatch.setattr("app.rag.hybrid_retriever.get_embedding", lambda *_args, **_kwargs: [])

    request = AnalyzeJdRequest(
        taskId="project-rag-workflow",
        userId="1",
        jdText="Python FastAPI engineer needed for payment platform API work.",
        resumeText="Current resume says Python backend engineer, but omits delivery metrics.",
        documents=[
            {
                "documentId": "payment-platform",
                "chunkId": "payment-1",
                "content": "Built a FastAPI payment platform and reduced settlement latency by 40%.",
                "metadata": {"sourceType": "project", "documentTitle": "Payment platform"},
            },
            {
                "documentId": "old-resume",
                "chunkId": "resume-1",
                "content": "This must not be recommended as a project document.",
                "metadata": {"sourceType": "resume", "documentTitle": "Current resume"},
            },
        ],
    )

    state = build_analyze_jd_workflow().run(WorkflowState(request=request))
    response = workflow_response(request.taskId, state)
    project_rerank = response["data"]["projectRerank"]

    assert project_rerank["recommendations"]
    recommendation = project_rerank["recommendations"][0]
    assert recommendation["documentId"] == "payment-platform"
    assert recommendation["evidence"]
    assert response["data"]["finalReport"]["projectRecommendations"] == project_rerank["recommendations"]
    assert response["data"]["finalReport"]["resumeSuggestions"]
