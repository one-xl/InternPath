from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from document_parser import DocumentParseError, extract_text_from_docx_bytes, extract_text_from_pdf_bytes


SUPPORTED_TYPES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}
SUPPORTED_EXTENSIONS = {".pdf", ".doc", ".docx"}
MAX_FILE_SIZE = 10 * 1024 * 1024
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
    "基本信息": ["基本信息", "个人信息", "联系方式"],
    "教育经历": ["教育经历", "教育背景", "Education"],
    "技能": ["技能", "专业技能", "技能栈", "Skills"],
    "项目经历": ["项目经历", "项目经验", "Projects"],
    "实习 / 工作经历": ["实习经历", "工作经历", "Work Experience", "Experience"],
    "获奖 / 证书": ["获奖", "证书", "荣誉", "Awards"],
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
        raise DocumentParseError("仅支持 PDF、DOC、DOCX 格式")


def parse_resume(file_name: str, content_type: str, data: bytes) -> dict[str, Any]:
    validate_resume_upload(file_name, content_type, data)
    suffix = Path(file_name).suffix.lower()
    if suffix == ".pdf":
        raw_text = extract_text_from_pdf_bytes(data)
    elif suffix == ".docx":
        raw_text = extract_text_from_docx_bytes(data)
    elif suffix == ".doc":
        raise DocumentParseError("DOC 格式无法可靠解析，请转换为 DOCX 或 PDF 后上传")
    else:
        raise DocumentParseError("仅支持 PDF、DOC、DOCX 格式")

    cleaned_text = clean_resume_text(raw_text)
    file_id = uuid4().hex
    import base64
    b64_content = base64.b64encode(data).decode("utf-8")
    resume_file = {
        "id": file_id,
        "name": file_name,
        "size": len(data),
        "type": content_type,
        "uploadedAt": datetime.now().isoformat(),
        "status": "parsed",
        "b64_content": b64_content,
    }
    chunks = chunk_resume(cleaned_text, file_id, file_name)
    return {
        "file": resume_file,
        "rawText": raw_text,
        "cleanedText": cleaned_text,
        "chunks": chunks,
        "extractedProfile": extract_profile(cleaned_text),
    }


def clean_resume_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = re.sub(r"(?<![。；;:：])\n(?!\n|[-•])", " ", normalized)
    return normalized.strip()


def section_for_line(line: str) -> str | None:
    compact = line.strip().strip(":：")
    if len(compact) > 28:
        return None
    for section, aliases in SECTION_ALIASES.items():
        if any(alias.lower() == compact.lower() for alias in aliases):
            return section
    return None


def chunk_resume(cleaned_text: str, file_id: str, file_name: str) -> list[dict[str, Any]]:
    sections: list[tuple[str, list[str]]] = []
    current_section = "其他"
    current_lines: list[str] = []
    for line in cleaned_text.splitlines():
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
    return {
        "id": f"{file_id}-{len(chunks)}",
        "resumeFileId": file_id,
        "index": len(chunks),
        "content": content.strip(),
        "section": section,
        "keywords": detect_keywords(content),
        "metadata": {
            "heading": section,
            "source": file_name,
        },
    }


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
