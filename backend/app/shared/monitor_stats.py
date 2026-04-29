"""Monitor event query and stats API — P2-4.

Provides:
- GET /api/v1/monitor/events       — filtered event list (index anomalies)
- GET /api/v1/monitor/events/stats — aggregated stats for verification
- GET /api/v1/monitor/largecap     — filtered largecap alert list
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time as dt_time

from fastapi import APIRouter, Query
from sqlalchemy import text
from app.core.database import async_session

logger = logging.getLogger(__name__)

monitor_stats_router = APIRouter(prefix="/api/v1/monitor", tags=["monitor"])

# After 15:10 we consider the session closed enough for backfill to be meaningful.
# (Scheduler runs backfill at 16:10; giving the user a tighter fallback here.)
_BACKFILL_AFTER = dt_time(15, 10)


async def _maybe_backfill_events_for(date_iso: str) -> int:
    """One-shot safety net: if *date_iso* is the latest event date, the market
    has already closed, and at least one monitor_events row has ret_eod IS NULL,
    run backfill_monitor_returns synchronously and return how many rows were
    updated.  No-op otherwise.  Never touches base market-data tables.
    """
    if not date_iso:
        return 0
    now = datetime.now()
    try:
        ed = datetime.strptime(date_iso, "%Y-%m-%d").date()
    except ValueError:
        return 0
    if ed > now.date():
        return 0
    # If the target date is today, only attempt after session close.
    if ed == now.date() and now.time() < _BACKFILL_AFTER:
        return 0
    try:
        async with async_session() as session:
            r = await session.execute(text(
                "SELECT MAX(event_date) FROM monitor_events"
            ))
            latest = r.scalar_one_or_none()
            if not latest or str(latest) != date_iso:
                return 0
            r2 = await session.execute(text(
                "SELECT COUNT(*) FROM monitor_events "
                "WHERE event_date = :d AND ret_eod IS NULL"
            ), {"d": date_iso})
            pending = r2.scalar_one_or_none() or 0
        if pending <= 0:
            return 0

        trade_date = date_iso.replace("-", "")
        logger.info(
            "monitor events on-demand backfill: trade_date=%s pending=%s",
            trade_date, pending,
        )
        from app.execution.feed.monitor_backfill import backfill_monitor_returns
        result = await asyncio.to_thread(backfill_monitor_returns, trade_date)
        updated = result.get("events_updated", 0) if isinstance(result, dict) else 0
        logger.info(
            "monitor events on-demand backfill done: trade_date=%s events_updated=%s alerts_updated=%s",
            trade_date, updated,
            result.get("alerts_updated") if isinstance(result, dict) else None,
        )
        return updated
    except Exception:
        logger.exception("monitor events on-demand backfill failed for %s", date_iso)
        return 0

# ── Shared SQL fragments ──
# "effective return" = first non-NULL of ret_15m, ret_30m, ret_eod.
# This is what we use for win_rate: direction consistency check.
_EFF_RET = "COALESCE(ret_15m, ret_30m, ret_eod)"
_CORRECT = f"""(
    {_EFF_RET} IS NOT NULL AND (
        (delta_pct > 0 AND {_EFF_RET} > 0) OR
        (delta_pct < 0 AND {_EFF_RET} < 0)
    )
)"""
_VERIFIED = f"({_EFF_RET} IS NOT NULL)"


@monitor_stats_router.get("/events")
async def get_monitor_events(
    date: str = Query("", description="YYYY-MM-DD, empty = latest available"),
    pattern: str = Query("", description="Filter by pattern"),
    level: str = Query("", description="Filter by level"),
    min_score: int = Query(0, description="Minimum event_score"),
    only_watchlist_hit: bool = Query(False),
    only_position_hit: bool = Query(False),
    limit: int = Query(100, le=500),
):
    """Return filtered monitor events for a given date."""
    async with async_session() as session:
        if not date:
            r = await session.execute(text(
                "SELECT MAX(event_date) FROM monitor_events"
            ))
            row = r.fetchone()
            date = row[0] if row and row[0] else ""
            if not date:
                return {"events": [], "trade_date": "", "total": 0}

    # One-shot fallback: if the requested date is the latest event_date, the
    # session has closed, and some ret_eod are still NULL, run backfill now.
    await _maybe_backfill_events_for(str(date))

    async with async_session() as session:
        conditions = ["event_date = :d"]
        params: dict = {"d": date, "lim": limit}

        if pattern:
            conditions.append("pattern = :pat")
            params["pat"] = pattern
        if level:
            conditions.append("level = :lev")
            params["lev"] = level
        if min_score > 0:
            conditions.append("event_score >= :ms")
            params["ms"] = min_score
        if only_watchlist_hit:
            conditions.append("hit_count > 0 AND watchlist_hits_json != '[]'")
        if only_position_hit:
            conditions.append("hit_count > 0 AND position_hits_json != '[]'")

        where = " AND ".join(conditions)
        r = await session.execute(text(f"""
            SELECT id, event_date, event_ts, event_time, index_code, index_name,
                   "window", delta_pct, price_now, price_then,
                   pattern, level, event_score,
                   watchlist_hits_json, position_hits_json, hit_count,
                   top_sectors_json, summary, action_hint,
                   ret_5m, ret_15m, ret_30m, max_move_30m, min_move_30m, ret_eod,
                   ret_60m, max_up_60m, max_down_60m,
                   close_pos_30m, close_pos_60m, path_label
            FROM monitor_events
            WHERE {where}
            ORDER BY event_score DESC, event_ts DESC
            LIMIT :lim
        """), params)

        events = []
        for row in r.fetchall():
            events.append({
                "id": row[0], "event_date": row[1], "event_ts": row[2],
                "event_time": row[3], "index_code": row[4], "index_name": row[5],
                "window": row[6], "delta_pct": row[7], "price_now": row[8],
                "price_then": row[9], "pattern": row[10], "level": row[11],
                "event_score": row[12],
                "watchlist_hits_json": row[13], "position_hits_json": row[14],
                "hit_count": row[15], "top_sectors_json": row[16],
                "summary": row[17], "action_hint": row[18],
                "ret_5m": row[19], "ret_15m": row[20], "ret_30m": row[21],
                "max_move_30m": row[22], "min_move_30m": row[23],
                "ret_eod": row[24],
                "ret_60m": row[25], "max_up_60m": row[26], "max_down_60m": row[27],
                "close_pos_30m": row[28], "close_pos_60m": row[29],
                "path_label": row[30],
            })

        cr = await session.execute(text(f"""
            SELECT COUNT(*) FROM monitor_events WHERE {where}
        """), params)
        total = cr.scalar() or 0

        return {"events": events, "trade_date": date, "total": total}


@monitor_stats_router.get("/largecap")
async def get_monitor_largecap(
    date: str = Query("", description="YYYY-MM-DD, empty = latest"),
    limit: int = Query(100, le=500),
):
    """Return largecap alerts for a given date."""
    async with async_session() as session:
        if not date:
            r = await session.execute(text(
                "SELECT MAX(event_date) FROM monitor_largecap_alerts"
            ))
            row = r.fetchone()
            date = row[0] if row and row[0] else ""
            if not date:
                return {"alerts": [], "trade_date": "", "total": 0}

        r = await session.execute(text("""
            SELECT id, event_date, event_ts, event_time, ts_code, name,
                   price_now, price_yesterday, price_chg_pct,
                   vol_now, vol_yesterday, vol_ratio, circ_mv_yi,
                   sector, sector_strong, in_watchlist, in_position,
                   ret_5m, ret_15m, ret_30m,
                   ret_60m, ret_eod,
                   max_up_30m, max_down_30m, max_up_60m, max_down_60m,
                   close_pos_30m, close_pos_60m, path_label,
                   entry_price, entry_time
            FROM monitor_largecap_alerts
            WHERE event_date = :d
            ORDER BY event_ts DESC
            LIMIT :lim
        """), {"d": date, "lim": limit})

        alerts = []
        for row in r.fetchall():
            alerts.append({
                "id": row[0], "event_date": row[1], "event_ts": row[2],
                "event_time": row[3], "ts_code": row[4], "name": row[5],
                "price_now": row[6], "price_yesterday": row[7],
                "price_chg_pct": row[8], "vol_now": row[9],
                "vol_yesterday": row[10], "vol_ratio": row[11],
                "circ_mv_yi": row[12], "sector": row[13],
                "sector_strong": row[14], "in_watchlist": row[15],
                "in_position": row[16],
                "ret_5m": row[17], "ret_15m": row[18], "ret_30m": row[19],
                "ret_60m": row[20], "ret_eod": row[21],
                "max_up_30m": row[22], "max_down_30m": row[23],
                "max_up_60m": row[24], "max_down_60m": row[25],
                "close_pos_30m": row[26], "close_pos_60m": row[27],
                "path_label": row[28],
                "entry_price": row[29], "entry_time": row[30],
            })

        cr = await session.execute(text("""
            SELECT COUNT(*) FROM monitor_largecap_alerts WHERE event_date = :d
        """), {"d": date})
        total = cr.scalar() or 0

        return {"alerts": alerts, "trade_date": date, "total": total}


@monitor_stats_router.get("/events/stats")
async def get_monitor_event_stats(
    start_date: str = Query("", description="YYYY-MM-DD start"),
    end_date: str = Query("", description="YYYY-MM-DD end, empty = latest"),
    days: int = Query(30, description="Lookback days if no start/end"),
):
    """Aggregated stats for index anomalies + largecap alerts.

    Win rate uses COALESCE(ret_15m, ret_30m, ret_eod) — the best available
    return horizon, so index events (which only have ret_eod) are still counted.
    """
    async with async_session() as session:
        if not end_date:
            r = await session.execute(text("""
                SELECT GREATEST(
                    (SELECT MAX(event_date) FROM monitor_events),
                    (SELECT MAX(event_date) FROM monitor_largecap_alerts)
                )
            """))
            row = r.fetchone()
            end_date = row[0] if row and row[0] else ""
        if not start_date and end_date:
            from datetime import datetime, timedelta
            try:
                ed = datetime.strptime(end_date, "%Y-%m-%d")
                start_date = (ed - timedelta(days=days)).strftime("%Y-%m-%d")
            except ValueError:
                start_date = ""

        if not start_date or not end_date:
            return {
                "by_pattern": [], "by_level": [], "by_score_band": [],
                "hit_comparison": {}, "largecap_stats": {},
                "date_range": [start_date, end_date],
            }

        base_where = "event_date >= :sd AND event_date <= :ed"
        params = {"sd": start_date, "ed": end_date}

        # ── Index summary (direct from DB, not derived from groups) ──
        idx_r = await session.execute(text(f"""
            SELECT
                COUNT(*) AS cnt,
                ROUND(AVG(ret_eod)::numeric, 3),
                COUNT(*) FILTER (WHERE {_CORRECT}),
                COUNT(*) FILTER (WHERE {_VERIFIED})
            FROM monitor_events
            WHERE {base_where}
        """), params)
        idx_row = idx_r.fetchone()
        total_event_count = idx_row[0] if idx_row else 0
        index_summary = {
            "count": total_event_count,
            "avg_ret_eod": _f(idx_row[1]) if idx_row else None,
            "win_rate": _wr(idx_row[2], idx_row[3]) if idx_row else None,
            # Backfill of indexes is limited to the close-of-day window —
            # minute-level index klines are not synced, so 15m/30m are
            # marked unavailable instead of silently returning NULL.
            "avg_ret_15m": None,
            "avg_ret_30m": None,
            "win_rate_15m": None,
            "win_rate_30m": None,
        }

        # ── By pattern ──
        r = await session.execute(text(f"""
            SELECT COALESCE(NULLIF(TRIM(pattern), ''), 'unknown') AS pattern,
                   COUNT(*) AS cnt,
                   ROUND(AVG(ret_eod)::numeric, 3) AS avg_ret_eod,
                   ROUND(AVG(ret_15m)::numeric, 3) AS avg_ret_15m,
                   ROUND(AVG(ret_30m)::numeric, 3) AS avg_ret_30m,
                   ROUND(AVG(event_score)::numeric, 1) AS avg_score,
                   COUNT(*) FILTER (WHERE {_CORRECT}) AS correct_count,
                   COUNT(*) FILTER (WHERE {_VERIFIED}) AS verified_count
            FROM monitor_events
            WHERE {base_where}
            GROUP BY pattern
            ORDER BY cnt DESC
        """), params)
        by_pattern = [
            {"pattern": row[0], "count": row[1],
             "avg_ret_eod": _f(row[2]), "avg_ret_15m": _f(row[3]),
             "avg_ret_30m": _f(row[4]), "avg_score": _f(row[5]),
             "win_rate": _wr(row[6], row[7])}
            for row in r.fetchall()
        ]

        # ── By level ──
        r = await session.execute(text(f"""
            SELECT COALESCE(NULLIF(TRIM(level), ''), 'unknown') AS level,
                   COUNT(*) AS cnt,
                   ROUND(AVG(ret_eod)::numeric, 3),
                   ROUND(AVG(ret_15m)::numeric, 3),
                   ROUND(AVG(ret_30m)::numeric, 3),
                   ROUND(AVG(event_score)::numeric, 1),
                   COUNT(*) FILTER (WHERE {_CORRECT}),
                   COUNT(*) FILTER (WHERE {_VERIFIED})
            FROM monitor_events
            WHERE {base_where}
            GROUP BY level
            ORDER BY CASE level WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END
        """), params)
        by_level = [
            {"level": row[0], "count": row[1],
             "avg_ret_eod": _f(row[2]), "avg_ret_15m": _f(row[3]),
             "avg_ret_30m": _f(row[4]), "avg_score": _f(row[5]),
             "win_rate": _wr(row[6], row[7])}
            for row in r.fetchall()
        ]

        # ── By score band ──
        r = await session.execute(text(f"""
            SELECT
                CASE WHEN event_score >= 80 THEN '80+'
                     WHEN event_score >= 60 THEN '60-79'
                     ELSE '0-59' END AS band,
                COUNT(*),
                ROUND(AVG(ret_eod)::numeric, 3),
                ROUND(AVG(ret_15m)::numeric, 3),
                ROUND(AVG(ret_30m)::numeric, 3),
                COUNT(*) FILTER (WHERE {_CORRECT}),
                COUNT(*) FILTER (WHERE {_VERIFIED})
            FROM monitor_events
            WHERE {base_where}
            GROUP BY band
            ORDER BY band DESC
        """), params)
        by_score_band = [
            {"band": row[0], "count": row[1],
             "avg_ret_eod": _f(row[2]), "avg_ret_15m": _f(row[3]),
             "avg_ret_30m": _f(row[4]),
             "win_rate": _wr(row[5], row[6])}
            for row in r.fetchall()
        ]

        # ── Hit vs non-hit ──
        r = await session.execute(text(f"""
            SELECT
                CASE WHEN hit_count > 0 THEN 'hit' ELSE 'no_hit' END AS grp,
                COUNT(*),
                ROUND(AVG(ret_eod)::numeric, 3),
                ROUND(AVG(ret_15m)::numeric, 3),
                ROUND(AVG(event_score)::numeric, 1),
                COUNT(*) FILTER (WHERE {_CORRECT}),
                COUNT(*) FILTER (WHERE {_VERIFIED})
            FROM monitor_events
            WHERE {base_where}
            GROUP BY grp
        """), params)
        hit_comparison = {}
        for row in r.fetchall():
            hit_comparison[row[0]] = {
                "count": row[1], "avg_ret_eod": _f(row[2]),
                "avg_ret_15m": _f(row[3]), "avg_score": _f(row[4]),
                "win_rate": _wr(row[5], row[6]),
            }

        # ── Largecap alert stats ──
        # Largecap is a buy-simulation (entry=next-bar open), so win rate is
        # "did the trade make money" — ret_xx > 0 — not direction-consistency.
        lc_r = await session.execute(text(f"""
            SELECT
                COUNT(*) AS cnt,
                ROUND(AVG(ret_5m)::numeric, 3),
                ROUND(AVG(ret_15m)::numeric, 3),
                ROUND(AVG(ret_30m)::numeric, 3),
                ROUND(AVG(ret_eod)::numeric, 3),
                COUNT(*) FILTER (WHERE ret_15m > 0),
                COUNT(*) FILTER (WHERE ret_15m IS NOT NULL),
                COUNT(*) FILTER (WHERE ret_30m > 0),
                COUNT(*) FILTER (WHERE ret_30m IS NOT NULL),
                COUNT(*) FILTER (WHERE ret_eod > 0),
                COUNT(*) FILTER (WHERE ret_eod IS NOT NULL),
                COUNT(*) FILTER (WHERE in_watchlist = true),
                COUNT(*) FILTER (WHERE in_position = true),
                COUNT(*) FILTER (WHERE sector_strong = true)
            FROM monitor_largecap_alerts
            WHERE {base_where}
        """), params)
        lc_row = lc_r.fetchone()
        largecap_stats = {}
        if lc_row and lc_row[0] > 0:
            largecap_stats = {
                "count": lc_row[0],
                "avg_ret_5m": _f(lc_row[1]),
                "avg_ret_15m": _f(lc_row[2]),
                "avg_ret_30m": _f(lc_row[3]),
                "avg_ret_eod": _f(lc_row[4]),
                "win_rate_15m": _wr(lc_row[5], lc_row[6]),
                "win_rate_30m": _wr(lc_row[7], lc_row[8]),
                "win_rate_eod": _wr(lc_row[9], lc_row[10]),
                # Back-compat: `win_rate` used to mean 15m-based rate.
                "win_rate": _wr(lc_row[5], lc_row[6]),
                "watchlist_hits": lc_row[11],
                "position_hits": lc_row[12],
                "sector_strong_count": lc_row[13],
            }

        # ── Largecap: hit vs non-hit breakdown ──
        lc_hit_r = await session.execute(text(f"""
            SELECT
                CASE WHEN in_watchlist = true OR in_position = true THEN 'hit' ELSE 'no_hit' END AS grp,
                COUNT(*),
                ROUND(AVG(ret_15m)::numeric, 3),
                ROUND(AVG(ret_30m)::numeric, 3),
                ROUND(AVG(ret_eod)::numeric, 3),
                COUNT(*) FILTER (WHERE ret_30m > 0),
                COUNT(*) FILTER (WHERE ret_30m IS NOT NULL),
                COUNT(*) FILTER (WHERE ret_eod > 0),
                COUNT(*) FILTER (WHERE ret_eod IS NOT NULL)
            FROM monitor_largecap_alerts
            WHERE {base_where}
            GROUP BY grp
        """), params)
        largecap_by_hit = {}
        for row in lc_hit_r.fetchall():
            largecap_by_hit[row[0]] = {
                "count": row[1],
                "avg_ret_15m": _f(row[2]),
                "avg_ret_30m": _f(row[3]),
                "avg_ret_eod": _f(row[4]),
                "win_rate_30m": _wr(row[5], row[6]),
                "win_rate_eod": _wr(row[7], row[8]),
                "win_rate": _wr(row[5], row[6]),  # back-compat
            }

        # ── Largecap: sector_strong (板块共振) vs not ──
        lc_ss_r = await session.execute(text(f"""
            SELECT
                CASE WHEN sector_strong = true THEN 'sector_strong' ELSE 'sector_weak' END AS grp,
                COUNT(*),
                ROUND(AVG(ret_15m)::numeric, 3),
                ROUND(AVG(ret_30m)::numeric, 3),
                ROUND(AVG(ret_eod)::numeric, 3),
                COUNT(*) FILTER (WHERE ret_30m > 0),
                COUNT(*) FILTER (WHERE ret_30m IS NOT NULL),
                COUNT(*) FILTER (WHERE ret_eod > 0),
                COUNT(*) FILTER (WHERE ret_eod IS NOT NULL)
            FROM monitor_largecap_alerts
            WHERE {base_where}
            GROUP BY grp
        """), params)
        largecap_by_sector_strong = {}
        for row in lc_ss_r.fetchall():
            largecap_by_sector_strong[row[0]] = {
                "count": row[1],
                "avg_ret_15m": _f(row[2]),
                "avg_ret_30m": _f(row[3]),
                "avg_ret_eod": _f(row[4]),
                "win_rate_30m": _wr(row[5], row[6]),
                "win_rate_eod": _wr(row[7], row[8]),
                "win_rate": _wr(row[5], row[6]),
            }

        # ── Largecap: time-slot breakdown ──
        lc_ts_r = await session.execute(text(f"""
            SELECT
                CASE
                    WHEN event_time < '10:00' THEN '早盘(09:30-10:00)'
                    WHEN event_time < '11:30' THEN '上午盘(10:00-11:30)'
                    WHEN event_time < '13:30' THEN '午后开盘(13:00-13:30)'
                    ELSE '下午盘(13:30-15:00)'
                END AS slot,
                COUNT(*),
                ROUND(AVG(ret_15m)::numeric, 3),
                ROUND(AVG(ret_30m)::numeric, 3),
                ROUND(AVG(ret_eod)::numeric, 3),
                COUNT(*) FILTER (WHERE ret_30m > 0),
                COUNT(*) FILTER (WHERE ret_30m IS NOT NULL),
                COUNT(*) FILTER (WHERE ret_eod > 0),
                COUNT(*) FILTER (WHERE ret_eod IS NOT NULL)
            FROM monitor_largecap_alerts
            WHERE {base_where}
            GROUP BY slot
            ORDER BY MIN(event_time)
        """), params)
        largecap_by_time_slot = [
            {"slot": row[0], "count": row[1],
             "avg_ret_15m": _f(row[2]),
             "avg_ret_30m": _f(row[3]),
             "avg_ret_eod": _f(row[4]),
             "win_rate_30m": _wr(row[5], row[6]),
             "win_rate_eod": _wr(row[7], row[8]),
             "win_rate": _wr(row[5], row[6])}
            for row in lc_ts_r.fetchall()
        ]

        # Window availability map — the frontend uses this to decide whether
        # to render a metric or the literal text "暂不可用", never to fake a
        # value.  Keys are per-source, values are per-window.
        window_availability = {
            "index": {
                "ret_15m": "unavailable",
                "ret_30m": "unavailable",
                "ret_eod": "ok",
            },
            "largecap": {
                "ret_15m": "ok",
                "ret_30m": "ok",
                "ret_eod": "ok",
            },
        }

        return {
            "date_range": [start_date, end_date],
            "total_event_count": total_event_count,
            "index_summary": index_summary,
            "by_pattern": by_pattern,
            "by_level": by_level,
            "by_score_band": by_score_band,
            "hit_comparison": hit_comparison,
            "largecap_stats": largecap_stats,
            "largecap_by_hit": largecap_by_hit,
            "largecap_by_sector_strong": largecap_by_sector_strong,
            "largecap_by_time_slot": largecap_by_time_slot,
            "window_availability": window_availability,
        }


def _f(v) -> float | None:
    return float(v) if v is not None else None


def _wr(correct, verified) -> float | None:
    if not verified:
        return None
    return round(correct / verified * 100, 1)
