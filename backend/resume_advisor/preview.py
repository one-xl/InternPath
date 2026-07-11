from __future__ import annotations

import base64
import copy
import io
import re
from typing import Any


def original_file_bytes(parsed_resume: dict[str, Any]) -> bytes:
    file_info = parsed_resume.get("file") if isinstance(parsed_resume.get("file"), dict) else {}
    encoded = str(file_info.get("b64_content") or "")
    if not encoded:
        raise LookupError("该简历版本没有保留原始文件字节。")
    try:
        return base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise LookupError("该简历版本的原始文件字节已损坏。") from exc


def _normalise_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def extract_pdf_text_locations(data: bytes) -> list[dict[str, Any]]:
    """Extract text fragments with page coordinates without introducing a new runtime engine."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return []

    locations: list[dict[str, Any]] = []
    try:
        reader = PdfReader(io.BytesIO(data))
        for page_number, page in enumerate(reader.pages, start=1):
            def visitor_text(text, _cm, tm, _font_dict, font_size) -> None:
                content = str(text or "").strip()
                if not content:
                    return
                x = float(tm[4] or 0)
                y = float(tm[5] or 0)
                size = max(float(font_size or 0), 1.0)
                locations.append(
                    {
                        "text": content,
                        "pageNumber": page_number,
                        "bbox": [x, max(0.0, y - size), x + max(size * len(content) * 0.55, size), y + size * 0.25],
                    }
                )

            page.extract_text(visitor_text=visitor_text)
    except Exception:
        return []
    return locations


def enrich_blocks_with_original_locations(
    blocks: list[dict[str, Any]],
    *,
    file_name: str,
    file_bytes: bytes,
) -> list[dict[str, Any]]:
    """Attach only verifiable original-file location data to parsed blocks."""
    source_format = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "txt"
    enriched = copy.deepcopy(blocks)
    if source_format != "pdf":
        return enriched

    locations = extract_pdf_text_locations(file_bytes)
    if not locations:
        return enriched

    for block in enriched:
        existing_locator = block.get("locator") if isinstance(block.get("locator"), dict) else {}
        # Structured PDF parsing already owns an exact source bbox.  Re-running a
        # fuzzy text match here can choose a different repeated sentence and make the
        # right-hand preview jump to the wrong page.
        if existing_locator.get("pageNumber") and isinstance(existing_locator.get("bbox"), list) and len(existing_locator["bbox"]) == 4:
            continue
        normalized_block = _normalise_text(str(block.get("text") or ""))
        if not normalized_block:
            continue
        matching = [
            location
            for location in locations
            if normalized_block in _normalise_text(location["text"])
            or _normalise_text(location["text"]) in normalized_block
        ]
        if not matching:
            continue
        best = min(matching, key=lambda location: abs(len(_normalise_text(location["text"])) - len(normalized_block)))
        locator = dict(existing_locator)
        locator.update({"sourceFormat": "pdf", "pageNumber": best["pageNumber"], "bbox": best["bbox"]})
        block["locator"] = locator
        block["locatorConfidence"] = "high"
    return enriched


def preview_metadata(parsed_resume: dict[str, Any]) -> dict[str, Any]:
    file_info = parsed_resume.get("file") if isinstance(parsed_resume.get("file"), dict) else {}
    name = str(file_info.get("name") or "resume")
    source_format = name.rsplit(".", 1)[-1].lower() if "." in name else "txt"
    has_original_file = bool(file_info.get("b64_content"))
    return {
        "sourceFormat": source_format,
        "hasOriginalFile": has_original_file,
        "inlinePreviewAvailable": has_original_file and source_format == "pdf",
        "locationNotice": (
            "PDF 位置来自原始页面文本坐标。"
            if source_format == "pdf"
            else "DOCX 暂以结构化文本近似定位；不会伪造页码或坐标。"
        ),
    }
