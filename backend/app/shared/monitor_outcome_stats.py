"""Monitor outcome analysis API — P3-3/4/6.

Two distinct methodologies — do NOT mix them:

  Largecap (买入基线):
    entry = next-minute-bar open after signal trigger.
    All returns vs entry_price. Simulates executable buy.

  Index events (信号后效, NOT a buy simulation):
    ret_eod = trigger snapshot price → index close.
    No executable entry — no index minute klines. For reference only.

Provides:
- GET /api/v1/monitor/outcomes/baseline     — largecap buy sim + events signal stats
- GET /api/v1/monitor/outcomes/slices       — grouped slice statistics
- GET /api/v1/monitor/outcomes/distribution — path label distribution
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import text
from app.core.database import async_session

outcome_router = APIRouter(prefix="/api/v1/monitor/outcomes", tags=["monitor"])


def _date_range_params(start_date: str, end_date: str, days: int) -> tuple[str, str]:
    """Resolve start/end dates, defaulting to last N days from latest data."""
    return start_date, end_date  # resolved in each endpoint with DB


def _f(v) -> float | None:
    return float(v) if v is not None else None


def _wr(correct: int, total: int) -> float | None:
    if not total:
        return None
    return round(correct / total * 100, 1)


# ── Baseline: next-bar-open entry simulation ─────────────────────

@outcome_router.get("/baseline")
async def get_outcome_baseline(
    start_date: str = Query("", description="YYYY-MM-DD"),
    end_date: str = Query("", description="YYYY-MM-DD"),
    days: int = Query(30),
    source: str = Query("largecap", description="largecap|events|all"),
):
    """Baseline stats — largecap: entry=next-bar open; index: trigger→close."""
    async with async_session() as session:
        end_date, start_date = await _resolve_dates(session, end_date, start_date, days)
        if not start_date or not end_date:
            return {"baseline": {}, "date_range": [start_date, end_date]}

        params = {"sd": start_date, "ed": end_date}
        result = {}

        if source in ("largecap", "all"):
            r = await session.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE ret_5m IS NOT NULL) AS n,
                    ROUND(AVG(ret_5m)::numeric, 3),
                    ROUND(AVG(ret_15m)::numeric, 3),
                    ROUND(AVG(ret_30m)::numeric, 3),
                    ROUND(AVG(ret_60m)::numeric, 3),
                    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ret_30m)::numeric, 3),
                    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ret_60m)::numeric, 3),
                    COUNT(*) FILTER (WHERE ret_30m > 0),
                    COUNT(*) FILTER (WHERE ret_30m IS NOT NULL),
                    COUNT(*) FILTER (WHERE ret_60m > 0),
                    COUNT(*) FILTER (WHERE ret_60m IS NOT NULL),
                    ROUND(MIN(max_down_30m)::numeric, 3),
                    ROUND(MIN(max_down_60m)::numeric, 3),
                    ROUND(AVG(max_up_30m)::numeric, 3),
                    ROUND(AVG(max_down_30m)::numeric, 3),
                    ROUND(AVG(CASE WHEN ret_30m > 0 THEN ret_30m END)::numeric, 3),
                    ROUND(AVG(CASE WHEN ret_30m < 0 THEN ABS(ret_30m) END)::numeric, 3),
                    ROUND(AVG(close_pos_30m)::numeric, 3),
                    ROUND(AVG(close_pos_60m)::numeric, 3),
                    ROUND(AVG(ret_eod)::numeric, 3),
                    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ret_eod)::numeric, 3),
                    COUNT(*) FILTER (WHERE ret_eod > 0),
                    COUNT(*) FILTER (WHERE ret_eod IS NOT NULL)
                FROM monitor_largecap_alerts
                WHERE event_date >= :sd AND event_date <= :ed
            """), params)
            row = r.fetchone()
            if row and row[0]:
                avg_win = _f(row[15])
                avg_loss = _f(row[16])
                result["largecap"] = {
                    "sample_count": row[0],
                    "avg_ret_5m": _f(row[1]),
                    "avg_ret_15m": _f(row[2]),
                    "avg_ret_30m": _f(row[3]),
                    "avg_ret_60m": _f(row[4]),
                    "median_ret_30m": _f(row[5]),
                    "median_ret_60m": _f(row[6]),
                    "win_rate_30m": _wr(row[7], row[8]),
                    "win_rate_60m": _wr(row[9], row[10]),
                    "worst_drawdown_30m": _f(row[11]),
                    "worst_drawdown_60m": _f(row[12]),
                    "avg_max_up_30m": _f(row[13]),
                    "avg_max_down_30m": _f(row[14]),
                    "profit_loss_ratio": (
                        round(avg_win / avg_loss, 2)
                        if avg_win and avg_loss and avg_loss > 0 else None
                    ),
                    "avg_close_pos_30m": _f(row[17]),
                    "avg_close_pos_60m": _f(row[18]),
                    "avg_ret_eod": _f(row[19]),
                    "median_ret_eod": _f(row[20]),
                    "win_rate_eod": _wr(row[21], row[22]),
                }

        if source in ("events", "all"):
            r = await session.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE ret_eod IS NOT NULL) AS n,
                    ROUND(AVG(ret_eod)::numeric, 3),
                    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ret_eod)::numeric, 3),
                    COUNT(*) FILTER (WHERE ret_eod > 0),
                    COUNT(*) FILTER (WHERE ret_eod IS NOT NULL),
                    ROUND(AVG(CASE WHEN ret_eod > 0 THEN ret_eod END)::numeric, 3),
                    ROUND(AVG(CASE WHEN ret_eod < 0 THEN ABS(ret_eod) END)::numeric, 3)
                FROM monitor_events
                WHERE event_date >= :sd AND event_date <= :ed
            """), params)
            row = r.fetchone()
            if row and row[0]:
                avg_win = _f(row[5])
                avg_loss = _f(row[6])
                result["events"] = {
                    "sample_count": row[0],
                    "avg_ret_eod": _f(row[1]),
                    "median_ret_eod": _f(row[2]),
                    "win_rate_eod": _wr(row[3], row[4]),
                    "profit_loss_ratio": (
                        round(avg_win / avg_loss, 2)
                        if avg_win and avg_loss and avg_loss > 0 else None
                    ),
                }

        return {
            "baseline": result,
            "date_range": [start_date, end_date],
            "window_availability": {
                "index": {"ret_15m": "unavailable", "ret_30m": "unavailable", "ret_eod": "ok"},
                "largecap": {"ret_15m": "ok", "ret_30m": "ok", "ret_eod": "ok"},
            },
        }


# ── Slices: group by different dimensions ────────────────────────

@outcome_router.get("/slices")
async def get_outcome_slices(
    start_date: str = Query("", description="YYYY-MM-DD"),
    end_date: str = Query("", description="YYYY-MM-DD"),
    days: int = Query(30),
    group_by: str = Query("pattern", description="pattern|level|score_band|hit_type|time_slot|path_label|sector_strong"),
    source: str = Query("largecap", description="largecap|events"),
):
    """Return outcome stats grouped by a dimension."""
    async with async_session() as session:
        end_date, start_date = await _resolve_dates(session, end_date, start_date, days)
        if not start_date or not end_date:
            return {"slices": [], "group_by": group_by, "date_range": [start_date, end_date]}

        params = {"sd": start_date, "ed": end_date}
        base_where = "event_date >= :sd AND event_date <= :ed"

        if source == "largecap":
            slices = await _largecap_slices(session, base_where, params, group_by)
        else:
            slices = await _event_slices(session, base_where, params, group_by)

        return {"slices": slices, "group_by": group_by,
                "source": source, "date_range": [start_date, end_date]}


async def _largecap_slices(session, base_where: str, params: dict, group_by: str) -> list:
    """Compute largecap outcome slices."""
    group_expr = _group_expr_largecap(group_by)
    if not group_expr:
        return []

    # Require backfilled data
    where = f"{base_where} AND ret_5m IS NOT NULL"

    r = await session.execute(text(f"""
        SELECT
            {group_expr} AS grp,
            COUNT(*) AS n,
            ROUND(AVG(ret_5m)::numeric, 3),
            ROUND(AVG(ret_15m)::numeric, 3),
            ROUND(AVG(ret_30m)::numeric, 3),
            ROUND(AVG(ret_60m)::numeric, 3),
            ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ret_30m)::numeric, 3),
            COUNT(*) FILTER (WHERE ret_30m > 0),
            COUNT(*) FILTER (WHERE ret_30m IS NOT NULL),
            ROUND(AVG(max_up_30m)::numeric, 3),
            ROUND(AVG(max_down_30m)::numeric, 3),
            ROUND(AVG(close_pos_30m)::numeric, 3),
            ROUND(AVG(CASE WHEN ret_30m > 0 THEN ret_30m END)::numeric, 3),
            ROUND(AVG(CASE WHEN ret_30m < 0 THEN ABS(ret_30m) END)::numeric, 3),
            ROUND(AVG(ret_60m) FILTER (WHERE ret_60m IS NOT NULL)::numeric, 3),
            ROUND(AVG(ret_eod)::numeric, 3),
            ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ret_eod)::numeric, 3),
            COUNT(*) FILTER (WHERE ret_eod > 0),
            COUNT(*) FILTER (WHERE ret_eod IS NOT NULL)
        FROM monitor_largecap_alerts
        WHERE {where}
        GROUP BY grp
        ORDER BY n DESC
    """), params)

    slices = []
    for row in r.fetchall():
        avg_win = _f(row[12])
        avg_loss = _f(row[13])
        slices.append({
            "group": row[0],
            "count": row[1],
            "avg_ret_5m": _f(row[2]),
            "avg_ret_15m": _f(row[3]),
            "avg_ret_30m": _f(row[4]),
            "avg_ret_60m": _f(row[5]),
            "median_ret_30m": _f(row[6]),
            "win_rate_30m": _wr(row[7], row[8]),
            "avg_max_up_30m": _f(row[9]),
            "avg_max_down_30m": _f(row[10]),
            "avg_close_pos_30m": _f(row[11]),
            "profit_loss_ratio": (
                round(avg_win / avg_loss, 2)
                if avg_win and avg_loss and avg_loss > 0 else None
            ),
            "avg_ret_eod": _f(row[15]),
            "median_ret_eod": _f(row[16]),
            "win_rate_eod": _wr(row[17], row[18]),
        })
    return slices


async def _event_slices(session, base_where: str, params: dict, group_by: str) -> list:
    """Compute index event outcome slices."""
    group_expr = _group_expr_events(group_by)
    if not group_expr:
        return []

    where = f"{base_where} AND ret_eod IS NOT NULL"

    r = await session.execute(text(f"""
        SELECT
            {group_expr} AS grp,
            COUNT(*) AS n,
            ROUND(AVG(ret_eod)::numeric, 3),
            ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ret_eod)::numeric, 3),
            COUNT(*) FILTER (WHERE ret_eod > 0),
            COUNT(*) FILTER (WHERE ret_eod IS NOT NULL),
            ROUND(AVG(CASE WHEN ret_eod > 0 THEN ret_eod END)::numeric, 3),
            ROUND(AVG(CASE WHEN ret_eod < 0 THEN ABS(ret_eod) END)::numeric, 3),
            ROUND(AVG(event_score)::numeric, 1)
        FROM monitor_events
        WHERE {where}
        GROUP BY grp
        ORDER BY n DESC
    """), params)

    slices = []
    for row in r.fetchall():
        avg_win = _f(row[6])
        avg_loss = _f(row[7])
        slices.append({
            "group": row[0],
            "count": row[1],
            "avg_ret_eod": _f(row[2]),
            "median_ret_eod": _f(row[3]),
            "win_rate_eod": _wr(row[4], row[5]),
            "profit_loss_ratio": (
                round(avg_win / avg_loss, 2)
                if avg_win and avg_loss and avg_loss > 0 else None
            ),
            "avg_score": _f(row[8]),
        })
    return slices


def _group_expr_largecap(group_by: str) -> str | None:
    """Return SQL expression for largecap grouping."""
    return {
        "path_label": "COALESCE(path_label, 'unlabeled')",
        "sector_strong": "CASE WHEN sector_strong THEN 'sector_strong' ELSE 'sector_weak' END",
        "hit_type": """CASE
            WHEN in_watchlist AND in_position THEN 'both'
            WHEN in_watchlist THEN 'watchlist'
            WHEN in_position THEN 'position'
            ELSE 'none' END""",
        "time_slot": """CASE
            WHEN event_time < '10:00:00' THEN '09:30-10:00'
            WHEN event_time < '11:00:00' THEN '10:00-11:00'
            WHEN event_time < '11:30:00' THEN '11:00-11:30'
            WHEN event_time < '14:00:00' THEN '13:00-14:00'
            ELSE '14:00-15:00' END""",
        "sector": "COALESCE(sector, 'unknown')",
    }.get(group_by)


def _group_expr_events(group_by: str) -> str | None:
    """Return SQL expression for index event grouping."""
    return {
        "pattern": "COALESCE(pattern, 'unknown')",
        "level": "COALESCE(level, 'unknown')",
        "score_band": """CASE
            WHEN event_score >= 80 THEN '80+'
            WHEN event_score >= 60 THEN '60-79'
            ELSE '0-59' END""",
        "hit_type": """CASE
            WHEN hit_count > 0 THEN 'hit'
            ELSE 'no_hit' END""",
        "path_label": "COALESCE(path_label, 'unlabeled')",
        "time_slot": """CASE
            WHEN event_time < '10:00:00' THEN '09:30-10:00'
            WHEN event_time < '11:00:00' THEN '10:00-11:00'
            WHEN event_time < '11:30:00' THEN '11:00-11:30'
            WHEN event_time < '14:00:00' THEN '13:00-14:00'
            ELSE '14:00-15:00' END""",
    }.get(group_by)


# ── Distribution: path label counts ─────────────────────────────

@outcome_router.get("/distribution")
async def get_outcome_distribution(
    start_date: str = Query("", description="YYYY-MM-DD"),
    end_date: str = Query("", description="YYYY-MM-DD"),
    days: int = Query(30),
):
    """Path label distribution for both event types."""
    async with async_session() as session:
        end_date, start_date = await _resolve_dates(session, end_date, start_date, days)
        if not start_date or not end_date:
            return {"distribution": {}, "date_range": [start_date, end_date]}

        params = {"sd": start_date, "ed": end_date}
        base_where = "event_date >= :sd AND event_date <= :ed AND path_label IS NOT NULL"

        # Largecap
        r = await session.execute(text(f"""
            SELECT path_label, COUNT(*) AS n
            FROM monitor_largecap_alerts
            WHERE {base_where}
            GROUP BY path_label ORDER BY n DESC
        """), params)
        lc_dist = {row[0]: row[1] for row in r.fetchall()}

        # Index events
        r = await session.execute(text(f"""
            SELECT path_label, COUNT(*) AS n
            FROM monitor_events
            WHERE {base_where}
            GROUP BY path_label ORDER BY n DESC
        """), params)
        ev_dist = {row[0]: row[1] for row in r.fetchall()}

        return {
            "largecap": lc_dist,
            "events": ev_dist,
            "date_range": [start_date, end_date],
        }


# ── Date resolution helper ───────────────────────────────────────

async def _resolve_dates(session, end_date: str, start_date: str, days: int):
    """Resolve end/start dates from DB if not provided."""
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
    return end_date, start_date
