from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from backend.docx_boundary_check import DocxBoundaryCheckConfig, check_page_images
from backend.main import create_app
from config import Config
from database import Database
from service import CareerPathAIService


def _config(tmp_path: Path) -> DocxBoundaryCheckConfig:
    return DocxBoundaryCheckConfig(
        region_ratio=0.20,
        edge_band_ratio=0.08,
        dark_pixel_threshold=225,
        min_edge_dark_pixels=8,
        min_edge_dark_ratio=0.0005,
        horizontal_line_width_ratio=0.32,
        vertical_line_height_ratio=0.60,
        min_vertical_edge_lines=2,
        save_evidence=True,
        evidence_dir=str(tmp_path / "evidence"),
        llm_enabled=False,
    )


def _page(path: Path, draw_fn=None) -> str:
    image = Image.new("RGB", (400, 600), "white")
    draw = ImageDraw.Draw(image)
    if draw_fn:
        draw_fn(draw)
    image.save(path)
    return str(path)


def _text_line(draw: ImageDraw.ImageDraw, y: int, *, width: int = 96) -> None:
    draw.rectangle((80, y, 80 + width, y + 3), fill="black")


def _table(draw: ImageDraw.ImageDraw, *, top: int, bottom: int) -> None:
    for x in (50, 160, 270):
        draw.line((x, top, x, bottom), fill="black", width=2)
    for y in (top, (top + bottom) // 2, bottom):
        draw.line((50, y, 270, y), fill="black", width=2)


def test_docx_boundary_passes_normal_page_break(tmp_path):
    page_1 = _page(tmp_path / "page_1.png", lambda draw: _text_line(draw, 500))
    page_2 = _page(tmp_path / "page_2.png", lambda draw: _text_line(draw, 60))

    report = check_page_images([page_1, page_2], file_label="normal.docx", config=_config(tmp_path))

    assert report["status"] == "pass"
    assert report["results"][0]["status"] == "pass"
    assert all(Path(path).exists() for path in report["results"][0]["evidence"])


def test_docx_boundary_fails_when_tail_text_is_clipped(tmp_path):
    page_1 = _page(tmp_path / "page_1.png", lambda draw: _text_line(draw, 597))
    page_2 = _page(tmp_path / "page_2.png", lambda draw: _text_line(draw, 60))

    report = check_page_images([page_1, page_2], file_label="tail-clipped.docx", config=_config(tmp_path))

    assert report["status"] == "fail"
    assert report["results"][0]["status"] == "fail"
    assert "页尾文字" in report["results"][0]["reason"]


def test_docx_boundary_fails_when_head_text_is_clipped(tmp_path):
    page_1 = _page(tmp_path / "page_1.png", lambda draw: _text_line(draw, 500))
    page_2 = _page(tmp_path / "page_2.png", lambda draw: _text_line(draw, 0))

    report = check_page_images([page_1, page_2], file_label="head-clipped.docx", config=_config(tmp_path))

    assert report["status"] == "fail"
    assert report["results"][0]["status"] == "fail"
    assert "页首文字" in report["results"][0]["reason"]


def test_docx_boundary_warns_for_normal_table_continuation(tmp_path):
    page_1 = _page(tmp_path / "page_1.png", lambda draw: _table(draw, top=500, bottom=560))
    page_2 = _page(tmp_path / "page_2.png", lambda draw: _table(draw, top=40, bottom=100))

    report = check_page_images([page_1, page_2], file_label="table-continues.docx", config=_config(tmp_path))

    assert report["status"] == "warning"
    assert report["results"][0]["status"] == "warning"
    assert "表格跨页续接" in report["results"][0]["reason"]


def test_docx_boundary_fails_when_table_line_is_clipped(tmp_path):
    def draw_clipped_table(draw: ImageDraw.ImageDraw) -> None:
        _table(draw, top=530, bottom=598)
        draw.line((40, 599, 360, 599), fill="black", width=2)

    page_1 = _page(tmp_path / "page_1.png", draw_clipped_table)
    page_2 = _page(tmp_path / "page_2.png", lambda draw: _table(draw, top=40, bottom=100))

    report = check_page_images([page_1, page_2], file_label="table-clipped.docx", config=_config(tmp_path))

    assert report["status"] == "fail"
    assert report["results"][0]["status"] == "fail"
    assert "表格" in report["results"][0]["reason"]


def test_docx_boundary_uses_llm_judgment_as_primary(tmp_path):
    page_1 = _page(tmp_path / "page_1.png", lambda draw: _text_line(draw, 500))
    page_2 = _page(tmp_path / "page_2.png", lambda draw: _text_line(draw, 60))

    def fake_llm_judge(**kwargs):
        assert kwargs["rule_result"]["status"] == "pass"
        assert kwargs["bottom_features"]["edge"] == "bottom"
        assert kwargs["top_features"]["edge"] == "top"
        return {
            "status": "fail",
            "reason": "LLM judged top text clipped",
            "confidence": 0.91,
            "issues": [{"type": "clipped_text", "page": 2, "edge": "top", "message": "top crop is visually cut"}],
        }

    report = check_page_images(
        [page_1, page_2],
        file_label="llm-primary.docx",
        config=replace(_config(tmp_path), llm_enabled=True),
        llm_judge=fake_llm_judge,
    )

    result = report["results"][0]
    assert report["status"] == "fail"
    assert result["status"] == "fail"
    assert result["reason"] == "LLM judged top text clipped"
    assert result["metrics"]["judge_source"] == "llm"
    assert result["metrics"]["rule_result"]["status"] == "pass"
    assert result["metrics"]["llm_judgment"]["confidence"] == 0.91


def test_docx_boundary_api_accepts_docx_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))

    def fake_check_docx_file_boundaries(docx_path, **kwargs):
        assert Path(docx_path).exists()
        assert kwargs["file_label"] == "sample.docx"
        assert kwargs["config"].region_ratio == 0.15
        assert kwargs["config"].save_evidence is False
        assert kwargs["config"].llm_enabled is False
        return {
            "file": kwargs["file_label"],
            "page_count": 2,
            "status": "pass",
            "results": [],
            "task_id": kwargs["task_id"],
        }

    monkeypatch.setattr("backend.main.check_docx_file_boundaries", fake_check_docx_file_boundaries)
    service = object.__new__(CareerPathAIService)
    app = create_app(service=service, auth_db=Database(str(tmp_path / "auth.db")))
    client = TestClient(app)
    register_response = client.post(
        "/api/auth/register",
        json={"username": "docx@example.com", "password": "password123"},
    )
    token = register_response.json()["token"]

    response = client.post(
        "/api/documents/docx-boundary-check",
        headers={"Authorization": f"Bearer {token}"},
        files={
            "file": (
                "sample.docx",
                b"not-a-real-docx-because-rendering-is-mocked",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"save_evidence": "false", "region_ratio": "0.15", "use_llm": "false"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "pass"
