"""Sentiment analysis engine.

Builds on limit board / dragon-tiger / hot-money data to produce
structured sentiment signals for trading decisions.
"""

from __future__ import annotations

import math
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _clean(data: list[dict]) -> list[dict]:
    for d in data:
        for k, v in d.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                d[k] = None
    return data


async def market_temperature(session: AsyncSession, trade_date: str = "") -> dict:
    """Compute market sentiment temperature for a given trading day.

    Returns counts and rates: limit-up, limit-down, broken-board, seal rate,
    max consecutive boards, hot-money activity.
    """
    if not trade_date:
        r = await session.execute(text(
            "SELECT trade_date FROM limit_list_ths ORDER BY trade_date DESC LIMIT 1"
        ))
        row = r.fetchone()
        trade_date = row[0] if row else ""
    if not trade_date:
        return {"trade_date": "", "data": None}

    board_r = await session.execute(text("""
        SELECT limit_type, COUNT(*) FROM limit_list_ths
        WHERE trade_date = :td GROUP BY limit_type
    """), {"td": trade_date})
    counts: dict[str, int] = {}
    for row in board_r.fetchall():
        counts[row[0]] = row[1]

    up_count = counts.get("涨停池", 0)
    down_count = counts.get("跌停池", 0)
    broken_count = counts.get("炸板池", 0)
    seal_rate = (up_count / (up_count + broken_count) * 100) if (up_count + broken_count) > 0 else 0

    step_r = await session.execute(text("""
        SELECT MAX(CAST(nums AS INTEGER)) FROM limit_step WHERE trade_date = :td
    """), {"td": trade_date})
    max_board = step_r.scalar() or 0

    step_detail_r = await session.execute(text("""
        SELECT nums, COUNT(*) FROM limit_step
        WHERE trade_date = :td GROUP BY nums ORDER BY CAST(nums AS INTEGER) DESC
    """), {"td": trade_date})
    ladder = [{"level": int(row[0]), "count": row[1]} for row in step_detail_r.fetchall()]

    hm_r = await session.execute(text("""
        SELECT COUNT(DISTINCT hm_name), COUNT(DISTINCT ts_code),
               SUM(buy_amount), SUM(sell_amount)
        FROM hm_detail WHERE trade_date = :td
    """), {"td": trade_date})
    hm_row = hm_r.fetchone()
    hot_money = {
        "active_seats": hm_row[0] if hm_row else 0,
        "involved_stocks": hm_row[1] if hm_row else 0,
        "total_buy": hm_row[2] if hm_row else 0,
        "total_sell": hm_row[3] if hm_row else 0,
    }

    total = up_count + down_count + broken_count
    up_ratio = up_count / total * 100 if total > 0 else 0
    if up_ratio >= 60 and seal_rate >= 70 and max_board >= 5:
        level = "极热"
    elif up_ratio >= 45 and seal_rate >= 55:
        level = "偏热"
    elif down_count > up_count * 1.5:
        level = "冰点"
    elif down_count > up_count:
        level = "偏冷"
    else:
        level = "中性"

    return {
        "trade_date": trade_date,
        "data": {
            "limit_up": up_count,
            "limit_down": down_count,
            "broken": broken_count,
            "seal_rate": round(seal_rate, 1),
            "max_board": max_board,
            "ladder": ladder,
            "hot_money": hot_money,
            "temperature": level,
        },
    }


