from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "internpath-ai-service"}


def test_rag_search_runs_hybrid_retrieval_and_preserves_resume_provenance(monkeypatch):
    monkeypatch.setattr(
        "app.rag.hybrid_retriever.get_embedding",
        lambda _query, _config=None: [1.0, 0.0],
    )
    response = client.post(
        "/ai/rag/search",
        json={
            "query": "Python FastAPI",
            "documents": [
                {
                    "documentId": "doc-1",
                    "chunkId": "resume-1",
                    "content": "This role needs Python and FastAPI backend development.",
                    "sectionType": "project_experience",
                    "semanticType": "experience",
                    "importance": 0.9,
                    "embedding": [1.0, 0.0],
                    "metadata": {"sourceType": "RESUME", "sourceBlockIds": ["block-1"]},
                },
                {
                    "documentId": "doc-2",
                    "chunkId": "resume-2",
                    "content": "Marketing copy and unrelated operations text.",
                    "embedding": [0.0, 1.0],
                    "metadata": {"sourceType": "RESUME", "sourceBlockIds": ["block-2"]},
                },
            ],
            "topK": 2,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["results"]
    assert body["strategy"] == "hybrid"
    assert body["semanticMode"] == "embedding"
    assert body["semanticChunkCount"] == 2
    assert body["results"][0]["documentId"] == "doc-1"
    assert body["results"][0]["sectionType"] == "project_experience"
    assert body["results"][0]["metadata"]["sourceBlockIds"] == ["block-1"]


def test_rag_search_marks_missing_vectors_as_lexical_fallback(monkeypatch):
    monkeypatch.setattr(
        "app.rag.hybrid_retriever.get_embedding",
        lambda _query, _config=None: [],
    )
    response = client.post(
        "/ai/rag/search",
        json={
            "query": "Python FastAPI",
            "documents": [
                {
                    "documentId": "doc-1",
                    "chunkId": "resume-1",
                    "content": "Built Python FastAPI backend APIs.",
                    "metadata": {"sourceBlockIds": ["block-1"]},
                }
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["strategy"] == "hybrid"
    assert body["semanticMode"] == "lexical_fallback"
    assert body["semanticChunkCount"] == 0
    assert body["results"][0]["metadata"]["sourceBlockIds"] == ["block-1"]


def test_verify_report_finds_unsupported_claim():
    response = client.post(
        "/ai/verify-report",
        json={
            "report": {"summary": "Candidate has Kubernetes production experience."},
            "jdText": "Need Python backend experience.",
            "resumeText": "Candidate has Python project experience.",
            "evidenceChunks": [
                {
                    "documentId": "resume",
                    "chunkId": "resume#chunk-0",
                    "text": "Candidate has Python project experience.",
                    "metadata": {"sourceType": "RESUME"},
                }
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["evidenceSummary"]["unsupportedClaims"] >= 1
    assert body["hallucinationRisk"] in {"MEDIUM", "HIGH"}
    assert body["verificationResults"][0]["status"] == "unsupported"


def test_analyze_jd_returns_required_sections():
    response = client.post(
        "/ai/analyze-jd",
        json={
            "taskId": "task-1",
            "userId": "user-1",
            "jdText": "Python backend intern, requires FastAPI and SQL.",
            "resumeText": "I built a Python FastAPI project.",
            "knowledgeTexts": ["SQL basics are useful for backend interns."],
            "options": {
                "enableRag": True,
                "enableVerification": True,
                "enableHallucinationCheck": True,
                "enableRewrite": True,
            },
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert "finalReport" in data
    assert "evidenceSummary" in data
    assert "hallucinationControl" in data
    assert "claims" in data
    assert "verificationResults" in data
    assert "workflowLogs" in data
    assert "qualityEvaluation" in data
    assert {"finalQualityScore", "qualityGrade", "qualityGateStatus", "scores", "issues"} <= set(data["qualityEvaluation"])
    assert data["verificationResults"]
    first = data["verificationResults"][0]
    assert {"claimId", "claimText", "claimType", "status", "confidenceScore", "reason", "evidenceChunks"} <= set(first)
    node_names = {item["nodeName"] for item in data["workflowLogs"]}
    assert {"JDParserNode", "RAGRetrieverNode", "EvidenceCheckNode", "FinalReportNode"} <= node_names
    for item in data["workflowLogs"]:
        assert {"nodeName", "status", "durationMs", "inputSummary", "outputSummary"} <= set(item)


def test_analyze_jd_accepts_documents_and_returns_document_citations():
    response = client.post(
        "/ai/analyze-jd",
        json={
            "taskId": "task-docs",
            "userId": "user-1",
            "jdText": "Need Python backend intern.",
            "resumeText": "",
            "knowledgeTexts": [],
            "documents": [
                {
                    "documentId": "42",
                    "chunkId": "42-0",
                    "content": "Python backend project evidence.",
                    "metadata": {
                        "fileName": "resume.pdf",
                        "sourceType": "resume",
                        "chunkIndex": 0,
                    },
                }
            ],
            "options": {
                "enableRag": True,
                "enableVerification": True,
                "enableHallucinationCheck": True,
                "enableRewrite": True,
            },
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["citations"]
    assert data["citations"][0]["documentId"] == "42"
    assert data["citations"][0]["chunkId"] == "42-0"
    assert data["citations"][0]["fileName"] == "resume.pdf"
    evidence_chunks = data["verificationResults"][0]["evidenceChunks"]
    if evidence_chunks:
        assert evidence_chunks[0]["fileName"] == "resume.pdf"
