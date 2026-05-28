"""Hybrid Retrieval Engine combining BM25, Keyword matching, Section Boosts, and Semantic alignments."""

from typing import Any, Dict, List
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


def retrieve_hybrid(chunks: List[Dict[str, Any]], query: str, top_k: int = 15) -> List[Dict[str, Any]]:
    """
    Perform hybrid retrieval:
    1. Score all chunks with BM25
    2. Score with keyword overlap
    3. Score with section importance (Section Boost)
    4. Score with semantic similarity (Character bigram Jaccard)
    5. Combine using custom weights
    """
    if not chunks or not query.strip() or top_k <= 0:
        return []
        
    # Step 1: Run BM25 search
    bm25_results = search_chunks_bm25(chunks, query, len(chunks))
    bm25_scores = {c["chunkId"]: c["score"] for c in bm25_results}
    max_bm25 = max(bm25_scores.values()) if bm25_scores else 0.0
    
    # Extract query keywords
    query_keywords = extract_keywords(query)
    
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
        
        # 4. Semantic Similarity component
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
