from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import task_queue
from backend.resume_advisor.router import build_resume_advisor_router
from backend.resume_advisor.session_module import ResumeAdvisorModule


class _RunRepository:
    def __init__(self):
        self.cancel_calls: list[dict[str, str]] = []

    def cancel_run(self, **kwargs):
        self.cancel_calls.append(kwargs)
        return {"id": kwargs["run_id"], "status": "CANCELLED", "alreadyCancelled": False}

    @staticmethod
    def get_run(**_kwargs):
        return {"rqJobId": "rq-advisor-42"}


def test_cancelling_an_advisor_run_forwards_its_rq_job_id_after_persisting_state():
    repository = _RunRepository()
    requested_job_ids: list[str] = []
    module = ResumeAdvisorModule(
        db=None,
        repository=repository,
        cancel_enqueued_run=lambda job_id: requested_job_ids.append(job_id) or True,
    )

    result = module.cancel_run(user_id="u1", session_id="advisor-1", run_id="run-1")

    assert repository.cancel_calls == [{"user_id": "u1", "session_id": "advisor-1", "run_id": "run-1"}]
    assert requested_job_ids == ["rq-advisor-42"]
    assert result["rqCancellationRequested"] is True


def test_cancel_api_returns_conflict_for_a_terminal_run():
    class Module:
        def __init__(self):
            self.cancelled = False

        def cancel_run(self, **_kwargs):
            if self.cancelled:
                raise ValueError("该运行已经取消，不能重复取消。")
            self.cancelled = True
            return {"id": "run-1", "status": "CANCELLED"}

    app = FastAPI()
    app.include_router(build_resume_advisor_router(Module(), lambda: "u1"))
    client = TestClient(app)

    assert client.post("/api/agent/resume/sessions/advisor-1/runs/run-1/cancel").status_code == 200
    assert client.post("/api/agent/resume/sessions/advisor-1/runs/run-1/cancel").status_code == 409


def test_rq_cancellation_sends_both_queue_cancel_and_stop_command(monkeypatch):
    calls: list[tuple[str, object]] = []
    connection = object()

    class Job:
        @staticmethod
        def fetch(job_id, *, connection):
            calls.append(("fetch", (job_id, connection)))
            return Job()

        def cancel(self):
            calls.append(("cancel", None))

    monkeypatch.setattr(task_queue, "get_redis_connection", lambda: connection)
    monkeypatch.setattr(task_queue, "Job", Job)
    monkeypatch.setattr(task_queue, "send_stop_job_command", lambda conn, job_id: calls.append(("stop", (conn, job_id))))

    assert task_queue.cancel_job("rq-advisor-42") is True
    assert calls == [
        ("fetch", ("rq-advisor-42", connection)),
        ("cancel", None),
        ("stop", (connection, "rq-advisor-42")),
    ]
