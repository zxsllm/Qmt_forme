"""MarketDataScheduler — unified full-market rt_k polling.

Data source: Tushare `rt_k` (实时日K线快照)
- Every 1.2s: ONE call with wildcard `6*.SH,0*.SZ,3*.SZ,9*.BJ` → ~5400 stocks
- Same result serves: order matching, WS broadcast, real-time rankings, sector aggregation
- 50 calls/min = 1.2s interval (extreme rate)

Lifecycle:
  - Auto-started at FastAPI startup on trade dates
  - watch_codes auto-collected from OMS positions + active orders
  - During trading hours: full-market rt_k → snapshot cache + watched bars → matching
  - Non-trading hours / non-trade dates: sleeps efficiently
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
from datetime import date, datetime, time as dtime

from app.shared.interfaces.models import BarData
from app.execution.feed.market_feed import market_feed

logger = logging.getLogger(__name__)

MORNING_OPEN = dtime(9, 30)
MORNING_CLOSE = dtime(11, 30)
AFTERNOON_OPEN = dtime(13, 0)
AFTERNOON_CLOSE = dtime(15, 0)

POLL_INTERVAL = 1.2  # 50 calls/min extreme rate
FULL_MARKET_PATTERN = "6*.SH,0*.SZ,3*.SZ,9*.BJ"

SETTLEMENT_TIME = dtime(15, 1)
SYNC_TIME = dtime(15, 30)
REVIEW_TIME = dtime(16, 0)       # generate daily review after sync completes
VERIFY_TIME = dtime(16, 5)       # auto-verify morning plan after review + sync
PLAN_TIME = dtime(8, 0)          # generate morning plan before market open


def _is_trading_time(now: datetime | None = None) -> bool:
    t = (now or datetime.now()).time()
    return (MORNING_OPEN <= t <= MORNING_CLOSE) or (AFTERNOON_OPEN <= t <= AFTERNOON_CLOSE)


MINS_PULL_INTERVAL = 60  # pull minute bars every 60s during trading

# In-memory real-time market snapshot (set by scheduler, read by API)
_rt_snapshot: dict = {}       # ts_code -> {name, close, pct_chg, vol, amount, ...}
_rt_snapshot_ts: float = 0    # last update timestamp

# Pre-computed rankings cache (rebuilt every rt_k tick, ~1.2s)
_cached_rankings: dict[str, list[dict]] = {}   # "gain"/"lose"/"turnover" -> top-N
_cached_sector_rankings: list[dict] = []       # full sorted sector list
_cached_indices: list[dict] = []               # domestic index rows
_RANKINGS_TOP_N = 50  # pre-cache more than needed

# ---------------------------------------------------------------------------
# Intraday minute-bar aggregator: builds 1-min OHLCV from rt_k snapshots
# ---------------------------------------------------------------------------
_intraday_mins: dict[str, dict[str, dict]] = {}  # ts_code -> { "HH:MM" -> bar }
_intraday_date: str = ""  # e.g. "2026-03-26"
_intraday_prev_vol: dict[str, float] = {}  # ts_code -> last-seen cumulative vol


INTRADAY_GRANULARITY_SEC = 5  # one data point per 5 seconds (~2880 points/day)


_intraday_prev_amt: dict[str, float] = {}  # cumulative amount tracker


def _aggregate_minute_bars(snap: dict) -> None:
    """Called every rt_k tick (~1.2s). Aggregate into 5-second bars for smooth intraday chart."""
    global _intraday_mins, _intraday_date, _intraday_prev_vol, _intraday_prev_amt
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    sec = now.second
    slot = (sec // INTRADAY_GRANULARITY_SEC) * INTRADAY_GRANULARITY_SEC
    time_key = f"{now.strftime('%H:%M')}:{slot:02d}"

    if today != _intraday_date:
        _intraday_mins = {}
        _intraday_prev_vol = {}
        _intraday_prev_amt = {}
        _intraday_date = today

    for code, row in snap.items():
        price = row.get("close", 0)
        if price <= 0:
            continue
        cum_vol = row.get("vol", 0)
        cum_amt = row.get("amount", 0)

        if code not in _intraday_mins:
            _intraday_mins[code] = {}
        bars = _intraday_mins[code]

        first_seen = code not in _intraday_prev_vol
        if first_seen:
            delta_vol = cum_vol
            delta_amt = cum_amt
        else:
            delta_vol = max(0, cum_vol - _intraday_prev_vol[code])
            delta_amt = max(0, cum_amt - _intraday_prev_amt[code])

        if time_key not in bars:
            bars[time_key] = {
                "open": price, "high": price, "low": price, "close": price,
                "vol": delta_vol, "amount": delta_amt,
            }
        else:
            b = bars[time_key]
            b["high"] = max(b["high"], price)
            b["low"] = min(b["low"], price)
            b["close"] = price
            b["vol"] += delta_vol
            b["amount"] += delta_amt

        _intraday_prev_vol[code] = cum_vol
        _intraday_prev_amt[code] = cum_amt


def get_intraday_minutes(ts_code: str) -> list[dict]:
    """Return today's intraday bars (5-sec granularity) for a single stock."""
    bars = _intraday_mins.get(ts_code, {})
    if not bars:
        return []
    result = []
    prefix = _intraday_date
    for tk in sorted(bars.keys()):
        b = bars[tk]
        result.append({
            "ts_code": ts_code,
            "trade_time": f"{prefix} {tk}",
            "open": b["open"], "high": b["high"],
            "low": b["low"], "close": b["close"],
            "vol": b["vol"], "amount": b["amount"],
            "freq": "1min",
        })
    return result


