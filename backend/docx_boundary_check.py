from __future__ import annotations

import base64
import io
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from backend.agents.tools.layout_tools import render_docx_to_images


BoundaryEdge = Literal["top", "bottom"]
PairStatus = Literal["pass", "warning", "fail"]
LlmJudge = Callable[..., dict[str, Any] | None]


@dataclass(frozen=True)
class DocxBoundaryCheckConfig:
    region_ratio: float = 0.12
    edge_band_ratio: float = 0.04
    dark_pixel_threshold: int = 225
    min_edge_dark_pixels: int = 12
    min_edge_dark_ratio: float = 0.0007
    horizontal_line_width_ratio: float = 0.32
    vertical_line_height_ratio: float = 0.65
    min_vertical_edge_lines: int = 2
    save_evidence: bool = True
    evidence_dir: str | None = None
    llm_enabled: bool = True
    llm_required: bool = False
    llm_model: str = "gemini-1.5-flash"
    llm_base_url: str | None = None
    llm_temperature: float = 0.0
    llm_timeout: float = 120.0

    @classmethod
    def from_app_config(cls) -> "DocxBoundaryCheckConfig":
        from config import Config

        return cls(
            region_ratio=Config.DOCX_BOUNDARY_REGION_RATIO,
            edge_band_ratio=Config.DOCX_BOUNDARY_EDGE_BAND_RATIO,
            dark_pixel_threshold=Config.DOCX_BOUNDARY_DARK_PIXEL_THRESHOLD,
            min_edge_dark_pixels=Config.DOCX_BOUNDARY_MIN_EDGE_DARK_PIXELS,
            min_edge_dark_ratio=Config.DOCX_BOUNDARY_MIN_EDGE_DARK_RATIO,
            horizontal_line_width_ratio=Config.DOCX_BOUNDARY_HORIZONTAL_LINE_WIDTH_RATIO,
            vertical_line_height_ratio=Config.DOCX_BOUNDARY_VERTICAL_LINE_HEIGHT_RATIO,
            min_vertical_edge_lines=Config.DOCX_BOUNDARY_MIN_VERTICAL_EDGE_LINES,
            save_evidence=Config.DOCX_BOUNDARY_SAVE_EVIDENCE,
            evidence_dir=Config.DOCX_BOUNDARY_EVIDENCE_DIR or None,
            llm_enabled=Config.DOCX_BOUNDARY_LLM_ENABLED,
            llm_required=Config.DOCX_BOUNDARY_LLM_REQUIRED,
            llm_model=Config.DOCX_BOUNDARY_LLM_MODEL,
            llm_base_url=Config.DOCX_BOUNDARY_LLM_BASE_URL or None,
            llm_temperature=Config.DOCX_BOUNDARY_LLM_TEMPERATURE,
            llm_timeout=Config.DOCX_BOUNDARY_LLM_TIMEOUT,
        ).normalized()

    def normalized(self) -> "DocxBoundaryCheckConfig":
        return replace(
            self,
            region_ratio=_clamp_float(self.region_ratio, 0.05, 0.30),
            edge_band_ratio=_clamp_float(self.edge_band_ratio, 0.01, 0.25),
            dark_pixel_threshold=int(_clamp_float(float(self.dark_pixel_threshold), 1, 254)),
            min_edge_dark_pixels=max(1, int(self.min_edge_dark_pixels)),
            min_edge_dark_ratio=_clamp_float(self.min_edge_dark_ratio, 0.0, 0.20),
            horizontal_line_width_ratio=_clamp_float(self.horizontal_line_width_ratio, 0.05, 0.95),
            vertical_line_height_ratio=_clamp_float(self.vertical_line_height_ratio, 0.05, 0.95),
            min_vertical_edge_lines=max(1, int(self.min_vertical_edge_lines)),
            llm_model=(self.llm_model or "gemini-1.5-flash").strip(),
            llm_base_url=(self.llm_base_url or "").strip() or None,
            llm_temperature=_clamp_float(self.llm_temperature, 0.0, 1.0),
            llm_timeout=_clamp_float(self.llm_timeout, 10.0, 600.0),
        )


