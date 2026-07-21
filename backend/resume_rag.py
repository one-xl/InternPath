from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from document_parser import (
    DocumentParseError,
    extract_docx_structure,
    extract_pdf_structure,
    extract_text_from_txt_bytes,
)


SUPPORTED_TYPES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
}
SUPPORTED_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".md"}
MAX_FILE_SIZE = 10 * 1024 * 1024
STRUCTURED_RESUME_PARSER_VERSION = "v5"
SKILL_KEYWORDS = [
    "React",
    "TypeScript",
    "JavaScript",
    "Node.js",
    "Python",
    "Java",
    "SQL",
    "AWS",
    "Docker",
    "Kubernetes",
    "前端",
    "后端",
    "全栈",
    "算法",
    "系统设计",
    "RAG",
]
SECTION_ALIASES = {
    "基本信息": [
        "基本信息",
        "个人信息",
        "个人资料",
        "联系方式",
        "联系信息",
        "Contact",
        "Contact Information",
        "Personal Info",
        "Personal Details",
    ],
    "教育经历": [
        "教育经历",
        "教育背景",
        "教育经验",
        "学习经历",
        "学历背景",
        "教育及培训",
        "教育与培训",
        "教育/培训",
        "Education",
        "Academic Background",
    ],
    "核心课程": [
        "核心课程",
        "相关课程",
        "主修课程",
        "专业课程",
        "课程列表",
        "Relevant Coursework",
        "Coursework",
    ],
    "技能": [
        "技能",
        "专业技能",
        "个人技能",
        "技能栈",
        "技术栈",
        "技术能力",
        "技能证书",
        "技能特长",
        "语言能力",
        "外语能力",
        "英语能力",
        "核心技能",
        "职业技能",
        "专业能力",
        "技能与工具",
        "工具技能",
        "Skills",
        "Technical Skills",
        "Core Skills",
        "Language Skills",
    ],
    "项目经历": [
        "项目经历",
        "项目经验",
        "项目实践",
        "研发项目",
        "个人项目",
        "项目及实践",
        "项目与实践",
        "项目/实践",
        "实践项目",
        "Projects",
        "Project Experience",
        "Personal Projects",
    ],
    "实习 / 工作经历": [
        "实习经历",
        "工作经历",
        "工作经验",
        "实习经验",
        "职业经历",
        "相关经历",
        "实践经历",
        "实践经验",
        "社会实践",
        "校园经历",
        "校内经历",
        "学生工作",
        "社团经历",
        "活动经历",
        "志愿经历",
        "志愿者经历",
        "实训经历",
        "专业实践",
        "Experience",
        "Work Experience",
        "Professional Experience",
        "Employment",
        "Internship",
        "Internship Experience",
        "Campus Experience",
        "Leadership Experience",
        "Volunteer Experience",
        "Extracurricular Experience",
    ],
    "获奖 / 证书": [
        "获奖",
        "获奖经历",
        "获奖证书",
        "荣誉奖项",
        "荣誉奖励",
        "荣誉",
        "证书",
        "资格证书",
        "竞赛经历",
        "竞赛获奖",
        "比赛经历",
        "比赛获奖",
        "Awards",
        "Honors",
        "Certifications",
        "Certificates",
    ],
    "科研经历": [
        "科研经历",
        "科研项目",
        "研究经历",
        "研究项目",
        "论文发表",
        "学术成果",
        "Research",
        "Research Experience",
        "Publications",
    ],
    "自我评价": [
        "自我评价",
        "自我介绍",
        "个人总结",
        "个人简介",
        "个人优势",
        "个人陈述",
        "Summary",
        "Profile",
        "About Me",
    ],
    "求职意向": [
        "求职意向",
        "职业目标",
        "意向岗位",
        "目标岗位",
        "Objective",
        "Career Objective",
    ],
}

SECTION_TYPES = {
    "基本信息": "contact",
    "教育经历": "education",
    "核心课程": "coursework",
    "技能": "skills",
    "项目经历": "project_experience",
    "实习 / 工作经历": "work_experience",
    "获奖 / 证书": "awards",
    "科研经历": "research",
    "自我评价": "self_introduction",
    "求职意向": "objective",
    "其他": "generic_section",
    "简历内容": "generic_section",
}

# Kept deliberately narrow: this is a common source-document typo observed in
# floating-textbox resumes, not a fuzzy heading classifier.
_EXACT_HEADING_CORRECTIONS = {
    "自我评价家": "自我评价",
}

SECTION_IMPORTANCE = {
    "contact": 0.60,
    "education": 0.80,
    "coursework": 0.86,
    "skills": 0.85,
    "project_experience": 0.95,
    "work_experience": 0.90,
    "awards": 0.70,
    "research": 0.85,
    "self_introduction": 0.50,
    "objective": 0.0,
    "generic_section": 0.60,
}

_INLINE_HEADING_SEPARATORS = set(" \t:：|｜-—–/、)")
_HEADING_DECORATION_RE = re.compile(r"^[#>\-\s*•·●○◆◇■□▶▷\d.、()（）\[\]【】]+|[\s:：|｜\-—–/、()（）\[\]【】]+$")
_LEADING_HEADING_DECORATION_RE = re.compile(r"^[#>\-\s*•·●○◆◇■□▶▷\d.、()（）\[\]【】]+")
_NORMALIZED_HEADING_SEPARATORS = set(" \t:：|｜-—–_/、()（）[]【】")
_FALSE_INLINE_HEADING_TAIL_RE = re.compile(r"^\s*(包括|包含|有|是|为|主要|相关|如下|体现|来自|来自于)")
_EMBEDDED_HEADING_BOUNDARY_CHARS = set(" \t;；。.!！?？|｜/、,，")
_GENERIC_SECTION_VALUES = {
    "",
    "其他",
    "简历内容",
    "generic",
    "generic_section",
    "general",
    "other",
    "document content",
    "general info",
    "introduction",
    "未命名 section",
}


def validate_resume_upload(file_name: str, content_type: str, data: bytes) -> None:
    suffix = Path(file_name).suffix.lower()
    if not data:
        raise DocumentParseError("文件为空，请重新选择")
    if len(data) > MAX_FILE_SIZE:
        raise DocumentParseError("文件大小不能超过 10MB")
    mime_allowed = content_type in SUPPORTED_TYPES
    extension_allowed = suffix in SUPPORTED_EXTENSIONS
    if not mime_allowed and not extension_allowed:
        raise DocumentParseError("仅支持 PDF、DOC、DOCX、TXT 格式")