def get_rt_snapshot() -> tuple[dict, float]:
    return _rt_snapshot, _rt_snapshot_ts


def _rebuild_rankings_cache(snap: dict) -> None:
    """Pre-compute all ranking lists from snapshot. Called once per rt_k tick."""
    global _cached_rankings, _cached_sector_rankings, _cached_indices

    valid = [v for v in snap.values() if v.get("close", 0) > 0 and v.get("vol", 0) > 0]

    gain = sorted(valid, key=lambda x: x.get("pct_chg", 0), reverse=True)
    lose = sorted(valid, key=lambda x: x.get("pct_chg", 0))
    turnover = sorted(valid, key=lambda x: x.get("amount", 0), reverse=True)
    _cached_rankings = {
        "gain": gain[:_RANKINGS_TOP_N],
        "lose": lose[:_RANKINGS_TOP_N],
        "turnover": turnover[:_RANKINGS_TOP_N],
    }

    from collections import defaultdict
    agg: dict[str, list[float]] = defaultdict(list)
    for code, row in snap.items():
        if row.get("close", 0) <= 0 or row.get("vol", 0) <= 0:
            continue
        pct = row.get("pct_chg")
        ind = _industry_cache.get(code)
        if pct is not None and ind:
            agg[ind].append(pct)
    sectors = []
    for ind_name, pcts in agg.items():
        if len(pcts) < 5:
            continue
        sectors.append({
            "industry": ind_name,
            "avg_pct_chg": round(sum(pcts) / len(pcts), 2),
            "stock_count": len(pcts),
        })
    sectors.sort(key=lambda x: x["avg_pct_chg"], reverse=True)
    _cached_sector_rankings = sectors

    idx_codes = ["000001.SH", "399001.SZ", "399006.SZ", "000300.SH", "000905.SH", "000688.SH"]
    _cached_indices = [snap[c] for c in idx_codes if c in snap]


def _snapshot_is_today() -> bool:
    """Check if the rt snapshot was taken today (valid even after market close)."""
    if not _rt_snapshot or not _rt_snapshot_ts:
        return False
    from datetime import date as _date
    return _date.fromtimestamp(_rt_snapshot_ts) == _date.today()


def get_rt_rankings(rank_type: str = "gain", limit: int = 10) -> list[dict] | None:
    if not _snapshot_is_today():
        return None
    return _cached_rankings.get(rank_type, _cached_rankings.get("gain", []))[:limit]


def get_rt_global_indices() -> list[dict] | None:
    if not _snapshot_is_today():
        return None
    return _cached_indices if _cached_indices else None


def get_rt_sector_rankings(limit: int = 30, direction: str = "gain") -> list[dict] | None:
    if not _snapshot_is_today() or not _cached_sector_rankings:
        return None
    return _cached_sector_rankings[:limit]


# ts_code → industry_name cache (loaded once at startup)
_industry_cache: dict[str, str] = {}


