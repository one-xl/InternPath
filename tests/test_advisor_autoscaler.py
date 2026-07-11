from __future__ import annotations

from backend.advisor_autoscaler import AdvisorWorkerAutoscaler


class _Queue:
    def __init__(self, _name, connection):
        self.connection = connection
        self.depth = 0

    def __len__(self):
        return self.depth


class _Process:
    def __init__(self):
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        self.terminated = True


def test_advisor_autoscaler_only_spawns_dedicated_workers_and_scales_idle_capacity(monkeypatch):
    monkeypatch.setattr("backend.advisor_autoscaler.Queue", _Queue)
    commands: list[list[str]] = []
    processes: list[_Process] = []

    def process_factory(command):
        commands.append(command)
        process = _Process()
        processes.append(process)
        return process

    scaler = AdvisorWorkerAutoscaler(
        object(),
        queue_name="internpath-advisor-test",
        min_workers=1,
        max_workers=3,
        jobs_per_worker=2,
        process_factory=process_factory,
        worker_is_idle=lambda _name: True,
    )
    scaler.queue.depth = 5

    assert scaler.run_once() == 3
    assert len(commands) == 3
    assert all(command[command.index("--queues") + 1] == "internpath-advisor-test" for command in commands)
    assert all("internpath-default" not in command for command in commands)

    scaler.queue.depth = 0
    assert scaler.run_once() == 1
    assert sum(process.terminated for process in processes) == 2


def test_advisor_autoscaler_respects_minimum_and_maximum_worker_limits(monkeypatch):
    monkeypatch.setattr("backend.advisor_autoscaler.Queue", _Queue)
    scaler = AdvisorWorkerAutoscaler(
        object(),
        queue_name="internpath-advisor-test",
        min_workers=1,
        max_workers=3,
        jobs_per_worker=2,
        process_factory=lambda _command: _Process(),
        worker_is_idle=lambda _name: True,
    )

    assert scaler.desired_worker_count(0) == 1
    assert scaler.desired_worker_count(1) == 1
    assert scaler.desired_worker_count(5) == 3
    assert scaler.desired_worker_count(99) == 3
