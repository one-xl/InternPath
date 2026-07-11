from backend.rq_worker import parse_queue_names
from config import Config


def test_rq_worker_default_queue_excludes_realtime_advisor(monkeypatch):
    monkeypatch.setattr(Config, "RQ_QUEUE_NAME", "internpath-default-test")
    monkeypatch.setattr(Config, "RQ_ADVISOR_QUEUE_NAME", "internpath-advisor-test")

    assert parse_queue_names("") == ["internpath-default-test"]


def test_rq_worker_explicit_queue_list_is_preserved(monkeypatch):
    monkeypatch.setattr(Config, "RQ_QUEUE_NAME", "internpath-default-test")
    monkeypatch.setattr(Config, "RQ_ADVISOR_QUEUE_NAME", "internpath-advisor-test")

    assert parse_queue_names("custom-high, custom-low, custom-high") == ["custom-high", "custom-low"]
