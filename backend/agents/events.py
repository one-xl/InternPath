from __future__ import annotations

import json
from datetime import datetime
from typing import Any


MAX_AGENT_LOG_ITEMS = 500


def parse_agent_log_items(raw_logs: Any) -> list[dict[str, Any]]:
    if isinstance(raw_logs, list):
        return [item for item in raw_logs if isinstance(item, dict)]
    if not raw_logs:
        return []
    try:
        parsed = json.loads(raw_logs) if isinstance(raw_logs, str) else raw_logs
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def build_agent_log(
    message: str,
    *,
    log_type: str = "info",
    detail: Any = None,
    trace_id: str = "",
    task_id: str = "",
    stage: str = "bootstrap",
    agent: str = "InternPath",
    status: str = "running",
    cache_namespace: str = "",
    cache_hit: bool | None = None,
    duration_ms: int | None = None,
    model_id: str = "",
    provider_cache: dict[str, Any] | None = None,
    retry_count: int = 0,
    error_type: str = "",
    sequence: int | None = None,
) -> dict[str, Any]:
    provider_cache_data = provider_cache if isinstance(provider_cache, dict) else {}
    log_item = {
        "timestamp": datetime.now().isoformat(),
        "type": log_type,
        "message": message,
        "detail": detail,
        "traceId": trace_id or task_id,
        "stage": stage,
        "agent": agent,
        "status": status,
        "cacheNamespace": cache_namespace,
        "cacheHit": cache_hit,
        "durationMs": duration_ms,
        "modelId": model_id,
        "providerCacheAvailable": bool(provider_cache_data.get("providerCacheAvailable")),
        "providerCacheHit": provider_cache_data.get("providerCacheHit"),
        "providerCachedTokens": int(provider_cache_data.get("providerCachedTokens") or 0),
        "providerCacheMissTokens": int(provider_cache_data.get("providerCacheMissTokens") or 0),
        "providerInputTokens": int(provider_cache_data.get("providerInputTokens") or 0),
        "providerEndpointMode": str(provider_cache_data.get("providerEndpointMode") or ""),
        "providerStream": provider_cache_data.get("providerStream"),
        "providerPromptCacheKey": str(provider_cache_data.get("providerPromptCacheKey") or ""),
        "providerPromptCacheRetention": str(provider_cache_data.get("providerPromptCacheRetention") or ""),
        "providerPromptCacheDisabledReason": str(provider_cache_data.get("providerPromptCacheDisabledReason") or ""),
        "retryCount": int(retry_count or 0),
        "errorType": error_type,
    }
    if sequence is not None:
        log_item["sequence"] = int(sequence)
    return log_item


def append_agent_log_json(raw_logs: Any, log_item: dict[str, Any]) -> str:
    logs = parse_agent_log_items(raw_logs)
    logs.append(log_item)
    for index, item in enumerate(logs, start=1):
        item.setdefault("sequence", index)
    return json.dumps(logs[-MAX_AGENT_LOG_ITEMS:], ensure_ascii=False)
