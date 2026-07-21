from __future__ import annotations

from models import JobAnalysis
from service import CareerPathAIService


class _RecordingAiServiceClient:
    def __init__(self) -> None:
        self.last_kwargs: dict | None = None

    def analyze_jd(self, **kwargs):
        self.last_kwargs = kwargs
        return {
            "taskId": kwargs["task_id"],
            "status": "success",
            "data": {
                "finalReport": {},
                "evidenceSummary": {},
                "hallucinationControl": {},
                "citations": [],
                "verificationResults": [],
                "workflowLogs": [],
                "qualityEvaluation": {},
            },
        }


class _Cursor:
    def execute(self, *_args, **_kwargs) -> None:
        pass

    def fetchone(self):
        return None


class _Connection:
    def cursor(self) -> _Cursor:
        return _Cursor()

    def close(self) -> None:
        pass


class _ProjectKnowledgeStore:
    def __init__(self) -> None:
        self.chunks = [
            {
                "document_id": 41,
                "chunk_index": 0,
                "chunk_text": "Built a FastAPI payment platform and reduced settlement latency by 40%.",
                "metadata": {"sourceType": "project"},
                "file_name": "payment-platform.txt",
                "source_type": "project",
                "title": "payment-platform",
                "sectionId": "project-payment",
                "sectionType": "project_experience",
                "sectionTitle": "Payment platform",
                "hierarchy": ["Payment platform"],
                "semanticType": "experience",
                "importance": 0.9,
                "keywords": ["Python", "FastAPI"],
                "embeddingText": "FastAPI payment platform",
                "embedding": [],
            },
            {
                "document_id": 42,
                "chunk_index": 0,
                "chunk_text": "This resume material must not become project knowledge evidence.",
                "metadata": {"sourceType": "resume"},
                "file_name": "current-resume.txt",
                "source_type": "resume",
                "title": "current-resume",
                "sectionId": "resume-summary",
                "sectionType": "summary",
                "sectionTitle": "Summary",
                "hierarchy": ["Summary"],
                "semanticType": "general",
                "importance": 0.6,
                "keywords": [],
                "embeddingText": "resume material",
                "embedding": [],
            },
        ]

    def get_connection(self) -> _Connection:
        return _Connection()

    def create_analysis_task(self, **_kwargs) -> int:
        return 1

    def update_analysis_task_status(self, *_args, **_kwargs) -> None:
        pass

    def get_knowledge_chunks(self, _user_id: int, document_ids: list[int]) -> list[dict]:
        return [chunk for chunk in self.chunks if chunk["document_id"] in document_ids]

    def list_knowledge_documents(self, _user_id: int, source_type: str | None = None, _limit: int = 50) -> list[dict]:
        documents = [
            {"id": 41, "source_type": "project", "status": "READY"},
            {"id": 42, "source_type": "resume", "status": "READY"},
        ]
        return [document for document in documents if source_type is None or document["source_type"] == source_type]

    def save_analysis_report(self, **_kwargs) -> int:
        return 1

    def save_claim_check_results(self, *_args, **_kwargs) -> None:
        pass

    def save_workflow_logs(self, *_args, **_kwargs) -> None:
        pass

    def save_quality_evaluation(self, *_args, **_kwargs) -> None:
        pass


def test_analysis_forwards_only_selected_project_knowledge_documents(monkeypatch):
    """Project RAG must not silently mix a resume material into the selected project scope."""
    client = _RecordingAiServiceClient()
    store = _ProjectKnowledgeStore()
    service = object.__new__(CareerPathAIService)
    service.ai_service_client = client
    service.user_db = lambda _user_id: store
    monkeypatch.setattr(service, "get_embedding_for_text", lambda *_args: [])

    service.analyze_jd_with_guardrails(
        user_id=1,
        jd_text="Looking for a Python FastAPI engineer with payment platform experience.",
        resume_text="Current resume says Python backend engineer.",
        selected_document_ids=[41, 42],
        project_knowledge_scope="selected",
        original_analysis=JobAnalysis(skills=["Python"], difficulty="medium", job_summary="backend"),
    )

    assert client.last_kwargs is not None
    documents = client.last_kwargs["documents"]
    assert {document["documentId"] for document in documents} == {"41"}
    assert {document["metadata"]["sourceType"] for document in documents} == {"project"}


def test_analysis_all_scope_uses_all_and_only_ready_project_documents(monkeypatch):
    client = _RecordingAiServiceClient()
    store = _ProjectKnowledgeStore()
    service = object.__new__(CareerPathAIService)
    service.ai_service_client = client
    service.user_db = lambda _user_id: store
    monkeypatch.setattr(service, "get_embedding_for_text", lambda *_args: [])

    service.analyze_jd_with_guardrails(
        user_id=1,
        jd_text="Looking for a Python FastAPI engineer with payment platform experience.",
        resume_text="Current resume says Python backend engineer.",
        selected_document_ids=[42],
        project_knowledge_scope="all",
        original_analysis=JobAnalysis(skills=["Python"], difficulty="medium", job_summary="backend"),
    )

    assert client.last_kwargs is not None
    assert {document["documentId"] for document in client.last_kwargs["documents"]} == {"41"}
