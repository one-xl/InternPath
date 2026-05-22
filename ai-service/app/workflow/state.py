from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowState:
    request: Any
    data: dict[str, Any] = field(default_factory=dict)
    workflow_logs: list[dict[str, Any]] = field(default_factory=list)
    failed: bool = False
    error: str | None = None

