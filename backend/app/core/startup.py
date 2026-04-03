"""Startup checks — data freshness, OMS state recovery, trade calendar.

Called during FastAPI lifespan. All queries are async.
If data is stale, a background subprocess runs sync_incremental.py.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text

from app.core.database import async_session

logger = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"


# ---------------------------------------------------------------------------
# Trade calendar helpers (reused by scheduler, settlement, etc.)
# ---------------------------------------------------------------------------

async def is_trade_date(d: date | None = None) -> bool:
    """Check if *d* (default: today) is a trading day via trade_cal.

    Falls back to weekday heuristic (Mon-Fri = trading) if the date
    is missing from trade_cal to prevent scheduler from idling
    all day when the calendar hasn't been synced far enough ahead.
    """
    if d is None:
        d = date.today()
    cal_date = d.strftime("%Y%m%d")
    async with async_session() as session:
        row = await session.execute(
            text(
                "SELECT is_open FROM trade_cal "
                "WHERE cal_date = :d AND exchange = 'SSE' LIMIT 1"
            ),
            {"d": cal_date},
        )
        val = row.scalar_one_or_none()

    if val is not None:
        return val == 1

    is_weekday = d.weekday() < 5
    if is_weekday:
        logger.warning(
            "trade_cal missing %s — falling back to weekday heuristic (assume trading). "
            "Run sync_incremental.py to update calendar.",
            cal_date,
        )
    return is_weekday


async def last_trade_date(before: date | None = None) -> str:
    """Most recent trade date (YYYYMMDD) on or before *before*."""
    if before is None:
        before = date.today()
    cal_str = before.strftime("%Y%m%d")
    async with async_session() as session:
        row = await session.execute(
            text(
                "SELECT cal_date FROM trade_cal "
                "WHERE is_open = 1 AND cal_date <= :d "
                "ORDER BY cal_date DESC LIMIT 1"
            ),
            {"d": cal_str},
        )
        return row.scalar_one_or_none() or cal_str


async def _latest_date(table: str, col: str = "trade_date") -> str | None:
    async with async_session() as session:
        row = await session.execute(text(f"SELECT max({col}) FROM {table}"))
        return row.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Startup orchestrator
# ---------------------------------------------------------------------------

async def startup_checks() -> dict:
    """Run all startup checks; return summary dict (stored in app.state)."""
    summary: dict = {"data": {}, "sync_triggered": False, "oms": {}}

    await _ensure_trade_cal_coverage()

    is_today_td = await is_trade_date()
    now = datetime.now()

    if is_today_td and now.hour < 16:
        from datetime import timedelta
        expected_td = await last_trade_date(before=date.today() - timedelta(days=1))
    else:
        expected_td = await last_trade_date()

    # ---- Data freshness ----
    cal_latest = await _latest_date("trade_cal", "cal_date")
    daily_latest = await _latest_date("stock_daily")
    limit_latest = await _latest_date("stock_limit")

    summary["data"] = {
        "trade_cal": cal_latest,
        "stock_daily": daily_latest,
        "stock_limit": limit_latest,
        "expected_trade_date": expected_td,
    }

    needs_sync = False
    today_str = date.today().strftime("%Y%m%d")

    if cal_latest and cal_latest < today_str:
        logger.warning("trade_cal stale: latest=%s today=%s", cal_latest, today_str)
        needs_sync = True

    if daily_latest and daily_latest < expected_td:
        gap = _date_gap(daily_latest, expected_td)
        logger.warning("stock_daily behind %d days: %s → %s", gap, daily_latest, expected_td)
        needs_sync = True
    else:
        logger.info("stock_daily up-to-date: %s (expected: %s)", daily_latest, expected_td)

    if limit_latest and limit_latest < expected_td:
        logger.warning("stock_limit behind: %s → %s", limit_latest, expected_td)
        needs_sync = True

    if needs_sync:
        import asyncio
        from app.execution.feed.data_sync import run_post_market_sync

        async def _bg_sync():
            try:
                await asyncio.to_thread(run_post_market_sync, expected_td)
            except Exception:
                logger.exception("startup background sync failed")

        asyncio.ensure_future(_bg_sync())
        summary["sync_triggered"] = True
        logger.info("startup: triggered in-process sync for %s", expected_td)

    # ---- OMS state recovery ----
    from app.execution.engine import trading_engine
    oms = await trading_engine.restore_from_db()
    summary["oms"] = oms

    # ---- Auto-start scheduler on trade dates ----
    from app.execution.feed.scheduler import scheduler
    if is_today_td:
        await scheduler.start()
        summary["scheduler"] = "auto-started"
        logger.info("trade date → scheduler auto-started")
    else:
        await scheduler.start()
        summary["scheduler"] = "started (non-trade-date, will idle)"
        logger.info("non-trade date → scheduler started but will idle")

    # ---- Final summary ----
    summary["is_trade_date"] = is_today_td

    logger.info(
        "startup OK | trade_date=%s | daily=%s | orders=%d active, %d positions",
        "yes" if is_today_td else "no",
        daily_latest,
        oms.get("active_orders", 0),
        oms.get("positions", 0),
    )
    return summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _ensure_trade_cal_coverage() -> None:
    """Ensure trade_cal covers at least 30 days into the future.

    If the max cal_date is behind, synchronously pull from Tushare to fill the gap.
    This prevents the scheduler from thinking today is not a trade date.
    """
    today = date.today()
    today_str = today.strftime("%Y%m%d")

    cal_max = await _latest_date("trade_cal", "cal_date")
    if cal_max and cal_max >= today_str:
        return

    logger.warning(
        "trade_cal max=%s is behind today=%s — pulling calendar from Tushare now",
        cal_max, today_str,
    )
    try:
        import asyncio
        await asyncio.to_thread(_sync_trade_cal_now, cal_max or today_str, today_str)
    except Exception:
        logger.exception("failed to update trade_cal at startup")


def _sync_trade_cal_now(start: str, today_str: str) -> None:
    """Synchronous trade_cal update (runs in thread)."""
    from datetime import timedelta as td
    from app.research.data.tushare_service import TushareService
    from sqlalchemy import create_engine

    future_end = (datetime.strptime(today_str, "%Y%m%d") + td(days=90)).strftime("%Y%m%d")
    svc = TushareService()
    df = svc.trade_cal(start_date=start, end_date=future_end)
    if df.empty:
        return

    from app.core.config import settings
    sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg")
    eng = create_engine(sync_url, echo=False)
    with eng.begin() as conn:
        from sqlalchemy import text as sa_text
        conn.execute(sa_text("DELETE FROM trade_cal WHERE cal_date >= :s"), {"s": start})
        df.to_sql("trade_cal", conn, if_exists="append", index=False)
    logger.info("trade_cal updated: %d rows (up to %s)", len(df), future_end)


async def load_price_limits(codes: list[str]) -> dict[str, tuple[float, float]]:
    """Calculate next-day up/down limits from latest close for given codes."""
    if not codes:
        return {}

    placeholders = ", ".join(f":c{i}" for i in range(len(codes)))
    params = {f"c{i}": c for i, c in enumerate(codes)}

    async with async_session() as session:
        result = await session.execute(
            text(f"""
                SELECT DISTINCT ON (d.ts_code) d.ts_code, d.close, b.name
                FROM stock_daily d
                JOIN stock_basic b ON d.ts_code = b.ts_code
                WHERE d.ts_code IN ({placeholders})
                ORDER BY d.ts_code, d.trade_date DESC
            """),
            params,
        )
        rows = result.all()

    limits: dict[str, tuple[float, float]] = {}
    for ts_code, close, name in rows:
        code = ts_code.split(".")[0]
        is_st = "ST" in (name or "").upper()

        if code.startswith("3") or code.startswith("688"):
            pct = 0.20
        elif code.startswith("8"):
            pct = 0.30
        elif is_st:
            pct = 0.05
        else:
            pct = 0.10

        limits[ts_code] = (round(close * (1 + pct), 2), round(close * (1 - pct), 2))

    logger.info("calculated price limits for %d / %d codes", len(limits), len(codes))
    return limits


def _date_gap(a: str, b: str) -> int:
    d1 = datetime.strptime(a, "%Y%m%d")
    d2 = datetime.strptime(b, "%Y%m%d")
    return max(0, (d2 - d1).days)


def _trigger_background_sync() -> None:
    """Legacy entry point — kept for backward compatibility but delegates to data_sync."""
    from app.execution.feed.data_sync import run_post_market_sync
    today = date.today().strftime("%Y%m%d")
    run_post_market_sync(today)
