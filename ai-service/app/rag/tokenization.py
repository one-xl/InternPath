"""Shared tokenization helpers for retrieval and lightweight metrics."""

from __future__ import annotations

import re

TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    """Conservative tokenization: ASCII words plus CJK bigrams."""
    if not text:
        return []
    out: list[str] = []
    for match in TOKEN_PATTERN.finditer(text):
        token = match.group(0)
        if token.isascii():
            out.append(token.lower())
        elif len(token) >= 2:
            out.extend(token[i : i + 2] for i in range(len(token) - 1))
    return out