async def board_leader(session: AsyncSession, trade_date: str = "", concept: str = "") -> dict:
    """Identify board leaders (龙1/龙2) for a given day, optionally filtered by concept/tag."""
    if not trade_date:
        r = await session.execute(text(
            "SELECT trade_date FROM limit_list_ths ORDER BY trade_date DESC LIMIT 1"
        ))
        row = r.fetchone()
        trade_date = row[0] if row else ""
    if not trade_date:
        return {"trade_date": "", "data": []}

    wheres = ["trade_date = :td", "limit_type = '涨停池'"]
    params: dict = {"td": trade_date}
    if concept:
        wheres.append("tag ILIKE :tag")
        params["tag"] = f"%{concept}%"

    where_sql = " AND ".join(wheres)
    r = await session.execute(text(f"""
        SELECT ts_code, name, pct_chg, first_lu_time, last_lu_time,
               open_num, limit_amount, turnover_rate, tag, status
        FROM limit_list_ths
        WHERE {where_sql}
        ORDER BY first_lu_time ASC NULLS LAST
    """), params)

    cols = ["ts_code", "name", "pct_chg", "first_lu_time", "last_lu_time",
            "open_num", "limit_amount", "turnover_rate", "tag", "status"]
    data = [dict(zip(cols, row)) for row in r.fetchall()]

    for i, d in enumerate(data):
        d["rank"] = i + 1
        d["label"] = f"龙{i + 1}" if i < 3 else ""

    return {"trade_date": trade_date, "count": len(data), "data": _clean(data)}


async def continuation_analysis(session: AsyncSession, ts_code: str) -> dict:
    """Analyze consecutive limit-up history for a stock.

    Returns: current streak, max historical streak, broken probability.
    """
    r = await session.execute(text("""
        SELECT trade_date, limit_type, pct_chg, open_num, first_lu_time
        FROM limit_list_ths
        WHERE ts_code = :code
        ORDER BY trade_date DESC
        LIMIT 60
    """), {"code": ts_code})

    cols = ["trade_date", "limit_type", "pct_chg", "open_num", "first_lu_time"]
    history = [dict(zip(cols, row)) for row in r.fetchall()]

    current_streak = 0
    for h in history:
        if h["limit_type"] == "U":
            current_streak += 1
        else:
            break

    all_streaks: list[int] = []
    streak = 0
    for h in reversed(history):
        if h["limit_type"] == "U":
            streak += 1
        else:
            if streak > 0:
                all_streaks.append(streak)
            streak = 0
    if streak > 0:
        all_streaks.append(streak)

    max_streak = max(all_streaks) if all_streaks else 0

    broken_days = sum(1 for h in history if h["limit_type"] == "Z")
    up_days = sum(1 for h in history if h["limit_type"] == "U")
    broken_rate = (broken_days / (up_days + broken_days) * 100) if (up_days + broken_days) > 0 else 0

    step_r = await session.execute(text("""
        SELECT trade_date, nums FROM limit_step
        WHERE ts_code = :code ORDER BY trade_date DESC LIMIT 10
    """), {"code": ts_code})
    step_history = [{"trade_date": row[0], "nums": int(row[1])} for row in step_r.fetchall()]

    return {
        "ts_code": ts_code,
        "current_streak": current_streak,
        "max_streak": max_streak,
        "broken_rate": round(broken_rate, 1),
        "total_limit_up_days": up_days,
        "total_broken_days": broken_days,
        "recent_history": _clean(history[:20]),
        "step_history": step_history,
    }


async def hot_money_signal(session: AsyncSession, trade_date: str = "") -> dict:
    """Get hot-money activity signals for a given day."""
    if not trade_date:
        r = await session.execute(text(
            "SELECT trade_date FROM hm_detail ORDER BY trade_date DESC LIMIT 1"
        ))
        row = r.fetchone()
        trade_date = row[0] if row else ""
    if not trade_date:
        return {"trade_date": "", "data": []}

    r = await session.execute(text("""
        SELECT hm_name,
               COUNT(DISTINCT ts_code) as stock_count,
               SUM(buy_amount) as total_buy,
               SUM(sell_amount) as total_sell,
               SUM(net_amount) as total_net,
               ARRAY_AGG(DISTINCT ts_name) as stocks
        FROM hm_detail
        WHERE trade_date = :td
        GROUP BY hm_name
        ORDER BY SUM(buy_amount) DESC NULLS LAST
        LIMIT 20
    """), {"td": trade_date})

    data = []
    for row in r.fetchall():
        stocks_arr = row[5] if row[5] else []
        data.append({
            "hm_name": row[0],
            "stock_count": row[1],
            "total_buy": row[2],
            "total_sell": row[3],
            "total_net": row[4],
            "stocks": stocks_arr[:5],
        })

    return {"trade_date": trade_date, "data": _clean(data)}
