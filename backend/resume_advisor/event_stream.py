from __future__ import annotations

import logging
import threading
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from config import Config


_LOGGER = logging.getLogger(__name__)
_STREAM_PREFIX = "internpath:resume-advisor:events:"
_client_lock = threading.Lock()
_client: Redis | None = None
_client_url = ""


def stream_key(session_id: str) -> str:
    return f"{_STREAM_PREFIX}{session_id}"


def _redis_client() -> Redis | None:
    global _client, _client_url
    redis_url = Config.REDIS_URL.strip()
    if not redis_url:
        return None
    with _client_lock:
        if _client is None or _client_url != redis_url:
            _client = Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=Config.ADVISOR_EVENT_STREAM_CONNECT_TIMEOUT_SECONDS,
                socket_timeout=Config.ADVISOR_EVENT_STREAM_READ_TIMEOUT_SECONDS,
            )
            _client_url = redis_url
        return _client


def publish_event_notification(*, session_id: str, sequence: int) -> None:
    """Wake SSE readers after the corresponding event has committed to PostgreSQL."""
    client = _redis_client()
    if client is None:
        return
    try:
        client.xadd(
            stream_key(session_id),
            {"sequence": str(max(0, int(sequence)))},
            maxlen=Config.ADVISOR_EVENT_STREAM_MAXLEN,
            approximate=True,
        )
    except RedisError:
        # PostgreSQL remains the source of truth; polling is a safe fallback.
        _LOGGER.debug("Unable to publish Resume Advisor event notification", exc_info=True)


def current_stream_cursor(*, session_id: str) -> str | None:
    client = _redis_client()
    if client is None:
        return None
    try:
        entries = client.xrevrange(stream_key(session_id), max="+", min="-", count=1)
    except RedisError:
        _LOGGER.debug("Unable to read Resume Advisor event stream cursor", exc_info=True)
        return None
    if not entries:
        # 0-0 avoids losing the first notification created between cursor setup and XREAD.
        return "0-0"
    entry_id = entries[0][0]
    return entry_id.decode("utf-8") if isinstance(entry_id, bytes) else str(entry_id)


def wait_for_event_notification(*, session_id: str, cursor: str, block_ms: int) -> str:
    client = _redis_client()
    if client is None:
        return cursor
    try:
        results: list[Any] = client.xread(
            {stream_key(session_id): cursor or "0-0"},
            count=1,
            block=max(1, int(block_ms)),
        )
    except RedisError:
        _LOGGER.debug("Unable to wait on Resume Advisor event stream", exc_info=True)
        return cursor
    if not results or not results[0][1]:
        return cursor
    entry_id = results[0][1][-1][0]
    return entry_id.decode("utf-8") if isinstance(entry_id, bytes) else str(entry_id)
