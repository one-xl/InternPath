from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any, BinaryIO
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


class DocumentParseError(ValueError):
    """Raised when an uploaded document cannot be parsed."""


_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WORD = {"w": _WORD_NS}
_MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_MC_ALTERNATE_CONTENT = f"{{{_MC_NS}}}AlternateContent"
_MC_CHOICE = f"{{{_MC_NS}}}Choice"
_MC_FALLBACK = f"{{{_MC_NS}}}Fallback"
_WORD_TEXTBOX_CONTENT = f"{{{_WORD_NS}}}txbxContent"
_WORD_PARAGRAPH = f"{{{_WORD_NS}}}p"
_WORDPROCESSING_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_WORDPROCESSING_DRAWING_ANCHOR = f"{{{_WORDPROCESSING_DRAWING_NS}}}anchor"
_WORDPROCESSING_DRAWING_POSITION_H = f"{{{_WORDPROCESSING_DRAWING_NS}}}positionH"
_WORDPROCESSING_DRAWING_POSITION_V = f"{{{_WORDPROCESSING_DRAWING_NS}}}positionV"
_WORDPROCESSING_DRAWING_POS_OFFSET = f"{{{_WORDPROCESSING_DRAWING_NS}}}posOffset"
_VML_NS = "urn:schemas-microsoft-com:vml"
_VML_SHAPE = f"{{{_VML_NS}}}shape"
_WORD_IGNORED_TEXT_CONTAINERS = {
    f"{{{_WORD_NS}}}del",
    f"{{{_WORD_NS}}}moveFrom",
}


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
    return _ensure_text("\n".join(record["text"] for record in extract_pdf_structure(data)))


def extract_pdf_structure(data: bytes) -> list[dict[str, Any]]:
    """Extract PDF text as independently locatable reading blocks.

    ``pdfplumber`` is used when available because it exposes real page geometry.  The
    pypdf fallback deliberately keeps a conservative, line-based structure instead of
    inventing coordinates.  Both paths return the same record shape as the DOCX parser
    so callers can create one Markdown mirror and one canonical set of RAG chunks.
    """
    try:
        return _extract_pdf_structure_with_pdfplumber(data)
    except ImportError:
        return _extract_pdf_structure_with_pypdf(data)
    except DocumentParseError:
        raise
    except Exception:
        # A malformed layout stream should not turn an otherwise readable PDF into an
        # upload failure.  pypdf's layout extractor is less precise but still honest.
        return _extract_pdf_structure_with_pypdf(data)


def _extract_pdf_structure_with_pdfplumber(data: bytes) -> list[dict[str, Any]]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise exc

    records: list[dict[str, Any]] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            try:
                working_page = page.dedupe_chars(tolerance=1)
            except Exception:
                working_page = page

            table_records, table_boxes = _pdf_table_records(working_page, page_number)
            try:
                words = working_page.extract_words(
                    x_tolerance=1,
                    y_tolerance=3,
                    keep_blank_chars=False,
                    extra_attrs=["fontname", "size"],
                    use_text_flow=False,
                ) or []
            except Exception:
                words = []

            line_records = _pdf_line_records(
                words,
                page_number=page_number,
                page_width=float(working_page.width or 0),
                page_height=float(working_page.height or 0),
                table_boxes=table_boxes,
            )
            page_records = [*line_records, *table_records]
            # ``_pdf_line_records`` has already applied a column-safe reading order.
            # Only merge table rows into visual order when a page actually has tables.
            if table_records:
                page_records.sort(key=lambda record: (float(record.get("_sort_top", 0)), float(record.get("_sort_x", 0))))
            for record in page_records:
                record.pop("_sort_top", None)
                record.pop("_sort_x", None)
            for order, record in enumerate(page_records):
                record["order"] = len(records) + order
            records.extend(page_records)

    records = _drop_repeated_pdf_headers_and_footers(records)
    return _ensure_structure(records, "PDF")


