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
from datetime import date, datetime, time as dt_time

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
REDIS_KEY_EVENT_DATE = "monitor:event_date"  # 记录事件归属日期

# ── Large-cap volume-price surge detection ──────────────────────
LARGECAP_MV_THRESHOLD = 10_000_000  # circ_mv 万元 = 1000亿
LARGECAP_VOL_RATIO_MIN = 1.2        # 今日累计量 > 昨日同时刻 × 1.2
LARGECAP_MIN_CHG_PCT = 1.0          # P1-5: 最低涨幅 1%
LARGECAP_MIN_AMOUNT = 500_000       # P1-5: 最低成交额 5亿 (单位:千元)
REDIS_KEY_LARGECAP = "monitor:largecap_alerts"

# ── Anomaly pattern classification ──────────────────────────────
# Weight sectors that represent large-cap / broad market influence
WEIGHT_SECTORS = {"银行", "非银金融", "食品饮料", "电力设备", "医药生物", "电子", "汽车"}

# ── Trading session windows ─────────────────────────────────────
_MORNING_OPEN = dt_time(9, 15)
_MORNING_CLOSE = dt_time(11, 35)
_AFTERNOON_OPEN = dt_time(12, 55)
_AFTERNOON_CLOSE = dt_time(15, 5)


def _is_trading_time(now: datetime | None = None) -> bool:
    """Check if current time falls within A-share trading session (with buffer)."""
    t = (now or datetime.now()).time()
    return (_MORNING_OPEN <= t <= _MORNING_CLOSE) or (_AFTERNOON_OPEN <= t <= _AFTERNOON_CLOSE)


def _redis():
    """Lazy import to avoid circular import at module load."""
    from app.core.redis import redis_client
    return redis_client


def _get_sync_engine():
    """Lazy create a sync engine for fire-and-forget DB writes."""
    global _sync_engine
    if _sync_engine is None:
        from sqlalchemy import create_engine
        from app.core.config import settings
        url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg")
        _sync_engine = create_engine(url, echo=False, pool_size=2, max_overflow=2)
    return _sync_engine


_sync_engine = None


def _db_persist_event(ev: dict) -> None:
    """Insert enriched anomaly event into monitor_events (fire-and-forget)."""
    try:
        from threading import Thread

        def _insert():
            try:
                from sqlalchemy import text as sa_text
                eng = _get_sync_engine()
                today = date.today().isoformat()
                with eng.connect() as conn:
                    conn.execute(sa_text("""
                        INSERT INTO monitor_events
                            (event_date, event_ts, event_time, index_code, index_name,
                             "window", delta_pct, price_now, price_then,
                             pattern, level, event_score,
                             watchlist_hits_json, position_hits_json, hit_count,
                             top_sectors_json, summary, action_hint)
                        VALUES
                            (:event_date, :event_ts, :event_time, :index_code, :index_name,
                             :window, :delta_pct, :price_now, :price_then,
                             :pattern, :level, :event_score,
                             :watchlist_hits_json, :position_hits_json, :hit_count,
                             :top_sectors_json, :summary, :action_hint)
                        ON CONFLICT (event_date, event_ts, index_code, "window") DO NOTHING
                    """), {
                        "event_date": today,
                        "event_ts": ev.get("ts"),
                        "event_time": ev.get("time", ""),
                        "index_code": ev.get("index_code", ""),
                        "index_name": ev.get("index_name", ""),
                        "window": ev.get("window", ""),
                        "delta_pct": ev.get("delta_pct", 0),
                        "price_now": ev.get("price_now"),
                        "price_then": ev.get("price_then"),
                        "pattern": ev.get("pattern"),
                        "level": ev.get("level"),
                        "event_score": ev.get("event_score"),
                        "watchlist_hits_json": json.dumps(ev.get("watchlist_hits", []), ensure_ascii=False),
                        "position_hits_json": json.dumps(ev.get("position_hits", []), ensure_ascii=False),
                        "hit_count": ev.get("hit_count", 0),
                        "top_sectors_json": json.dumps(ev.get("top_sectors", []), ensure_ascii=False),
                        "summary": ev.get("summary"),
                        "action_hint": ev.get("action_hint"),
                    })
                    conn.commit()
            except Exception:
                logger.warning("DB persist anomaly failed", exc_info=True)

        Thread(target=_insert, daemon=True).start()
    except Exception:
        logger.warning("failed to start DB persist thread for anomaly", exc_info=True)