def check_docx_file_boundaries(
    docx_path: str | Path,
    *,
    user_id: Any = "docx-boundary",
    task_id: str | None = None,
    config: DocxBoundaryCheckConfig | None = None,
    file_label: str | None = None,
) -> dict[str, Any]:
    path = Path(docx_path)
    if not path.exists():
        raise FileNotFoundError(f"DOCX 文件不存在: {path}")
    if path.suffix.lower() != ".docx":
        raise ValueError("仅支持 DOCX 文件")

    task_id = task_id or f"docx-boundary-{uuid4().hex}"
    runtime_config = _with_default_evidence_dir(
        (config or DocxBoundaryCheckConfig.from_app_config()).normalized(),
        user_id=user_id,
        task_id=task_id,
    )
    page_image_paths = render_docx_to_images(user_id, task_id, str(path))
    report = check_page_images(
        page_image_paths,
        file_label=file_label or path.name,
        config=runtime_config,
    )
    report["task_id"] = task_id
    return report


def check_page_images(
    page_image_paths: list[str | Path],
    *,
    file_label: str,
    config: DocxBoundaryCheckConfig | None = None,
    llm_judge: LlmJudge | None = None,
) -> dict[str, Any]:
    runtime_config = (config or DocxBoundaryCheckConfig.from_app_config()).normalized()
    pages = [Path(path) for path in page_image_paths]
    page_count = len(pages)
    results: list[dict[str, Any]] = []

    if page_count < 2:
        return {
            "file": file_label,
            "page_count": page_count,
            "status": "pass",
            "results": [],
            "metrics": {"config": _config_metrics(runtime_config)},
        }

    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("DOCX 页边界检测需要安装 Pillow") from exc

    for index in range(page_count - 1):
        with Image.open(pages[index]) as current_page, Image.open(pages[index + 1]) as next_page:
            bottom_region = _crop_region(current_page, "bottom", runtime_config)
            top_region = _crop_region(next_page, "top", runtime_config)

        bottom_features = analyze_region(bottom_region, edge="bottom", config=runtime_config)
        top_features = analyze_region(top_region, edge="top", config=runtime_config)
        evidence = _save_evidence(
            bottom_region,
            top_region,
            page_number=index + 1,
            config=runtime_config,
        )
        rule_result = _classify_pair(
            page_number=index + 1,
            bottom_features=bottom_features,
            top_features=top_features,
            evidence=evidence,
            config=runtime_config,
        )
        results.append(
            _apply_llm_judgment(
                rule_result=rule_result,
                page_number=index + 1,
                bottom_region=bottom_region,
                top_region=top_region,
                bottom_features=bottom_features,
                top_features=top_features,
                evidence=evidence,
                config=runtime_config,
                llm_judge=llm_judge,
            )
        )

    overall_status: PairStatus = "pass"
    if any(result["status"] == "fail" for result in results):
        overall_status = "fail"
    elif any(result["status"] == "warning" for result in results):
        overall_status = "warning"

    return {
        "file": file_label,
        "page_count": page_count,
        "status": overall_status,
        "results": results,
        "metrics": {"config": _config_metrics(runtime_config)},
    }


