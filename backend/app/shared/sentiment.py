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


def _rt_limit_counts(snap: dict) -> tuple[int, int]:
    """Count limit-up / limit-down from real-time snapshot using pct_chg threshold."""
    up = down = 0
    for v in snap.values():
        pct = v.get("pct_chg", 0)
        code = v.get("ts_code", "")
        if not code or not pct:
            continue
        prefix = code.split(".")[0]
        is_gem_star = prefix.startswith("3") or prefix.startswith("68")
        is_bj = code.endswith(".BJ")
        is_st = "ST" in v.get("name", "").upper()
        if is_st:
            thresh = 4.8
        elif is_bj:
            thresh = 29.5
        elif is_gem_star:
            thresh = 19.5
        else:
            thresh = 9.8
        if pct >= thresh:
            up += 1
        elif pct <= -thresh:
            down += 1
    return up, down


async def market_temperature(session: AsyncSession, trade_date: str = "") -> dict:
    """Compute market sentiment temperature for a given trading day.

    Returns counts and rates: limit-up, limit-down, broken-board, seal rate,
    max consecutive boards, hot-money activity.
    Falls back to real-time rt_k snapshot when DB has no data for today.
    """
    from datetime import datetime

    today = datetime.now().strftime("%Y%m%d")
    if not trade_date:
        trade_date = today

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

    use_rt = (up_count + down_count + broken_count) == 0 and trade_date == today
    if use_rt:
        try:
            from app.execution.feed.scheduler import get_rt_snapshot
            snap, _ = get_rt_snapshot()
            if snap:
                up_count, down_count = _rt_limit_counts(snap)
        except Exception:
            pass

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
            "realtime": use_rt,
        },
    }


async def board_leader(session: AsyncSession, trade_date: str = "", concept: str = "") -> dict:
    """Identify board leaders for a given day, with real-time fallback for today."""
    from datetime import datetime

    today = datetime.now().strftime("%Y%m%d")
    if not trade_date:
        trade_date = today

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

    if not data and trade_date == today:
        try:
            from app.execution.feed.scheduler import get_rt_snapshot
            snap, _ = get_rt_snapshot()
            if snap:
                rt_leaders = []
                for v in snap.values():
                    pct = v.get("pct_chg", 0)
                    code = v.get("ts_code", "")
                    name = v.get("name", "")
                    if not code or not pct:
                        continue
                    prefix = code.split(".")[0]
                    is_gem_star = prefix.startswith("3") or prefix.startswith("68")
                    is_bj = code.endswith(".BJ")
                    is_st = "ST" in name.upper()
                    if is_st:
                        thresh = 4.8
                    elif is_bj:
                        thresh = 29.5
                    elif is_gem_star:
                        thresh = 19.5
                    else:
                        thresh = 9.8
                    if pct >= thresh:
                        rt_leaders.append({
                            "ts_code": code, "name": name, "pct_chg": round(pct, 2),
                            "first_lu_time": None, "last_lu_time": None,
                            "open_num": None, "limit_amount": v.get("amount", None),
                            "turnover_rate": None, "tag": "", "status": "实时",
                        })
                rt_leaders.sort(key=lambda x: -(x.get("pct_chg") or 0))
                data = rt_leaders
        except Exception:
            pass

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
        if h["limit_type"] == "涨停池":
            current_streak += 1
        else:
            break

    all_streaks: list[int] = []
    streak = 0
    for h in reversed(history):
        if h["limit_type"] == "涨停池":
            streak += 1
        else:
            if streak > 0:
                all_streaks.append(streak)
            streak = 0
    if streak > 0:
        all_streaks.append(streak)

    max_streak = max(all_streaks) if all_streaks else 0

    broken_days = sum(1 for h in history if h["limit_type"] == "炸板池")
    up_days = sum(1 for h in history if h["limit_type"] == "涨停池")
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
    """Get hot-money activity: aggregated per trader + per-stock detail."""
    from datetime import datetime
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")

    # Aggregated summary per trader
    r = await session.execute(text("""
        SELECT hm_name,
               COUNT(DISTINCT ts_code) as stock_count,
               SUM(buy_amount) as total_buy,
               SUM(sell_amount) as total_sell,
               SUM(net_amount) as total_net
        FROM hm_detail
        WHERE trade_date = :td
        GROUP BY hm_name
        ORDER BY SUM(buy_amount) DESC NULLS LAST
        LIMIT 30
    """), {"td": trade_date})

    # Per-stock detail for all traders
    detail_r = await session.execute(text("""
        SELECT hm_name, ts_code, ts_name, buy_amount, sell_amount, net_amount
        FROM hm_detail
        WHERE trade_date = :td
        ORDER BY hm_name, net_amount DESC NULLS LAST
    """), {"td": trade_date})

    # Build detail map: hm_name -> list of stock trades
    detail_map: dict[str, list] = {}
    for hm_name, ts_code, ts_name, buy, sell, net in detail_r.fetchall():
        detail_map.setdefault(hm_name, []).append({
            "ts_code": ts_code, "name": ts_name,
            "buy": buy, "sell": sell, "net": net,
        })

    data = []
    for row in r.fetchall():
        hm_name = row[0]
        stocks = detail_map.get(hm_name, [])
        data.append({
            "hm_name": hm_name,
            "stock_count": row[1],
            "total_buy": row[2],
            "total_sell": row[3],
            "total_net": row[4],
            "stocks": stocks,
        })

    return {"trade_date": trade_date, "data": _clean(data)}
