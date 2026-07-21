from __future__ import annotations

import json

from backend.resume_optimization.service import ResumeOptimizationService


class FakeDb:
    def __init__(self): self.tasks = {}; self.turns = []
    def create_agent_resume_task(self, **kwargs): self.tasks[kwargs["task_id"]] = {**kwargs, "status": "PENDING", "optimized_resume_md": ""}
    def update_agent_resume_task_status(self, task_id, _user_id, status, **kwargs): self.tasks[task_id].update(status=status, **kwargs)
    def get_agent_resume_task(self, _user_id, task_id): return self.tasks.get(task_id)
    def add_agent_resume_turn(self, **kwargs): self.turns.append(kwargs); return str(len(self.turns))


def test_start_persists_queued_session_without_running_model(monkeypatch):
    db = FakeDb()
    queued = []
    service = ResumeOptimizationService(
        db,
        resume_provider=lambda _user, _resume: {"file": {"name": "resume.txt"}, "blocks": [{"id": "b1", "text": "Python 开发", "locator": {}, "sectionName": "项目经历"}]},
        project_provider=lambda *_args: [],
        enqueue_run=lambda session_id, user_id: queued.append((session_id, user_id)),
    )
    result = service.start(user_id="u1", resume_id="r1", jd_text="需要 Python", model_config_id="cfg", project_scope="none", project_ids=[])

    assert result["snapshot"]["status"] == "PENDING"
    assert queued == [(result["sessionId"], "u1")]
    saved = json.loads(db.tasks[result["sessionId"]]["optimized_resume_md"])
    assert saved["resumeId"] == "r1"
