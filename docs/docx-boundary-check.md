# DOCX Page-Boundary Visual Check

This feature renders a DOCX document and checks adjacent page boundaries for obvious visual format issues:

- clipped text at the bottom of the current page
- clipped text at the top of the next page
- table borders, cells, or content truncated at the page boundary
- normal table continuation across pages, usually reported as `warning`

The checker does not inspect DOCX XML for pagination. It uses the rendered visual output. The primary judgment is made by a multimodal LLM from cropped evidence images and rule metrics; deterministic image rules are kept as evidence and fallback.

## Runtime Dependencies

Python packages:

- `pdf2image`
- `Pillow`
- `docx2pdf` fallback on Windows

System tools:

- LibreOffice headless: `soffice` or `libreoffice`
- Poppler: `pdftoppm`, required by `pdf2image`

## API

Authenticated users can upload a DOCX directly:

```http
POST /api/documents/docx-boundary-check
Content-Type: multipart/form-data

file=@example.docx
save_evidence=true
region_ratio=0.12
edge_band_ratio=0.04
use_llm=true
llm_required=false
```

Response:

```json
{
  "file": "example.docx",
  "page_count": 12,
  "status": "fail",
  "results": [
    {
      "page_pair": [3, 4],
      "status": "fail",
      "reason": "第 3 页底部表格疑似被截断",
      "evidence": [
        "C:/.../page_3_bottom.png",
        "C:/.../page_4_top.png"
      ],
      "metrics": {
        "judge_source": "llm",
        "rule_result": {"status": "warning"},
        "llm_judgment": {"confidence": 0.91}
      }
    }
  ]
}
```

`status` is one of `pass`, `warning`, or `fail`.

## CLI

Default: render, crop, save evidence, and ask the multimodal LLM to judge.

```powershell
.\.venv\Scripts\python.exe -m backend.docx_boundary_cli .\example.docx --output-dir .\outputs --json-output .\outputs\report.json
```

Offline rule fallback only:

```powershell
.\.venv\Scripts\python.exe -m backend.docx_boundary_cli .\example.docx --no-llm
```

Require the LLM judgment to succeed:

```powershell
.\.venv\Scripts\python.exe -m backend.docx_boundary_cli .\example.docx --llm-required
```

The command exits with code `0` for `pass` or `warning`, and `2` for `fail`.

## Configuration

Environment variables:

- `DOCX_BOUNDARY_REGION_RATIO`: bottom/top crop ratio, default `0.12`
- `DOCX_BOUNDARY_EDGE_BAND_RATIO`: edge band inside each crop, default `0.04`
- `DOCX_BOUNDARY_DARK_PIXEL_THRESHOLD`: grayscale threshold for ink pixels, default `225`
- `DOCX_BOUNDARY_MIN_EDGE_DARK_PIXELS`: minimum dark pixels at the physical edge, default `12`
- `DOCX_BOUNDARY_MIN_EDGE_DARK_RATIO`: minimum edge ink ratio, default `0.0007`
- `DOCX_BOUNDARY_HORIZONTAL_LINE_WIDTH_RATIO`: long horizontal line threshold, default `0.32`
- `DOCX_BOUNDARY_VERTICAL_LINE_HEIGHT_RATIO`: vertical line threshold, default `0.65`
- `DOCX_BOUNDARY_MIN_VERTICAL_EDGE_LINES`: table-like vertical edge lines, default `2`
- `DOCX_BOUNDARY_SAVE_EVIDENCE`: save cropped evidence images, default `true`
- `DOCX_BOUNDARY_EVIDENCE_DIR`: optional fixed evidence output directory
- `DOCX_BOUNDARY_LLM_ENABLED`: use multimodal LLM as primary judge, default `true`
- `DOCX_BOUNDARY_LLM_REQUIRED`: fail instead of falling back to rules when LLM is unavailable, default `false`
- `DOCX_BOUNDARY_LLM_MODEL`: multimodal model, default `gemini-1.5-flash`
- `DOCX_BOUNDARY_LLM_BASE_URL`: optional OpenAI-compatible base URL; default uses `GEMINI_BASE_URL + /openai`
- `DOCX_BOUNDARY_LLM_API_KEY`: optional dedicated key; falls back to `GEMINI_API_KEY`
- `DOCX_BOUNDARY_LLM_TEMPERATURE`: default `0`
- `DOCX_BOUNDARY_LLM_TIMEOUT`: default `120`

## Known Limits

The final page-pair judgment is model-based, with deterministic image rules as fallback. The checker still does not inspect DOCX XML and does not use the PDF text layer. If no LLM API key is configured and `DOCX_BOUNDARY_LLM_REQUIRED=false`, the report falls back to rule judgment with `metrics.judge_source="rule_fallback"`.
