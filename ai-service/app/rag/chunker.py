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
