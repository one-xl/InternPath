"""LLM gate that turns retrieved resume chunks into attributable evidence."""

from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.agents.base import BaseAgent
from backend.agents.schemas import parse_json_model


class RagEvidenceReview(BaseModel):
    """Only identifiers from the supplied retrieval result may be selected."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    selected_chunk_ids: list[str] = Field(default_factory=list, max_length=6)
    relevance_summary: str = Field(min_length=1, max_length=1200)
    uncovered_requirements: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("selected_chunk_ids")
    @classmethod
    def unique_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("selected_chunk_ids 不能重复")
        return normalized


class RagEvidenceReviewer(BaseAgent):
    """Review retrieved evidence with the configured model before a writer sees it."""

    def __init__(
        self,
        agent_id: str = "resume_rag_reviewer",
        role: str = "RAG_Evidence_Reviewer",
        model: str = "gpt-4o-mini",
        openai_client: Any | None = None,
    ) -> None:
        super().__init__(agent_id=agent_id, role=role, model=model, openai_client=openai_client)
        self._load_system_prompt()

    def _load_system_prompt(self) -> None:
        prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "rag_evidence_reviewer.md")
        try:
            with open(prompt_path, "r", encoding="utf-8") as file:
                self.system_prompt = file.read()
                return
        except OSError:
            self.system_prompt = (
                "你是 RAG 证据审阅 Agent。仅能从给定候选片段选择支持 JD 的简历证据，"
                "不得补充事实。只输出 selected_chunk_ids、relevance_summary、uncovered_requirements 的 JSON 对象。"
            )

    async def review(
        self,
        *,
        jd_text: str,
        jd_requirements: list[str],
        candidates: list[dict[str, Any]],
        user_id: str = "default",
    ) -> RagEvidenceReview:
        if not candidates:
            raise ValueError("RAG 证据审阅需要至少一个候选片段")
        self.reset_context(user_id=user_id, query="")
        candidate_payload = []
        for item in candidates:
            chunk_id = str(item.get("id") or item.get("chunkId") or "").strip()
            content = str(item.get("content") or "").strip()
            if not chunk_id or not content:
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            candidate_payload.append(
                {
                    "chunk_id": chunk_id,
                    "section": str(item.get("section") or item.get("sectionTitle") or "简历内容"),
                    "text": content[:900],
                    "source_block_ids": item.get("sourceBlockIds") or metadata.get("sourceBlockIds") or [],
                }
            )
        if not candidate_payload:
            raise ValueError("RAG 证据审阅没有有效候选片段")
        response = await self._call_llm(
            system_prompt=self.system_prompt,
            user_prompt=(
                f"[JD 原文]\n{jd_text[:6000]}\n\n"
                f"[结构化要求]\n{json.dumps(jd_requirements[:20], ensure_ascii=False)}\n\n"
                f"[RAG 候选片段]\n{json.dumps(candidate_payload, ensure_ascii=False)}"
            ),
            temperature=0.1,
        )
        result = parse_json_model(response, RagEvidenceReview, "RAG 证据审阅结果")
        allowed_ids = {item["chunk_id"] for item in candidate_payload}
        unknown = set(result.selected_chunk_ids) - allowed_ids
        if unknown:
            raise ValueError(f"RAG 证据审阅选择了未检索到的片段：{', '.join(sorted(unknown))}")
        return result
