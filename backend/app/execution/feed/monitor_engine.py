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

# ── Large-cap volume-price surge detection ──────────────────────
LARGECAP_MV_THRESHOLD = 10_000_000  # circ_mv 万元 = 1000亿
LARGECAP_VOL_RATIO_MIN = 1.2        # 今日累计量 > 昨日同时刻 × 1.2
REDIS_KEY_LARGECAP = "monitor:largecap_alerts"


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


@dataclass
class LargecapAlert:
    ts: float
    ts_code: str
    name: str
    price_now: float
    price_yesterday: float
    vol_now: float
    vol_yesterday: float
    vol_ratio: float
    circ_mv: float  # 万元

    def to_dict(self) -> dict:
        pchg = round((self.price_now - self.price_yesterday) / self.price_yesterday * 100, 2) if self.price_yesterday else 0
        return {
            "ts": self.ts,
            "time": _time.strftime("%H:%M:%S", _time.localtime(self.ts)),
            "ts_code": self.ts_code,
            "name": self.name,
            "price_now": round(self.price_now, 2),
            "price_yesterday": round(self.price_yesterday, 2),
            "price_chg_pct": pchg,
            "vol_now": round(self.vol_now, 2),
            "vol_yesterday": round(self.vol_yesterday, 2),
            "vol_ratio": round(self.vol_ratio, 2),
            "circ_mv_yi": round(self.circ_mv / 10000, 1),  # 转为亿元
        }


