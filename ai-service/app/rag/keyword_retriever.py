"""Deterministic keyword search over in-memory document chunks."""

from __future__ import annotations

TEXT_PREVIEW_MAX_CHARS = 240


def _chunk_score(chunk_text: str, tokens: list[str]) -> int:
    haystack = chunk_text.lower()
    total = 0
    for tok in tokens:
        total += haystack.count(tok.lower())
    return total


def _safe_preview(text: str, max_chars: int = TEXT_PREVIEW_MAX_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def search_chunks(chunks: list[dict], query: str, top_k: int) -> list[dict]:
    """Rank chunks by case-insensitive substring hits."""
    q = query.strip()
    tokens = [t for t in q.split() if t]
    if not tokens or top_k <= 0:
        return []

    matches: list[tuple[int, str, str, str, dict]] = []
    for chunk in chunks:
        text = str(chunk.get("text", ""))
        score = _chunk_score(text, tokens)
        if score <= 0:
            continue
        matches.append(
            (
                score,
                str(chunk.get("documentId", "")),
                str(chunk.get("chunkId", "")),
                text,
                chunk,
            )
        )

    matches.sort(key=lambda row: (-row[0], row[1], row[2]))

    out: list[dict] = []
    for score, doc_id, chunk_id, text, raw in matches[:top_k]:
        out.append(
            {
                "documentId": doc_id,
                "chunkId": chunk_id,
                "text": text,
                "score": score,
                "metadata": raw.get("metadata", {}),
            }
        )
    return out

