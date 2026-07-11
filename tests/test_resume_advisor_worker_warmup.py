from __future__ import annotations

from backend import jobs
from backend.resume_advisor import session_module
from config import Config


class _Cursor:
    def __init__(self):
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query, params):
        self.calls.append((query, params))


class _Connection:
    def __init__(self):
        self.cursor_instance = _Cursor()
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


class _Database:
    def __init__(self):
        self.connection = _Connection()

    def get_connection(self):
        return self.connection


def test_worker_marks_run_running_before_loading_the_resume_advisor(monkeypatch):
    order: list[str] = []

    class Module:
        def run_session(self, **_kwargs):
            order.append("run")

    monkeypatch.setattr(jobs, "_mark_resume_advisor_run_started", lambda **_kwargs: order.append("started"))
    monkeypatch.setattr(jobs, "_get_resume_advisor_module", lambda: order.append("module") or Module())

    jobs.run_resume_advisor_session_job(run_id="run-1", user_id="user-1", session_id="session-1")

    assert order == ["started", "module", "run"]


def test_worker_start_marker_uses_the_existing_started_at_value(monkeypatch):
    database = _Database()
    monkeypatch.setattr(jobs, "Database", lambda: database)

    jobs._mark_resume_advisor_run_started(run_id="run-1", user_id="user-1")

    query, params = database.connection.cursor_instance.calls[0]
    assert "started_at = COALESCE(started_at" in query
    assert params[1:] == ("run-1", "user-1")
    assert database.connection.committed is True
    assert database.connection.closed is True


def test_advisor_model_client_is_reused_until_the_configured_ttl_expires(monkeypatch):
    calls: list[str] = []
    client = object()
    monkeypatch.setattr(session_module, "_ADVISOR_MODEL_CACHE", {})
    monkeypatch.setattr(Config, "ADVISOR_MODEL_CLIENT_TTL_SECONDS", 900)
    monkeypatch.setattr(
        session_module,
        "_resolve_advisor_model_uncached",
        lambda user_id: calls.append(str(user_id)) or (client, "gpt-test"),
    )

    first = session_module.resolve_advisor_model("user-1")
    second = session_module.resolve_advisor_model("user-1")

    assert first == second == (client, "gpt-test")
    assert calls == ["user-1"]