def _db_persist_largecap(data: dict) -> None:
    """Insert largecap alert into monitor_largecap_alerts (fire-and-forget)."""
    try:
        from threading import Thread

        def _insert():
            try:
                from sqlalchemy import text as sa_text
                eng = _get_sync_engine()
                today = date.today().isoformat()
                with eng.connect() as conn:
                    conn.execute(sa_text("""
                        INSERT INTO monitor_largecap_alerts
                            (event_date, event_ts, event_time, ts_code, name,
                             price_now, price_yesterday, price_chg_pct,
                             vol_now, vol_yesterday, vol_ratio, circ_mv_yi,
                             sector, sector_strong, in_watchlist, in_position)
                        VALUES
                            (:event_date, :event_ts, :event_time, :ts_code, :name,
                             :price_now, :price_yesterday, :price_chg_pct,
                             :vol_now, :vol_yesterday, :vol_ratio, :circ_mv_yi,
                             :sector, :sector_strong, :in_watchlist, :in_position)
                        ON CONFLICT (event_date, event_ts, ts_code) DO NOTHING
                    """), {
                        "event_date": today,
                        "event_ts": data.get("ts"),
                        "event_time": data.get("time", ""),
                        "ts_code": data.get("ts_code", ""),
                        "name": data.get("name", ""),
                        "price_now": data.get("price_now"),
                        "price_yesterday": data.get("price_yesterday"),
                        "price_chg_pct": data.get("price_chg_pct"),
                        "vol_now": data.get("vol_now"),
                        "vol_yesterday": data.get("vol_yesterday"),
                        "vol_ratio": data.get("vol_ratio"),
                        "circ_mv_yi": data.get("circ_mv_yi"),
                        "sector": data.get("sector"),
                        "sector_strong": data.get("sector_strong", False),
                        "in_watchlist": data.get("in_watchlist", False),
                        "in_position": data.get("in_position", False),
                    })
                    conn.commit()
            except Exception:
                logger.warning("DB persist largecap alert failed", exc_info=True)

        Thread(target=_insert, daemon=True).start()
    except Exception:
        logger.warning("failed to start DB persist thread for largecap", exc_info=True)


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
        detected_at = _time.strftime("%H:%M:%S", _time.localtime(self.ts))
        trigger_minute = _time.strftime("%H:%M", _time.localtime(self.ts))
        return {
            "ts": self.ts,
            "time": detected_at,           # kept for compat
            "detected_at": detected_at,     # explicit: scan timestamp
            "trigger_minute": trigger_minute,  # HH:MM used for comparison
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
        detected_at = _time.strftime("%H:%M:%S", _time.localtime(self.ts))
        trigger_minute = _time.strftime("%H:%M", _time.localtime(self.ts))
        return {
            "ts": self.ts,
            "time": detected_at,
            "detected_at": detected_at,
            "trigger_minute": trigger_minute,
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
        # P1 context: watchlist / positions / industry map
        self._watchlist_codes: set[str] = set()
        self._position_codes: set[str] = set()
        self._industry_map: dict[str, str] = {}  # ts_code -> industry_name
        # Reverse index: industry_name -> set of watchlist/position codes
        self._watch_by_sector: dict[str, set[str]] = {}
        self._pos_by_sector: dict[str, set[str]] = {}

    def update_context(
        self,
        watchlist_codes: set[str] | None = None,
        position_codes: set[str] | None = None,
        industry_map: dict[str, str] | None = None,
    ) -> None:
        """Update trading context for anomaly enrichment (called by scheduler)."""
        if industry_map is not None:
            self._industry_map = industry_map
        if watchlist_codes is not None:
            self._watchlist_codes = watchlist_codes
        if position_codes is not None:
            self._position_codes = position_codes
        # Rebuild reverse indexes
        self._watch_by_sector = {}
        for code in self._watchlist_codes:
            ind = self._industry_map.get(code)
            if ind:
                self._watch_by_sector.setdefault(ind, set()).add(code)
        self._pos_by_sector = {}
        for code in self._position_codes:
            ind = self._industry_map.get(code)
            if ind:
                self._pos_by_sector.setdefault(ind, set()).add(code)

    def _reset_day(self, today_iso: str, *, purge_redis: bool = True) -> None:
        """Reset all in-memory + Redis state for a new day."""
        self._history.clear()
        self._cooldowns.clear()
        self._triggered_largecap = set()
        self._today = today_iso
        if purge_redis:
            try:
                r = _redis()
                r.delete(REDIS_KEY)
                r.delete(REDIS_KEY_LARGECAP)
                r.set(REDIS_KEY_EVENT_DATE, today_iso, ex=24 * 3600)
            except Exception:
                logger.warning("failed to clear Redis on day change", exc_info=True)

    def _new_day_check(self) -> None:
        """Clear in-memory state and Redis anomalies on day change."""
        today = date.today().isoformat()
        if today != self._today:
            self._reset_day(today)
            self._load_largecap_baseline()

    def _persist_anomaly(self, event: AnomalyEvent) -> None:
        """Append anomaly to Redis list with EOD expiry + write to DB."""
        ev_dict = event.to_dict()
        try:
            r = _redis()
            r.rpush(REDIS_KEY, json.dumps(ev_dict, ensure_ascii=False))
            r.expire(REDIS_KEY, 18 * 3600)  # auto-expire after 18h
        except Exception:
            logger.warning("failed to persist anomaly to Redis", exc_info=True)
        # P2-1: persist enriched event to DB — use full Redis anomaly list
        # so resonance / level / score match what the frontend sees.
        all_anomalies = self._load_anomalies_from_redis()
        enriched = self._enrich_anomaly(dict(ev_dict), all_anomalies)
        _db_persist_event(enriched)

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

            price_chg_pct = (price_now - price_yest) / price_yest * 100
            vol_ratio = vol_now / vol_yest if vol_yest > 0 else 0
            amount = snap.get("amount", 0)  # 千元

            # P1-5: tightened conditions
            if not (price_chg_pct >= LARGECAP_MIN_CHG_PCT
                    and vol_ratio >= LARGECAP_VOL_RATIO_MIN
                    and amount >= LARGECAP_MIN_AMOUNT):
                continue

            # P1-5: check if stock's sector is also strong today
            sector_strong = False
            ind = self._industry_map.get(code)
            if ind and self._history:
                latest_pct = self._history[-1].sector_pcts.get(ind)
                if latest_pct is not None and latest_pct > 0.3:
                    sector_strong = True

            alert = LargecapAlert(
                ts=now, ts_code=code,
                name=snap.get("name", code),
                price_now=price_now, price_yesterday=price_yest,
                vol_now=vol_now, vol_yesterday=vol_yest,
                vol_ratio=round(vol_ratio, 2),
                circ_mv=self._largecap_mv.get(code, 0),
            )
            alert_dict = alert.to_dict()
            alert_dict["sector_strong"] = sector_strong
            alert_dict["sector"] = ind or ""
            self._persist_largecap_alert_dict(alert_dict)
            self._triggered_largecap.add(code)
            logger.info(
                "LARGECAP ALERT %s %s chg=%.1f%% vol=%.1fx amt=%.0f千 sector=%s(%s)",
                code, snap.get("name", ""), price_chg_pct, vol_ratio,
                amount, ind or "?", "strong" if sector_strong else "weak",
            )

    def _persist_largecap_alert(self, alert: LargecapAlert) -> None:
        self._persist_largecap_alert_dict(alert.to_dict())

    def _persist_largecap_alert_dict(self, data: dict) -> None:
        try:
            r = _redis()
            r.rpush(REDIS_KEY_LARGECAP, json.dumps(data, ensure_ascii=False))
            r.expire(REDIS_KEY_LARGECAP, 18 * 3600)
        except Exception:
            logger.warning("failed to persist largecap alert", exc_info=True)
        # P2-2: persist to DB
        # Add watchlist/position flags that get_snapshot() normally adds
        code = data.get("ts_code", "")
        data_with_flags = dict(data)
        data_with_flags.setdefault("in_watchlist", code in self._watchlist_codes)
        data_with_flags.setdefault("in_position", code in self._position_codes)
        _db_persist_largecap(data_with_flags)

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

    # ── P1: Anomaly enrichment pipeline ──────────────────────────

    def _enrich_anomaly(self, ev: dict, all_anomalies: list[dict]) -> dict:
        """Enrich a single anomaly dict with hits, pattern, level, score, action_hint."""
        top_sectors = ev.get("top_sectors", [])
        sector_names = {s["name"] for s in top_sectors[:5]}
        delta = ev.get("delta_pct", 0)
        window = ev.get("window", "")
        is_up = delta > 0

        # ── P1-1: watchlist / position hits ──
        watch_hits: list[str] = []
        pos_hits: list[str] = []
        for sec_name in sector_names:
            for code in self._watch_by_sector.get(sec_name, ()):
                if code not in watch_hits:
                    watch_hits.append(code)
            for code in self._pos_by_sector.get(sec_name, ()):
                if code not in pos_hits:
                    pos_hits.append(code)
        ev["watchlist_hits"] = watch_hits[:10]
        ev["position_hits"] = pos_hits[:10]
        # Deduplicate: a stock in both watchlist and position counts as 1 unique hit
        ev["hit_count"] = len(set(watch_hits) | set(pos_hits))

        # ── P1-2: pattern / level / summary ──
        top3_deltas = [abs(s.get("delta", 0)) for s in top_sectors[:3]]
        top3_names = [s["name"] for s in top_sectors[:3]]
        weight_count = sum(1 for n in top3_names if n in WEIGHT_SECTORS)
        avg_top3 = sum(top3_deltas) / max(len(top3_deltas), 1)
        sector_spread = len([s for s in top_sectors[:8] if abs(s.get("delta", 0)) > 0.05])

        # Multi-index resonance: how many indices triggered same window recently
        ev_ts = ev.get("ts", 0)
        resonance = sum(
            1 for a in all_anomalies
            if a.get("window") == window
            and abs(a.get("ts", 0) - ev_ts) < 120
            and a.get("index_code") != ev.get("index_code")
            and (a.get("delta_pct", 0) > 0) == is_up
        )

        # Classify pattern
        if weight_count >= 2 and is_up:
            pattern = "weight_pull"
        elif sector_spread <= 2 and avg_top3 > 0.1:
            pattern = "theme_burst"
        elif not is_up and sector_spread >= 4:
            pattern = "risk_off"
        elif is_up and sector_spread >= 4:
            pattern = "broad_risk_on"
        elif not is_up and weight_count >= 2:
            pattern = "weight_drag"
        else:
            pattern = "mixed"

        # Level
        abs_delta = abs(delta)
        window_mult = {"1min": 2.0, "5min": 1.2, "15min": 1.0}.get(window, 1.0)
        urgency = abs_delta * window_mult
        if urgency > 1.5 or (resonance >= 2 and urgency > 0.8):
            level = "high"
        elif urgency > 0.8 or resonance >= 1:
            level = "medium"
        else:
            level = "low"

        # Summary
        direction = "拉升" if is_up else "回落"
        pattern_label = {
            "weight_pull": "权重板块带动",
            "theme_burst": f"{'、'.join(top3_names[:2])}主题脉冲",
            "risk_off": "多板块共振下杀",
            "broad_risk_on": "普涨情绪扩散",
            "weight_drag": "权重板块拖累",
            "mixed": "混合驱动",
        }.get(pattern, "")
        hit_desc = ""
        if watch_hits or pos_hits:
            parts = []
            if watch_hits:
                parts.append(f"观察池{len(watch_hits)}只")
            if pos_hits:
                parts.append(f"持仓{len(pos_hits)}只")
            hit_desc = f"，命中{'、'.join(parts)}"
        summary = f"{ev.get('index_name', '')} {window}内{direction}{abs_delta:.2f}%，{pattern_label}{hit_desc}"

        ev["pattern"] = pattern
        ev["level"] = level
        ev["summary"] = summary

        # ── P1-4: event_score (0-100) ──
        # Components: threshold overshoot, window weight, sector concentration,
        #             hits, multi-index resonance
        threshold = {"1min": 0.3, "5min": 0.5, "15min": 1.0}.get(window, 0.5)
        overshoot = min((abs_delta - threshold) / threshold, 2.0)  # 0~2
        score_overshoot = overshoot * 25                            # 0~50
        score_window = {"15min": 10, "5min": 15, "1min": 20}.get(window, 10)
        score_concentration = min(avg_top3 * 40, 15)               # 0~15
        score_hits = min(len(watch_hits) * 3 + len(pos_hits) * 5, 15)  # 0~15
        score_resonance = min(resonance * 8, 16)                   # 0~16
        raw = score_overshoot + score_window + score_concentration + score_hits + score_resonance
        ev["event_score"] = round(min(max(raw, 0), 100))

        # ── P1-3: action_hint ──
        if level == "high" and pos_hits:
            hint = "检查持仓暴露，谨防冲高回落" if is_up else "持仓承压，评估止损/减仓"
        elif level == "high" and watch_hits:
            hint = "观察池优先确认，不追非核心" if is_up else "观察池标的回调，关注低吸机会"
        elif pattern == "theme_burst":
            hint = "板块确认后再考虑跟随" if is_up else "主题退潮，回避追高"
        elif pattern in ("risk_off", "weight_drag"):
            hint = "防御为主，减少操作"
        elif pattern == "broad_risk_on" and level != "low":
            hint = "普涨行情，关注强势板块龙头"
        elif watch_hits:
            hint = "关注观察池标的表现"
        else:
            hint = "继续观察，暂不操作"
        ev["action_hint"] = hint

        return ev

    def get_snapshot(self) -> dict:
        """Build the full monitoring snapshot for the API.

        Returns explicit state fields so the frontend can render a correct
        three-state UI (live / replay / no-data) without guessing.
        """
        now = _time.time()
        now_dt = datetime.now()
        today_iso = date.today().isoformat()
        trading_time = _is_trading_time(now_dt)

        # ── Cross-day cleanup (read-only: don't advance _today) ──
        # get_snapshot() is a read path — it must NOT push _today forward,
        # otherwise the first on_tick() would skip _new_day_check() and
        # miss _load_largecap_baseline().  We only purge stale Redis keys
        # and discard stale in-memory data for this response.
        is_new_day = self._today != "" and self._today != today_iso
        event_date = self._today or today_iso
        stale_events = False
        if is_new_day:
            # In-memory history/cooldowns belong to yesterday — ignore them
            # for this snapshot, but do NOT mutate _today so on_tick() still
            # runs the full _new_day_check() (including largecap baseline).
            stale_events = True
            logger.info("get_snapshot: stale in-memory state from %s, will be cleaned on next tick", self._today)
        try:
            r = _redis()
            stored_date = r.get(REDIS_KEY_EVENT_DATE)
            if stored_date:
                stored_date = stored_date if isinstance(stored_date, str) else stored_date.decode()
            if stored_date and stored_date != today_iso:
                # Redis events belong to a previous day — purge
                r.delete(REDIS_KEY)
                r.delete(REDIS_KEY_LARGECAP)
                r.set(REDIS_KEY_EVENT_DATE, today_iso, ex=24 * 3600)
                stale_events = True
                logger.info("get_snapshot: purged stale Redis events from %s", stored_date)
            event_date = stored_date if stored_date == today_iso else today_iso
        except Exception:
            logger.warning("get_snapshot: Redis date check failed", exc_info=True)

        # ── Snapshot age & last tick ──
        # When stale (cross-day), ignore yesterday's in-memory history
        has_valid_history = bool(self._history) and not is_new_day
        last_tick_ts: float | None = None
        snapshot_age_s: float | None = None
        last_tick_time: str | None = None
        if has_valid_history:
            last_tick_ts = self._history[-1].ts
            snapshot_age_s = round(now - last_tick_ts, 1)
            last_tick_time = _time.strftime("%H:%M:%S", _time.localtime(last_tick_ts))

        # live_ready: we have fresh ticks (< 30s old) during trading hours
        live_ready = (
            has_valid_history
            and snapshot_age_s is not None
            and snapshot_age_s < 30
            and trading_time
        )

        # ── Build indices / sectors from history ──
        indices = []
        if has_valid_history:
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
        if has_valid_history:
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

        # Read anomalies from Redis (survives restart); stale already purged above
        anomalies = [] if stale_events else self._load_anomalies_from_redis()
        anomalies.reverse()  # newest first

        # P1: enrich each anomaly with hits, pattern, level, score, action_hint
        for ev in anomalies:
            self._enrich_anomaly(ev, anomalies)

        largecap_alerts = [] if stale_events else self._load_largecap_alerts_from_redis()

        # P1-1: enrich largecap alerts with watchlist/position hit flag
        for la in largecap_alerts:
            code = la.get("ts_code", "")
            la["in_watchlist"] = code in self._watchlist_codes
            la["in_position"] = code in self._position_codes

        return {
            "ts": now,
            # ── State fields (P0) ──
            "trading_time": trading_time,
            "live_ready": live_ready,
            "snapshot_age_s": snapshot_age_s,
            "last_tick_time": last_tick_time,
            "event_date": event_date,
            # ── Context summary ──
            "watchlist_count": len(self._watchlist_codes),
            "position_count": len(self._position_codes),
            # ── Existing fields ──
            "history_len": len(self._history) if has_valid_history else 0,
            "indices": indices,
            "sectors": sectors,
            "anomalies": anomalies,
            "anomaly_count": len(anomalies),
            "largecap_alerts": largecap_alerts,
            "largecap_alert_count": len(largecap_alerts),
        }


monitor_engine = MonitorEngine()
