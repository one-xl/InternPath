from __future__ import annotations

import os

from redis import Redis
from rq import SimpleWorker, Worker

from config import Config


def main() -> None:
    if not Config.REDIS_URL:
        raise RuntimeError("REDIS_URL is required to start the InternPath RQ worker.")
    redis = Redis.from_url(Config.REDIS_URL)
    redis.ping()
    worker_class = SimpleWorker if os.name == "nt" else Worker
    worker = worker_class([Config.RQ_QUEUE_NAME], connection=redis)
    worker.work()


if __name__ == "__main__":
    main()