def _extract_txt_structure(data: bytes) -> list[dict[str, Any]]:
    text = extract_text_from_txt_bytes(data)
    return [
        {
            "kind": "paragraph",
            "text": line,
            "locator": {"paragraphIndex": index},
        }
        for index, raw_line in enumerate(text.splitlines())
        if (line := raw_line.strip())
    ]


def parse_resume(file_name: str, content_type: str, data: bytes) -> dict[str, Any]:
    validate_resume_upload(file_name, content_type, data)
    suffix = Path(file_name).suffix.lower()
    if suffix == ".pdf":
        source_records = extract_pdf_structure(data)
    elif suffix == ".docx":
        source_records = extract_docx_structure(data)
    elif suffix in {".txt", ".md"}:
        source_records = _extract_txt_structure(data)
    elif suffix == ".doc":
        raise DocumentParseError("DOC 格式无法可靠解析，请转换为 DOCX 或 PDF 后上传")
    else:
        raise DocumentParseError("仅支持 PDF、DOC、DOCX、TXT 格式")

    extracted_record_count = len(source_records)
    source_records = normalize_resume_source_records(source_records)
    raw_text = "\n".join(str(record.get("text") or "") for record in source_records).strip()
    cleaned_text = clean_resume_text(raw_text)
    file_id = uuid4().hex
    content_hash = hashlib.sha256(data).hexdigest()
    import base64
    b64_content = base64.b64encode(data).decode("utf-8")
    resume_file = {
        "id": file_id,
        "name": file_name,
        "size": len(data),
        "type": content_type,
        "uploadedAt": datetime.now().isoformat(),
        "status": "parsed",
        "contentHash": content_hash,
        "b64_content": b64_content,
    }
    structured_markdown = build_structured_markdown(source_records)
    blocks = build_resume_blocks_from_source_records(
        source_records,
        file_id,
        file_name,
        content_hash=content_hash,
    )
    chunks = chunk_resume_blocks(
        blocks,
        file_id,
        file_name,
        content_hash=content_hash,
    )
    # PDF block locations are produced by the structured parser.  The retired
    # ResumeAdvisor preview enrichment is deliberately not part of the new
    # optimization workflow.
    cleaning_report = build_resume_cleaning_report(
        source_records=source_records,
        blocks=blocks,
        content_hash=content_hash,
        parser_version=STRUCTURED_RESUME_PARSER_VERSION,
        source_format=suffix.lstrip("."),
        extracted_record_count=extracted_record_count,
        cleaned_text=cleaned_text,
        warnings=_parse_warnings_for_source_records(source_records),
    )
    return {
        "structureVersion": "resume-structure-v2",
        "parser": {
            "name": "structured-resume-parser",
            "version": STRUCTURED_RESUME_PARSER_VERSION,
            "sourceFormat": suffix.lstrip("."),
            "warnings": _parse_warnings_for_source_records(source_records),
        },
        "file": resume_file,
        "contentHash": content_hash,
        "rawText": raw_text,
        "cleanedText": cleaned_text,
        "structuredMarkdown": structured_markdown,
        "markdownMirror": {
            "version": "resume-markdown-v1",
            "content": structured_markdown,
            "contentHash": hashlib.sha256(structured_markdown.encode("utf-8")).hexdigest(),
        },
        "sourceBlocks": source_records,
        "chunks": chunks,
        "blocks": blocks,
        "cleaningReport": cleaning_report,
        "extractedProfile": extract_profile(cleaned_text),
    }


def build_resume_cleaning_report(
    *,
    source_records: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    content_hash: str,
    parser_version: str,
    source_format: str,
    extracted_record_count: int,
    cleaned_text: str,
    warnings: list[str],
) -> dict[str, Any]:
    """Return a compact, PII-free summary of the upload-time canonicalisation."""
    section_ids = {
        str(block.get("sectionId") or "generic_section")
        for block in blocks
        if isinstance(block, dict)
    }
    duplicate_source_count = sum(
        len(record.get("duplicateSourceIds") or [])
        for record in source_records
        if isinstance(record, dict)
    )
    editable_block_count = sum(
        1
        for block in blocks
        if isinstance(block, dict)
        and str(block.get("kind") or "") in {"bullet", "paragraph", "table_cell"}
        and bool(str(block.get("text") or "").strip())
    )
    low_confidence_location_count = sum(
        1
        for block in blocks
        if isinstance(block, dict) and block.get("locatorConfidence") == "approximate"
    )
    return {
        "schemaVersion": "resume-cleaning-v1",
        "contentHash": content_hash,
        "parserVersion": parser_version,
        "sourceFormat": source_format,
        "extractedRecordCount": max(0, extracted_record_count),
        "canonicalRecordCount": len(source_records),
        "duplicateSourceCount": duplicate_source_count,
        "blockCount": len(blocks),
        "editableBlockCount": editable_block_count,
        "sectionCount": len(section_ids),
        "lowConfidenceLocationCount": low_confidence_location_count,
        "cleanedCharacterCount": len(cleaned_text),
        "warnings": list(dict.fromkeys(str(item) for item in warnings if str(item).strip())),
    }


def _section_aliases_by_length() -> list[tuple[str, str]]:
    aliases = [
        (section, alias.strip())
        for section, values in SECTION_ALIASES.items()
        for alias in values
        if alias and alias.strip()
    ]
    aliases.sort(key=lambda item: len(_normalized_heading_key(item[1])), reverse=True)
    return aliases


def _consume_alias_prefix(value: str, alias: str) -> int | None:
    """Return consumed length if value starts with alias, allowing heading spacing."""
    i = 0
    j = 0
    while i < len(value) and j < len(alias):
        current = value[i]
        expected = alias[j]
        if current in _NORMALIZED_HEADING_SEPARATORS:
            i += 1
            continue
        if expected in _NORMALIZED_HEADING_SEPARATORS:
            j += 1
            continue
        if current.lower() != expected.lower():
            return None
        i += 1
        j += 1

    while j < len(alias) and alias[j] in _NORMALIZED_HEADING_SEPARATORS:
        j += 1
    if j != len(alias):
        return None
    return i


