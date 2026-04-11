"""Intraday monitor engine — index anomaly detection + sector attribution.

Hooks into scheduler's rt_k tick (~1.2s). Maintains a sliding window of
index & sector snapshots. When index moves beyond threshold in any window,
fires an anomaly event with sector-level attribution.

Anomaly events are persisted to Redis so they survive process restarts.
"""

from __future__ import annotations

import json
import logging
import time as _time
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

INDEX_CODES = [
    "000001.SH", "399001.SZ", "399006.SZ",
    "000300.SH", "000905.SH", "000688.SH",
]
INDEX_NAMES = {
    "000001.SH": "上证指数", "399001.SZ": "深证成指", "399006.SZ": "创业板指",
    "000300.SH": "沪深300", "000905.SH": "中证500", "000688.SH": "科创50",
}

WINDOWS = [
    {"label": "1min", "seconds": 60, "threshold": 0.3},
    {"label": "5min", "seconds": 300, "threshold": 0.5},
    {"label": "15min", "seconds": 900, "threshold": 1.0},
]

MAX_HISTORY = 1200  # ~20 min at 1 tick/sec

REDIS_KEY = "monitor:anomalies"


def _redis():
    """Lazy import to avoid circular import at module load."""
    from app.core.redis import redis_client
    return redis_client


@dataclass
class TickRecord:
    ts: float
    indices: dict[str, float]            # code -> close price
    sector_pcts: dict[str, float]        # industry_name -> avg daily pct_chg


@dataclass
class AnomalyEvent:
    ts: float
    index_code: str
    index_name: str
    window: str
    delta_pct: float
    price_now: float
    price_then: float
    top_sectors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "time": _time.strftime("%H:%M:%S", _time.localtime(self.ts)),
            "index_code": self.index_code,
            "index_name": self.index_name,
            "window": self.window,
            "delta_pct": self.delta_pct,
            "price_now": self.price_now,
            "price_then": self.price_then,
            "top_sectors": self.top_sectors,
        }


