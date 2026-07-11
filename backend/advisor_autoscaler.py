from __future__ import annotations

import argparse
import math
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any, Callable
from uuid import uuid4

from redis import Redis
from rq import Queue, Worker

from config import Config


@dataclass
class ManagedWorker:
    name: str
    process: Any


class AdvisorWorkerAutoscaler:
    """Scale dedicated Advisor workers from Redis queue depth without touching default work."""

    def __init__(
        self,
        redis: Redis,
        *,
        queue_name: str,
        min_workers: int,
        max_workers: int,
        jobs_per_worker: int,
        process_factory: Callable[[list[str]], Any] | None = None,
        worker_is_idle: Callable[[str], bool] | None = None,
    ):
        self.redis = redis
        self.queue = Queue(queue_name, connection=redis)
        self.queue_name = queue_name
        self.min_workers = max(0, int(min_workers))
        self.max_workers = max(self.min_workers, int(max_workers))
        self.jobs_per_worker = max(1, int(jobs_per_worker))
        self._process_factory = process_factory or self._start_worker_process
        self._worker_is_idle = worker_is_idle or self._is_worker_idle
        self._workers: list[ManagedWorker] = []

    def desired_worker_count(self, queue_depth: int) -> int:
        if queue_depth <= 0:
            return self.min_workers
        demand = math.ceil(queue_depth / self.jobs_per_worker)
        return min(self.max_workers, max(self.min_workers, demand))

    def run_once(self) -> int:
        self._workers = [worker for worker in self._workers if worker.process.poll() is None]
        desired = self.desired_worker_count(len(self.queue))
        while len(self._workers) < desired:
            self._workers.append(self._spawn_worker())
        while len(self._workers) > desired:
            idle_index = next(
                (index for index in range(len(self._workers) - 1, -1, -1) if self._worker_is_idle(self._workers[index].name)),
                None,
            )
            if idle_index is None:
                break
            worker = self._workers.pop(idle_index)
            worker.process.terminate()
        return len(self._workers)

    def stop(self) -> None:
        for worker in self._workers:
            if worker.process.poll() is None:
                worker.process.terminate()
        deadline = time.monotonic() + 10
        for worker in self._workers:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                worker.process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                worker.process.kill()
        self._workers.clear()

    def _spawn_worker(self) -> ManagedWorker:
        name = f"internpath-advisor-{uuid4().hex[:12]}"
        command = [
            sys.executable,
            "-m",
            "backend.rq_worker",
            "--queues",
            self.queue_name,
            "--name",
            name,
        ]
        return ManagedWorker(name=name, process=self._process_factory(command))

    @staticmethod
    def _start_worker_process(command: list[str]) -> subprocess.Popen[Any]:
        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        return subprocess.Popen(
            command,
            cwd=str(Path(__file__).resolve().parents[1]),
            creationflags=creation_flags,
        )

    def _is_worker_idle(self, worker_name: str) -> bool:
        try:
            worker = Worker.find_by_key(worker_name, connection=self.redis)
            return worker.get_state() == "idle" if worker is not None else False
        except Exception:
            return False


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Autoscale InternPath Resume Advisor RQ workers.")
    parser.add_argument("--queue", default=Config.RQ_ADVISOR_QUEUE_NAME)
    parser.add_argument("--poll-seconds", type=float, default=Config.ADVISOR_AUTOSCALE_POLL_SECONDS)
    args = parser.parse_args(argv)
    if not Config.REDIS_URL:
        raise RuntimeError("REDIS_URL is required to autoscale InternPath Resume Advisor workers.")

    redis = Redis.from_url(Config.REDIS_URL)
    redis.ping()
    scaler = AdvisorWorkerAutoscaler(
        redis,
        queue_name=str(args.queue).strip() or Config.RQ_ADVISOR_QUEUE_NAME,
        min_workers=Config.ADVISOR_AUTOSCALE_MIN_WORKERS,
        max_workers=Config.ADVISOR_AUTOSCALE_MAX_WORKERS,
        jobs_per_worker=Config.ADVISOR_AUTOSCALE_JOBS_PER_WORKER,
    )
    stop_requested = Event()

    def request_stop(_signum: int, _frame: Any) -> None:
        stop_requested.set()

    if os.name != "nt":
        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
    try:
        while not stop_requested.is_set():
            scaler.run_once()
            stop_requested.wait(max(0.1, float(args.poll_seconds)))
    finally:
        scaler.stop()


if __name__ == "__main__":
    main()
