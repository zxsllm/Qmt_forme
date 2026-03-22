"""Heartbeat monitor — modules publish heartbeats to Redis, monitor checks."""

from __future__ import annotations

import logging
import time

from app.core.redis import redis_client

logger = logging.getLogger(__name__)

HEARTBEAT_PREFIX = "heartbeat:"
HEARTBEAT_TTL = 120  # seconds before considered stale


def send_heartbeat(module: str) -> None:
    """Publish heartbeat for a module (feed, oms, risk, matcher)."""
    key = f"{HEARTBEAT_PREFIX}{module}"
    redis_client.set(key, str(time.time()), ex=HEARTBEAT_TTL)


def check_heartbeats(modules: list[str] | None = None) -> dict[str, dict]:
    """Check all module heartbeats, return status dict."""
    modules = modules or ["feed", "oms", "risk", "matcher"]
    now = time.time()
    result: dict[str, dict] = {}

    for mod in modules:
        key = f"{HEARTBEAT_PREFIX}{mod}"
        ts_raw = redis_client.get(key)
        if ts_raw is None:
            result[mod] = {"status": "missing", "last_seen": None, "age_s": None}
        else:
            ts = float(ts_raw)
            age = now - ts
            status = "ok" if age < HEARTBEAT_TTL else "stale"
            result[mod] = {"status": status, "last_seen": ts, "age_s": round(age, 1)}

    return result
