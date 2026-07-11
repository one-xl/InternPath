from document_parser import extract_pdf_structure
from backend.resume_rag import parse_resume


def _pdf(pages: list[list[tuple[int, int, str, int]]]) -> bytes:
    """Build a tiny text PDF without adding a test-only dependency."""
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    page_ids: list[int] = []
    next_id = 4
    for items in pages:
        page_id, content_id = next_id, next_id + 1
        next_id += 2
        page_ids.append(page_id)

        def escape(value: str) -> str:
            return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

        stream = b"\n".join(
            f"BT /F1 {size} Tf 1 0 0 1 {x} {y} Tm ({escape(text)}) Tj ET".encode("latin-1")
            for x, y, text, size in items
        )
        objects[content_id] = b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)
        objects[page_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content_id
        )
    objects[2] = b"<< /Type /Pages /Kids [ %s ] /Count %d >>" % (
        b" ".join(f"{page_id} 0 R".encode() for page_id in page_ids),
        len(page_ids),
    )

    maximum_id = max(objects)
    output = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = [0] * (maximum_id + 1)
    for object_id in range(1, maximum_id + 1):
        offsets[object_id] = len(output)
        output += f"{object_id} 0 obj\n".encode() + objects[object_id] + b"\nendobj\n"
    xref = len(output)
    output += f"xref\n0 {maximum_id + 1}\n0000000000 65535 f \n".encode()
    output += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    output += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (maximum_id + 1, xref)
    return output


def test_pdf_structure_keeps_real_bbox_and_generates_one_markdown_chunk_path():
    data = _pdf([[(72, 700, "Project Experience", 14), (72, 675, "Built FastAPI API", 11)]])

    records = extract_pdf_structure(data)
    parsed = parse_resume("resume.pdf", "application/pdf", data)

    assert [record["text"] for record in records] == ["Project Experience", "Built FastAPI API"]
    assert all(record["locator"]["sourceFormat"] == "pdf" for record in records)
    assert all(record["locator"]["pageNumber"] == 1 for record in records)
    assert all(len(record["locator"]["bbox"]) == 4 for record in records)
    assert all(record["locator"]["coordinateSpace"] == "pdf_user_space_bottom_left" for record in records)
    assert "## Project Experience" in parsed["structuredMarkdown"]
    assert all(chunk["sourceBlockIds"] for chunk in parsed["chunks"])
    target = next(block for block in parsed["blocks"] if block["text"] == "Built FastAPI API")
    assert target["locator"]["bbox"]


def test_pdf_repeated_page_header_and_body_are_canonicalized_before_preview_and_rag():
    data = _pdf([
        [(72, 740, "Candidate Name", 16), (72, 700, "Project Experience", 14), (72, 675, "Built FastAPI API", 11)],
        [(72, 740, "Candidate Name", 16), (72, 700, "Project Experience", 14), (72, 675, "Built FastAPI API", 11)],
    ])

    parsed = parse_resume("resume.pdf", "application/pdf", data)
    blocks = parsed["blocks"]
    chunk_content = "\n".join(chunk["content"] for chunk in parsed["chunks"])

    assert sum(block["text"] == "Candidate Name" for block in blocks) == 1
    assert sum(block["text"] == "Built FastAPI API" for block in blocks) == 1
    assert chunk_content.count("Built FastAPI API") == 1


def test_pdf_two_columns_stay_as_independent_blocks_and_never_form_cross_column_chunk():
    data = _pdf([[
        (72, 700, "Left A", 11),
        (340, 700, "Right A", 11),
        (72, 680, "Left B", 11),
        (340, 680, "Right B", 11),
    ]])

    records = extract_pdf_structure(data)
    parsed = parse_resume("resume.pdf", "application/pdf", data)
    contents = [chunk["content"] for chunk in parsed["chunks"]]

    assert [record["text"] for record in records] == ["Left A", "Left B", "Right A", "Right B"]
    assert not any("Left A\nRight A" in content or "Left B\nRight B" in content for content in contents)