def _pdf_table_records(page: Any, page_number: int) -> tuple[list[dict[str, Any]], list[tuple[float, float, float, float]]]:
    records: list[dict[str, Any]] = []
    boxes: list[tuple[float, float, float, float]] = []
    try:
        tables = page.find_tables() or []
    except Exception:
        tables = []

    page_height = float(page.height or 0)
    for table_index, table in enumerate(tables):
        raw_bbox = tuple(float(value) for value in (table.bbox or ()))
        if len(raw_bbox) != 4:
            continue
        boxes.append(raw_bbox)
        try:
            rows = table.extract() or []
        except Exception:
            rows = []
        for row_index, row in enumerate(rows):
            cells = [re.sub(r"\s+", " ", str(cell or "")).strip() for cell in (row or [])]
            if not any(cells):
                continue
            text = " | ".join(cells).strip(" |")
            if not text:
                continue
            top = raw_bbox[1] + ((raw_bbox[3] - raw_bbox[1]) * row_index / max(len(rows), 1))
            bottom = raw_bbox[1] + ((raw_bbox[3] - raw_bbox[1]) * (row_index + 1) / max(len(rows), 1))
            records.append(
                {
                    "sourceId": f"pdf:p:{page_number}:t:{table_index}:r:{row_index}",
                    "kind": "table_cell",
                    "text": text,
                    "locator": {
                        "sourceFormat": "pdf",
                        "pageNumber": page_number,
                        "tableIndex": table_index,
                        "rowIndex": row_index,
                        "bbox": [raw_bbox[0], page_height - bottom, raw_bbox[2], page_height - top],
                        "coordinateSpace": "pdf_user_space_bottom_left",
                        "readingOrder": row_index,
                        "columnIndex": 0,
                        "layoutEngine": "pdfplumber-table",
                        "layoutConfidence": "high",
                        "sourceId": f"pdf:p:{page_number}:t:{table_index}:r:{row_index}",
                    },
                    "_sort_top": top,
                    "_sort_x": raw_bbox[0],
                    "_page_height": page_height,
                    "_header_footer_candidate": False,
                }
            )
    return records, boxes


