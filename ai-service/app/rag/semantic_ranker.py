"""Semantic Ranker to rerank top-K hybrid retrieved chunks."""

import re
from typing import Any, Dict, List
from app.verification.evidence_checker import extract_keywords
from app.rag.hybrid_retriever import char_bigram_similarity


def detect_query_semantic_type(query: str) -> str:
    """Classify the query's implied semantic type based on keyword indicators."""
    query_clean = query.strip().lower()
    
    if any(w in query_clean for w in ("经历", "工作", "项目", "实习", "年限", "经验", "experience", "internship", "project", "work", "responsibilit")):
        return "experience"
    if any(w in query_clean for w in ("技能", "语言", "框架", "库", "开发", "熟悉", "熟练", "精通", "skills", "tech stack", "languages", "proficien")):
        return "skills"
    if any(w in query_clean for w in ("学历", "学校", "大学", "硕士", "博士", "本科", "学士", "专业", "教育", "education", "academic", "university", "degree")):
        return "education"
        
    return "general"


def rerank_chunks(chunks: List[Dict[str, Any]], query: str, top_k: int = 8) -> List[Dict[str, Any]]:
    """
    Rerank a set of candidate chunks based on multi-factor semantic alignment:
    - Base retrieval score
    - Heuristic semantic type matching
    - Hierarchy relevance
    - Keyword overlap
    - Section importance
    - Deep character similarity
    """
    if not chunks or not query.strip() or top_k <= 0:
        return []
        
    query_keywords = extract_keywords(query)
    query_semantic_type = detect_query_semantic_type(query)
    
    reranked = []
    
    for chunk in chunks:
        base_score = float(chunk.get("score", 0.50))
        importance = float(chunk.get("importance", 0.60))
        
        # 1. Semantic Type match boost
        chunk_semantic_type = str(chunk.get("semanticType", chunk.get("semantic_type", "general"))).lower()
        semantic_boost = 0.20 if chunk_semantic_type == query_semantic_type else 0.0
        
        # 2. Hierarchy match boost
        hierarchy = chunk.get("hierarchy", [])
        hierarchy_boost = 0.0
        if hierarchy and query_keywords:
            hierarchy_str = " ".join(hierarchy).lower()
            matched_hierarchy = sum(1 for kw in query_keywords if kw.lower() in hierarchy_str)
            hierarchy_boost = min(0.15, matched_hierarchy * 0.05)
            
        # 3. Content character Jaccard similarity
        text = chunk.get("text", chunk.get("chunkText", ""))
        content_sim = char_bigram_similarity(query, text)
        
        # Calculate final rerank score
        rerank_score = (
            0.40 * base_score +
            0.20 * content_sim +
            0.15 * semantic_boost +
            0.15 * hierarchy_boost +
            0.10 * importance
        )
        
        # Make a copy of the chunk with updated score and rank details
        chunk_copy = dict(chunk)
        chunk_copy["score"] = round(rerank_score, 4)
        
        # Append ranked reasons if not already present
        reasons = list(chunk.get("retrievalReasons", []))
        if semantic_boost > 0.0 and "semantic_type_match" not in reasons:
            reasons.append("semantic_type_match")
        if hierarchy_boost > 0.0 and "hierarchy_match" not in reasons:
            reasons.append("hierarchy_match")
        chunk_copy["retrievalReasons"] = reasons
        
        reranked.append(chunk_copy)
        
    # Sort and rank
    reranked.sort(key=lambda c: (-c["score"], c["documentId"], c["chunkId"]))
    return reranked[:top_k]
