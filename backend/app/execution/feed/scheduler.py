"""MarketDataScheduler — feeds realtime minute data during trading hours.

Lifecycle (Phase 4.6):
  - Auto-started at FastAPI startup on trade dates
  - watch_codes auto-collected from OMS positions + active orders
  - During trading hours: polls Tushare rt_min → Redis → on_bar() matching
  - Non-trading hours / non-trade dates: sleeps efficiently
  - New orders automatically add their stock code to watch list
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time as dtime

from app.shared.interfaces.models import BarData
from app.execution.feed.market_feed import market_feed

logger = logging.getLogger(__name__)

MORNING_OPEN = dtime(9, 30)
MORNING_CLOSE = dtime(11, 30)
AFTERNOON_OPEN = dtime(13, 0)
AFTERNOON_CLOSE = dtime(15, 0)

POLL_INTERVAL = 60


def _is_trading_time(now: datetime | None = None) -> bool:
    t = (now or datetime.now()).time()
    return (MORNING_OPEN <= t <= MORNING_CLOSE) or (AFTERNOON_OPEN <= t <= AFTERNOON_CLOSE)


def _seconds_until_next_session(now: datetime | None = None) -> int:
    dt = now or datetime.now()
    t = dt.time()
    if t < MORNING_OPEN:
        target = dt.replace(hour=9, minute=30, second=0, microsecond=0)
    elif MORNING_CLOSE < t < AFTERNOON_OPEN:
        target = dt.replace(hour=13, minute=0, second=0, microsecond=0)
    else:
        from datetime import timedelta
        next_day = dt.date() + timedelta(days=1)
        target = datetime.combine(next_day, dtime(9, 30))
    diff = (target - dt).total_seconds()
    return max(int(diff), 10)


async def _fetch_realtime_bars(ts_codes: list[str]) -> list[BarData]:
    """Fetch realtime minute bars from Tushare rt_min (sync, runs in thread)."""

    def _sync_fetch() -> list[BarData]:
        from app.research.data.tushare_service import TushareService
        svc = TushareService()
        bars: list[BarData] = []
        now = datetime.now()

        for code in ts_codes:
            try:
                df = svc.query("rt_min", ts_code=code, freq="1min")
                if df.empty:
                    continue
                latest = df.iloc[0]
                bar = BarData(
                    ts_code=code,
                    timestamp=now,
                    open=float(latest.get("open", 0)),
                    high=float(latest.get("high", 0)),
                    low=float(latest.get("low", 0)),
                    close=float(latest.get("close", 0)),
                    vol=float(latest.get("vol", 0)),
                    amount=float(latest.get("amount", 0)),
                    freq="1min",
                )
                bars.append(bar)
            except Exception:
                logger.warning("rt_min fetch failed for %s", code, exc_info=True)
        return bars

    return await asyncio.to_thread(_sync_fetch)


SETTLEMENT_TIME = dtime(15, 1)
SYNC_TIME = dtime(15, 30)


class MarketDataScheduler:

    def __init__(self):
        self._running = False
        self._task: asyncio.Task | None = None
        self._watch_codes: list[str] = []
        self._today_is_trading: bool | None = None
        self._last_check_date: date | None = None
        self._settled_today = False
        self._synced_today = False

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
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("scheduler started, watching %d codes", len(self._watch_codes))

    async def stop(self) -> None:
        self._running = False
        market_feed.stop()
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("scheduler stopped")

    # ------------------------------------------------------------------
    # Main loop (trade-date + trading-time aware)
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        from app.core.startup import is_trade_date

        self._today_is_trading = await is_trade_date()
        self._last_check_date = date.today()

        while self._running:
            try:
                # ---- Day change detection ----
                if date.today() != self._last_check_date:
                    self._today_is_trading = await is_trade_date()
                    self._last_check_date = date.today()
                    self._settled_today = False
                    self._synced_today = False
                    if self._today_is_trading:
                        from app.execution.engine import trading_engine
                        trading_engine.begin_day()
                        self.collect_watch_codes()
                        await self._load_limits()
                        logger.info("new trade date → begin_day + limits + watch list refreshed")
                    else:
                        logger.info("new day, not a trade date")

                # ---- Non-trade date → idle ----
                if not self._today_is_trading:
                    await asyncio.sleep(1800)
                    continue

                now = datetime.now()
                t = now.time()

                # ---- Trading hours → poll + match ----
                if _is_trading_time(now):
                    bars = await _fetch_realtime_bars(self._watch_codes)
                    if bars:
                        await market_feed.publish_batch(bars)
                        bars_dict = {b.ts_code: b for b in bars}

                        from app.execution.engine import trading_engine
                        filled = trading_engine.on_bar(bars_dict)
                        if filled:
                            logger.info("matched %d orders from %d bars", len(filled), len(bars))
                        else:
                            logger.info("published %d bars, no orders matched", len(bars))
                    await asyncio.sleep(POLL_INTERVAL)

                # ---- Post-market: settlement + sync ----
                elif t >= AFTERNOON_CLOSE:
                    if not self._settled_today and t >= SETTLEMENT_TIME:
                        await self._run_settlement()
                        self._settled_today = True

                    if not self._synced_today and t >= SYNC_TIME:
                        self._run_daily_sync()
                        self._synced_today = True

                    await asyncio.sleep(600)

                # ---- Pre-market / lunch ----
                else:
                    wait = _seconds_until_next_session(now)
                    logger.info("pre-market/lunch, sleeping %ds", min(wait, 300))
                    await asyncio.sleep(min(wait, 300))

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("scheduler loop error")
                await asyncio.sleep(30)

    # ------------------------------------------------------------------
    # Settlement & daily sync
    # ------------------------------------------------------------------

    async def _run_settlement(self) -> None:
        """End-of-day settlement: finalize PnL, persist state, log summary."""
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
            today_str,
            summary.orders_filled,
            summary.orders_canceled,
            summary.total_pnl,
            summary.total_fee,
            acct.total_asset,
        )

    @staticmethod
    def _run_daily_sync() -> None:
        """Trigger post-market data sync as background subprocess."""
        from app.core.startup import _trigger_background_sync
        logger.info("triggering post-market data sync...")
        _trigger_background_sync()

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
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict:
        return {
            "running": self._running,
            "trading_time": _is_trading_time(),
            "is_trade_date": self._today_is_trading,
            "watch_codes": len(self._watch_codes),
            "codes": self._watch_codes[:10],
        }


scheduler = MarketDataScheduler()
