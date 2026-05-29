from __future__ import annotations

from pathlib import Path
from typing import BinaryIO
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


class DocumentParseError(ValueError):
    """Raised when an uploaded document cannot be parsed."""


def extract_text_from_uploaded_file(uploaded_file) -> tuple[str, str]:
    file_name = getattr(uploaded_file, "name", "") or "upload"
    suffix = Path(file_name).suffix.lower().lstrip(".")
    data = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else uploaded_file.read()
    if suffix == "txt":
        return extract_text_from_txt_bytes(data), "txt"
    if suffix == "md":
        return extract_text_from_md_bytes(data), "md"
    if suffix == "pdf":
        return extract_text_from_pdf_bytes(data), "pdf"
    if suffix == "docx":
        return extract_text_from_docx_bytes(data), "docx"
    if suffix == "doc":
        raise DocumentParseError("老 DOC 格式暂不支持可靠解析，请转换为 DOCX 或 PDF 后上传")
    raise DocumentParseError("仅支持 txt / md / pdf / docx 文件")


def extract_text_from_txt(file: BinaryIO) -> str:
    return _decode_bytes(file.read())


def extract_text_from_md(file: BinaryIO) -> str:
    return _decode_bytes(file.read())


def extract_text_from_pdf(file: BinaryIO) -> str:
    return extract_text_from_pdf_bytes(file.read())


def extract_text_from_txt_bytes(data: bytes) -> str:
    return _ensure_text(_decode_bytes(data))


def extract_text_from_md_bytes(data: bytes) -> str:
    return _ensure_text(_decode_bytes(data))


def extract_text_from_pdf_bytes(data: bytes) -> str:
    try:
      from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentParseError("PDF 解析需要安装 pypdf") from exc

    try:
        import io

        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        return _ensure_text("\n\n".join(pages))
    except Exception as exc:  # noqa: BLE001
        raise DocumentParseError(f"PDF 解析失败：{exc}") from exc


def extract_text_from_docx_bytes(data: bytes) -> str:
    try:
        import io

        with ZipFile(io.BytesIO(data)) as archive:
            # Prevent Zip Bomb / Decompression resource exhaustion
            info = archive.getinfo("word/document.xml")
            if info.file_size > 20 * 1024 * 1024:  # limit uncompressed size to 20MB
                raise DocumentParseError("文档正文大小超出限制，解析终止以确保安全")
            document_xml = archive.read("word/document.xml")
    except (KeyError, BadZipFile) as exc:
        raise DocumentParseError("DOCX 解析失败，请检查文件是否损坏") from exc

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as exc:
        raise DocumentParseError("DOCX 正文解析失败") from exc

    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        texts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        line = "".join(texts).strip()
        if line:
            paragraphs.append(line)
    return _ensure_text("\n".join(paragraphs))


def _decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _ensure_text(text: str) -> str:
    stripped = (text or "").strip()
    if not stripped:
        raise DocumentParseError("未提取到有效文本")
    return stripped
