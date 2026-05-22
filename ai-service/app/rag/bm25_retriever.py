"""Okapi BM25 over in-memory document chunks."""

from __future__ import annotations

import math
from collections import Counter

from app.rag.tokenization import tokenize

K1 = 1.2
B = 0.75
EPS = 1e-9


def _bm25_idf(n_docs: int, df: int) -> float:
    return math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)


def _bm25_term_score(tf: int, len_d: int, avgdl: float, idf: float) -> float:
    if tf <= 0 or idf <= 0:
        return 0.0
    denom = tf + K1 * (1.0 - B + B * (len_d / avgdl))
    return idf * (tf * (K1 + 1.0)) / denom


def search_chunks_bm25(chunks: list[dict], query: str, top_k: int) -> list[dict]:
    """Rank chunks with BM25; ties break by documentId then chunkId."""
    q_tokens = tokenize(query.strip())
    if not q_tokens or top_k <= 0:
        return []

    rows = [
        (
            str(chunk.get("documentId", "")),
            str(chunk.get("chunkId", "")),
            str(chunk.get("text", "")),
            chunk,
        )
        for chunk in chunks
        if str(chunk.get("text", "")).strip()
    ]
    if not rows:
        return []

    doc_tokens = [tokenize(text) for _, _, text, _ in rows]
    doc_lengths = [len(tokens) for tokens in doc_tokens]
    avgdl = sum(doc_lengths) / len(doc_lengths) if doc_lengths else 1.0
    if avgdl < EPS:
        avgdl = 1.0

    document_frequency: dict[str, int] = {}
    for tokens in doc_tokens:
        for token in set(tokens):
            document_frequency[token] = document_frequency.get(token, 0) + 1

    idf = {t: _bm25_idf(len(rows), dfc) for t, dfc in document_frequency.items() if dfc > 0}
    q_freq = Counter(q_tokens)
    scores: list[tuple[float, str, str, str, dict]] = []

    for i, (doc_id, chunk_id, text, raw) in enumerate(rows):
        tf = Counter(doc_tokens[i])
        len_d = doc_lengths[i] or 1
        score = 0.0
        for qterm, q_weight in q_freq.items():
            idf_t = idf.get(qterm, 0.0)
            if idf_t <= 0.0:
                continue
            score += q_weight * _bm25_term_score(tf.get(qterm, 0), len_d, avgdl, idf_t)
        if score > 0.0:
            scores.append((score, doc_id, chunk_id, text, raw))

    scores.sort(key=lambda row: (-row[0], row[1], row[2]))
    return [
        {
            "documentId": doc_id,
            "chunkId": chunk_id,
            "text": text,
            "score": score,
            "metadata": raw.get("metadata", {}),
        }
        for score, doc_id, chunk_id, text, raw in scores[:top_k]
    ]