def _pdf_line_records(
    words: list[dict[str, Any]],
    *,
    page_number: int,
    page_width: float,
    page_height: float,
    table_boxes: list[tuple[float, float, float, float]],
) -> list[dict[str, Any]]:
    grouped_lines = _group_pdf_words_into_lines(words, table_boxes)
    if not grouped_lines:
        return []

    columns, column_confidence = _detect_pdf_columns(grouped_lines, page_width)
    median_size = sorted(line["size"] for line in grouped_lines)[len(grouped_lines) // 2]
    for line in grouped_lines:
        is_full_width = page_width > 0 and (line["x1"] - line["x0"]) >= page_width * 0.72
        if columns and not is_full_width:
            line["columnIndex"] = 0 if line["center"] < columns["split"] else 1
        else:
            line["columnIndex"] = 0
        line["isFullWidth"] = is_full_width

    if columns:
        # Keep a full-width title before its columns, then read each column top to
        # bottom.  This avoids joining or interleaving the two visual columns.
        ordered = sorted(
            grouped_lines,
            key=lambda line: (
                0 if line["isFullWidth"] else 1,
                0 if line["isFullWidth"] else line["columnIndex"] + 1,
                line["top"],
                line["x0"],
            ),
        )
    else:
        ordered = sorted(grouped_lines, key=lambda line: (line["top"], line["x0"]))

    records: list[dict[str, Any]] = []
    for reading_order, line in enumerate(ordered):
        text = line["text"]
        source_id = f"pdf:p:{page_number}:b:{reading_order}"
        kind = "heading" if line["size"] >= median_size + 1.5 else "paragraph"
        records.append(
            {
                "sourceId": source_id,
                "kind": kind,
                "text": text,
                "locator": {
                    "sourceFormat": "pdf",
                    "pageNumber": page_number,
                    "bbox": [line["x0"], page_height - line["bottom"], line["x1"], page_height - line["top"]],
                    "coordinateSpace": "pdf_user_space_bottom_left",
                    "readingOrder": reading_order,
                    "columnIndex": line["columnIndex"],
                    "layoutEngine": "pdfplumber",
                    "layoutConfidence": "high" if columns or len(grouped_lines) == 1 else column_confidence,
                    "sourceId": source_id,
                },
                "_sort_top": line["top"],
                "_sort_x": line["x0"],
                "_page_height": page_height,
                "_header_footer_candidate": line["top"] <= page_height * 0.12 or line["bottom"] >= page_height * 0.88,
            }
        )
    return records


def _group_pdf_words_into_lines(
    words: list[dict[str, Any]],
    table_boxes: list[tuple[float, float, float, float]],
) -> list[dict[str, Any]]:
    usable_words = [
        word
        for word in words
        if str(word.get("text") or "").strip()
        and not any(
            float(box[0]) <= float(word.get("x0") or 0) <= float(box[2])
            and float(box[1]) <= (float(word.get("top") or 0) + float(word.get("bottom") or 0)) / 2 <= float(box[3])
            for box in table_boxes
        )
    ]
    usable_words.sort(key=lambda word: (float(word.get("top") or 0), float(word.get("x0") or 0)))
    lines: list[list[dict[str, Any]]] = []
    for word in usable_words:
        top = float(word.get("top") or 0)
        size = float(word.get("size") or 10)
        if not lines:
            lines.append([word])
            continue
        previous = lines[-1]
        previous_top = min(float(item.get("top") or 0) for item in previous)
        tolerance = max(2.5, min(6.0, size * 0.42))
        if abs(top - previous_top) <= tolerance:
            previous.append(word)
        else:
            lines.append([word])

    output: list[dict[str, Any]] = []
    for line_words in lines:
        line_words.sort(key=lambda word: float(word.get("x0") or 0))
        segments: list[list[dict[str, Any]]] = [[]]
        previous_x1: float | None = None
        for word in line_words:
            x0 = float(word.get("x0") or 0)
            if previous_x1 is not None and x0 - previous_x1 > 24:
                # A sizeable same-baseline gap is a visual column, not a word space.
                # Keep each side as an independent block so it can never become one
                # hallucinated sentence or one cross-column RAG chunk.
                segments.append([])
            segments[-1].append(word)
            previous_x1 = float(word.get("x1") or x0)
        for segment in segments:
            text = _join_pdf_words(segment)
            if not text:
                continue
            output.append(
                {
                    "text": text,
                    "x0": min(float(word.get("x0") or 0) for word in segment),
                    "x1": max(float(word.get("x1") or 0) for word in segment),
                    "top": min(float(word.get("top") or 0) for word in segment),
                    "bottom": max(float(word.get("bottom") or 0) for word in segment),
                    "size": max(float(word.get("size") or 10) for word in segment),
                }
            )
            output[-1]["center"] = (output[-1]["x0"] + output[-1]["x1"]) / 2
    return output


def _join_pdf_words(words: list[dict[str, Any]]) -> str:
    values = [str(word.get("text") or "").strip() for word in words]
    values = [value for value in values if value]
    if not values:
        return ""
    joined = values[0]
    for value in values[1:]:
        previous = joined[-1:]
        next_char = value[:1]
        no_space = bool(previous and next_char and "\u4e00" <= previous <= "\u9fff" and "\u4e00" <= next_char <= "\u9fff")
        joined += ("" if no_space else " ") + value
    return re.sub(r"\s+", " ", joined).strip()


def _detect_pdf_columns(lines: list[dict[str, Any]], page_width: float) -> tuple[dict[str, float] | None, str]:
    if page_width <= 0 or len(lines) < 4:
        return None, "approximate"
    centers = sorted(float(line["center"]) for line in lines if (line["x1"] - line["x0"]) < page_width * 0.72)
    if len(centers) < 4:
        return None, "approximate"
    gaps = [(centers[index + 1] - centers[index], index) for index in range(len(centers) - 1)]
    largest_gap, gap_index = max(gaps, default=(0.0, 0))
    if largest_gap < page_width * 0.18:
        return None, "approximate"
    split = (centers[gap_index] + centers[gap_index + 1]) / 2
    left_count = sum(1 for center in centers if center < split)
    right_count = len(centers) - left_count
    if min(left_count, right_count) < 2:
        return None, "approximate"
    return {"split": split}, "high"


def _drop_repeated_pdf_headers_and_footers(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_text: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        normalized = re.sub(r"\s+", "", str(record.get("text") or "")).casefold()
        if normalized:
            by_text.setdefault(normalized, []).append(record)

    excluded_ids: set[str] = set()
    for repeated in by_text.values():
        pages = {int((record.get("locator") or {}).get("pageNumber") or 0) for record in repeated}
        if len(pages) < 2 or not all(record.get("_header_footer_candidate") for record in repeated):
            continue
        # Keep the first occurrence as an identifiable contact/header block but do not
        # let repeated page chrome become duplicate RAG evidence or preview paragraphs.
        excluded_ids.update(str(record.get("sourceId") or "") for record in repeated[1:])

    output = [record for record in records if str(record.get("sourceId") or "") not in excluded_ids]
    for record in output:
        record.pop("_page_height", None)
        record.pop("_header_footer_candidate", None)
    return output


def _extract_pdf_structure_with_pypdf(data: bytes) -> list[dict[str, Any]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentParseError("PDF 解析需要安装 pypdf") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
        records: list[dict[str, Any]] = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                page_text = page.extract_text(extraction_mode="layout") or ""
            except TypeError:
                page_text = page.extract_text() or ""
            for line_number, line in enumerate(page_text.splitlines(), start=1):
                text = re.sub(r"\s+", " ", line).strip()
                if not text:
                    continue
                source_id = f"pdf:p:{page_number}:l:{line_number}"
                records.append(
                    {
                        "sourceId": source_id,
                        "order": len(records),
                        "kind": "paragraph",
                        "text": text,
                        "locator": {
                            "sourceFormat": "pdf",
                            "pageNumber": page_number,
                            "lineStart": line_number,
                            "lineEnd": line_number,
                            "readingOrder": line_number - 1,
                            "columnIndex": 0,
                            "layoutEngine": "pypdf-layout",
                            "layoutConfidence": "approximate",
                            "sourceId": source_id,
                        },
                    }
                )
        return _ensure_structure(records, "PDF")
    except DocumentParseError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DocumentParseError(f"PDF 解析失败：{exc}") from exc


def extract_text_from_docx_bytes(data: bytes) -> str:
    return _ensure_text("\n".join(record["text"] for record in extract_docx_structure(data)))


def extract_docx_structure(data: bytes) -> list[dict[str, Any]]:
    """Read DOCX body elements in document order without discarding structure.

    The return value deliberately uses plain dictionaries so it can be stored with a
    parsed resume. Each record has stable logical source coordinates even when a
    browser cannot reproduce DOCX pagination.
    """
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            # Prevent Zip Bomb / Decompression resource exhaustion
            info = archive.getinfo("word/document.xml")
            if info.file_size > 20 * 1024 * 1024:  # limit uncompressed size to 20MB
                raise DocumentParseError("文档正文大小超出限制，解析终止以确保安全")
            document_xml = archive.read("word/document.xml")
    except (KeyError, BadZipFile) as exc:
        raise DocumentParseError("DOCX 解析失败，请检查文件是否损坏") from exc

    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as exc:
        raise DocumentParseError("DOCX 正文解析失败") from exc

    body = root.find("w:body", _WORD)
    if body is None:
        raise DocumentParseError("DOCX 正文为空")

    records: list[dict[str, Any]] = []
    paragraph_index = 0
    table_index = 0
    textbox_index = 0
    for body_index, element in enumerate(list(body)):
        if element.tag == f"{{{_WORD_NS}}}p":
            text = _docx_paragraph_text(element)
            if text:
                source_id = f"docx:p:{body_index}"
                style_name, heading_level = _docx_paragraph_style(element)
                records.append(
                    {
                        "sourceId": source_id,
                        "order": len(records),
                        "text": text,
                        "kind": _docx_paragraph_kind(element),
                        "styleName": style_name,
                        "headingLevel": heading_level,
                        "locator": {
                            "sourceFormat": "docx",
                            "paragraphIndex": paragraph_index,
                            "bodyIndex": body_index,
                            "sourceId": source_id,
                        },
                    }
                )
            for textbox in _docx_textboxes(element):
                for textbox_paragraph_index, textbox_paragraph in enumerate(textbox["paragraphs"]):
                    textbox_text = _docx_paragraph_text(textbox_paragraph)
                    if not textbox_text:
                        continue
                    source_id = f"docx:txbx:{body_index}:{textbox_index}:p:{textbox_paragraph_index}"
                    style_name, heading_level = _docx_paragraph_style(textbox_paragraph)
                    records.append(
                        {
                            "sourceId": source_id,
                            "order": len(records),
                            "text": textbox_text,
                            "kind": _docx_paragraph_kind(textbox_paragraph),
                            "styleName": style_name,
                            "headingLevel": heading_level,
                            "locator": {
                                "sourceFormat": "docx",
                                "paragraphIndex": paragraph_index,
                                "bodyIndex": body_index,
                                "textboxIndex": textbox_index,
                                "textboxParagraphIndex": textbox_paragraph_index,
                                **textbox["layout"],
                                "sourceId": source_id,
                            },
                        }
                    )
                textbox_index += 1
            paragraph_index += 1
            continue

        if element.tag != f"{{{_WORD_NS}}}tbl":
            continue
        for row_index, row in enumerate(element.findall("w:tr", _WORD)):
            cells: list[str] = []
            textbox_records: list[dict[str, Any]] = []
            for cell_index, cell in enumerate(row.findall("w:tc", _WORD)):
                cell_paragraphs = cell.findall("w:p", _WORD)
                paragraphs = [_docx_paragraph_text(paragraph) for paragraph in cell_paragraphs]
                cell_text = " ".join(part for part in paragraphs if part).strip()
                if cell_text:
                    cells.append(cell_text)
                for cell_paragraph in cell_paragraphs:
                    for textbox in _docx_textboxes(cell_paragraph):
                        for textbox_paragraph_index, textbox_paragraph in enumerate(textbox["paragraphs"]):
                            textbox_text = _docx_paragraph_text(textbox_paragraph)
                            if not textbox_text:
                                continue
                            source_id = (
                                f"docx:tbl:{body_index}:r:{row_index}:c:{cell_index}:"
                                f"txbx:{textbox_index}:p:{textbox_paragraph_index}"
                            )
                            style_name, heading_level = _docx_paragraph_style(textbox_paragraph)
                            textbox_records.append(
                                {
                                    "sourceId": source_id,
                                    "order": len(records) + len(textbox_records),
                                    "text": textbox_text,
                                    "kind": _docx_paragraph_kind(textbox_paragraph),
                                    "styleName": style_name,
                                    "headingLevel": heading_level,
                                    "locator": {
                                        "sourceFormat": "docx",
                                        "tableIndex": table_index,
                                        "rowIndex": row_index,
                                        "cellIndex": cell_index,
                                        "bodyIndex": body_index,
                                        "textboxIndex": textbox_index,
                                        "textboxParagraphIndex": textbox_paragraph_index,
                                        **textbox["layout"],
                                        "sourceId": source_id,
                                    },
                                }
                            )
                        textbox_index += 1
            if cells:
                source_id = f"docx:tbl:{body_index}:r:{row_index}"
                records.append(
                    {
                        "sourceId": source_id,
                        "order": len(records),
                        "text": " | ".join(cells),
                        "kind": "table_cell",
                        "locator": {
                            "sourceFormat": "docx",
                            "tableIndex": table_index,
                            "rowIndex": row_index,
                            "bodyIndex": body_index,
                            "sourceId": source_id,
                        },
                    }
                )
            for textbox_record in textbox_records:
                textbox_record["order"] = len(records)
                records.append(textbox_record)
        table_index += 1
    return _ensure_structure(_sort_docx_records_by_visual_layout(records), "DOCX")


def _docx_paragraph_text(paragraph: ElementTree.Element) -> str:
    values: list[str] = []

    def collect(node: ElementTree.Element) -> None:
        for child in _docx_effective_children(node):
            if child.tag in _WORD_IGNORED_TEXT_CONTAINERS:
                continue
            if child.tag == _WORD_TEXTBOX_CONTENT or child.tag == _WORD_PARAGRAPH:
                # A drawing host paragraph must not aggregate all nested textbox
                # paragraphs into one giant block.  Textboxes are emitted separately.
                continue
            if child.tag == f"{{{_WORD_NS}}}t":
                values.append(child.text or "")
            elif child.tag == f"{{{_WORD_NS}}}tab":
                values.append("\t")
            elif child.tag in {f"{{{_WORD_NS}}}br", f"{{{_WORD_NS}}}cr"}:
                values.append(" ")
            else:
                collect(child)

    collect(paragraph)
    return re.sub(r"\s+", " ", "".join(values)).strip()


def _docx_effective_children(element: ElementTree.Element) -> list[ElementTree.Element]:
    """Return one renderable branch for OOXML AlternateContent containers."""
    if element.tag != _MC_ALTERNATE_CONTENT:
        return list(element)
    choices = [child for child in list(element) if child.tag == _MC_CHOICE]
    fallback = next((child for child in list(element) if child.tag == _MC_FALLBACK), None)
    choice = next(
        (
            candidate
            for candidate in choices
            if any(
                node.tag == f"{{{_WORD_NS}}}t" and str(node.text or "").strip()
                for node in candidate.iter()
            )
        ),
        None,
    )
    if choice is not None:
        selected = choice
    elif fallback is not None:
        selected = fallback
    else:
        selected = choices[0] if choices else None
    return list(selected) if selected is not None else []


def _docx_textboxes(element: ElementTree.Element) -> list[dict[str, Any]]:
    """Collect textbox paragraphs together with honest, sortable layout metadata.

    Word stores floating textbox XML in anchor creation order, which can differ from
    the visual reading order.  When the OOXML anchor provides a vertical position we
    preserve it here instead of pretending that XML order represents the page.
    """
    textboxes: list[dict[str, Any]] = []

    def container_paragraphs(container: ElementTree.Element) -> list[ElementTree.Element]:
        paragraphs: list[ElementTree.Element] = []

        def collect(node: ElementTree.Element) -> None:
            for child in _docx_effective_children(node):
                if child.tag in _WORD_IGNORED_TEXT_CONTAINERS:
                    continue
                if child.tag == _WORD_PARAGRAPH:
                    paragraphs.append(child)
                    continue
                if child.tag == _WORD_TEXTBOX_CONTENT:
                    # Nested textboxes are collected independently by the outer walk.
                    continue
                collect(child)

        collect(container)
        return paragraphs

    def walk(node: ElementTree.Element, layout: dict[str, Any] | None = None) -> None:
        current_layout = _docx_textbox_layout(node) or layout
        for child in _docx_effective_children(node):
            if child.tag in _WORD_IGNORED_TEXT_CONTAINERS:
                continue
            if child.tag == _WORD_TEXTBOX_CONTENT:
                paragraphs = container_paragraphs(child)
                if paragraphs:
                    textboxes.append({"paragraphs": paragraphs, "layout": dict(current_layout or {})})
                continue
            walk(child, current_layout)

    walk(element)
    return textboxes


def _docx_textbox_layout(element: ElementTree.Element) -> dict[str, Any] | None:
    """Read one floating textbox's layout coordinate without inventing a page number."""
    if element.tag == _WORDPROCESSING_DRAWING_ANCHOR:
        horizontal = element.find(_WORDPROCESSING_DRAWING_POSITION_H)
        vertical = element.find(_WORDPROCESSING_DRAWING_POSITION_V)
        x_offset = _docx_layout_offset(horizontal)
        y_offset = _docx_layout_offset(vertical)
        if y_offset is None:
            return None
        return {
            "layoutY": y_offset,
            "layoutX": x_offset,
            "layoutCoordinateSpace": "docx_anchor",
            "layoutYRelativeTo": str(vertical.get("relativeFrom") or "") if vertical is not None else "",
            "layoutXRelativeTo": str(horizontal.get("relativeFrom") or "") if horizontal is not None else "",
            "layoutEngine": "docx-anchor",
        }
    if element.tag == _VML_SHAPE:
        offsets = _docx_vml_shape_offsets(str(element.get("style") or ""))
        if offsets[1] is None:
            return None
        return {
            "layoutY": offsets[1],
            "layoutX": offsets[0],
            "layoutCoordinateSpace": "docx_vml_shape",
            "layoutEngine": "docx-vml",
        }
    return None


def _docx_layout_offset(position: ElementTree.Element | None) -> int | None:
    if position is None:
        return None
    raw = str(position.findtext(_WORDPROCESSING_DRAWING_POS_OFFSET) or "").strip()
    try:
        return int(raw)
    except ValueError:
        return None


def _docx_vml_shape_offsets(style: str) -> tuple[float | None, float | None]:
    """Parse VML ``left/top`` or margin offsets when a legacy textbox has no anchor."""
    values: dict[str, float] = {}
    for key, raw_value, unit in re.findall(r"(?:^|;)(left|top|margin-left|margin-top)\s*:\s*(-?\d+(?:\.\d+)?)(pt)?", style, flags=re.IGNORECASE):
        value = float(raw_value)
        # Plain VML values are shape coordinates; points are converted only to make
        # the two VML axes comparable. They are never mixed with EMU anchor values.
        values[key.casefold()] = value * 12700 if unit else value
    return values.get("left", values.get("margin-left")), values.get("top", values.get("margin-top"))


def _sort_docx_records_by_visual_layout(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort a fully-positioned textbox group by its visual y/x coordinate.

    We only reorder a body element when *every* emitted record is a positioned
    textbox.  A mixed text/table body has no complete page geometry, so retaining its
    XML order is safer than fabricating a visual reading order.
    """
    grouped: dict[int, list[tuple[int, dict[str, Any]]]] = {}
    for source_index, record in enumerate(records):
        locator = record.get("locator") if isinstance(record.get("locator"), dict) else {}
        body_index = locator.get("bodyIndex")
        if isinstance(body_index, int):
            grouped.setdefault(body_index, []).append((source_index, record))

    sorted_groups: dict[int, list[dict[str, Any]]] = {}
    for body_index, group in grouped.items():
        positioned = all(
            isinstance((record.get("locator") or {}).get("layoutY"), (int, float))
            and (record.get("locator") or {}).get("textboxIndex") is not None
            for _, record in group
        )
        if not positioned:
            sorted_groups[body_index] = [record for _, record in group]
            continue
        sorted_groups[body_index] = [
            record
            for _, record in sorted(
                group,
                key=lambda item: (
                    float((item[1].get("locator") or {}).get("layoutY")),
                    float((item[1].get("locator") or {}).get("layoutX") or 0),
                    int((item[1].get("locator") or {}).get("textboxIndex") or 0),
                    int((item[1].get("locator") or {}).get("textboxParagraphIndex") or 0),
                    item[0],
                ),
            )
        ]

    output: list[dict[str, Any]] = []
    emitted_groups: set[int] = set()
    for record in records:
        locator = record.get("locator") if isinstance(record.get("locator"), dict) else {}
        body_index = locator.get("bodyIndex")
        if not isinstance(body_index, int):
            output.append(record)
            continue
        if body_index in emitted_groups:
            continue
        output.extend(sorted_groups[body_index])
        emitted_groups.add(body_index)
    for order, record in enumerate(output):
        record["order"] = order
    return output


def _docx_paragraph_kind(paragraph: ElementTree.Element) -> str:
    style_id, _ = _docx_paragraph_style(paragraph)
    if any(token in style_id.casefold() for token in ("heading", "title", "标题")):
        return "heading"
    properties = paragraph.find("w:pPr", _WORD)
    if properties is not None and properties.find("w:numPr", _WORD) is not None:
        return "bullet"
    return "paragraph"


def _docx_paragraph_style(paragraph: ElementTree.Element) -> tuple[str, int | None]:
    properties = paragraph.find("w:pPr", _WORD)
    if properties is None:
        return "", None
    style = properties.find("w:pStyle", _WORD)
    style_id = str(style.get(f"{{{_WORD_NS}}}val") or "") if style is not None else ""
    match = re.search(r"(?:heading|标题)\s*([1-9])", style_id, flags=re.IGNORECASE)
    return style_id, int(match.group(1)) if match else (1 if style_id.casefold() == "title" else None)


def _ensure_structure(records: list[dict[str, Any]], source_name: str) -> list[dict[str, Any]]:
    deduplicated: list[dict[str, Any]] = []
    previous_text = ""
    for record in records:
        text = re.sub(r"\s+", " ", str(record.get("text") or "")).strip()
        if not text:
            continue
        normalized = re.sub(r"\s+", "", text).casefold()
        if normalized == previous_text:
            # Keep source provenance for a repeated extraction fragment even though it
            # must not become a second preview paragraph or RAG evidence block.
            existing = deduplicated[-1]
            existing_ids = [str(value) for value in existing.get("sourceIds") or [existing.get("sourceId")] if str(value)]
            record_ids = [str(value) for value in record.get("sourceIds") or [record.get("sourceId")] if str(value)]
            for source_id in record_ids:
                if source_id not in existing_ids:
                    existing_ids.append(source_id)
            if existing_ids:
                existing["sourceIds"] = existing_ids
                existing["duplicateSourceIds"] = existing_ids[1:]
            continue
        source_ids = [str(value) for value in record.get("sourceIds") or [record.get("sourceId")] if str(value)]
        deduplicated.append({**record, "text": text, "sourceIds": list(dict.fromkeys(source_ids))})
        previous_text = normalized
    if not deduplicated:
        raise DocumentParseError(f"未从{source_name}提取到有效结构化文本")
    return deduplicated


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