def _match_heading_prefix(line: str) -> tuple[str, int] | None:
    stripped = line.strip()
    if not stripped:
        return None

    leading_match = _LEADING_HEADING_DECORATION_RE.match(stripped)
    leading_offset = leading_match.end() if leading_match else 0
    candidate = stripped[leading_offset:].lstrip()
    leading_offset += len(stripped[leading_offset:]) - len(candidate)
    if not candidate:
        return None

    normalized_candidate = _normalized_heading_key(candidate)
    corrected_section = _EXACT_HEADING_CORRECTIONS.get(normalized_candidate)
    if corrected_section:
        return corrected_section, len(stripped)
    for section, alias in _section_aliases_by_length():
        alias_key = _normalized_heading_key(alias)
        if normalized_candidate == alias_key:
            return section, len(stripped)

        consumed = _consume_alias_prefix(candidate, alias)
        if consumed is None:
            continue

        tail = candidate[consumed:]
        if not tail:
            return section, leading_offset + consumed
        if tail[0] in _INLINE_HEADING_SEPARATORS and not _FALSE_INLINE_HEADING_TAIL_RE.match(tail):
            return section, leading_offset + consumed
    return None


def _can_start_embedded_heading(line: str, index: int) -> bool:
    if index <= 0:
        return True
    previous = line[index - 1]
    return previous.isspace() or previous in _EMBEDDED_HEADING_BOUNDARY_CHARS


