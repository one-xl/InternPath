from __future__ import annotations

import re
from typing import Any, Callable

from redis import Redis
from rq import Queue

from config import Config


_RQ_JOB_ID_PATTERN = re.compile(r"[^A-Za-z0-9_-]+")


def normalize_job_id(job_id: str | None) -> str | None:
    if job_id is None:
        return None
    normalized = _RQ_JOB_ID_PATTERN.sub("-", job_id).strip("-")
    return normalized or None


def get_redis_connection() -> Redis:
    if not Config.REDIS_URL:
        raise RuntimeError("REDIS_URL is required for InternPath background jobs.")
    redis = Redis.from_url(Config.REDIS_URL)
    redis.ping()
    return redis


def get_queue(queue_name: str | None = None) -> Queue:
    return Queue(
        (queue_name or Config.RQ_QUEUE_NAME).strip() or Config.RQ_QUEUE_NAME,
        connection=get_redis_connection(),
        default_timeout=Config.RQ_JOB_TIMEOUT_SECONDS,
    )


def enqueue_job(
    func: Callable[..., Any],
    *args: Any,
    job_id: str | None = None,
    queue_name: str | None = None,
    **kwargs: Any,
):
    queue = get_queue(queue_name)
    return queue.enqueue(
        func,
        *args,
        **kwargs,
        job_id=normalize_job_id(job_id),
        job_timeout=Config.RQ_JOB_TIMEOUT_SECONDS,
        result_ttl=Config.RQ_RESULT_TTL_SECONDS,
        failure_ttl=Config.RQ_RESULT_TTL_SECONDS,
    )