class MonitorEngine:

    def __init__(self):
        self._history: deque[TickRecord] = deque(maxlen=MAX_HISTORY)
        self._cooldowns: dict[str, float] = {}  # "code:window" -> last fire ts
        self._today: str = ""

    def _new_day_check(self) -> None:
        """Clear in-memory state and Redis anomalies on day change."""
        from datetime import date
        today = date.today().isoformat()
        if today != self._today:
            self._history.clear()
            self._cooldowns.clear()
            self._today = today
            try:
                _redis().delete(REDIS_KEY)
            except Exception:
                logger.warning("failed to clear Redis anomalies on day change", exc_info=True)

    def _persist_anomaly(self, event: AnomalyEvent) -> None:
        """Append anomaly to Redis list with EOD expiry."""
        try:
            r = _redis()
            r.rpush(REDIS_KEY, json.dumps(event.to_dict(), ensure_ascii=False))
            r.expire(REDIS_KEY, 18 * 3600)  # auto-expire after 18h
        except Exception:
            logger.warning("failed to persist anomaly to Redis", exc_info=True)

    def _load_anomalies_from_redis(self) -> list[dict]:
        """Load all anomalies from Redis."""
        try:
            raw_list = _redis().lrange(REDIS_KEY, 0, -1)
            return [json.loads(item) for item in raw_list]
        except Exception:
            logger.warning("failed to load anomalies from Redis", exc_info=True)
            return []

    def on_tick(self, snapshot: dict, sector_rankings: list[dict]) -> None:
        """Called every rt_k tick from the scheduler."""
        self._new_day_check()

        now = _time.time()

        idx_prices = {}
        for code in INDEX_CODES:
            row = snapshot.get(code)
            if row and row.get("close", 0) > 0:
                idx_prices[code] = row["close"]

        sec_pcts = {}
        for s in sector_rankings:
            name = s.get("industry")
            pct = s.get("avg_pct_chg")
            if name and pct is not None:
                sec_pcts[name] = pct

        tick = TickRecord(ts=now, indices=idx_prices, sector_pcts=sec_pcts)
        self._history.append(tick)

        if len(self._history) < 10:
            return

        for w in WINDOWS:
            cutoff = now - w["seconds"]
            old_tick = self._find_tick_near(cutoff)
            if old_tick is None:
                continue

            for code in INDEX_CODES:
                price_now = idx_prices.get(code)
                price_then = old_tick.indices.get(code)
                if not price_now or not price_then or price_then == 0:
                    continue

                delta = (price_now - price_then) / price_then * 100
                if abs(delta) < w["threshold"]:
                    continue

                cooldown_key = f"{code}:{w['label']}"
                last_fire = self._cooldowns.get(cooldown_key, 0)
                if now - last_fire < w["seconds"] * 0.8:
                    continue

                sec_deltas = []
                for name, pct_now in sec_pcts.items():
                    pct_then = old_tick.sector_pcts.get(name, 0)
                    sec_delta = pct_now - pct_then
                    sec_deltas.append({"name": name, "delta": round(sec_delta, 3), "pct_now": round(pct_now, 2)})

                if delta > 0:
                    sec_deltas.sort(key=lambda x: x["delta"], reverse=True)
                else:
                    sec_deltas.sort(key=lambda x: x["delta"])

                event = AnomalyEvent(
                    ts=now,
                    index_code=code,
                    index_name=INDEX_NAMES.get(code, code),
                    window=w["label"],
                    delta_pct=round(delta, 3),
                    price_now=price_now,
                    price_then=price_then,
                    top_sectors=sec_deltas[:8],
                )
                self._persist_anomaly(event)
                self._cooldowns[cooldown_key] = now

                logger.info(
                    "ANOMALY %s %s %.2f%% in %s | top: %s",
                    code, INDEX_NAMES.get(code, ""), delta, w["label"],
                    ", ".join(f"{s['name']}({s['delta']:+.2f})" for s in sec_deltas[:3]),
                )

    def _find_tick_near(self, target_ts: float) -> TickRecord | None:
        """Binary-ish search for tick closest to target timestamp."""
        if not self._history:
            return None
        if self._history[0].ts > target_ts:
            return None

        best = None
        best_diff = float("inf")
        for tick in self._history:
            diff = abs(tick.ts - target_ts)
            if diff < best_diff:
                best_diff = diff
                best = tick
            if tick.ts > target_ts + 5:
                break
        return best

    def get_snapshot(self) -> dict:
        """Build the full monitoring snapshot for the API."""
        now = _time.time()

        indices = []
        if self._history:
            latest = self._history[-1]
            for code in INDEX_CODES:
                price = latest.indices.get(code)
                if not price:
                    continue
                row = {"code": code, "name": INDEX_NAMES.get(code, code), "price": price, "windows": {}}
                for w in WINDOWS:
                    old = self._find_tick_near(now - w["seconds"])
                    if old and old.indices.get(code):
                        old_p = old.indices[code]
                        d = (price - old_p) / old_p * 100
                        row["windows"][w["label"]] = round(d, 3)
                    else:
                        row["windows"][w["label"]] = None
                indices.append(row)

        sectors = []
        if self._history:
            latest = self._history[-1]
            for name, pct in latest.sector_pcts.items():
                sec_row = {"name": name, "pct_chg": round(pct, 2), "windows": {}}
                for w in WINDOWS:
                    old = self._find_tick_near(now - w["seconds"])
                    if old:
                        old_pct = old.sector_pcts.get(name, 0)
                        sec_row["windows"][w["label"]] = round(pct - old_pct, 3)
                    else:
                        sec_row["windows"][w["label"]] = None
                sectors.append(sec_row)
            sectors.sort(key=lambda x: abs(x["pct_chg"]), reverse=True)

        # Read anomalies from Redis (survives restart)
        anomalies = self._load_anomalies_from_redis()
        anomalies.reverse()  # newest first

        return {
            "ts": now,
            "history_len": len(self._history),
            "indices": indices,
            "sectors": sectors,
            "anomalies": anomalies,
            "anomaly_count": len(anomalies),
        }


monitor_engine = MonitorEngine()