class MonitorEngine:

    def __init__(self):
        self._history: deque[TickRecord] = deque(maxlen=MAX_HISTORY)
        self._cooldowns: dict[str, float] = {}  # "code:window" -> last fire ts
        self._today: str = ""
        # largecap volume-price surge
        self._largecap_mv: dict[str, float] = {}       # code -> circ_mv (万元)
        self._yesterday_baseline: dict[str, dict[str, dict]] = {}  # code -> {HH:MM -> {close, cum_vol}}
        self._triggered_largecap: set[str] = set()

    def _new_day_check(self) -> None:
        """Clear in-memory state and Redis anomalies on day change."""
        from datetime import date
        today = date.today().isoformat()
        if today != self._today:
            self._history.clear()
            self._cooldowns.clear()
            self._triggered_largecap = set()
            self._today = today
            try:
                r = _redis()
                r.delete(REDIS_KEY)
                r.delete(REDIS_KEY_LARGECAP)
            except Exception:
                logger.warning("failed to clear Redis on day change", exc_info=True)
            self._load_largecap_baseline()

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

    # ── Large-cap volume-price surge ────────────────────────────────

    def _load_largecap_baseline(self) -> None:
        """Load large-cap stocks list and yesterday's minute-level price/volume baseline."""
        try:
            from sqlalchemy import create_engine, text as sa_text
            from app.core.config import settings
            from collections import defaultdict

            sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg")
            eng = create_engine(sync_url, echo=False)
            today_str = __import__("datetime").date.today().strftime("%Y%m%d")

            with eng.connect() as conn:
                row = conn.execute(sa_text(
                    "SELECT MAX(cal_date) FROM trade_cal "
                    "WHERE is_open = 1 AND cal_date < :td"
                ), {"td": today_str}).fetchone()
                if not row or not row[0]:
                    logger.warning("largecap: no previous trading day found")
                    return
                prev_date = row[0]

                mv_rows = conn.execute(sa_text(
                    "SELECT ts_code, circ_mv FROM daily_basic "
                    "WHERE trade_date = ("
                    "  SELECT MAX(trade_date) FROM daily_basic WHERE trade_date <= :d"
                    ") AND circ_mv > :mv"
                ), {"d": prev_date, "mv": LARGECAP_MV_THRESHOLD}).fetchall()

                self._largecap_mv = {r[0]: float(r[1]) for r in mv_rows}
                if not self._largecap_mv:
                    logger.info("largecap: no stocks above 1000亿 threshold")
                    return

                prev_dash = f"{prev_date[:4]}-{prev_date[4:6]}-{prev_date[6:]}"
                min_rows = conn.execute(sa_text(
                    "SELECT m.ts_code, m.trade_time, m.close, m.vol "
                    "FROM stock_min_kline m "
                    "WHERE m.ts_code IN ("
                    "  SELECT ts_code FROM daily_basic "
                    "  WHERE trade_date = ("
                    "    SELECT MAX(trade_date) FROM daily_basic WHERE trade_date <= :d"
                    "  ) AND circ_mv > :mv"
                    ") "
                    "AND m.trade_time >= :ts0 AND m.trade_time <= :ts1 "
                    "AND m.freq = '1min' "
                    "ORDER BY m.ts_code, m.trade_time"
                ), {
                    "d": prev_date, "mv": LARGECAP_MV_THRESHOLD,
                    "ts0": f"{prev_dash} 09:00:00", "ts1": f"{prev_dash} 16:00:00",
                }).fetchall()

            eng.dispose()

            code_bars: dict[str, list] = defaultdict(list)
            for r in min_rows:
                code_bars[r[0]].append((r[1], float(r[2] or 0), float(r[3] or 0)))

            self._yesterday_baseline = {}
            for code, bars in code_bars.items():
                cum_vol = 0.0
                minute_data: dict[str, dict] = {}
                for trade_time, close, vol in bars:
                    cum_vol += vol
                    minute_key = trade_time.strftime("%H:%M")
                    minute_data[minute_key] = {"close": close, "cum_vol": cum_vol}
                self._yesterday_baseline[code] = minute_data

            logger.info(
                "largecap baseline loaded: %d stocks (>1000亿), %d minute records from %s",
                len(self._largecap_mv), len(min_rows), prev_date,
            )
        except Exception:
            logger.warning("failed to load largecap baseline", exc_info=True)

    def _check_largecap_alerts(self, snapshot: dict) -> None:
        """Check large-cap stocks for volume-price surge vs yesterday same time."""
        if not self._yesterday_baseline:
            return

        now = _time.time()
        current_minute = _time.strftime("%H:%M")

        for code in self._largecap_mv:
            if code in self._triggered_largecap:
                continue

            snap = snapshot.get(code)
            if not snap:
                continue
            baseline = self._yesterday_baseline.get(code)
            if not baseline:
                continue
            yest = baseline.get(current_minute)
            if not yest:
                continue

            price_now = snap.get("close", 0)
            vol_now = snap.get("vol", 0)
            price_yest = yest["close"]
            vol_yest = yest["cum_vol"]

            if price_yest <= 0 or vol_yest <= 0:
                continue

            if price_now > price_yest and vol_now > vol_yest * LARGECAP_VOL_RATIO_MIN:
                alert = LargecapAlert(
                    ts=now, ts_code=code,
                    name=snap.get("name", code),
                    price_now=price_now, price_yesterday=price_yest,
                    vol_now=vol_now, vol_yesterday=vol_yest,
                    vol_ratio=round(vol_now / vol_yest, 2),
                    circ_mv=self._largecap_mv.get(code, 0),
                )
                self._persist_largecap_alert(alert)
                self._triggered_largecap.add(code)
                logger.info(
                    "LARGECAP ALERT %s %s price %.2f>%.2f vol %.0f>%.0f (%.1fx)",
                    code, snap.get("name", ""), price_now, price_yest,
                    vol_now, vol_yest, alert.vol_ratio,
                )

    def _persist_largecap_alert(self, alert: LargecapAlert) -> None:
        try:
            r = _redis()
            r.rpush(REDIS_KEY_LARGECAP, json.dumps(alert.to_dict(), ensure_ascii=False))
            r.expire(REDIS_KEY_LARGECAP, 18 * 3600)
        except Exception:
            logger.warning("failed to persist largecap alert", exc_info=True)

    def _load_largecap_alerts_from_redis(self) -> list[dict]:
        try:
            raw = _redis().lrange(REDIS_KEY_LARGECAP, 0, -1)
            return [json.loads(item) for item in raw]
        except Exception:
            logger.warning("failed to load largecap alerts from Redis", exc_info=True)
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

        # Large-cap volume-price surge check
        self._check_largecap_alerts(snapshot)

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

        largecap_alerts = self._load_largecap_alerts_from_redis()

        return {
            "ts": now,
            "history_len": len(self._history),
            "indices": indices,
            "sectors": sectors,
            "anomalies": anomalies,
            "anomaly_count": len(anomalies),
            "largecap_alerts": largecap_alerts,
            "largecap_alert_count": len(largecap_alerts),
        }


monitor_engine = MonitorEngine()