def analyze_region(
    image: Any,
    *,
    edge: BoundaryEdge,
    config: DocxBoundaryCheckConfig | None = None,
) -> dict[str, Any]:
    runtime_config = (config or DocxBoundaryCheckConfig.from_app_config()).normalized()
    try:
        from PIL import ImageOps
    except ImportError as exc:
        raise RuntimeError("DOCX 页边界检测需要安装 Pillow") from exc

    gray = ImageOps.grayscale(image)
    width, height = gray.size
    pixels = gray.load()
    row_counts = [0 for _ in range(height)]
    col_counts = [0 for _ in range(width)]
    min_x = width
    min_y = height
    max_x = -1
    max_y = -1

    for y in range(height):
        row_dark = 0
        for x in range(width):
            if pixels[x, y] <= runtime_config.dark_pixel_threshold:
                row_dark += 1
                col_counts[x] += 1
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
        row_counts[y] = row_dark

    edge_band_px = max(2, int(round(height * runtime_config.edge_band_ratio)))
    if edge == "bottom":
        edge_rows = range(max(0, height - edge_band_px), height)
        distance_to_edge = None if max_y < 0 else height - 1 - max_y
    else:
        edge_rows = range(0, min(height, edge_band_px))
        distance_to_edge = None if min_y == height else min_y

    edge_row_indexes = list(edge_rows)
    edge_dark_pixels = sum(row_counts[y] for y in edge_row_indexes)
    edge_area = max(1, len(edge_row_indexes) * width)
    edge_dark_ratio = edge_dark_pixels / edge_area
    edge_has_ink = (
        edge_dark_pixels >= runtime_config.min_edge_dark_pixels
        and edge_dark_ratio >= runtime_config.min_edge_dark_ratio
    )

    horizontal_line_threshold = max(1, int(width * runtime_config.horizontal_line_width_ratio))
    vertical_line_threshold = max(1, int(len(edge_row_indexes) * runtime_config.vertical_line_height_ratio))
    horizontal_edge_rows = [y for y in edge_row_indexes if row_counts[y] >= horizontal_line_threshold]
    edge_col_counts = [
        sum(1 for y in edge_row_indexes if pixels[x, y] <= runtime_config.dark_pixel_threshold)
        for x in range(width)
    ]
    vertical_edge_line_count = _count_runs(
        x for x, count in enumerate(edge_col_counts) if count >= vertical_line_threshold
    )

    horizontal_rows = [y for y, count in enumerate(row_counts) if count >= horizontal_line_threshold]
    vertical_line_count = _count_runs(
        x for x, count in enumerate(col_counts) if count >= max(1, int(height * runtime_config.vertical_line_height_ratio))
    )
    table_presence = len(horizontal_rows) >= 2 or vertical_line_count >= 2
    table_clipped = bool(horizontal_edge_rows) or vertical_edge_line_count >= runtime_config.min_vertical_edge_lines
    text_clipped = edge_has_ink and not table_clipped
    near_edge_margin = max(edge_band_px * 2, 4)
    near_edge_content = (
        distance_to_edge is not None
        and not edge_has_ink
        and distance_to_edge <= near_edge_margin
    )

    bbox = None
    if max_x >= 0:
        bbox = [min_x, min_y, max_x, max_y]

    return {
        "edge": edge,
        "width": width,
        "height": height,
        "edge_band_px": edge_band_px,
        "edge_dark_pixels": edge_dark_pixels,
        "edge_dark_ratio": round(edge_dark_ratio, 6),
        "dark_bbox": bbox,
        "distance_to_edge_px": distance_to_edge,
        "horizontal_edge_rows": len(horizontal_edge_rows),
        "vertical_edge_lines": vertical_edge_line_count,
        "table_presence": table_presence,
        "table_clipped": table_clipped,
        "text_clipped": text_clipped,
        "near_edge_content": near_edge_content,
    }


def _classify_pair(
    *,
    page_number: int,
    bottom_features: dict[str, Any],
    top_features: dict[str, Any],
    evidence: list[str],
    config: DocxBoundaryCheckConfig,
) -> dict[str, Any]:
    reasons: list[str] = []
    status_value: PairStatus = "pass"

    if bottom_features["table_clipped"]:
        reasons.append(f"第 {page_number} 页底部表格疑似被截断")
    if top_features["table_clipped"]:
        reasons.append(f"第 {page_number + 1} 页顶部表格疑似被截断")
    if bottom_features["text_clipped"]:
        reasons.append(f"第 {page_number} 页页尾文字疑似显示不全")
    if top_features["text_clipped"]:
        reasons.append(f"第 {page_number + 1} 页页首文字疑似显示不全")

    if reasons:
        status_value = "fail"
    elif bottom_features["table_presence"] and top_features["table_presence"]:
        status_value = "warning"
        reasons.append(f"第 {page_number} 页到第 {page_number + 1} 页存在表格跨页续接迹象，未发现明显裁切")
    elif bottom_features["near_edge_content"] or top_features["near_edge_content"]:
        status_value = "warning"
        reasons.append(f"第 {page_number} 页到第 {page_number + 1} 页内容靠近页边界，建议人工复核")
    else:
        reasons.append("未发现明显页边界裁切")

    return {
        "page_pair": [page_number, page_number + 1],
        "status": status_value,
        "reason": "；".join(reasons),
        "evidence": evidence,
        "metrics": {
            "bottom": bottom_features,
            "top": top_features,
            "thresholds": _config_metrics(config),
        },
    }


