"""Lightweight evidence support checks for generated answers."""

from __future__ import annotations

import re

_ASCII_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")
CONTENT_STOPWORDS = {
    "the",
    "a",
    "an",
    "as",
    "at",
    "be",
    "by",
    "can",
    "does",
    "is",
    "are",
    "of",
    "to",
    "and",
    "or",
    "from",
    "in",
    "on",
    "for",
    "with",
    "it",
    "this",
    "that",
    "what",
    "how",
    "has",
    "have",
    "candidate",
    "experience",
    "paper",
    "model",
    "system",
    "question",
    "dataset",
    "method",
    "based",
    "using",
    "according",
    "uploaded",
    "set",
    "step",
    "是",
    "的",
    "了",
    "和",
    "与",
    "及",
    "在",
    "中",
    "为",
    "对",
    "由",
    "可以",
    "一个",
    "使用",
    "基于",
    "根据",
    "问题",
    "论文",
    "模型",
    "系统",
    "数据",
    "方法",
    "好的",
    "以下",
    "下面",
    "结论",
}


def split_claims(answer: str) -> list[str]:
    """Split an answer into short factual-looking claims."""
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(answer) if part.strip()]


def extract_keywords(text: str) -> set[str]:
    """Extract conservative English words and CJK bigrams for support matching."""
    keywords: set[str] = set()
    for token in _ASCII_TOKEN_RE.findall(text.lower()):
        if len(token) >= 2 and token not in CONTENT_STOPWORDS:
            keywords.add(token)
    for match in _CJK_RUN_RE.finditer(text):
        run = match.group(0)
        if len(run) < 2:
            continue
        for i in range(len(run) - 1):
            token = run[i : i + 2]
            if token not in CONTENT_STOPWORDS:
                keywords.add(token)
    return keywords


def _evidence_text(citations: list[dict]) -> str:
    return "\n".join(
        str(item.get("text_preview", "")) for item in citations if isinstance(item, dict)
    )


def check_answer_faithfulness(answer: str, citations: list[dict]) -> dict:
    """
    Estimate whether answer claims are supported by cited evidence.

    This is a deterministic proxy metric, not a semantic entailment model. A claim is
    supported when at least half of its extracted keywords appear in citation previews.
    """
    claims = split_claims(answer)
    evidence_keywords = extract_keywords(_evidence_text(citations))
    results: list[dict] = []

    for claim in claims:
        claim_keywords = extract_keywords(claim)
        if not claim_keywords:
            overlap: list[str] = []
            supported: bool | None = None
            skipped = True
        else:
            overlap_set = claim_keywords & evidence_keywords
            supported = len(overlap_set) / len(claim_keywords) >= 0.5
            overlap = sorted(overlap_set)
            skipped = False
        results.append(
            {
                "claim": claim,
                "supported": supported,
                "skipped": skipped,
                "keywords": sorted(claim_keywords),
                "matched_keywords": overlap,
            }
        )

    supported_count = sum(1 for item in results if item["supported"] is True)
    skipped_count = sum(1 for item in results if item["skipped"])
    total = len(results) - skipped_count
    support_rate = supported_count / total if total else 0.0
    unsupported_claim_rate = 1.0 - support_rate if total else 0.0
    return {
        "claim_count": total,
        "raw_claim_count": len(results),
        "skipped_claim_count": skipped_count,
        "supported_claim_count": supported_count,
        "support_rate": support_rate,
        "unsupported_claim_rate": unsupported_claim_rate,
        "hallucination_proxy_rate": unsupported_claim_rate,
        "hallucination_rate": unsupported_claim_rate,
        "claims": results,
    }
