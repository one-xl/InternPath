from __future__ import annotations

import json

from backend.resume_advisor.repository import ResumeAdvisorRepository


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _query, _params):
        return None

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return _Cursor(self.rows)

    def close(self):
        return None


class _Database:
    def __init__(self, rows):
        self.rows = rows

    def get_connection(self):
        return _Connection(self.rows)


def test_slo_dashboard_calculates_p95_and_exposes_threshold_breaches():
    rows = [
        (json.dumps({"queueMs": 90, "providerFirstTokenMs": 7_000, "endToEndFirstTokenMs": 8_500}), "COMPLETED", None),
        (json.dumps({"queueMs": 1_100, "providerFirstTokenMs": 7_500, "endToEndFirstTokenMs": 9_000}), "CANCELLED", None),
        (json.dumps({"queueMs": 1_200, "providerFirstTokenMs": 7_900, "endToEndFirstTokenMs": 10_000}), "FAILED", "tool_timeout"),
    ]
    repository = ResumeAdvisorRepository(_Database(rows))

    dashboard = repository.get_slo_dashboard(user_id="user-1", window_hours=24)

    assert dashboard["runCount"] == 3
    assert dashboard["metrics"]["queueMs"] == {"count": 3, "p95Ms": 1_200, "thresholdMs": 1_000, "met": False}
    assert dashboard["metrics"]["providerFirstTokenMs"]["met"] is True
    assert dashboard["metrics"]["endToEndFirstTokenMs"]["met"] is False
    assert {alert["code"] for alert in dashboard["alerts"]} == {
        "queueMs_p95_breach",
        "endToEndFirstTokenMs_p95_breach",
    }
    assert dashboard["health"] == {"cancelledRuns": 1, "failedRuns": 1, "toolTimeoutRuns": 1}