class MarketDataScheduler:

    NEWS_REFRESH_INTERVAL = 5  # poll news every 5s
    ALERT_REFRESH_INTERVAL = 600  # poll forecast/ST/CB every 10min

    def __init__(self):
        self._running = False
        self._task: asyncio.Task | None = None
        self._news_task: asyncio.Task | None = None
        self._alert_task: asyncio.Task | None = None
        self._watch_codes: list[str] = []
        self._today_is_trading: bool | None = None
        self._last_check_date: date | None = None
        self._settled_today = False
        self._sync_started_today = False
        self._synced_today = False
        self._last_news_pull: float = 0
        self._last_mins_pull: float = 0
        self._last_alert_pull: float = 0
        self._mins_backfilled = False
        self._industry_loaded = False
        self._review_generated_today = False
        self._plan_generated_today = False
        self._plan_verified_today = False

    def _maybe_pull_mins(self) -> None:
        """Pull minute bars for watched stocks — fire-and-forget, every 60s."""
        import time as _t
        if _t.time() - self._last_mins_pull < MINS_PULL_INTERVAL:
            return
        self._last_mins_pull = _t.time()
        codes = list(self._watch_codes)
        if not codes:
            return
        asyncio.ensure_future(asyncio.to_thread(self._pull_mins_sync, codes))

    @staticmethod
    def _pull_mins_sync(codes: list[str]) -> None:
        """Pull today's minute bars for given codes and upsert into DB."""
        import os, sys, psycopg2
        from io import StringIO
        try:
            from app.research.data.tushare_service import TushareService
            svc = TushareService()
            db_url = os.getenv("DATABASE_URL", "").replace(
                "postgresql+asyncpg://", "postgresql://"
            )
            today = datetime.now().strftime("%Y-%m-%d")
            start = f"{today} 09:30:00"
            end = f"{today} 15:00:00"

            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            total = 0
            for code in codes:
                try:
                    df = svc.stk_mins(ts_code=code, freq="1min",
                                      start_date=start, end_date=end)
                    if df.empty:
                        continue
                    for col in ["ts_code", "trade_time"]:
                        if col not in df.columns:
                            continue
                    df["freq"] = "1min"
                    cols = ["ts_code", "trade_time", "open", "close", "high",
                            "low", "vol", "amount", "freq"]
                    available = [c for c in cols if c in df.columns]
                    buf = StringIO()
                    df[available].to_csv(buf, index=False, header=False,
                                         sep="\t", na_rep="\\N")
                    buf.seek(0)
                    cur.execute(
                        "DELETE FROM stock_min_kline WHERE ts_code=%s "
                        "AND trade_time >= %s AND trade_time <= %s AND freq='1min'",
                        (code, start, end),
                    )
                    cur.copy_from(buf, "stock_min_kline",
                                  columns=available, sep="\t", null="\\N")
                    conn.commit()
                    total += len(df)
                except Exception:
                    conn.rollback()
                    logger.warning("mins pull failed for %s", code, exc_info=True)
            cur.close()
            conn.close()
            if total:
                logger.info("mins pull: wrote %d bars for %d codes", total, len(codes))
        except Exception:
            logger.exception("mins pull error")

    def _maybe_backfill_mins(self) -> None:
        """One-time backfill of recent missing minute data for watched stocks."""
        if self._mins_backfilled:
            return
        self._mins_backfilled = True
        codes = list(self._watch_codes)
        if not codes:
            return
        asyncio.ensure_future(asyncio.to_thread(self._backfill_mins_sync, codes))

    @staticmethod
    def _backfill_mins_sync(codes: list[str]) -> None:
        """Fill missing recent minute data (last 5 trade days) for watched codes."""
        import os, psycopg2
        from io import StringIO
        try:
            from app.research.data.tushare_service import TushareService
            svc = TushareService()
            db_url = os.getenv("DATABASE_URL", "").replace(
                "postgresql+asyncpg://", "postgresql://"
            )
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()

            cur.execute(
                "SELECT cal_date FROM trade_cal "
                "WHERE is_open='1' AND cal_date <= %s "
                "ORDER BY cal_date DESC LIMIT 5",
                (datetime.now().strftime("%Y%m%d"),),
            )
            recent_dates = [r[0] for r in cur.fetchall()]

            total = 0
            for code in codes:
                for td in recent_dates:
                    try:
                        y, m, d = td[:4], td[4:6], td[6:8]
                        start = f"{y}-{m}-{d} 09:30:00"
                        end = f"{y}-{m}-{d} 15:00:00"

                        cur.execute(
                            "SELECT COUNT(*) FROM stock_min_kline "
                            "WHERE ts_code=%s AND trade_time >= %s AND trade_time <= %s",
                            (code, start, end),
                        )
                        if cur.fetchone()[0] > 200:
                            continue

                        df = svc.stk_mins(ts_code=code, freq="1min",
                                          start_date=start, end_date=end)
                        if df.empty:
                            continue
                        df["freq"] = "1min"
                        cols = ["ts_code", "trade_time", "open", "close", "high",
                                "low", "vol", "amount", "freq"]
                        available = [c for c in cols if c in df.columns]
                        buf = StringIO()
                        df[available].to_csv(buf, index=False, header=False,
                                             sep="\t", na_rep="\\N")
                        buf.seek(0)
                        cur.execute(
                            "DELETE FROM stock_min_kline WHERE ts_code=%s "
                            "AND trade_time >= %s AND trade_time <= %s",
                            (code, start, end),
                        )
                        cur.copy_from(buf, "stock_min_kline",
                                      columns=available, sep="\t", null="\\N")
                        conn.commit()
                        total += len(df)
                        logger.info("backfill mins: %s %s → %d bars", code, td, len(df))
                    except Exception:
                        conn.rollback()
                        logger.warning("backfill mins failed: %s %s", code, td, exc_info=True)

            cur.close()
            conn.close()
            if total:
                logger.info("backfill mins complete: %d total bars", total)
            else:
                logger.info("backfill mins: all recent data present")
        except Exception:
            logger.exception("backfill mins error")

    def _maybe_pull_news(self) -> None:
        """Fire-and-forget news pull — never blocks the scheduler loop."""
        import time as _t
        if _t.time() - self._last_news_pull < self.NEWS_REFRESH_INTERVAL:
            return
        if self._news_task and not self._news_task.done():
            logger.debug("news pull still running, skip")
            return
        self._last_news_pull = _t.time()

        async def _pull_with_timeout():
            try:
                await asyncio.wait_for(asyncio.to_thread(self._pull_news_sync), timeout=15)
            except asyncio.TimeoutError:
                logger.warning("news pull timed out (15s)")
            except Exception:
                logger.warning("news pull task error", exc_info=True)

        self._news_task = asyncio.ensure_future(_pull_with_timeout())

    def _maybe_pull_alerts(self) -> None:
        """Fire-and-forget alert data pull (forecast/ST/CB) — every 10 min."""
        import time as _t
        if _t.time() - self._last_alert_pull < self.ALERT_REFRESH_INTERVAL:
            return
        if self._alert_task and not self._alert_task.done():
            logger.debug("alert pull still running, skip")
            return
        self._last_alert_pull = _t.time()

        async def _pull():
            try:
                await asyncio.wait_for(asyncio.to_thread(self._pull_alerts_sync), timeout=120)
            except asyncio.TimeoutError:
                logger.warning("alert pull timed out (120s)")
            except Exception:
                logger.warning("alert pull task error", exc_info=True)

        self._alert_task = asyncio.ensure_future(_pull())

    @staticmethod
    def _pull_alerts_sync() -> None:
        """Pull latest forecast / ST / CB call from Tushare into DB."""
        import psycopg2
        from app.execution.feed.data_sync import (
            _db_url, sync_forecast, sync_st_list, sync_cb,
        )
        from app.research.data.tushare_service import TushareService

        db_url = _db_url()
        svc = TushareService()
        today = datetime.now().strftime("%Y%m%d")

        with psycopg2.connect(db_url) as conn:
            conn.autocommit = False
            sync_forecast(conn, svc)
            sync_st_list(conn, svc, today)
            # CB call only (lightweight, skip cb_basic/cb_daily here)
            try:
                df = svc.cb_call()
                if df is not None and not df.empty:
                    from app.execution.feed.data_sync import _df_to_values
                    from psycopg2.extras import execute_values
                    cols, vals = _df_to_values(df)
                    with conn.cursor() as cur:
                        cur.execute("TRUNCATE cb_call")
                        execute_values(cur, f"INSERT INTO cb_call ({','.join(cols)}) VALUES %s", vals)
                    conn.commit()
                    logger.info("alert pull: cb_call refreshed %d rows", len(df))
            except Exception:
                conn.rollback()
                logger.warning("alert pull cb_call failed", exc_info=True)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def watch_codes(self) -> list[str]:
        return self._watch_codes

    # ------------------------------------------------------------------
    # Watch list management
    # ------------------------------------------------------------------

    def collect_watch_codes(self) -> list[str]:
        """Gather unique codes from active orders + held positions."""
        from app.execution.engine import trading_engine
        codes: set[str] = set()
        for order in trading_engine.order_mgr.get_open_orders():
            codes.add(order.ts_code)
        for pos in trading_engine.position_book.get_all():
            codes.add(pos.ts_code)
        if not codes:
            codes.add("000001.SZ")
        self._watch_codes = sorted(codes)
        logger.info("watch list refreshed: %d codes", len(self._watch_codes))
        return self._watch_codes

    def add_watch_code(self, code: str) -> None:
        """Add a stock code and load its price limits."""
        if code not in self._watch_codes:
            self._watch_codes.append(code)
            asyncio.ensure_future(self._load_limits_for([code]))

    def set_watch_codes(self, codes: list[str]) -> None:
        self._watch_codes = list(codes)
        logger.info("scheduler watch list set: %d codes", len(codes))

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    async def start(self, codes: list[str] | None = None) -> None:
        if self._running:
            return
        if codes:
            self._watch_codes = list(codes)
        if not self._watch_codes:
            self.collect_watch_codes()
        await self._load_limits()
        await self._load_industry_map()
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("scheduler started (rt_k, %ds interval), watching %d codes",
                     POLL_INTERVAL, len(self._watch_codes))

    async def stop(self) -> None:
        self._running = False
        market_feed.stop()
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("scheduler stopped")

    # ------------------------------------------------------------------
    # Main loop — unified full-market polling
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        from app.core.startup import is_trade_date

        self._today_is_trading = await is_trade_date()
        self._last_check_date = date.today()

        while self._running:
            try:
                if date.today() != self._last_check_date:
                    self._today_is_trading = await is_trade_date()
                    self._last_check_date = date.today()
                    self._settled_today = False
                    self._sync_started_today = False
                    self._synced_today = False
                    self._review_generated_today = False
                    self._plan_generated_today = False
                    self._plan_verified_today = False
                    if self._today_is_trading:
                        from app.execution.engine import trading_engine
                        trading_engine.begin_day()
                        self.collect_watch_codes()
                        await self._load_limits()
                        logger.info("new trade date → begin_day + limits + watch list refreshed")
                    else:
                        logger.info("new day, not a trade date")

                if not self._today_is_trading:
                    self._maybe_pull_news()
                    self._maybe_pull_alerts()
                    await asyncio.sleep(self.NEWS_REFRESH_INTERVAL)
                    continue

                now = datetime.now()
                t = now.time()

                self._maybe_pull_news()
                self._maybe_pull_alerts()
                self._maybe_backfill_mins()

                is_trading = _is_trading_time(now)
                if not hasattr(self, '_last_trading_log') or _time.time() - self._last_trading_log > 60:
                    logger.info("loop tick: now=%s is_trading=%s today_is_trading=%s",
                                now.strftime("%H:%M:%S"), is_trading, self._today_is_trading)
                    self._last_trading_log = _time.time()

                if is_trading:
                    # 补生成：如果 scheduler 在开盘后启动，plan 可能未生成
                    if not self._plan_generated_today:
                        self._run_plan_generation()
                        self._plan_generated_today = True
                    self._maybe_pull_mins()

                    t0 = _time.monotonic()
                    result = await self._fetch_full_market()
                    elapsed = _time.monotonic() - t0

                    if result:
                        snapshot, watched_bars = result
                        global _rt_snapshot, _rt_snapshot_ts
                        _rt_snapshot = snapshot
                        _rt_snapshot_ts = _time.time()
                        _rebuild_rankings_cache(snapshot)
                        _aggregate_minute_bars(snapshot)

                        from app.execution.feed.monitor_engine import monitor_engine
                        monitor_engine.on_tick(snapshot, _cached_sector_rankings)

                        if watched_bars:
                            self._update_limits_from_bars(watched_bars)
                            await market_feed.publish_batch(watched_bars)
                            bars_dict = {b.ts_code: b for b in watched_bars}

                            from app.execution.engine import trading_engine
                            filled = trading_engine.on_bar(bars_dict)
                            if filled:
                                logger.info("matched %d orders | snapshot %d stocks | %.1fs",
                                            len(filled), len(snapshot), elapsed)

                    sleep = max(0.1, POLL_INTERVAL - elapsed)
                    await asyncio.sleep(sleep)

                elif t >= AFTERNOON_CLOSE:
                    if not self._settled_today and t >= SETTLEMENT_TIME:
                        await self._run_settlement()
                        self._settled_today = True
                    if not self._sync_started_today and t >= SYNC_TIME:
                        self._run_daily_sync()
                        self._sync_started_today = True
                        # _synced_today 在 _sync 完成后由回调设 True，
                        # 防止 review 在 sync 未完成时就开始生成
                    if not self._review_generated_today and t >= REVIEW_TIME and self._synced_today:
                        self._run_review_generation()
                        self._review_generated_today = True
                    if not self._plan_verified_today and t >= VERIFY_TIME and self._synced_today:
                        self._run_plan_verification()
                        self._plan_verified_today = True
                    await asyncio.sleep(self.NEWS_REFRESH_INTERVAL)

                else:
                    # Pre-market: generate morning plan at 08:00
                    if not self._plan_generated_today and t >= PLAN_TIME:
                        self._run_plan_generation()
                        self._plan_generated_today = True
                    await asyncio.sleep(self.NEWS_REFRESH_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("scheduler loop error")
                await asyncio.sleep(30)

    # ------------------------------------------------------------------
    # Unified full-market fetch (snapshot + watched bars in ONE call)
    # ------------------------------------------------------------------

    async def _fetch_full_market(self) -> tuple[dict, list[BarData]] | None:
        """Single rt_k call for entire market. Returns (snapshot_dict, watched_bars)."""
        logger.debug("_fetch_full_market, watch=%d codes", len(self._watch_codes))
        watch_set = set(self._watch_codes)

        def _sync() -> tuple[dict, list[BarData]] | None:
            from app.research.data.tushare_service import TushareService
            svc = TushareService()
            now_dt = datetime.now()

            try:
                df = svc.rt_k(ts_code=FULL_MARKET_PATTERN)
            except Exception:
                logger.warning("rt_k full-market fetch failed", exc_info=True)
                return None
            if df is None or df.empty:
                logger.warning("rt_k returned empty data — Tushare may be unavailable or market not open")
                return None
            logger.info("rt_k snapshot: %d stocks", len(df))

            snapshot: dict = {}
            watched_bars: list[BarData] = []

            for _, row in df.iterrows():
                code = str(row.get("ts_code", ""))
                if not code:
                    continue
                pre_close = float(row["pre_close"]) if row.get("pre_close") else 0
                close = float(row.get("close", 0))
                pct_chg = round((close - pre_close) / pre_close * 100, 2) if pre_close else 0

                snapshot[code] = {
                    "ts_code": code,
                    "name": str(row.get("name", "")),
                    "close": close,
                    "pct_chg": pct_chg,
                    "vol": float(row.get("vol", 0)),
                    "amount": float(row.get("amount", 0)),
                    "pre_close": pre_close,
                    "open": float(row.get("open", 0)),
                    "high": float(row.get("high", 0)),
                    "low": float(row.get("low", 0)),
                }

                if code in watch_set:
                    watched_bars.append(BarData(
                        ts_code=code,
                        timestamp=now_dt,
                        open=float(row.get("open", 0)),
                        high=float(row.get("high", 0)),
                        low=float(row.get("low", 0)),
                        close=close,
                        vol=float(row.get("vol", 0)),
                        amount=float(row.get("amount", 0)),
                        pre_close=pre_close if pre_close else None,
                        freq="rt_k",
                    ))

            # rt_idx_k for global indices (BJ not supported by this API)
            IDX = "000001.SH,399001.SZ,399006.SZ,000300.SH,000905.SH,000688.SH"
            try:
                idx_df = svc.rt_idx_k(ts_code=IDX)
                if not idx_df.empty:
                    for _, irow in idx_df.iterrows():
                        ic = str(irow.get("ts_code", ""))
                        if not ic:
                            continue
                        ipc = float(irow["pre_close"]) if irow.get("pre_close") else 0
                        icl = float(irow.get("close", 0))
                        ipct = round((icl - ipc) / ipc * 100, 2) if ipc else 0
                        snapshot[ic] = {
                            "ts_code": ic, "name": str(irow.get("name", "")),
                            "open": float(irow.get("open", 0)),
                            "high": float(irow.get("high", 0)),
                            "low": float(irow.get("low", 0)),
                            "close": icl, "pct_chg": ipct,
                            "vol": float(irow.get("vol", 0)),
                            "amount": float(irow.get("amount", 0)),
                            "pre_close": ipc,
                        }
            except Exception:
                logger.warning("rt_idx_k fetch failed", exc_info=True)

            return snapshot, watched_bars

        return await asyncio.to_thread(_sync)

    # ------------------------------------------------------------------
    # Auto-update price limits from rt_k's pre_close
    # ------------------------------------------------------------------

    @staticmethod
    def _update_limits_from_bars(bars: list[BarData]) -> None:
        """Use rt_k pre_close to compute accurate intraday limits."""
        from app.execution.engine import trading_engine
        from app.execution.api import _limit_pct

        for bar in bars:
            if bar.pre_close and bar.ts_code not in trading_engine._price_limits:
                pct = _limit_pct(bar.ts_code)
                up = round(bar.pre_close * (1 + pct), 2)
                down = round(bar.pre_close * (1 - pct), 2)
                trading_engine._price_limits[bar.ts_code] = (up, down)

    # ------------------------------------------------------------------
    # Settlement & daily sync
    # ------------------------------------------------------------------

    async def _run_settlement(self) -> None:
        from app.execution.engine import trading_engine
        from app.execution.observability.daily_summary import build_summary

        acct = trading_engine.end_day()
        today_str = datetime.now().strftime("%Y%m%d")
        summary = build_summary(
            trade_date=today_str,
            orders=trading_engine.get_orders(),
            audit_events=[],
            account_pnl=acct.today_pnl,
        )
        logger.info(
            "SETTLEMENT %s | filled=%d canceled=%d pnl=%.2f fees=%.2f total_asset=%.2f",
            today_str, summary.orders_filled, summary.orders_canceled,
            summary.total_pnl, summary.total_fee, acct.total_asset,
        )

    def _run_daily_sync(self) -> None:
        """Post-market: run all data syncs in-process + minutes as subprocess."""
        from app.execution.feed.data_sync import run_post_market_sync, run_minutes_subprocess

        trade_date = datetime.now().strftime("%Y%m%d")
        logger.info("post-market sync: starting in-process for %s", trade_date)

        async def _sync():
            try:
                await asyncio.to_thread(run_post_market_sync, trade_date)
                await asyncio.to_thread(run_minutes_subprocess)
                self._synced_today = True
                logger.info("post-market sync completed for %s", trade_date)
            except Exception:
                logger.exception("post-market sync failed")

        asyncio.ensure_future(_sync())

    NEWS_RETENTION_DAYS = 30

    @staticmethod
    def _pull_news_sync() -> None:
        """Pull latest news, purge old ones (>30 days), notify via Redis."""
        logger.info("news pull: calling Tushare...")
        try:
            import json
            import os
            import sys
            from datetime import datetime, timedelta
            from pathlib import Path

            import psycopg2
            from app.core.redis import redis_client

            scripts_dir = str(Path(__file__).resolve().parents[4] / "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)

            from pull_news import fetch_latest_news  # noqa: E402
            from app.research.data.tushare_service import TushareService

            db_url = os.getenv("DATABASE_URL", "").replace(
                "postgresql+asyncpg://", "postgresql://"
            )
            svc = TushareService()
            count = fetch_latest_news(svc, db_url, limit=50)

            cutoff = (datetime.now() - timedelta(days=MarketDataScheduler.NEWS_RETENTION_DAYS)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            with psycopg2.connect(db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM stock_news WHERE datetime < %s", (cutoff,))
                    deleted = cur.rowcount
                conn.commit()
            if deleted:
                logger.info("news cleanup: deleted %d items older than %s", deleted, cutoff)

            if count:
                logger.info("news refresh: inserted %d items", count)
                redis_client.publish(
                    "market:news",
                    json.dumps({"type": "news_update", "count": count}),
                )
                # Classify newly inserted news inline
                try:
                    from app.shared.news_classifier import NewsClassifier
                    clf = NewsClassifier()
                    with psycopg2.connect(db_url) as conn2:
                        with conn2.cursor() as cur2:
                            cur2.execute("SELECT ts_code, name FROM stock_basic WHERE name IS NOT NULL")
                            stock_rows = cur2.fetchall()
                            cur2.execute("SELECT DISTINCT industry_name FROM index_classify WHERE industry_name IS NOT NULL")
                            ind_names = [r[0] for r in cur2.fetchall()]
                            clf.load_reference_data(stock_rows, ind_names)

                            cur2.execute(
                                "SELECT n.id, n.content, n.datetime FROM stock_news n "
                                "LEFT JOIN news_classified nc ON n.id = nc.news_id "
                                "WHERE nc.news_id IS NULL ORDER BY n.id"
                            )
                            unclassified = cur2.fetchall()
                            from psycopg2.extras import execute_values, Json
                            batch = []
                            for nid, content, dt_str in unclassified:
                                r = clf.classify_news(nid, content or "", dt_str or "")
                                d = r.to_db_dict(nid)
                                batch.append((
                                    d["news_id"], d["news_scope"], d["time_slot"],
                                    d["sentiment"],
                                    Json(d["related_codes"]) if d["related_codes"] else None,
                                    Json(d["related_industries"]) if d["related_industries"] else None,
                                    Json(d["keywords"]) if d["keywords"] else None,
                                ))
                            if batch:
                                execute_values(
                                    cur2,
                                    "INSERT INTO news_classified "
                                    "(news_id, news_scope, time_slot, sentiment, related_codes, related_industries, keywords) "
                                    "VALUES %s ON CONFLICT (news_id) DO NOTHING",
                                    batch,
                                )
                        conn2.commit()
                    logger.info("news classify: classified %d new items", len(batch) if batch else 0)
                except Exception:
                    logger.warning("inline news classification failed", exc_info=True)
        except Exception:
            logger.warning("news refresh failed", exc_info=True)

    async def _load_industry_map(self) -> None:
        """Load stock→industry mapping from stock_basic for sector ranking."""
        global _industry_cache
        if self._industry_loaded:
            return
        self._industry_loaded = True
        try:
            import os, psycopg2
            db_url = os.getenv("DATABASE_URL", "").replace(
                "postgresql+asyncpg://", "postgresql://"
            )

            def _load():
                conn = psycopg2.connect(db_url)
                cur = conn.cursor()
                cur.execute(
                    "SELECT ts_code, industry FROM stock_basic "
                    "WHERE list_status = 'L' AND industry IS NOT NULL"
                )
                result = {row[0]: row[1] for row in cur.fetchall()}
                cur.close()
                conn.close()
                return result

            _industry_cache = await asyncio.to_thread(_load)
            logger.info("industry map loaded: %d stocks", len(_industry_cache))
        except Exception:
            logger.warning("failed to load industry map", exc_info=True)

    # ------------------------------------------------------------------
    # Price limits
    # ------------------------------------------------------------------

    async def _load_limits_for(self, codes: list[str]) -> None:
        try:
            from app.core.startup import load_price_limits
            from app.execution.engine import trading_engine
            new_limits = await load_price_limits(codes)
            trading_engine._price_limits.update(new_limits)
        except Exception:
            logger.exception("failed to load limits for %s", codes)

    async def _load_limits(self) -> None:
        if self._watch_codes:
            await self._load_limits_for(self._watch_codes)

    # ------------------------------------------------------------------
    # Review & plan generation
    # ------------------------------------------------------------------

    def _run_review_generation(self) -> None:
        """Post-market: generate daily review via CLI subprocess.

        Called at ~16:00 after data_sync completes. Launches
        scripts/review_cli.sh which calls `claude-sg -p` to produce the
        review, then saves structured data to daily_review via API.
        """
        trade_date = datetime.now().strftime("%Y%m%d")
        logger.info("review generation: triggering for %s", trade_date)

        async def _gen():
            try:
                await asyncio.to_thread(self._run_cli_script, "review_cli.sh", trade_date)
            except Exception:
                logger.exception("review generation failed for %s", trade_date)

        asyncio.ensure_future(_gen())

    def _run_plan_verification(self) -> None:
        """Post-market: auto-verify today's morning plan vs actual results.

        Called at ~16:05 after data_sync completes. Compares predicted
        direction, watchlist, risk alerts, and sectors against actual
        closing data and writes accuracy_score back to daily_plan.
        """
        trade_date = datetime.now().strftime("%Y%m%d")
        logger.info("plan verification: triggering for %s", trade_date)

        async def _verify():
            try:
                from app.shared.plan_verifier import auto_verify_plan
                result = await auto_verify_plan(trade_date)
                if result:
                    logger.info(
                        "plan verification complete: %s → score=%.1f result=%s",
                        trade_date, result["accuracy_score"], result["actual_result"],
                    )
                else:
                    logger.info("plan verification: skipped for %s (no plan or already verified)", trade_date)
            except Exception:
                logger.exception("plan verification failed for %s", trade_date)

        asyncio.ensure_future(_verify())

    def _run_plan_generation(self) -> None:
        """Pre-market: generate morning plan via CLI subprocess.

        Called at ~08:00 on trade dates. Launches
        scripts/morning_plan_cli.sh which calls `claude-sg -p` to produce
        the plan, then saves structured data to daily_plan via API.
        """
        trade_date = datetime.now().strftime("%Y%m%d")
        logger.info("plan generation: triggering for %s", trade_date)

        async def _gen():
            try:
                await asyncio.to_thread(self._run_cli_script, "morning_plan_cli.sh", trade_date)
            except Exception:
                logger.exception("plan generation failed for %s", trade_date)

        asyncio.ensure_future(_gen())

    @staticmethod
    def _run_cli_script(script_name: str, trade_date: str) -> None:
        """Run a shell script from scripts/ dir as a subprocess with logging."""
        import subprocess
        import sys
        from pathlib import Path

        scripts_dir = Path(__file__).resolve().parents[4] / "scripts"
        script = scripts_dir / script_name

        if not script.exists():
            logger.warning("CLI script not found: %s (will be created later)", script)
            return

        log_dir = scripts_dir.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"{script_name.replace('.sh', '')}_{trade_date}.log"

        try:
            fh = open(log_file, "a", encoding="utf-8")
            # Windows: 用 Git\bin\bash.exe（支持 /e/ 路径映射），
            # 而非 Git\usr\bin\bash.EXE（MSYS2 底层，不支持）
            bash_cmd = "bash"
            if sys.platform == "win32":
                git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
                if git_bash.exists():
                    bash_cmd = str(git_bash)
            # bash 参数用 POSIX 路径（/e/...），cwd 用 Windows 原生路径
            script_str = str(script).replace("\\", "/")
            if sys.platform == "win32" and len(script_str) > 2 and script_str[1] == ":":
                script_str = "/" + script_str[0].lower() + script_str[2:]
            proc = subprocess.Popen(
                [bash_cmd, script_str, trade_date],
                cwd=str(scripts_dir.parent),
                env={**__import__("os").environ, "TRADE_DATE": trade_date},
                stdout=fh,
                stderr=subprocess.STDOUT,
            )
            logger.info("%s subprocess started (PID=%d), log=%s",
                        script_name, proc.pid, log_file)
        except Exception:
            logger.exception("failed to start %s subprocess", script_name)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict:
        snap_age = round(_time.time() - _rt_snapshot_ts, 1) if _rt_snapshot_ts else None
        return {
            "running": self._running,
            "trading_time": _is_trading_time(),
            "is_trade_date": self._today_is_trading,
            "watch_codes": len(self._watch_codes),
            "codes": self._watch_codes[:10],
            "poll_interval": POLL_INTERVAL,
            "snapshot_stocks": len(_rt_snapshot),
            "snapshot_age_s": snap_age,
            "data_source": "rt_k (full-market)",
            "review_generated_today": self._review_generated_today,
            "plan_generated_today": self._plan_generated_today,
            "plan_verified_today": self._plan_verified_today,
        }


scheduler = MarketDataScheduler()
