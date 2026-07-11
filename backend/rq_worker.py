from __future__ import annotations

import argparse
import os

from redis import Redis
from rq import SimpleWorker, Worker

from config import Config


def parse_queue_names(raw_value: str | None) -> list[str]:
    names = [item.strip() for item in str(raw_value or "").split(",") if item.strip()]
    if names:
        return list(dict.fromkeys(names))
    return [Config.RQ_QUEUE_NAME]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run an InternPath RQ worker.")
    parser.add_argument(
        "--queues",
        default=os.getenv("RQ_WORKER_QUEUES", ""),
        help="Comma-separated queue names. Defaults to RQ_QUEUE_NAME.",
    )
    parser.add_argument("--name", default=os.getenv("RQ_WORKER_NAME", ""), help="Optional unique RQ worker name.")
    args = parser.parse_args(argv)
    if not Config.REDIS_URL:
        raise RuntimeError("REDIS_URL is required to start the InternPath RQ worker.")
    redis = Redis.from_url(Config.REDIS_URL)
    redis.ping()
    queue_names = parse_queue_names(args.queues)
    if Config.RQ_ADVISOR_QUEUE_NAME in queue_names:
        from backend.jobs import warm_resume_advisor_worker

        warm_resume_advisor_worker()
    worker_class = SimpleWorker if os.name == "nt" else Worker
    worker = worker_class(queue_names, connection=redis, name=args.name.strip() or None)
    worker.work()


if __name__ == "__main__":
    main()
