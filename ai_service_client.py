from __future__ import annotations

from typing import Any

import httpx

from config import Config


class AiServiceClient:
    def __init__(self, base_url: str | None = None, timeout: float = 120.0):
        self.base_url = (base_url or Config.AI_SERVICE_BASE_URL).rstrip("/")
        self.timeout = timeout

    def health(self) -> dict[str, Any]:
        return self._get("/health")

    def analyze_jd(
        self,
        *,
        task_id: str,
        user_id: str,
        jd_text: str,
        resume_text: str = "",
        knowledge_texts: list[str] | None = None,
        documents: list[dict[str, Any]] | None = None,
        options: dict[str, bool] | None = None,
        embedding_model_id: str | None = None,
        embedding_provider: str | None = None,
        embedding_api_key: str | None = None,
        embedding_base_url: str | None = None,
    ) -> dict[str, Any]:
        return self._post(
            "/ai/analyze-jd",
            {
                "taskId": task_id,
                "userId": user_id,
                "jdText": jd_text,
                "resumeText": resume_text,
                "knowledgeTexts": knowledge_texts or [],
                "documents": documents or [],
                "options": options or {},
                "embeddingModelId": embedding_model_id,
                "embeddingProvider": embedding_provider,
                "embeddingApiKey": embedding_api_key,
                "embeddingBaseUrl": embedding_base_url,
            },
        )

    def rag_search(
        self,
        *,
        query: str,
        documents: list[dict[str, Any]],
        top_k: int = 6,
        strategy: str = "hybrid",
    ) -> dict[str, Any]:
        """Search structured evidence without forwarding backend model credentials."""
        return self._post(
            "/ai/rag/search",
            {
                "query": query,
                "documents": documents,
                "topK": top_k,
                "strategy": strategy,
            },
        )

    def _get(self, path: str) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(f"{self.base_url}{path}")
            response.raise_for_status()
            return response.json()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(f"{self.base_url}{path}", json=payload)
            response.raise_for_status()
            return response.json()
