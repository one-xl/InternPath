from backend.resume_advisor.preview import enrich_blocks_with_original_locations, preview_metadata


def test_pdf_blocks_receive_high_confidence_only_when_original_text_location_matches(monkeypatch):
    monkeypatch.setattr(
        "backend.resume_advisor.preview.extract_pdf_text_locations",
        lambda _data: [{"text": "负责 FastAPI 接口开发", "pageNumber": 2, "bbox": [12.0, 20.0, 100.0, 32.0]}],
    )
    blocks = [{"id": "block-1", "text": "负责 FastAPI 接口开发", "locator": {"sourceFormat": "pdf"}, "locatorConfidence": "approximate"}]

    enriched = enrich_blocks_with_original_locations(blocks, file_name="resume.pdf", file_bytes=b"pdf")

    assert enriched[0]["locatorConfidence"] == "high"
    assert enriched[0]["locator"]["pageNumber"] == 2
    assert enriched[0]["locator"]["bbox"] == [12.0, 20.0, 100.0, 32.0]
    assert blocks[0]["locatorConfidence"] == "approximate"


def test_docx_preview_metadata_never_claims_pdf_coordinates():
    metadata = preview_metadata({"file": {"name": "resume.docx", "b64_content": "dGVzdA=="}})

    assert metadata["inlinePreviewAvailable"] is False
    assert "不会伪造页码或坐标" in metadata["locationNotice"]


def test_pdf_structured_bbox_is_not_replaced_by_fuzzy_text_location(monkeypatch):
    monkeypatch.setattr(
        "backend.resume_advisor.preview.extract_pdf_text_locations",
        lambda _data: [{"text": "Built API", "pageNumber": 9, "bbox": [1.0, 2.0, 3.0, 4.0]}],
    )
    blocks = [{
        "id": "block-1",
        "text": "Built API",
        "locator": {"sourceFormat": "pdf", "pageNumber": 2, "bbox": [72.0, 650.0, 140.0, 665.0]},
        "locatorConfidence": "high",
    }]

    enriched = enrich_blocks_with_original_locations(blocks, file_name="resume.pdf", file_bytes=b"pdf")

    assert enriched[0]["locator"]["pageNumber"] == 2
    assert enriched[0]["locator"]["bbox"] == [72.0, 650.0, 140.0, 665.0]
