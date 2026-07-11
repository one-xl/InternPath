from __future__ import annotations

from backend.resume_advisor import event_stream
from config import Config


class _RedisStream:
    def __init__(self):
        self.entries: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.xadd_calls: list[tuple[str, dict[str, str], int, bool]] = []

    def xadd(self, key, fields, maxlen, approximate):
        entry_id = f"{len(self.entries.get(key, [])) + 1}-0"
        self.entries.setdefault(key, []).append((entry_id, dict(fields)))
        self.xadd_calls.append((key, dict(fields), maxlen, approximate))
        return entry_id

    def xrevrange(self, key, max, min, count):
        return list(reversed(self.entries.get(key, [])))[:count]

    def xread(self, streams, count, block):
        key, cursor = next(iter(streams.items()))
        entries = [entry for entry in self.entries.get(key, []) if entry[0] > cursor]
        return [(key, entries[:count])] if entries else []


def test_redis_stream_notifications_only_publish_event_sequence(monkeypatch):
    redis = _RedisStream()
    monkeypatch.setattr(Config, "REDIS_URL", "redis://stream-test")
    monkeypatch.setattr(event_stream, "_client", redis)
    monkeypatch.setattr(event_stream, "_client_url", Config.REDIS_URL)

    event_stream.publish_event_notification(session_id="session-1", sequence=7)

    key = event_stream.stream_key("session-1")
    assert redis.xadd_calls == [(key, {"sequence": "7"}, Config.ADVISOR_EVENT_STREAM_MAXLEN, True)]
    assert event_stream.current_stream_cursor(session_id="session-1") == "1-0"
    assert event_stream.wait_for_event_notification(session_id="session-1", cursor="0-0", block_ms=10) == "1-0"


def test_empty_redis_stream_uses_zero_cursor_to_avoid_first_event_race(monkeypatch):
    redis = _RedisStream()
    monkeypatch.setattr(Config, "REDIS_URL", "redis://stream-test")
    monkeypatch.setattr(event_stream, "_client", redis)
    monkeypatch.setattr(event_stream, "_client_url", Config.REDIS_URL)

    assert event_stream.current_stream_cursor(session_id="session-empty") == "0-0"
