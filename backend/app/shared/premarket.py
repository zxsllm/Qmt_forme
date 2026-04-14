"""Pre-market plan generator.

Combines after-hours news (A1), limit-board data (C1-C3), and fundamentals (B)
to produce a structured daily pre-market plan:
  1. Yesterday's market summary (temperature, leaders, hot sectors)
  2. Today's watchlist (continued limit-ups, news-driven, fundamental-backed)
  3. Risk alerts (broken boards, negative news, ST warnings)
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


async def _get_prev_trade_date(session: AsyncSession, ref_date: str) -> str:
    """Get the most recent trading day on or before ref_date."""
    r = await session.execute(text(
        "SELECT cal_date FROM trade_cal WHERE is_open='1' AND cal_date <= :d "
        "ORDER BY cal_date DESC LIMIT 1"
    ), {"d": ref_date})
    row = r.fetchone()
    return row[0] if row else ""


async def generate_premarket_plan(session: AsyncSession, today: str) -> dict:
    """Generate a pre-market plan.

    data_date = limit_list_ths 中 ≤ today 的最新交易日（收盘后同步完就是当天）
    plan_for  = data_date 的下一个交易日
    效果：收盘同步完成后自动切到当天数据，无需等到 0 点。
    """
    r = await session.execute(text(
        "SELECT trade_date FROM limit_list_ths WHERE trade_date <= :d "
        "ORDER BY trade_date DESC LIMIT 1"
    ), {"d": today})
    row = r.fetchone()
    data_date = row[0] if row else ""

    plan_for = today
    if data_date:
        r2 = await session.execute(text(
            "SELECT cal_date FROM trade_cal WHERE is_open='1' AND cal_date > :d "
            "ORDER BY cal_date ASC LIMIT 1"
        ), {"d": data_date})
        row2 = r2.fetchone()
        if row2:
            plan_for = row2[0]

    yesterday = data_date

    result: dict = {
        "today": plan_for,
        "yesterday": data_date,
        "market_summary": {},
        "watchlist": [],
        "risk_alerts": [],
    }

    if not yesterday:
        return result

    # ── 1. Yesterday's market summary ────────────────────────────

    board_r = await session.execute(text("""
        SELECT limit_type, COUNT(*) FROM limit_list_ths
        WHERE trade_date = :td GROUP BY limit_type
    """), {"td": yesterday})
    counts: dict[str, int] = {}
    for row in board_r.fetchall():
        counts[row[0]] = row[1]

    up_count = counts.get("涨停池", 0)
    down_count = counts.get("跌停池", 0)
    broken_count = counts.get("炸板池", 0)
    seal_rate = round(up_count / (up_count + broken_count) * 100, 1) if (up_count + broken_count) > 0 else 0

    max_board_r = await session.execute(text(
        "SELECT MAX(CAST(nums AS INTEGER)) FROM limit_step WHERE trade_date = :td"
    ), {"td": yesterday})
    max_board = max_board_r.scalar() or 0

    hot_sector_r = await session.execute(text("""
        SELECT name, up_nums, cons_nums
        FROM limit_cpt_list WHERE trade_date = :td
        ORDER BY up_nums DESC NULLS LAST LIMIT 5
    """), {"td": yesterday})
    hot_sectors = [{"name": r[0], "up_nums": r[1], "cons_nums": r[2]} for r in hot_sector_r.fetchall()]

    result["market_summary"] = {
        "limit_up": up_count,
        "limit_down": down_count,
        "broken": broken_count,
        "seal_rate": seal_rate,
        "max_board": max_board,
        "hot_sectors": hot_sectors,
    }

    # ── 2. Watchlist: continued limit-ups + news catalysts ───────

    step_r = await session.execute(text("""
        SELECT ls.ts_code, ls.name, ls.nums,
               ll.first_lu_time, ll.tag, ll.status, ll.pct_chg
        FROM limit_step ls
        LEFT JOIN limit_list_ths ll ON ls.ts_code = ll.ts_code
            AND ll.trade_date = :td AND ll.limit_type = '涨停池'
        WHERE ls.trade_date = :td
        ORDER BY CAST(ls.nums AS INTEGER) DESC
    """), {"td": yesterday})
    step_cols = ["ts_code", "name", "nums", "first_lu_time", "tag", "status", "pct_chg"]
    continued_boards = _clean([dict(zip(step_cols, r)) for r in step_r.fetchall()])
    for item in continued_boards:
        item["reason"] = f"连板{item['nums']}天"
        if item.get("tag"):
            item["reason"] += f" [{item['tag']}]"

    news_catalyst_r = await session.execute(text("""
        SELECT nc.related_codes, n.content, n.datetime
        FROM news_classified nc
        JOIN stock_news n ON n.id = nc.news_id
        WHERE nc.sentiment = 'positive'
          AND nc.news_scope IN ('stock', 'industry')
          AND n.datetime >= :start
          AND nc.related_codes IS NOT NULL
        ORDER BY n.datetime DESC
        LIMIT 30
    """), {"start": yesterday[:4] + '-' + yesterday[4:6] + '-' + yesterday[6:] + ' 15:00:00'})

    news_stocks: dict[str, tuple[str, str]] = {}
    for row in news_catalyst_r.fetchall():
        codes = row[0] if isinstance(row[0], list) else []
        content = (row[1] or "").strip()
        dt_str = str(row[2])[:16] if row[2] else ""
        for code in codes[:3]:
            if code not in news_stocks:
                news_stocks[code] = (content, dt_str)

    news_watchlist = []
    for code, (content, dt_str) in list(news_stocks.items())[:15]:
        sb_r = await session.execute(text(
            "SELECT name FROM stock_basic WHERE ts_code = :c"
        ), {"c": code})
        sb_row = sb_r.fetchone()
        news_watchlist.append({
            "ts_code": code,
            "name": sb_row[0] if sb_row else code,
            "reason": f"利好消息: {content}",
            "time": dt_str,
        })

    result["watchlist"] = continued_boards + news_watchlist

    # ── 3. Risk alerts ───────────────────────────────────────────

    broken_r = await session.execute(text("""
        SELECT ts_code, name, pct_chg, tag
        FROM limit_list_ths
        WHERE trade_date = :td AND limit_type = '炸板池'
        ORDER BY pct_chg ASC NULLS LAST
    """), {"td": yesterday})
    for row in broken_r.fetchall():
        result["risk_alerts"].append({
            "ts_code": row[0],
            "name": row[1],
            "type": "炸板",
            "detail": f"涨幅{row[2]:.1f}%" if row[2] else "",
            "tag": row[3],
        })

    neg_news_r = await session.execute(text("""
        SELECT nc.related_codes, n.content, n.datetime
        FROM news_classified nc
        JOIN stock_news n ON n.id = nc.news_id
        WHERE nc.sentiment = 'negative'
          AND nc.news_scope IN ('stock', 'mixed')
          AND n.datetime >= :start
          AND nc.related_codes IS NOT NULL
        ORDER BY n.datetime DESC
        LIMIT 20
    """), {"start": yesterday[:4] + '-' + yesterday[4:6] + '-' + yesterday[6:] + ' 15:00:00'})

    for row in neg_news_r.fetchall():
        codes = row[0] if isinstance(row[0], list) else []
        content = (row[1] or "").strip()
        dt_str = str(row[2])[:16] if row[2] else ""
        for code in codes[:2]:
            sb_r2 = await session.execute(text(
                "SELECT name FROM stock_basic WHERE ts_code = :c"
            ), {"c": code})
            sb_row2 = sb_r2.fetchone()
            result["risk_alerts"].append({
                "ts_code": code,
                "name": sb_row2[0] if sb_row2 else code,
                "type": "利空消息",
                "detail": content,
                "time": dt_str,
            })

    _clean(result["risk_alerts"])
    return result