def _split_line_at_inline_headings(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped:
        return []

    starts: list[int] = []
    for idx, char in enumerate(stripped):
        if idx > 0 and not _can_start_embedded_heading(stripped, idx):
            continue
        if not char.isalnum() and not ("\u4e00" <= char <= "\u9fff") and char not in "#>*•·●○◆◇■□▶▷0123456789":
            continue
        if _match_heading_prefix(stripped[idx:]):
            starts.append(idx)

    if not starts or starts == [0]:
        return [stripped]

    parts: list[str] = []
    previous = 0
    for start in starts:
        if start > previous:
            part = stripped[previous:start].strip()
            if part:
                parts.append(part)
        previous = start
    tail = stripped[previous:].strip()
    if tail:
        parts.append(tail)
    return parts or [stripped]


def _section_candidate_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.split("\n"):
        stripped = raw_line.strip()
        if not stripped:
            lines.append("")
            continue
        lines.extend(_split_line_at_inline_headings(stripped))
    return lines


def clean_resume_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    lines = _section_candidate_lines(normalized)

    merged_lines: list[str] = []
    buffer = ""
    for line in lines:
        if not line:
            if buffer:
                merged_lines.append(buffer)
                buffer = ""
            if merged_lines and merged_lines[-1] != "":
                merged_lines.append("")
            continue

        if section_for_line(line):
            if buffer:
                merged_lines.append(buffer)
                buffer = ""
            merged_lines.append(line)
            continue

        if not buffer:
            buffer = line
            continue

        if _should_preserve_line_break(buffer, line):
            merged_lines.append(buffer)
            buffer = line
        else:
            buffer = f"{buffer} {line}"

    if buffer:
        merged_lines.append(buffer)

    cleaned = "\n".join(merged_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _should_preserve_line_break(previous: str, current: str) -> bool:
    if section_for_line(current):
        return True
    if re.match(r"^([-•·*]|\d+[.、)])\s*", current):
        return True
    if re.match(r"^([-•·*]|\d+[.、)])\s*", previous):
        return True
    if previous.endswith(("。", "；", ";", ":", "：", "！", "？", ".", "!", "?")):
        return True
    return False


def _compact_heading(line: str) -> str:
    compact = re.sub(r"\s+", " ", line.strip())
    compact = _HEADING_DECORATION_RE.sub("", compact).strip()
    return compact


def _normalized_heading_key(value: str) -> str:
    return re.sub(r"[\s:：|｜\-—–_/、()（）\[\]【】]+", "", value).lower()


def section_for_line(line: str) -> str | None:
    compact = _compact_heading(line)
    if not compact:
        return None
    match = _match_heading_prefix(compact)
    return match[0] if match else None


def section_type_for_label(section: str) -> str:
    return SECTION_TYPES.get(section, "generic_section")


def semantic_type_for_section_type(section_type: str) -> str:
    if section_type in {"project_experience", "work_experience", "research"}:
        return "experience"
    if section_type == "skills":
        return "skills"
    if section_type in {"education", "coursework"}:
        return "education"
    return "general"


def _source_record_id(record: dict[str, Any], fallback_index: int) -> str:
    locator = record.get("locator") if isinstance(record.get("locator"), dict) else {}
    source_id = str(record.get("sourceId") or locator.get("sourceId") or "").strip()
    return source_id or f"source:{fallback_index}"


def _normalized_record_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _record_markdown(record: dict[str, Any]) -> str:
    text = str(record.get("text") or "").strip()
    kind = str(record.get("kind") or "paragraph")
    if kind == "heading":
        # Resume section names are deliberately rendered at one predictable depth.  It
        # keeps a Markdown mirror compact even when Word styles are inconsistent.
        return f"## {text}"
    if kind == "bullet":
        content = re.sub(r"^\s*(?:[-•·*]|\d+[.、)])\s*", "", text).strip()
        return f"- {content}" if content else "-"
    if kind == "table_cell":
        cells = [cell.strip() for cell in text.split("|")]
        cells = [cell for cell in cells if cell]
        return f"| {' | '.join(cells)} |" if cells else ""
    return text


def _inline_heading_fragments(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Split ``专业技能：Python`` without treating the value as a heading.

    Flattened PDFs often put a section title and its first value on one visual line.
    Splitting before section classification prevents the whole line from becoming a
    non-editable heading and fixes the historical "全部是其他" failure mode.
    """
    text = str(record.get("text") or "").strip()
    kind = str(record.get("kind") or "paragraph")
    if not text or kind == "table_cell":
        return [record]
    match = _match_heading_prefix(text)
    if not match:
        return [record]
    _section, consumed = match
    if consumed >= len(text):
        return [{**record, "kind": "heading"}]
    heading_text = _compact_heading(text[:consumed])
    tail = text[consumed:].lstrip(" \t:：-—–|｜")
    if not heading_text or not tail:
        return [{**record, "kind": "heading"}]

    base_source_id = str(record.get("sourceId") or "")
    base_locator = record.get("locator") if isinstance(record.get("locator"), dict) else {}
    heading_source_id = f"{base_source_id}:heading" if base_source_id else ""
    content_source_id = f"{base_source_id}:content" if base_source_id else ""
    return [
        {
            **record,
            "sourceId": heading_source_id or record.get("sourceId"),
            "sourceIds": [heading_source_id or record.get("sourceId")],
            "sourceRecordId": base_source_id,
            "kind": "heading",
            "text": heading_text,
            "locator": {**base_locator, "sourceId": heading_source_id or base_locator.get("sourceId"), "fragment": "heading"},
        },
        {
            **record,
            "sourceId": content_source_id or record.get("sourceId"),
            "sourceIds": [content_source_id or record.get("sourceId")],
            "sourceRecordId": base_source_id,
            "kind": "bullet" if kind == "bullet" else "paragraph",
            "text": tail,
            "locator": {**base_locator, "sourceId": content_source_id or base_locator.get("sourceId"), "fragment": "content"},
        },
    ]


def normalize_resume_source_records(source_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize source records once, then reuse them for blocks, Markdown and RAG.

    Exact duplicate fragments can be emitted by PDF page chrome, DOCX merged cells, or
    old extraction engines.  We retain all source ids on the first canonical record but
    never create a second display block or RAG evidence item for the same text.
    """
    canonical: list[dict[str, Any]] = []
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    current_section = "其他"
    for input_index, source_record in enumerate(source_records):
        if not isinstance(source_record, dict):
            continue
        for record in _inline_heading_fragments(source_record):
            text = re.sub(r"\s+", " ", str(record.get("text") or "")).strip()
            if not text:
                continue
            source_id = _source_record_id(record, input_index)
            locator = dict(record.get("locator") or {})
            locator.setdefault("sourceId", source_id)
            kind = str(record.get("kind") or "paragraph")
            detected_section = section_for_line(text)
            if kind == "heading" and detected_section:
                current_section = detected_section
            elif detected_section and kind not in {"bullet", "table_cell"}:
                kind = "heading"
                current_section = detected_section

            source_ids = [str(value) for value in (record.get("sourceIds") or [source_id]) if str(value)]
            if source_id not in source_ids:
                source_ids.insert(0, source_id)
            normalized = {
                **record,
                "sourceId": source_id,
                "sourceIds": list(dict.fromkeys(source_ids)),
                "order": len(canonical),
                "kind": kind,
                "text": text,
                "locator": locator,
            }
            duplicate_key = (kind, current_section, _normalized_record_text(text))
            existing = seen.get(duplicate_key)
            if existing is not None:
                existing_ids = [str(value) for value in existing.get("sourceIds") or []]
                for value in normalized["sourceIds"]:
                    if value not in existing_ids:
                        existing_ids.append(value)
                existing["sourceIds"] = existing_ids
                existing["duplicateSourceIds"] = existing_ids[1:]
                continue
            seen[duplicate_key] = normalized
            canonical.append(normalized)
    return canonical


def build_structured_markdown(source_records: list[dict[str, Any]]) -> str:
    return "\n".join(
        markdown
        for markdown in (_record_markdown(record) for record in source_records)
        if markdown
    ).strip()


def _source_records_content_hash(source_records: list[dict[str, Any]]) -> str:
    digest_input = "\n".join(
        f"{record.get('sourceId', '')}|{record.get('kind', '')}|{record.get('text', '')}"
        for record in source_records
    )
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()


def _locator_confidence_for_record(locator: dict[str, Any], source_format: str) -> str:
    if source_format == "txt":
        return "exact"
    if source_format == "pdf":
        return "high" if isinstance(locator.get("bbox"), list) and len(locator["bbox"]) == 4 else "approximate"
    # DOCX body order is reliable for ordinary paragraphs. Floating textboxes are a
    # different layout model: only an extracted anchor/VML vertical coordinate merits
    # a precise visual-position claim.  Missing coordinates must remain explicit.
    if locator.get("textboxIndex") is not None:
        return "high" if isinstance(locator.get("layoutY"), (int, float)) else "approximate"
    return "high" if locator.get("paragraphIndex") is not None or locator.get("tableIndex") is not None else "approximate"


def build_resume_blocks_from_source_records(
    source_records: list[dict[str, Any]],
    file_id: str,
    file_name: str,
    *,
    content_hash: str | None = None,
) -> list[dict[str, Any]]:
    """Create the sole canonical display/evidence blocks from structured source data."""
    del file_id  # Kept in the public signature for callers that also use legacy blocks.
    records = normalize_resume_source_records(source_records)
    source_format = Path(file_name).suffix.lower().lstrip(".") or "txt"
    if source_format == "docx":
        records = _move_detached_docx_project_records(records)
    stable_content_hash = content_hash or _source_records_content_hash(records)
    current_section = "其他"
    section_counts: dict[str, int] = {}
    blocks: list[dict[str, Any]] = []

    for record in records:
        text = str(record.get("text") or "").strip()
        kind = str(record.get("kind") or "paragraph")
        detected_section = section_for_line(text)
        if kind == "heading" or (detected_section and kind not in {"bullet", "table_cell"}):
            kind = "heading"
            if detected_section:
                current_section = detected_section
            section_counts.setdefault(current_section, 0)
        else:
            section_counts[current_section] = section_counts.get(current_section, 0) + 1

        source_ids = [str(value) for value in (record.get("sourceIds") or [record.get("sourceId")]) if str(value)]
        source_block_id = source_ids[0] if source_ids else _source_record_id(record, len(blocks))
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        block_seed = f"{stable_content_hash}:{source_block_id}:{kind}:{current_section}:{text_hash}"
        item_index = section_counts.get(current_section, 0)
        item_label = f"第 {item_index} 条" if item_index else "标题"
        locator = dict(record.get("locator") or {})
        locator.setdefault("sourceFormat", source_format)
        locator.setdefault("sourceId", source_block_id)
        section_uid_seed = f"{stable_content_hash}:{current_section}"
        blocks.append(
            {
                "id": f"block-{hashlib.sha256(block_seed.encode('utf-8')).hexdigest()[:24]}",
                "order": len(blocks),
                "kind": kind,
                "sectionId": section_type_for_label(current_section),
                "sectionUid": f"section-{hashlib.sha256(section_uid_seed.encode('utf-8')).hexdigest()[:16]}",
                "sectionName": current_section,
                "itemLabel": item_label,
                "text": text,
                "markdown": _record_markdown({**record, "kind": kind, "text": text}),
                "textHash": text_hash,
                "sourceBlockId": source_block_id,
                "sourceBlockIds": source_ids,
                "duplicateSourceIds": list(record.get("duplicateSourceIds") or []),
                "locationLabel": f"{current_section} > {item_label}",
                "locatorConfidence": _locator_confidence_for_record(locator, source_format),
                "locator": locator,
            }
        )

    return deduplicate_resume_blocks(blocks)


_PROJECT_TITLE_DATE_RE = re.compile(r"(?:19|20)\d{2}\s*[./年]\s*(?:0?[1-9]|1[0-2])\s*(?:[-~—–至]|至今)")
_PROJECT_TITLE_MARKERS = ("项目", "系统", "工具", "平台", "应用", "软件", "pro", "toolkit", "app")


def _move_detached_docx_project_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Place an unmistakable floating project subtree below its DOCX project title.

    Floating DOCX textboxes can carry a project title before the visible section
    heading in XML. Coordinates repair the common case; this conservative second pass
    only handles a date-bearing project title plus its following child records when it
    shares the same body host as a later ``项目经历`` heading. Ordinary paragraphs are
    never moved by this rule.
    """
    project_heading_index = next(
        (
            index
            for index, record in enumerate(records)
            if section_for_line(str(record.get("text") or "")) == "项目经历"
        ),
        None,
    )
    if project_heading_index is None:
        return records

    project_heading = records[project_heading_index]
    project_body_index = (project_heading.get("locator") or {}).get("bodyIndex")
    ranges: list[tuple[int, int]] = []
    index = 0
    while index < project_heading_index:
        record = records[index]
        text = str(record.get("text") or "").strip()
        locator = record.get("locator") if isinstance(record.get("locator"), dict) else {}
        marker_match = any(marker in text.casefold() for marker in _PROJECT_TITLE_MARKERS)
        same_body_host = project_body_index is not None and locator.get("bodyIndex") == project_body_index
        if not (_PROJECT_TITLE_DATE_RE.search(text) and marker_match and same_body_host):
            index += 1
            continue

        end = index + 1
        while end < project_heading_index:
            candidate = records[end]
            candidate_text = str(candidate.get("text") or "")
            if candidate.get("kind") == "heading" or section_for_line(candidate_text):
                break
            end += 1
        ranges.append((index, end))
        index = end

    if not ranges:
        return records

    moved_indexes = {index for start, end in ranges for index in range(start, end)}
    moved = [record for index, record in enumerate(records) if index in moved_indexes]
    remaining = [record for index, record in enumerate(records) if index not in moved_indexes]
    project_heading_index = next(
        index
        for index, record in enumerate(remaining)
        if section_for_line(str(record.get("text") or "")) == "项目经历"
    )
    insertion_index = next(
        (
            index
            for index in range(project_heading_index + 1, len(remaining))
            if remaining[index].get("kind") == "heading"
            or section_for_line(str(remaining[index].get("text") or ""))
        ),
        len(remaining),
    )
    output = [*remaining[:insertion_index], *moved, *remaining[insertion_index:]]
    for order, record in enumerate(output):
        record["order"] = order
    return output


def deduplicate_resume_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return canonical blocks while retaining aliases and source provenance."""
    canonical: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        key = (
            str(block.get("kind") or "paragraph"),
            str(block.get("sectionName") or "其他"),
            _normalized_record_text(text),
        )
        existing = by_key.get(key)
        if existing is None:
            clone = dict(block)
            clone["sourceBlockIds"] = list(dict.fromkeys(str(value) for value in clone.get("sourceBlockIds") or [] if str(value)))
            by_key[key] = clone
            canonical.append(clone)
            continue
        source_ids = [str(value) for value in existing.get("sourceBlockIds") or []]
        for value in block.get("sourceBlockIds") or [block.get("sourceBlockId")]:
            value = str(value or "")
            if value and value not in source_ids:
                source_ids.append(value)
        existing["sourceBlockIds"] = source_ids
        aliases = [str(value) for value in existing.get("legacyBlockIds") or []]
        duplicate_id = str(block.get("id") or "")
        if duplicate_id and duplicate_id != existing.get("id") and duplicate_id not in aliases:
            aliases.append(duplicate_id)
        if aliases:
            existing["legacyBlockIds"] = aliases

    for order, block in enumerate(canonical):
        block["order"] = order
        block["contextBefore"] = str(canonical[order - 1].get("text") or "") if order else ""
        block["contextAfter"] = str(canonical[order + 1].get("text") or "") if order + 1 < len(canonical) else ""
    return canonical


def _chunk_scope_for_block(block: dict[str, Any]) -> tuple[Any, ...]:
    locator = block.get("locator") if isinstance(block.get("locator"), dict) else {}
    if locator.get("sourceFormat") == "pdf":
        return (locator.get("pageNumber"), locator.get("columnIndex", 0))
    return ("document",)


def _structured_chunk(
    *,
    blocks: list[dict[str, Any]],
    file_id: str,
    file_name: str,
    content_hash: str,
    index: int,
) -> dict[str, Any]:
    section = str(blocks[0].get("sectionName") or "其他")
    section_type = section_type_for_label(section)
    semantic_type = semantic_type_for_section_type(section_type)
    content = "\n".join(str(block.get("text") or "").strip() for block in blocks if str(block.get("text") or "").strip())
    markdown = "\n".join(str(block.get("markdown") or block.get("text") or "").strip() for block in blocks if str(block.get("text") or "").strip())
    block_ids = [str(block.get("id") or "") for block in blocks if str(block.get("id") or "")]
    source_block_ids: list[str] = []
    for block in blocks:
        for source_id in block.get("sourceBlockIds") or [block.get("sourceBlockId")]:
            source_id = str(source_id or "")
            if source_id and source_id not in source_block_ids:
                source_block_ids.append(source_id)
    chunk_seed = f"{content_hash}:{index}:{section}:{'|'.join(source_block_ids)}:{content}"
    chunk_id = f"chunk-{hashlib.sha256(chunk_seed.encode('utf-8')).hexdigest()[:24]}"
    first_locator = dict(blocks[0].get("locator") or {})
    section_uid = str(blocks[0].get("sectionUid") or "")
    importance = SECTION_IMPORTANCE.get(section_type, 0.60)
    return {
        "id": chunk_id,
        "chunkId": chunk_id,
        "legacyId": f"{file_id}-{index}",
        "documentId": file_id,
        "resumeFileId": file_id,
        "index": index,
        "chunkIndex": index,
        "content": content,
        "text": content,
        "chunkText": content,
        "markdown": markdown,
        "embeddingText": content,
        "section": section,
        "sectionTitle": section,
        "sectionId": section_uid,
        "sectionType": section_type,
        "semanticType": semantic_type,
        "importance": importance,
        "hierarchy": [section],
        "keywords": detect_keywords(content),
        "blockIds": block_ids,
        "sourceBlockIds": source_block_ids,
        "sourceFormat": str(first_locator.get("sourceFormat") or Path(file_name).suffix.lower().lstrip(".")),
        "locator": first_locator,
        "metadata": {
            "heading": section,
            "source": file_name,
            "sectionTitle": section,
            "sectionId": section_uid,
            "sectionType": section_type,
            "semanticType": semantic_type,
            "importance": importance,
            "hierarchy": [section],
            "blockIds": block_ids,
            "sourceBlockIds": source_block_ids,
        },
    }


def chunk_resume_blocks(
    blocks: list[dict[str, Any]],
    file_id: str,
    file_name: str,
    *,
    content_hash: str | None = None,
    max_characters: int = 800,
) -> list[dict[str, Any]]:
    """Chunk only canonical blocks; Markdown is never parsed a second time."""
    chunks: list[dict[str, Any]] = []
    stable_content_hash = content_hash or _source_records_content_hash(blocks)
    buffer: list[dict[str, Any]] = []
    current_key: tuple[Any, ...] | None = None

    def flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        chunks.append(
            _structured_chunk(
                blocks=buffer,
                file_id=file_id,
                file_name=file_name,
                content_hash=stable_content_hash,
                index=len(chunks),
            )
        )
        buffer = []

    for block in blocks:
        if not isinstance(block, dict) or not str(block.get("text") or "").strip():
            continue
        group_key = (str(block.get("sectionName") or "其他"), *_chunk_scope_for_block(block))
        candidate_text = "\n".join([*(str(item.get("text") or "") for item in buffer), str(block.get("text") or "")]).strip()
        if buffer and (group_key != current_key or len(candidate_text) > max_characters):
            flush()
        if not buffer:
            current_key = group_key
        buffer.append(block)
    flush()
    return chunks


def _parse_warnings_for_source_records(source_records: list[dict[str, Any]]) -> list[str]:
    source_formats = {
        str((record.get("locator") or {}).get("sourceFormat") or "")
        for record in source_records
        if isinstance(record, dict)
    }
    layout_confidences = {
        str((record.get("locator") or {}).get("layoutConfidence") or "")
        for record in source_records
        if isinstance(record, dict)
    }
    if source_formats == {"pdf"} and layout_confidences == {"approximate"}:
        return ["PDF 未提供可靠版面坐标，已使用近似阅读顺序；请在原件中确认定位。"]
    return []


def build_resume_blocks(cleaned_text: str, file_id: str, file_name: str) -> list[dict[str, Any]]:
    """Build stable, display-oriented resume blocks from parsed text.

    PDF and DOCX extraction currently provides a text stream rather than a layout tree, so
    their locators are deliberately marked as approximate. The block id, text hash, order,
    and surrounding context still make the target immutable and safely addressable.
    """
    source_format = Path(file_name).suffix.lower().lstrip(".") or "txt"
    if source_format not in {"pdf", "docx", "txt"}:
        source_format = "txt"

    non_empty_lines = [
        (line_number, line.strip())
        for line_number, line in enumerate(cleaned_text.splitlines(), start=1)
        if line.strip()
    ]
    current_section = "其他"
    section_counts: dict[str, int] = {}
    blocks: list[dict[str, Any]] = []

    for order, (line_number, text) in enumerate(non_empty_lines):
        heading = section_for_line(text)
        if heading:
            current_section = heading
            section_counts.setdefault(current_section, 0)
            kind = "heading"
        else:
            section_counts[current_section] = section_counts.get(current_section, 0) + 1
            kind = "bullet" if re.match(r"^([-•·*]|\d+[.、)])\s*", text) else "paragraph"

        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        context_before = non_empty_lines[order - 1][1] if order > 0 else ""
        context_after = non_empty_lines[order + 1][1] if order + 1 < len(non_empty_lines) else ""
        item_index = section_counts.get(current_section, 0)
        block_seed = f"{file_id}:{order}:{text_hash}:{context_before}:{context_after}"
        block_id = f"block-{hashlib.sha256(block_seed.encode('utf-8')).hexdigest()[:24]}"
        item_label = f"第 {item_index} 条" if item_index else "标题"

        blocks.append(
            {
                "id": block_id,
                "order": order,
                "kind": kind,
                "sectionId": section_type_for_label(current_section),
                "sectionName": current_section,
                "itemLabel": item_label,
                "text": text,
                "textHash": text_hash,
                "contextBefore": context_before,
                "contextAfter": context_after,
                "locationLabel": f"{current_section} > {item_label}",
                "locatorConfidence": "exact" if source_format == "txt" else "approximate",
                "locator": {
                    "sourceFormat": source_format,
                    "lineStart": line_number,
                    "lineEnd": line_number,
                },
            }
        )
    return deduplicate_resume_blocks(blocks)


def chunk_resume(cleaned_text: str, file_id: str, file_name: str) -> list[dict[str, Any]]:
    sections: list[tuple[str, list[str]]] = []
    current_section = "其他"
    current_lines: list[str] = []
    for line in _section_candidate_lines(cleaned_text):
        heading = section_for_line(line)
        if heading:
            if current_lines:
                sections.append((current_section, current_lines))
            current_section = heading
            current_lines = [line]
        elif line.strip():
            current_lines.append(line)
    if current_lines:
        sections.append((current_section, current_lines))
    if not sections:
        sections = [("简历内容", cleaned_text.splitlines())]

    chunks: list[dict[str, Any]] = []
    for section, lines in sections:
        buffer: list[str] = []
        for line in lines:
            candidate = "\n".join([*buffer, line]).strip()
            if len(candidate) > 800 and buffer:
                chunks.append(build_chunk(file_id, file_name, section, chunks, "\n".join(buffer)))
                buffer = [line]
            else:
                buffer.append(line)
        if buffer:
            chunks.append(build_chunk(file_id, file_name, section, chunks, "\n".join(buffer)))
    return chunks


def build_chunk(file_id: str, file_name: str, section: str, chunks: list[dict[str, Any]], content: str) -> dict[str, Any]:
    section_type = section_type_for_label(section)
    semantic_type = semantic_type_for_section_type(section_type)
    importance = SECTION_IMPORTANCE.get(section_type, 0.60)
    return {
        "id": f"{file_id}-{len(chunks)}",
        "resumeFileId": file_id,
        "index": len(chunks),
        "content": content.strip(),
        "section": section,
        "sectionTitle": section,
        "sectionType": section_type,
        "semanticType": semantic_type,
        "importance": importance,
        "hierarchy": [section],
        "keywords": detect_keywords(content),
        "metadata": {
            "heading": section,
            "source": file_name,
            "sectionTitle": section,
            "sectionType": section_type,
            "semanticType": semantic_type,
            "importance": importance,
            "hierarchy": [section],
        },
    }


def _chunk_generic_section_value(chunk: dict[str, Any], key: str) -> str:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    value = chunk.get(key) or metadata.get(key) or ""
    return str(value).strip().lower()


def _is_generic_chunk_section(chunk: dict[str, Any]) -> bool:
    section = _chunk_generic_section_value(chunk, "section")
    section_title = _chunk_generic_section_value(chunk, "sectionTitle")
    section_type = _chunk_generic_section_value(chunk, "sectionType")
    semantic_type = _chunk_generic_section_value(chunk, "semanticType")
    section_values = [section, section_title]
    type_values = [section_type, semantic_type]
    has_specific_section = any(value and value not in _GENERIC_SECTION_VALUES for value in section_values)
    has_specific_type = any(value and value not in _GENERIC_SECTION_VALUES for value in type_values)
    return not has_specific_section and not has_specific_type


def resume_chunks_need_section_repair(chunks: list[dict[str, Any]]) -> bool:
    valid_chunks = [chunk for chunk in chunks if isinstance(chunk, dict)]
    return bool(valid_chunks) and all(_is_generic_chunk_section(chunk) for chunk in valid_chunks)


def resume_blocks_need_section_repair(blocks: list[dict[str, Any]]) -> bool:
    valid_blocks = [block for block in blocks if isinstance(block, dict)]
    if not valid_blocks:
        return False
    return all(
        str(block.get("sectionName") or "").strip().lower() in _GENERIC_SECTION_VALUES
        and str(block.get("sectionId") or "").strip().lower() in _GENERIC_SECTION_VALUES
        for block in valid_blocks
    )


def _contains_known_section_marker(text: str) -> bool:
    return any(section_for_line(line) for line in _section_candidate_lines(text))


def _deduplicate_resume_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    canonical: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        content = str(chunk.get("content") or chunk.get("text") or "").strip()
        if not content:
            continue
        key = (str(chunk.get("section") or "其他"), _normalized_record_text(content))
        existing = by_key.get(key)
        if existing is None:
            clone = dict(chunk)
            by_key[key] = clone
            canonical.append(clone)
            continue
        source_ids = [str(value) for value in existing.get("sourceBlockIds") or []]
        for source_id in chunk.get("sourceBlockIds") or []:
            source_id = str(source_id or "")
            if source_id and source_id not in source_ids:
                source_ids.append(source_id)
        if source_ids:
            existing["sourceBlockIds"] = source_ids
            existing.setdefault("metadata", {})["sourceBlockIds"] = source_ids
        aliases = [str(value) for value in existing.get("duplicateChunkIds") or []]
        duplicate_id = str(chunk.get("id") or "")
        if duplicate_id and duplicate_id != existing.get("id") and duplicate_id not in aliases:
            aliases.append(duplicate_id)
        if aliases:
            existing["duplicateChunkIds"] = aliases
    for index, chunk in enumerate(canonical):
        chunk["index"] = index
        chunk.setdefault("chunkIndex", index)
    return canonical


def _reparse_outdated_stored_resume(parsed_resume: dict[str, Any]) -> dict[str, Any] | None:
    parser = parsed_resume.get("parser") if isinstance(parsed_resume.get("parser"), dict) else {}
    if str(parser.get("version") or "") == STRUCTURED_RESUME_PARSER_VERSION:
        return None
    file_info = parsed_resume.get("file") if isinstance(parsed_resume.get("file"), dict) else {}
    file_name = str(file_info.get("name") or "")
    suffix = Path(file_name).suffix.lower()
    encoded = str(file_info.get("b64_content") or "")
    if suffix not in {".docx", ".pdf"} or not encoded:
        return None

    try:
        import base64

        data = base64.b64decode(encoded, validate=True)
        reparsed = parse_resume(file_name, str(file_info.get("type") or ""), data)
    except Exception:
        # Legacy snapshots without a valid original file still retain the text-only
        # section repair path below.  A failed lazy upgrade must not hide the resume.
        return None

    original_file_id = str(file_info.get("id") or reparsed.get("file", {}).get("id") or "resume")
    reparsed_file = reparsed.get("file") if isinstance(reparsed.get("file"), dict) else {}
    reparsed["file"] = {
        **reparsed_file,
        **file_info,
        "id": original_file_id,
        "name": file_name,
        "type": str(file_info.get("type") or reparsed_file.get("type") or ""),
        "contentHash": str(reparsed.get("contentHash") or reparsed_file.get("contentHash") or ""),
        "status": "parsed",
    }

    old_blocks_by_text: dict[str, list[str]] = {}
    for old_block in parsed_resume.get("blocks") or []:
        if not isinstance(old_block, dict):
            continue
        text_key = _normalized_record_text(str(old_block.get("text") or ""))
        old_ids = [old_block.get("id"), *(old_block.get("legacyBlockIds") or [])]
        for old_id in old_ids:
            old_id = str(old_id or "")
            if text_key and old_id and old_id not in old_blocks_by_text.setdefault(text_key, []):
                old_blocks_by_text[text_key].append(old_id)
    for block in reparsed.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        aliases = [
            old_id
            for old_id in old_blocks_by_text.get(_normalized_record_text(str(block.get("text") or "")), [])
            if old_id != block.get("id")
        ]
        if aliases:
            block["legacyBlockIds"] = list(dict.fromkeys([*(block.get("legacyBlockIds") or []), *aliases]))

    old_chunks_by_content = {
        _normalized_record_text(str(chunk.get("content") or chunk.get("text") or "")): chunk
        for chunk in parsed_resume.get("chunks") or []
        if isinstance(chunk, dict)
    }
    for index, chunk in enumerate(reparsed.get("chunks") or []):
        if not isinstance(chunk, dict):
            continue
        chunk["documentId"] = original_file_id
        chunk["resumeFileId"] = original_file_id
        chunk["legacyId"] = f"{original_file_id}-{index}"
        previous = old_chunks_by_content.get(_normalized_record_text(str(chunk.get("content") or "")))
        if previous and previous.get("embedding") is not None:
            chunk["embedding"] = previous.get("embedding")
            chunk.setdefault("metadata", {})["embedding"] = previous.get("embedding")
    return reparsed


def repair_resume_chunk_sections(parsed_resume: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    reparsed = _reparse_outdated_stored_resume(parsed_resume)
    if reparsed is not None:
        return reparsed, True
    chunks = parsed_resume.get("chunks") or []
    blocks = parsed_resume.get("blocks") or []
    if not isinstance(chunks, list):
        return parsed_resume, False
    if not isinstance(blocks, list):
        blocks = []
    text = str(parsed_resume.get("cleanedText") or parsed_resume.get("rawText") or "").strip()
    if not text:
        text = "\n".join(str(chunk.get("content") or chunk.get("text") or "") for chunk in chunks if isinstance(chunk, dict))
    if not text.strip():
        return parsed_resume, False

    # Structure v2 is created from native source records and may legitimately contain
    # an "其他" preamble.  Legacy flattened records with recognizable headings are
    # different: any remaining generic block/chunk is a sign that the old splitter
    # lost a section boundary and should be rebuilt once.
    is_structured_v2 = str(parsed_resume.get("structureVersion") or "") == "resume-structure-v2"
    has_known_sections = _contains_known_section_marker(text)
    repair_chunks = resume_chunks_need_section_repair(chunks)
    repair_blocks = resume_blocks_need_section_repair(blocks)
    if not is_structured_v2 and has_known_sections:
        repair_chunks = repair_chunks or any(_is_generic_chunk_section(chunk) for chunk in chunks if isinstance(chunk, dict))
        repair_blocks = repair_blocks or any(
            str(block.get("sectionName") or "").strip().lower() in _GENERIC_SECTION_VALUES
            and str(block.get("sectionId") or "").strip().lower() in _GENERIC_SECTION_VALUES
            for block in blocks
            if isinstance(block, dict)
        )
    if not repair_chunks and not repair_blocks:
        return parsed_resume, False

    cleaned_text = clean_resume_text(text)
    file_info = parsed_resume.get("file") if isinstance(parsed_resume.get("file"), dict) else {}
    first_chunk = next((chunk for chunk in chunks if isinstance(chunk, dict)), {})
    file_id = str(file_info.get("id") or first_chunk.get("resumeFileId") or "resume")
    file_name = str(file_info.get("name") or first_chunk.get("fileName") or "resume")
    repaired = dict(parsed_resume)
    repaired["cleanedText"] = cleaned_text
    if repair_chunks:
        rebuilt_chunks = chunk_resume(cleaned_text, file_id, file_name)
        if not rebuilt_chunks or resume_chunks_need_section_repair(rebuilt_chunks):
            return parsed_resume, False
        old_by_content = {
            str(chunk.get("content") or chunk.get("text") or "").strip(): chunk
            for chunk in chunks
            if isinstance(chunk, dict)
        }
        for chunk in rebuilt_chunks:
            previous = old_by_content.get(str(chunk.get("content") or "").strip())
            if previous and previous.get("embedding") is not None:
                chunk["embedding"] = previous.get("embedding")
                chunk.setdefault("metadata", {})["embedding"] = previous.get("embedding")
        repaired["chunks"] = _deduplicate_resume_chunks(rebuilt_chunks)
    if repair_blocks or not blocks:
        rebuilt_blocks = build_resume_blocks(cleaned_text, file_id, file_name)
        old_blocks_by_text: dict[str, list[str]] = {}
        for old_block in blocks:
            if not isinstance(old_block, dict):
                continue
            key = _normalized_record_text(str(old_block.get("text") or ""))
            old_id = str(old_block.get("id") or "")
            if key and old_id:
                old_blocks_by_text.setdefault(key, []).append(old_id)
        for block in rebuilt_blocks:
            aliases = [
                old_id
                for old_id in old_blocks_by_text.get(_normalized_record_text(str(block.get("text") or "")), [])
                if old_id != block.get("id")
            ]
            if aliases:
                block["legacyBlockIds"] = list(dict.fromkeys(aliases))
        repaired["blocks"] = rebuilt_blocks
    return repaired, True


def detect_keywords(text: str) -> list[str]:
    lower = text.lower()
    return [keyword for keyword in SKILL_KEYWORDS if keyword.lower() in lower]


def extract_profile(text: str) -> dict[str, Any]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return {
        "email": next(iter(re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)), None),
        "phone": next(iter(re.findall(r"(?:\+?86[- ]?)?1[3-9]\d{9}", text)), None),
        "education": [line for line in lines if any(word in line for word in ("大学", "学院", "本科", "硕士"))][:5],
        "skills": detect_keywords(text),
        "projects": [line for line in lines if "项目" in line][:8],
        "experiences": [line for line in lines if any(word in line for word in ("实习", "工作", "负责"))][:8],
    }


def retrieve_chunks(jd_text: str, chunks: list[dict[str, Any]], top_k: int = 8) -> dict[str, Any]:
    if not jd_text.strip():
        raise DocumentParseError("JD 为空，无法检索")
    if not chunks:
        raise DocumentParseError("简历还没有完成解析或 chunk 为空")

    jd_keywords = set(detect_keywords(jd_text))
    jd_terms = set(re.findall(r"[A-Za-z][A-Za-z.+#-]{1,}|[\u4e00-\u9fa5]{2,}", jd_text.lower()))
    scored = []
    for chunk in chunks:
        content = str(chunk.get("content") or "")
        chunk_keywords = set(chunk.get("keywords") or detect_keywords(content))
        chunk_terms = set(re.findall(r"[A-Za-z][A-Za-z.+#-]{1,}|[\u4e00-\u9fa5]{2,}", content.lower()))
        keyword_score = len(jd_keywords & chunk_keywords) * 2.8
        term_score = len(jd_terms & chunk_terms) * 0.32
        section_bonus = 1.2 if chunk.get("section") in {"项目经历", "实习 / 工作经历", "技能"} else 0
        score = min(1.0, (keyword_score + term_score + section_bonus) / 10)
        scored.append({**chunk, "score": round(score * 100)})

    top_chunks = sorted(scored, key=lambda item: item.get("score", 0), reverse=True)[:top_k]
    summary = f"检索到 {len(top_chunks)} 个相关简历片段，覆盖 {', '.join(sorted(jd_keywords)) or 'JD 高频词'}。"
    return {
        "query": jd_text,
        "topChunks": top_chunks,
        "retrievalSummary": summary,
    }
