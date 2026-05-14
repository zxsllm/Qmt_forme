"""Market Feed — polls Tushare realtime data and publishes to Redis.

Designed to run as an async background task during trading hours.
Non-trading hours: falls back to latest DB snapshot for demo purposes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from app.core.redis import redis_client
from app.shared.interfaces.models import BarData

logger = logging.getLogger(__name__)

REDIS_CHANNEL = "market:bars"
REDIS_LATEST_KEY_PREFIX = "market:latest:"
FEED_INTERVAL_SECONDS = 60

# Pattern1/2 走 1min batch channel — 与老的 rt_k 单 bar channel 分开，避免
# 老策略（MA/OvernightGap）每秒收到 1min batch 也跑一遍。strategy_runner 双订阅。
MINUTE_BARS_CHANNEL = "market:minute_bars"


class MarketFeed:
    """Polls data source and publishes BarData to Redis pub/sub + cache."""

    def __init__(self):
        self._running = False
        self._subscribers: set[str] = set()

    async def publish_bar(self, bar: BarData) -> None:
        """Publish a single bar to Redis channel and cache latest."""
        payload = bar.model_dump(mode="json")
        payload["timestamp"] = bar.timestamp.isoformat()
        msg = json.dumps(payload)

        redis_client.publish(REDIS_CHANNEL, msg)
        redis_client.set(
            f"{REDIS_LATEST_KEY_PREFIX}{bar.ts_code}",
            msg,
            ex=300,
        )

    async def publish_batch(self, bars: list[BarData]) -> None:
        """Publish multiple bars efficiently via pipeline."""
        if not bars:
            return

        pipe = redis_client.pipeline()
        for bar in bars:
            payload = bar.model_dump(mode="json")
            payload["timestamp"] = bar.timestamp.isoformat()
            msg = json.dumps(payload)
            pipe.publish(REDIS_CHANNEL, msg)
            pipe.set(f"{REDIS_LATEST_KEY_PREFIX}{bar.ts_code}", msg, ex=300)
        pipe.execute()
        logger.debug("published %d bars to Redis", len(bars))

    async def publish_minute_batch(
        self,
        bars: list[BarData],
        *,
        is_open_preview: bool = False,
    ) -> None:
        """Publish 1min bars batch to MINUTE_BARS_CHANNEL (Pattern1/2 channel).

        Single Redis message — strategy_runner 一次性 dispatch 给 batch-mode 策略，
        避免 5400 只票每分钟 5400 次 publish + 5400 次 on_bar 调用。

        is_open_preview: 09:30 那根 K 线的早发标记（Pattern 内部按分钟幂等）。
        """
        if not bars:
            return
        payload = {
            "minute": bars[0].timestamp.isoformat(),
            "is_open_preview": is_open_preview,
            "bars": [
                {**b.model_dump(mode="json"),
                 "timestamp": b.timestamp.isoformat()}
                for b in bars
            ],
        }
        redis_client.publish(MINUTE_BARS_CHANNEL, json.dumps(payload))
        logger.info(
            "published 1min batch: %d bars @ %s%s",
            len(bars), bars[0].timestamp.strftime("%H:%M"),
            " [open-preview]" if is_open_preview else "",
        )

    def get_latest(self, ts_code: str) -> BarData | None:
        """Get cached latest bar from Redis."""
        raw = redis_client.get(f"{REDIS_LATEST_KEY_PREFIX}{ts_code}")
        if raw is None:
            return None
        data = json.loads(raw)
        return BarData(**data)

    async def start_polling(
        self,
        ts_codes: list[str],
        fetch_fn,
        interval: int = FEED_INTERVAL_SECONDS,
    ) -> None:
        """Background loop: call fetch_fn periodically and publish results.

        fetch_fn(ts_codes) -> list[BarData]
        """
        self._running = True
        logger.info("market feed started for %d codes, interval=%ds",
                     len(ts_codes), interval)

        while self._running:
            try:
                bars = await fetch_fn(ts_codes)
                if bars:
                    await self.publish_batch(bars)
            except Exception:
                logger.exception("market feed poll error")

            await asyncio.sleep(interval)

    def stop(self) -> None:
        self._running = False
        logger.info("market feed stopped")


market_feed = MarketFeed()
