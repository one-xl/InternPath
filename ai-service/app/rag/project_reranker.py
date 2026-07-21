"""Evidence-grounded project ranking with a deterministic fallback."""

from __future__ import annotations

import json
import re
from typing import Any

from app.core.llm_client import generate_evidence_answer


def rerank_projects(
    candidates: list[dict[str, Any]],
    *,
    jd_text: str,
    resume_text: str,
    llm_answer: dict[str, Any] | str | BaseException | None = None,
) -> dict[str, Any]:
    """Return ranked projects that never cite evidence outside the candidate set."""
    grouped = _group_project_candidates(candidates)
    fallback = _deterministic_ranking(grouped, jd_text, resume_text)
    if not grouped:
        return {
            "recommendations": [],
            "rerankMode": "fallback",
            "fallbackReason": "没有可用的项目知识库证据。",
        }

    try:
        raw_answer = llm_answer if llm_answer is not None else _ask_llm(grouped, jd_text, resume_text)
        if isinstance(raw_answer, BaseException):
            raise raw_answer
        recommendations = _ground_recommendations(_parse_llm_answer(raw_answer), grouped)
        if not recommendations:
            raise ValueError("LLM 重排没有返回可验证的项目证据引用")
        return {"recommendations": recommendations, "rerankMode": "llm", "fallbackReason": None}
    except Exception as exc:  # noqa: BLE001
        return {
            "recommendations": fallback,
            "rerankMode": "fallback",
            "fallbackReason": str(exc) or exc.__class__.__name__,
        }


def _group_project_candidates(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        source_type = str(candidate.get("sourceType") or metadata.get("sourceType") or "").lower()
        if source_type != "project":
            continue
        document_id = str(candidate.get("documentId") or "").strip()
        chunk_id = str(candidate.get("chunkId") or "").strip()
        text = str(candidate.get("text") or candidate.get("chunkText") or "").strip()
        if not document_id or not chunk_id or not text:
            continue
        project = grouped.setdefault(
            document_id,
            {
                "documentId": document_id,
                "title": str(metadata.get("documentTitle") or candidate.get("sectionTitle") or document_id),
                "chunks": [],
            },
        )
        try:
            score = float(candidate.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        project["chunks"].append({"chunkId": chunk_id, "text": text, "score": score})
    return grouped


def _deterministic_ranking(
    grouped: dict[str, dict[str, Any]],
    jd_text: str,
    resume_text: str,
) -> list[dict[str, Any]]:
    query_terms = _terms(f"{jd_text} {resume_text}")
    ranked: list[dict[str, Any]] = []
    for project in grouped.values():
        chunks = sorted(project["chunks"], key=lambda chunk: chunk["score"], reverse=True)[:3]
        evidence = [chunk["text"] for chunk in chunks]
        evidence_text = " ".join(evidence)
        overlap = len(query_terms & _terms(evidence_text))
        retrieval_score = max((chunk["score"] for chunk in chunks), default=0.0)
        score = round(max(0.0, min(100.0, retrieval_score * 100 + overlap * 2)), 1)
        summary = evidence[0][:360]
        matched_terms = sorted(query_terms & _terms(evidence_text))[:6]
        match_reason = (
            "匹配岗位与当前简历中的 " + "、".join(matched_terms)
            if matched_terms
            else "项目证据与岗位要求存在语义相关性"
        )
        ranked.append(
            {
                "documentId": project["documentId"],
                "chunkIds": [chunk["chunkId"] for chunk in chunks],
                "evidence": evidence,
                "summary": summary,
                "matchReason": match_reason,
                "resumeSuggestion": f"可在项目经历中补充这项已验证的事实：{summary}",
                "score": score,
            }
        )
    return sorted(ranked, key=lambda item: (-item["score"], item["documentId"]))[:5]


def _ask_llm(grouped: dict[str, dict[str, Any]], jd_text: str, resume_text: str) -> str:
    citations: list[dict[str, Any]] = []
    for project in grouped.values():
        for chunk_index, chunk in enumerate(project["chunks"], start=1):
            citations.append(
                {
                    "index": len(citations) + 1,
                    "original_filename": project["title"],
                    "chunk_index": chunk_index,
                    "text_preview": (
                        f"documentId={project['documentId']}; chunkId={chunk['chunkId']}; {chunk['text'][:500]}"
                    ),
                }
            )
    question = (
        "只基于项目证据，为 JD 和当前简历重排最合适项目。返回 JSON 对象："
        '{"recommendations":[{"documentId":"...","chunkIds":["..."],"summary":"...",'
        '"matchReason":"...","resumeSuggestion":"...","score":0}]}'
        "。不得引用未提供的 documentId、chunkId 或事实。\n"
        f"JD：{jd_text[:1600]}\n当前简历：{resume_text[:1200]}"
    )
    return generate_evidence_answer(question, citations)


def _parse_llm_answer(value: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise ValueError("LLM 重排返回了非 JSON 内容")
    match = re.search(r"\{.*\}", value, flags=re.DOTALL)
    if not match:
        raise ValueError("LLM 重排未返回 JSON 对象")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("LLM 重排 JSON 必须是对象")
    return parsed


def _ground_recommendations(
    result: dict[str, Any],
    grouped: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    grounded: list[dict[str, Any]] = []
    for item in result.get("recommendations") or []:
        if not isinstance(item, dict):
            continue
        document_id = str(item.get("documentId") or "")
        project = grouped.get(document_id)
        if not project:
            continue
        evidence_by_id = {chunk["chunkId"]: chunk["text"] for chunk in project["chunks"]}
        chunk_ids = [str(chunk_id) for chunk_id in item.get("chunkIds") or [] if str(chunk_id) in evidence_by_id]
        if not chunk_ids:
            continue
        evidence = [evidence_by_id[chunk_id] for chunk_id in chunk_ids]
        fallback = _deterministic_ranking({document_id: project}, "", "")[0]
        grounded.append(
            {
                "documentId": document_id,
                "chunkIds": chunk_ids,
                "evidence": evidence,
                "summary": _ground_text(item.get("summary"), evidence, fallback["summary"]),
                "matchReason": _ground_text(
                    item.get("matchReason"),
                    evidence,
                    fallback["matchReason"],
                    require_fact=False,
                ),
                "resumeSuggestion": _ground_text(item.get("resumeSuggestion"), evidence, fallback["resumeSuggestion"]),
                "score": _score(item.get("score"), fallback["score"]),
            }
        )
    return sorted(grounded, key=lambda item: (-item["score"], item["documentId"]))[:5]


def _ground_text(value: Any, evidence: list[str], fallback: str, *, require_fact: bool = True) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    if require_fact:
        evidence_text = " ".join(evidence)
        numbers = re.findall(r"\d+(?:\.\d+)?%?", text)
        if any(number not in evidence_text for number in numbers):
            return fallback
    return text[:500]


def _score(value: Any, fallback: float) -> float:
    try:
        return round(max(0.0, min(100.0, float(value))), 1)
    except (TypeError, ValueError):
        return fallback


def _terms(value: str) -> set[str]:
    return set(re.findall(r"[A-Za-z][A-Za-z0-9.+#-]{1,}|[\u4e00-\u9fff]{2,}", value.lower()))