def _apply_llm_judgment(
    *,
    rule_result: dict[str, Any],
    page_number: int,
    bottom_region: Any,
    top_region: Any,
    bottom_features: dict[str, Any],
    top_features: dict[str, Any],
    evidence: list[str],
    config: DocxBoundaryCheckConfig,
    llm_judge: LlmJudge | None,
) -> dict[str, Any]:
    if not config.llm_enabled:
        return _with_rule_judge_source(rule_result, source="rule_disabled")

    judge = llm_judge or _default_llm_judge
    try:
        raw_judgment = judge(
            page_number=page_number,
            bottom_region=bottom_region,
            top_region=top_region,
            bottom_features=bottom_features,
            top_features=top_features,
            rule_result=rule_result,
            evidence=evidence,
            config=config,
        )
    except Exception as exc:  # noqa: BLE001
        if config.llm_required:
            raise RuntimeError(f"DOCX 页边界大模型判断失败: {exc}") from exc
        return _with_rule_judge_source(rule_result, source="rule_fallback", llm_error=str(exc))

    if not raw_judgment:
        if config.llm_required:
            raise RuntimeError("DOCX 页边界大模型判断未返回有效结果")
        return _with_rule_judge_source(rule_result, source="rule_fallback", llm_error="llm_judge_empty")

    llm_judgment = _normalize_llm_judgment(raw_judgment)
    result = dict(rule_result)
    result["status"] = llm_judgment["status"]
    result["reason"] = llm_judgment["reason"]
    metrics = dict(result.get("metrics") or {})
    metrics["judge_source"] = "llm"
    metrics["rule_result"] = {
        "status": rule_result.get("status"),
        "reason": rule_result.get("reason"),
    }
    metrics["llm_judgment"] = llm_judgment
    result["metrics"] = metrics
    return result


def _default_llm_judge(
    *,
    page_number: int,
    bottom_region: Any,
    top_region: Any,
    bottom_features: dict[str, Any],
    top_features: dict[str, Any],
    rule_result: dict[str, Any],
    evidence: list[str],
    config: DocxBoundaryCheckConfig,
) -> dict[str, Any] | None:
    from config import Config

    api_key = (Config.DOCX_BOUNDARY_LLM_API_KEY or Config.GEMINI_API_KEY or "").strip()
    if not api_key:
        if config.llm_required:
            raise RuntimeError("未配置 DOCX_BOUNDARY_LLM_API_KEY 或 GEMINI_API_KEY")
        return None

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("DOCX 页边界大模型判断需要安装 openai") from exc

    client = OpenAI(
        api_key=api_key,
        base_url=_resolve_llm_base_url(config),
        timeout=config.llm_timeout,
    )
    payload = {
        "page_pair": [page_number, page_number + 1],
        "task": "判断 DOCX 最终渲染后相邻页面边界是否存在明显格式错误。",
        "image_order": [
            f"第 {page_number} 页底部裁剪区域",
            f"第 {page_number + 1} 页顶部裁剪区域",
        ],
        "rule_result": {
            "status": rule_result.get("status"),
            "reason": rule_result.get("reason"),
        },
        "features": {
            "bottom": bottom_features,
            "top": top_features,
        },
        "evidence": evidence,
    }
    user_text = (
        "请只根据两张裁剪图和辅助指标判断页边界格式是否正确。"
        "第一张图是当前页最底部，第二张图是下一页最顶部。"
        "重点识别半行文字、顶部/底部文字裁切、表格线/单元格/内容被截断、上下页明显断裂。"
        "如果是正常跨页续接，返回 warning 或 pass；如果不确定但需要人工复核，返回 warning。"
        "请严格返回 JSON，不要 markdown："
        "{\"status\":\"pass|warning|fail\",\"reason\":\"中文原因\","
        "\"confidence\":0.0,\"issues\":[{\"type\":\"clipped_text|clipped_table|normal_continuation|uncertain\","
        "\"page\":1,\"edge\":\"top|bottom|both\",\"message\":\"说明\"}]}\n\n"
        f"辅助数据：{json.dumps(payload, ensure_ascii=False)}"
    )
    response = client.chat.completions.create(
        model=config.llm_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是资深文档排版质检专家。你的职责是审阅 DOCX 渲染截图，"
                    "判断相邻页面页尾和页首是否存在视觉裁切、表格断裂或异常跨页。"
                    "必须输出可解析 JSON。"
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": _image_data_url(bottom_region)}},
                    {"type": "image_url", "image_url": {"url": _image_data_url(top_region)}},
                ],
            },
        ],
        temperature=config.llm_temperature,
    )
    raw_text = response.choices[0].message.content or ""
    return _parse_llm_json(raw_text)


