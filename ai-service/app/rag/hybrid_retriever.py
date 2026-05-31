"""Hybrid Retrieval Engine combining BM25, Keyword matching, Section Boosts, and Semantic alignments."""

import math
import os
from typing import Any, Dict, List
import httpx
from app.rag.bm25_retriever import search_chunks_bm25
from app.verification.evidence_checker import extract_keywords


def char_bigram_similarity(s1: str, s2: str) -> float:
    """Compute character bigram Jaccard similarity to simulate semantic alignment."""
    def get_bigrams(s: str) -> set[str]:
        clean = "".join(c for c in s.lower() if c.isalnum() or c.isspace())
        return {clean[i:i+2] for i in range(len(clean)-1) if not clean[i:i+2].isspace()}
        
    b1 = get_bigrams(s1)
    b2 = get_bigrams(s2)
    if not b1 or not b2:
        return 0.0
    return len(b1 & b2) / len(b1 | b2)


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


def get_embedding(text: str, config: Dict[str, Any] | None = None) -> List[float]:
    """Retrieve embedding vector for query text using configured/passed credentials."""
    cfg = config or {}
    api_key = cfg.get("api_key")
    base_url = cfg.get("base_url")
    model_id = cfg.get("model_id")
    provider = cfg.get("provider")
    
    if not api_key:
        from app.core.config import Settings
        api_key = Settings.LLM_API_KEY.strip()
        base_url = Settings.LLM_BASE_URL.strip()
        model_id = os.getenv("EMBEDDING_MODEL", "doubao-embedding-large") or "doubao-embedding-large"
        provider = "doubao-multimodal"

    if not api_key or api_key in {"", "your_api_key_here", "your_deepseek_or_openai_api_key_here"}:
        return []

    base_url = base_url.rstrip("/")
    if provider == "doubao-multimodal" or "volces.com" in base_url:
        url = f"{base_url}/embeddings/multimodal"
        payload = {
            "model": model_id or "doubao-embedding-vision-250615",
            "input": [{"type": "text", "text": text}]
        }
    else:
        url = f"{base_url}/embeddings"
        payload = {
            "model": model_id or "text-embedding-3-small",
            "input": [text]
        }
        
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        with httpx.Client(timeout=15.0) as client:
            res = client.post(url, headers=headers, json=payload)
            if res.status_code == 200:
                data = res.json()
                if "data" in data:
                    d = data["data"]
                    if isinstance(d, dict):
                        return d.get("embedding") or []
                    elif isinstance(d, list) and len(d) > 0:
                        return d[0].get("embedding") or []
    except Exception as e:
        print(f"[HYBRID_RETRIEVER] Failed to fetch query embedding: {e}")
    return []


def retrieve_hybrid(
    chunks: List[Dict[str, Any]], 
    query: str, 
    top_k: int = 15,
    embedding_config: Dict[str, Any] | None = None
) -> List[Dict[str, Any]]:
    """
    Perform hybrid retrieval combining BM25, Keyword matching, Section Boosts, and Semantic alignments.
    Uses real cosine similarity if query and chunk embeddings are present, otherwise falls back to character bigram Jaccard.
    """
    if not chunks or not query.strip() or top_k <= 0:
        return []
        
    # Step 1: Run BM25 search
    bm25_results = search_chunks_bm25(chunks, query, len(chunks))
    bm25_scores = {c["chunkId"]: c["score"] for c in bm25_results}
    max_bm25 = max(bm25_scores.values()) if bm25_scores else 0.0
    
    # Extract query keywords
    query_keywords = extract_keywords(query)
    
    # Try fetching query embedding for real semantic search
    query_embedding = get_embedding(query, embedding_config)
    
    scored_results = []
    
    for chunk in chunks:
        chunk_id = chunk.get("chunkId", "")
        text = chunk.get("text", chunk.get("chunkText", ""))
        embedding_text = chunk.get("embeddingText", chunk.get("embedding_text", ""))
        if not embedding_text:
            from app.rag.embedding_formatter import format_embedding_text
            embedding_text = format_embedding_text(chunk)
            
        # 1. BM25 component (scaled to 0-1)
        raw_bm25 = bm25_scores.get(chunk_id, 0.0)
        bm25_norm = (raw_bm25 / max_bm25) if max_bm25 > 0.0 else 0.0
        
        # 2. Keyword component
        chunk_keywords_list = chunk.get("keywords", [])
        if isinstance(chunk_keywords_list, str):
            chunk_keywords_list = [k.strip() for k in chunk_keywords_list.split(",") if k.strip()]
        chunk_keywords = {k.lower() for k in chunk_keywords_list} if chunk_keywords_list else extract_keywords(text)
        
        if query_keywords:
            overlap = query_keywords & chunk_keywords
            keyword_score = len(overlap) / len(query_keywords)
        else:
            keyword_score = 0.0
            
        # 3. Section Importance (Section Boost)
        importance = float(chunk.get("importance", chunk.get("section_importance", 0.60)))
        
        # 4. Semantic Similarity component (real embedding similarity vs character Jaccard fallback)
        chunk_embedding = chunk.get("metadata", {}).get("embedding") or chunk.get("embedding")
        if query_embedding and chunk_embedding:
            semantic_score = cosine_similarity(query_embedding, chunk_embedding)
        else:
            semantic_score = char_bigram_similarity(query, embedding_text)
        
        # Combined Score
        final_score = (
            0.50 * bm25_norm +
            0.25 * keyword_score +
            0.15 * importance +
            0.10 * semantic_score
        )
        
        # Reasons
        reasons = []
        if raw_bm25 > 0.0:
            reasons.append("bm25_match")
        if keyword_score > 0.0:
            reasons.append("keyword_match")
        if importance >= 0.80:
            reasons.append("high_importance_section")
        if semantic_score > 0.15:
            reasons.append("semantic_match")
            
        if not reasons:
            reasons.append("generic_match")
            
        # Create output chunk dict
        scored_results.append({
            "documentId": chunk.get("documentId", chunk.get("document_id", "")),
            "chunkId": chunk_id,
            "text": text,
            "score": round(final_score, 4),
            "retrievalReasons": reasons,
            "sectionId": chunk.get("sectionId"),
            "sectionType": chunk.get("sectionType"),
            "sectionTitle": chunk.get("sectionTitle"),
            "hierarchy": chunk.get("hierarchy", []),
            "semanticType": chunk.get("semanticType"),
            "importance": importance,
            "keywords": list(chunk_keywords),
            "embeddingText": embedding_text,
            "metadata": chunk.get("metadata", {})
        })
        
    # Sort and rank
    scored_results.sort(key=lambda c: (-c["score"], c["documentId"], c["chunkId"]))
    return scored_results[:top_k]
