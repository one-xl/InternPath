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


    return keywords


def _evidence_text(citations: list[dict]) -> str:
    return "\n".join(
        str(item.get("text_preview", item.get("evidenceText", item.get("text", "")))) 
        for item in citations if isinstance(item, dict)
    )


def verify_claims_section_aware(claims: list[str], chunks: list[dict]) -> list[dict]:
    """
    Rigorously verify each claim against chunks considering section types.
    If a claim asserts experience but no matching chunk comes from an actual
    experience section (project_experience, work_experience, research, open_source),
    the claim is treated as UNSUPPORTED.
    """
    results = []
    
    # Pre-parse keywords for all chunks
    chunk_keywords_map = []
    for chunk in chunks:
        text = str(chunk.get("text", chunk.get("chunkText", "")))
        kw_list = chunk.get("keywords", [])
        if isinstance(kw_list, str):
            kw_list = [k.strip() for k in kw_list.split(",") if k.strip()]
        keywords = {k.lower() for k in kw_list} if kw_list else extract_keywords(text)
        chunk_keywords_map.append((chunk, keywords))

    for idx, claim_text in enumerate(claims, start=1):
        claim_keywords = extract_keywords(claim_text)
        if not claim_keywords:
            results.append({
                "claim": claim_text,
                "supported": None,
                "skipped": True,
                "keywords": [],
                "matched_keywords": [],
                "confidenceScore": 0.0,
                "status": "unsupported",
                "evidence": None
            })
            continue

        # Check if the claim implies experience / projects
        experience_words = {"经历", "项目", "实习", "负责", "研发", "实现", "主导", "开发", "experience", "internship", "project", "work"}
        claim_implies_experience = any(w in claim_text.lower() for w in experience_words)

        best_chunk = None
        best_ratio = 0.0
        best_overlap = set()
        
        for chunk, keywords in chunk_keywords_map:
            overlap = claim_keywords & keywords
            ratio = len(overlap) / len(claim_keywords) if claim_keywords else 0.0
            
            # Apply strict section-type constraint:
            # If claim implies experience, prioritize chunks from experience sections.
            # If a chunk is self_introduction, penalize it for experience claims.
            sec_type = str(chunk.get("sectionType", chunk.get("metadata", {}).get("sectionType", "generic_section")))
            is_experience_section = sec_type in ("project_experience", "work_experience", "open_source", "research")
            
            adjusted_ratio = ratio
            if claim_implies_experience and not is_experience_section:
                adjusted_ratio = ratio * 0.40  # severe penalty for non-experience sections
                
            if adjusted_ratio > best_ratio:
                best_ratio = adjusted_ratio
                best_chunk = chunk
                best_overlap = overlap
                
        # Non-penalized true ratio for scoring
        true_ratio = len(best_overlap) / len(claim_keywords) if best_chunk else 0.0
        
        # Rigorous support rules
        if best_chunk:
            sec_type = str(best_chunk.get("sectionType", best_chunk.get("metadata", {}).get("sectionType", "generic_section")))
            is_experience_section = sec_type in ("project_experience", "work_experience", "open_source", "research")
            
            # Strict enforcement: if experience is claimed but we only matched a non-experience chunk,
            # we force the status to "unsupported" (or "weak" if overlap is exceptionally high, but cap at weak).
            if claim_implies_experience and not is_experience_section:
                if true_ratio >= 0.70:
                    status = "weak"
                    supported = False
                else:
                    status = "unsupported"
                    supported = False
            else:
                if true_ratio >= 0.50:
                    status = "supported"
                    supported = True
                elif true_ratio >= 0.25:
                    status = "weak"
                    supported = False
                else:
                    status = "unsupported"
                    supported = False
        else:
            status = "unsupported"
            supported = False

        evidence_meta = None
        if best_chunk:
            meta = best_chunk.get("metadata", {})
            evidence_meta = {
                "sectionType": best_chunk.get("sectionType", meta.get("sectionType", "generic_section")),
                "sectionTitle": best_chunk.get("sectionTitle", meta.get("sectionTitle", "generic_section")),
                "hierarchy": best_chunk.get("hierarchy", meta.get("hierarchy", [])),
                "chunkId": best_chunk.get("chunkId", ""),
                "retrievalReasons": best_chunk.get("retrievalReasons", ["keyword_match"])
            }

        results.append({
            "claim": claim_text,
            "supported": supported,
            "skipped": False,
            "keywords": sorted(claim_keywords),
            "matched_keywords": sorted(best_overlap),
            "confidenceScore": round(true_ratio, 3),
            "status": status,
            "evidence": evidence_meta
        })
        
    return results


def check_answer_faithfulness(answer: str, citations: list[dict]) -> dict:
    """
    Estimate whether answer claims are supported by cited evidence.
    Enhanced to parse structured sections and hierarchy if present in citations.
    """
    claims = split_claims(answer)
    
    # Re-normalize citations into chunks for verify_claims_section_aware
    chunks = []
    for idx, item in enumerate(citations):
        if not isinstance(item, dict):
            continue
        chunks.append({
            "chunkId": item.get("chunkId", item.get("chunk_id", f"citation-{idx}")),
            "documentId": item.get("documentId", item.get("document_id", "doc")),
            "text": item.get("text_preview", item.get("evidenceText", item.get("text", ""))),
            "sectionType": item.get("sectionType", item.get("original_filename", "generic_section")),
            "sectionTitle": item.get("sectionTitle", item.get("title", "generic_section")),
            "hierarchy": item.get("hierarchy", []),
            "retrievalReasons": item.get("retrievalReasons", ["bm25_match"])
        })
        
    results = verify_claims_section_aware(claims, chunks)

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

