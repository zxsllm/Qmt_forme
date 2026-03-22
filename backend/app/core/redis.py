"""Redis connection pool — backed by Memurai on Windows."""

from __future__ import annotations

import os
import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

pool = redis.ConnectionPool.from_url(REDIS_URL, decode_responses=True)

redis_client: redis.Redis = redis.Redis(connection_pool=pool)


def get_redis() -> redis.Redis:
    """Dependency-injection helper for FastAPI / general usage."""
    return redis_client