def _with_rule_judge_source(
    rule_result: dict[str, Any],
    *,
    source: str,
    llm_error: str | None = None,
) -> dict[str, Any]:
    result = dict(rule_result)
    metrics = dict(result.get("metrics") or {})
    metrics["judge_source"] = source
    if llm_error:
        metrics["llm_error"] = llm_error
    result["metrics"] = metrics
    return result


def _normalize_llm_judgment(raw_judgment: dict[str, Any]) -> dict[str, Any]:
    status_value = str(raw_judgment.get("status") or "").strip().lower()
    if status_value not in {"pass", "warning", "fail"}:
        raise ValueError(f"大模型返回了无效 status: {status_value}")

    reason = str(raw_judgment.get("reason") or "").strip()
    if not reason:
        reason = "大模型未给出具体原因"

    raw_confidence = raw_judgment.get("confidence", 0.0)
    try:
        confidence = _clamp_float(float(raw_confidence), 0.0, 1.0)
    except (TypeError, ValueError):
        confidence = 0.0

    raw_issues = raw_judgment.get("issues")
    issues = raw_issues if isinstance(raw_issues, list) else []
    normalized_issues = [issue for issue in issues if isinstance(issue, dict)]

    return {
        "status": status_value,
        "reason": reason,
        "confidence": confidence,
        "issues": normalized_issues,
    }


def _parse_llm_json(raw_text: str) -> dict[str, Any]:
    try:
        from backend.agents.schemas import extract_json_object

        payload = extract_json_object(raw_text)
    except Exception:
        clean = raw_text.strip()
        if clean.startswith("```") or clean.endswith("```"):
            lines = clean.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines.pop(0)
            if lines and lines[-1].strip().endswith("```"):
                lines.pop()
            clean = "\n".join(lines).strip()
        payload = json.loads(clean)

    if not isinstance(payload, dict):
        raise ValueError("大模型返回 JSON 不是对象")
    return payload


def _image_data_url(image: Any) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def _resolve_llm_base_url(config: DocxBoundaryCheckConfig) -> str:
    if config.llm_base_url:
        return config.llm_base_url.rstrip("/")

    from config import Config

    base_url = (Config.GEMINI_BASE_URL or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    if base_url.endswith("/openai"):
        return base_url
    return f"{base_url}/openai"


def _crop_region(image: Any, edge: BoundaryEdge, config: DocxBoundaryCheckConfig) -> Any:
    width, height = image.size
    crop_height = max(1, int(round(height * config.region_ratio)))
    if edge == "bottom":
        return image.crop((0, height - crop_height, width, height)).copy()
    return image.crop((0, 0, width, crop_height)).copy()


def _save_evidence(bottom_region: Any, top_region: Any, *, page_number: int, config: DocxBoundaryCheckConfig) -> list[str]:
    if not config.save_evidence:
        return []

    evidence_dir = Path(config.evidence_dir or ".").resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    bottom_path = evidence_dir / f"page_{page_number}_bottom.png"
    top_path = evidence_dir / f"page_{page_number + 1}_top.png"
    bottom_region.save(bottom_path, "PNG")
    top_region.save(top_path, "PNG")
    return [str(bottom_path), str(top_path)]


def _with_default_evidence_dir(
    config: DocxBoundaryCheckConfig,
    *,
    user_id: Any,
    task_id: str,
) -> DocxBoundaryCheckConfig:
    if not config.save_evidence or config.evidence_dir:
        return config

    from config import Config

    evidence_dir = Path(Config.USER_DB_DIR) / "workspaces" / f"user_{user_id}" / f"task_{task_id}" / "docx_boundary_evidence"
    return replace(config, evidence_dir=str(evidence_dir))


def _config_metrics(config: DocxBoundaryCheckConfig) -> dict[str, Any]:
    return asdict(config)


def _count_runs(indexes: Any) -> int:
    count = 0
    previous: int | None = None
    for raw_index in indexes:
        index = int(raw_index)
        if previous is None or index > previous + 1:
            count += 1
        previous = index
    return count


def _clamp_float(value: float, lower: float, upper: float) -> float:
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value
