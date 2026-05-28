"""Text chunking helpers for document ingestion."""

import re

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")


def chunk_text(text: str, *, chunk_size: int, overlap: int = 0) -> list[str]:
    """
    将 `text` 切为连续片段；相邻片段在末尾与开头可重叠 `overlap` 个字符。

    空字符串返回 []. 每个片段长度至多为 `chunk_size`；最后一段可更短。

    参数
    ----
    chunk_size
        每段最大字符数，必须为正整数。
    overlap
        相邻窗口重叠的字符数，须满足 ``0 <= overlap < chunk_size``。
    """
    if not text:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    if _PARAGRAPH_SPLIT_RE.search(text):
        return _chunk_by_paragraphs(text, chunk_size=chunk_size, overlap=overlap)
    return _chunk_fixed_window(text, chunk_size=chunk_size, overlap=overlap)


def _chunk_fixed_window(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    step = chunk_size - overlap
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = start + chunk_size
        chunks.append(text[start:end])
        if end >= n:
            break
        start += step
    return chunks


def _chunk_by_paragraphs(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    paragraphs = [part.strip() for part in _PARAGRAPH_SPLIT_RE.split(text) if part.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_chunk_fixed_window(paragraph, chunk_size=chunk_size, overlap=overlap))
            continue

        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)
        current = paragraph

    if current:
        chunks.append(current)
    return chunks


def chunk_document_with_sections(
    content: str,
    *,
    document_id: str,
    file_name: str,
    source_type: str,
    chunk_size: int = 800,
    overlap: int = 120
) -> list[dict]:
    """
    Parse document into sections, then slice each section into boundary-respecting chunks.
    Automatically extracts keywords, maps semantic types, inherits parent section metadata,
    and pre-generates structured embedding text.
    """
    from app.rag.section_parser import parse_sections
    from app.rag.embedding_formatter import format_embedding_text
    from app.verification.evidence_checker import extract_keywords

    sections = parse_sections(content, source_type=source_type)
    all_chunks = []
    chunk_idx = 0

    for section in sections:
        sec_content = section["content"]
        sec_id = section["sectionId"]
        sec_type = section["sectionType"]
        sec_title = section["title"]
        importance = section["importance"]
        hierarchy = section["hierarchy"]
        
        # Map semantic type
        if sec_type in ("project_experience", "work_experience", "open_source", "research"):
            semantic_type = "experience"
        elif sec_type in ("skills", "tech_stack"):
            semantic_type = "skills"
        elif sec_type in ("education", "education_requirement"):
            semantic_type = "education"
        else:
            semantic_type = "general"
            
        # Chunk within section content (preserves boundaries)
        sub_chunks = chunk_text(sec_content, chunk_size=chunk_size, overlap=overlap)
        
        for idx, sub_text in enumerate(sub_chunks):
            # Extract conservative keywords for this chunk
            chunk_keywords = extract_keywords(sub_text)
            
            chunk_data = {
                "chunkId": f"{document_id}#chunk-{chunk_idx}",
                "documentId": document_id,
                "sectionId": sec_id,
                "sectionType": sec_type,
                "sectionTitle": sec_title,
                "hierarchy": hierarchy,
                "semanticType": semantic_type,
                "importance": importance,
                "keywords": list(chunk_keywords),
                "chunkIndex": chunk_idx,
                "chunkText": sub_text,
                "sourceType": source_type,
                "fileName": file_name,
                "metadata": {
                    "sourceType": source_type,
                    "fileName": file_name,
                    "chunkIndex": chunk_idx,
                    "sectionType": sec_type,
                    "sectionTitle": sec_title,
                    "hierarchy": hierarchy,
                    "semanticType": semantic_type,
                    "importance": importance,
                    "keywords": list(chunk_keywords)
                }
            }
            
            # Formulate structured embedding text
            chunk_data["embeddingText"] = format_embedding_text(chunk_data)
            all_chunks.append(chunk_data)
            chunk_idx += 1
            
    # Fallback in case of empty document
    if not all_chunks:
        all_chunks.append({
            "chunkId": f"{document_id}#chunk-0",
            "documentId": document_id,
            "sectionId": f"sec-{source_type}-pre",
            "sectionType": "generic_section",
            "sectionTitle": "Document Content",
            "hierarchy": ["Document Content"],
            "semanticType": "general",
            "importance": 0.60,
            "keywords": [],
            "chunkIndex": 0,
            "chunkText": content,
            "sourceType": source_type,
            "fileName": file_name,
            "embeddingText": content,
            "metadata": {
                "sourceType": source_type,
                "fileName": file_name,
                "chunkIndex": 0
            }
        })
        
    return all_chunks

