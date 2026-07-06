from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.docx_boundary_check import DocxBoundaryCheckConfig, check_docx_file_boundaries


def main() -> int:
    parser = argparse.ArgumentParser(description="Check rendered DOCX page-boundary format issues.")
    parser.add_argument("docx_path", help="Path to the DOCX file to check.")
    parser.add_argument("--output-dir", help="Directory for evidence screenshots.")
    parser.add_argument("--json-output", help="Optional path to write the JSON report.")
    parser.add_argument("--region-ratio", type=float, help="Top/bottom crop ratio, default from Config.")
    parser.add_argument("--edge-band-ratio", type=float, help="Edge band ratio inside each crop, default from Config.")
    parser.add_argument("--dark-threshold", type=int, help="Grayscale threshold for dark ink pixels.")
    parser.add_argument("--no-evidence", action="store_true", help="Do not save evidence screenshots.")
    parser.add_argument("--no-llm", action="store_true", help="Skip multimodal LLM judgment and use rule fallback.")
    parser.add_argument("--llm-required", action="store_true", help="Fail if multimodal LLM judgment is unavailable.")
    parser.add_argument("--llm-model", help="Override DOCX boundary multimodal model.")
    args = parser.parse_args()

    config = DocxBoundaryCheckConfig.from_app_config()
    config = DocxBoundaryCheckConfig(
        region_ratio=args.region_ratio if args.region_ratio is not None else config.region_ratio,
        edge_band_ratio=args.edge_band_ratio if args.edge_band_ratio is not None else config.edge_band_ratio,
        dark_pixel_threshold=args.dark_threshold if args.dark_threshold is not None else config.dark_pixel_threshold,
        min_edge_dark_pixels=config.min_edge_dark_pixels,
        min_edge_dark_ratio=config.min_edge_dark_ratio,
        horizontal_line_width_ratio=config.horizontal_line_width_ratio,
        vertical_line_height_ratio=config.vertical_line_height_ratio,
        min_vertical_edge_lines=config.min_vertical_edge_lines,
        save_evidence=not args.no_evidence,
        evidence_dir=args.output_dir or config.evidence_dir,
        llm_enabled=not args.no_llm,
        llm_required=args.llm_required or config.llm_required,
        llm_model=args.llm_model or config.llm_model,
        llm_base_url=config.llm_base_url,
        llm_temperature=config.llm_temperature,
        llm_timeout=config.llm_timeout,
    ).normalized()

    docx_path = Path(args.docx_path)
    report = check_docx_file_boundaries(
        docx_path,
        user_id="cli",
        task_id=f"docx-boundary-cli-{docx_path.stem}",
        config=config,
        file_label=docx_path.name,
    )
    output = json.dumps(report, ensure_ascii=False, indent=2)
    print(output)

    if args.json_output:
        output_path = Path(args.json_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output + "\n", encoding="utf-8")

    return 0 if report["status"] in {"pass", "warning"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
