from __future__ import annotations

from typing import Any


def make_workflow_log(
    *,
    node_name: str,
    status: str,
    duration_ms: int,
    input_summary: str,
    output_summary: str,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "nodeName": node_name,
        "status": status,
        "durationMs": duration_ms,
        "inputSummary": input_summary,
        "outputSummary": output_summary,
        "error": error,
    }

