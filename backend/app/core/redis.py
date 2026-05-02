"""Redis connection pool — backed by Memurai on Windows."""

from __future__ import annotations

import os
import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# 短超时 + 主动降级：Redis (Memurai) 没起或抽风时，调用方会立刻拿到
# ConnectionError，由各自的 try/except 兜底，避免接口卡住默认 ~12s。
pool = redis.ConnectionPool.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=0.5,
    socket_timeout=0.5,
)

redis_client: redis.Redis = redis.Redis(connection_pool=pool)


def get_redis() -> redis.Redis:
    """Dependency-injection helper for FastAPI / general usage."""
    return redis_client
