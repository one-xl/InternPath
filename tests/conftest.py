import asyncio
import warnings
from uuid import uuid4

import pytest
from redis import Redis
from redis.exceptions import RedisError
from rq import Queue

from config import Config


@pytest.fixture(autouse=True)
def ensure_event_loop():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("event loop is closed")
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
    yield


@pytest.fixture(autouse=True)
def isolate_rq_queue(monkeypatch):
    queue_name = f"internpath-test-{uuid4().hex}"
    monkeypatch.setattr(Config, "RQ_QUEUE_NAME", queue_name)
    yield
    if not Config.REDIS_URL:
        return
    try:
        redis = Redis.from_url(Config.REDIS_URL)
        Queue(queue_name, connection=redis).empty()
    except RedisError:
        return
