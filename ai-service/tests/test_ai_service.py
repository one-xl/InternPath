from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "internpath-ai-service"}


def test_rag_search_returns_relevant_chunk():
    response = client.post(
        "/ai/rag/search",
        json={
            "query": "Python FastAPI",
            "documents": [
                {
                    "documentId": "doc-1",
                    "content": "This role needs Python and FastAPI backend development.",
                    "metadata": {"sourceType": "JD"},
                },
                {
                    "documentId": "doc-2",
                    "content": "Marketing copy and unrelated operations text.",
                    "metadata": {"sourceType": "KNOWLEDGE_BASE"},
                },
            ],
            "topK": 2,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["results"]
    assert body["results"][0]["documentId"] == "doc-1"


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
