"""Scorer data layer — batch prefetch and per-dimension data fetching.

All DB queries for the scoring engine live here.
Scoring rules: scorer_rules.py | Orchestration: stock_scorer.py
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _clean_float(val):
    """Return None for NaN/Inf floats, otherwise the value."""
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


# ── Market-level helpers ─────────────────────────────────────────────────

async def _compute_market_data(session: AsyncSession, trade_date: str) -> dict:
    """Compute market temperature and board stats for a trade date."""
    board_r = await session.execute(text("""
        SELECT limit_type, COUNT(*) FROM limit_list_ths
        WHERE trade_date = :td GROUP BY limit_type
    """), {"td": trade_date})
    counts = {row[0]: row[1] for row in board_r.fetchall()}
    up_count = counts.get("涨停池", 0)
    down_count = counts.get("跌停池", 0)
    broken_count = counts.get("炸板池", 0)
    total = up_count + down_count + broken_count
    seal_rate = (up_count / (up_count + broken_count) * 100) if (up_count + broken_count) > 0 else 0

    step_r = await session.execute(text("""
        SELECT MAX(nums) FROM limit_step WHERE trade_date = :td
    """), {"td": trade_date})
    max_board = step_r.scalar() or 0

    up_ratio = up_count / total * 100 if total > 0 else 0
    if up_ratio >= 60 and seal_rate >= 70 and max_board >= 5:
        temperature = "极热"
    elif up_ratio >= 45 and seal_rate >= 55:
        temperature = "偏热"
    elif down_count > up_count * 1.5:
        temperature = "冰点"
    elif down_count > up_count:
        temperature = "偏冷"
    else:
        temperature = "中性"

    return {
        "temperature": temperature,
        "limit_up": up_count,
        "limit_down": down_count,
        "broken": broken_count,
        "seal_rate": round(seal_rate, 1),
        "max_board": max_board,
    }


async def _compute_hot_sectors(session: AsyncSession, trade_date: str) -> list[str]:
    """Top 5 sectors by limit-up count."""
    sector_r = await session.execute(text("""
        SELECT sb.industry, COUNT(*) as cnt
        FROM limit_list_ths ll
        JOIN stock_basic sb ON ll.ts_code = sb.ts_code
        WHERE ll.trade_date = :td AND ll.limit_type = '涨停池'
        GROUP BY sb.industry ORDER BY cnt DESC LIMIT 5
    """), {"td": trade_date})
    return [row[0] for row in sector_r.fetchall() if row[0]]


# ── Batch prefetch ──────────────────────────────────────────────────────

async def prefetch_batch(
    session: AsyncSession, trade_date: str, codes: list[str],
) -> dict:
    """Pre-fetch all scoring data for a batch of stocks.

    Returns a ctx dict consumed by the fetch_*_inputs functions.
    Uses ANY(:codes) for parameterized queries.
    """
    ctx: dict = {}
    codes_list = list(codes)
    codes_set = set(codes)

    # ── Market-wide ──────────────────────────────────────────────────────
    ctx["market"] = await _compute_market_data(session, trade_date)
    ctx["hot_sectors"] = await _compute_hot_sectors(session, trade_date)

    limit_set_r = await session.execute(text("""
        SELECT ts_code FROM limit_list_ths
        WHERE trade_date = :td AND limit_type = '涨停池'
    """), {"td": trade_date})
    ctx["on_limit_codes"] = {row[0] for row in limit_set_r.fetchall()}

    lhb_set_r = await session.execute(text("""
        SELECT DISTINCT ts_code FROM hm_detail WHERE trade_date = :td
    """), {"td": trade_date})
    ctx["on_lhb_codes"] = {row[0] for row in lhb_set_r.fetchall()}

    # ── Per-stock batch ──────────────────────────────────────────────────
    ind_r = await session.execute(
        text("SELECT ts_code, industry FROM stock_basic WHERE ts_code = ANY(:codes)"),
        {"codes": codes_list},
    )
    ctx["industry_map"] = {row[0]: row[1] for row in ind_r.fetchall()}

    limit_r = await session.execute(text("""
        SELECT ts_code, trade_date, limit_type FROM (
            SELECT ts_code, trade_date, limit_type,
                   ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) as rn
            FROM limit_list_ths
            WHERE ts_code = ANY(:codes) AND trade_date <= :td
        ) sub WHERE rn <= 15
        ORDER BY ts_code, trade_date DESC
    """), {"codes": codes_list, "td": trade_date})
    limit_hist: dict[str, list] = {}
    for row in limit_r.fetchall():
        limit_hist.setdefault(row[0], []).append((row[1], row[2]))
    ctx["limit_history"] = limit_hist

    bars_r = await session.execute(text("""
        SELECT ts_code, trade_date, open, high, low, close, pre_close, vol, pct_chg FROM (
            SELECT ts_code, trade_date, open, high, low, close, pre_close, vol, pct_chg,
                   ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) as rn
            FROM stock_daily
            WHERE ts_code = ANY(:codes) AND trade_date <= :td
        ) sub WHERE rn <= 60
        ORDER BY ts_code, trade_date DESC
    """), {"codes": codes_list, "td": trade_date})
    bars_dict: dict[str, list] = {}
    for row in bars_r.fetchall():
        bars_dict.setdefault(row[0], []).append(row[1:])
    ctx["daily_bars"] = bars_dict

    fina_r = await session.execute(text("""
        SELECT ts_code, end_date, roe, netprofit_yoy, or_yoy FROM (
            SELECT ts_code, end_date, roe, netprofit_yoy, or_yoy,
                   ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY end_date DESC) as rn
            FROM fina_indicator
            WHERE ts_code = ANY(:codes) AND ann_date <= :td
        ) sub WHERE rn = 1
    """), {"codes": codes_list, "td": trade_date})
    ctx["fina_data"] = {row[0]: row[1:] for row in fina_r.fetchall()}

    pe_r = await session.execute(text("""
        SELECT ts_code, pe_ttm FROM (
            SELECT ts_code, pe_ttm,
                   ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) as rn
            FROM daily_basic
            WHERE ts_code = ANY(:codes) AND trade_date <= :td AND pe_ttm > 0
        ) sub WHERE rn = 1
    """), {"codes": codes_list, "td": trade_date})
    ctx["pe_own"] = {row[0]: row[1] for row in pe_r.fetchall()}

    industries = {v for v in ctx["industry_map"].values() if v}
    if industries:
        ind_list = list(industries)
        ipe_r = await session.execute(text("""
            SELECT sb.industry, db.pe_ttm
            FROM daily_basic db
            JOIN stock_basic sb ON db.ts_code = sb.ts_code
            WHERE sb.industry = ANY(:inds) AND sb.list_status = 'L'
              AND db.trade_date = (SELECT MAX(trade_date) FROM daily_basic WHERE trade_date <= :td)
              AND db.pe_ttm > 0 AND db.pe_ttm IS NOT NULL
            ORDER BY sb.industry, db.pe_ttm
        """), {"inds": ind_list, "td": trade_date})
        ind_pe: dict[str, list[float]] = {}
        for row in ipe_r.fetchall():
            if row[1] and not math.isnan(row[1]):
                ind_pe.setdefault(row[0], []).append(row[1])
        ctx["industry_pe"] = ind_pe
    else:
        ctx["industry_pe"] = {}

    # ── News + announcements ─────────────────────────────────────────────
    try:
        td = datetime.strptime(trade_date, "%Y%m%d")
        start_dt = (td - timedelta(days=4)).strftime("%Y-%m-%d") + " 00:00:00"
        end_dt = td.strftime("%Y-%m-%d") + " 23:59:59"

        news_r = await session.execute(text("""
            SELECT nc.related_codes, nc.sentiment
            FROM news_classified nc
            JOIN stock_news n ON nc.news_id = n.id
            WHERE n.datetime BETWEEN :start AND :end
        """), {"start": start_dt, "end": end_dt})
        news_by_code: dict[str, dict[str, int]] = {}
        for row in news_r.fetchall():
            raw = row[0]
            sentiment = row[1] or ""
            if isinstance(raw, list):
                related_list = raw
            elif isinstance(raw, str):
                try:
                    related_list = json.loads(raw) if raw.startswith("[") else []
                except (json.JSONDecodeError, TypeError):
                    related_list = []
            else:
                related_list = []
            for code in related_list:
                if code in codes_set:
                    d = news_by_code.setdefault(code, {})
                    d[sentiment] = d.get(sentiment, 0) + 1
        ctx["news_sentiment"] = news_by_code

        ann_r = await session.execute(text("""
            SELECT sub.ts_code, ac.ann_type, ac.sentiment FROM (
                SELECT a.id, a.ts_code,
                       ROW_NUMBER() OVER (PARTITION BY a.ts_code ORDER BY a.ann_date DESC) as rn
                FROM stock_anns a
                WHERE a.ts_code = ANY(:codes) AND a.ann_date <= :td
            ) sub
            JOIN anns_classified ac ON ac.anns_id = sub.id
            WHERE sub.rn <= 10
        """), {"codes": codes_list, "td": trade_date})
        ann_dict: dict[str, list] = {}
        for row in ann_r.fetchall():
            ann_dict.setdefault(row[0], []).append((row[1], row[2]))
        ctx["ann_data"] = ann_dict
    except Exception:
        logger.debug("batch news/ann prefetch failed", exc_info=True)
        ctx["news_sentiment"] = {}
        ctx["ann_data"] = {}

    return ctx


# ── Per-dimension fetch (shared by single-stock + batch) ─────────────────

async def fetch_tech_inputs(
    session: AsyncSession, ts_code: str, trade_date: str,
    ctx: dict | None = None,
) -> dict:
    """Fetch inputs for tech scoring. Returns {limit_rows, bars}."""
    if ctx and "limit_history" in ctx:
        limit_rows = ctx["limit_history"].get(ts_code, [])
    else:
        r = await session.execute(text("""
            SELECT trade_date, limit_type FROM limit_list_ths
            WHERE ts_code = :code AND trade_date <= :td
            ORDER BY trade_date DESC LIMIT 15
        """), {"code": ts_code, "td": trade_date})
        limit_rows = r.fetchall()

    if ctx and "daily_bars" in ctx:
        bars = ctx["daily_bars"].get(ts_code, [])
    else:
        r = await session.execute(text("""
            SELECT trade_date, open, high, low, close, pre_close, vol, pct_chg
            FROM stock_daily
            WHERE ts_code = :code AND trade_date <= :td
            ORDER BY trade_date DESC LIMIT 60
        """), {"code": ts_code, "td": trade_date})
        bars = r.fetchall()

    return {"limit_rows": limit_rows, "bars": bars}


async def fetch_sentiment_inputs(
    session: AsyncSession, ts_code: str, trade_date: str,
    ctx: dict | None = None,
) -> dict:
    """Fetch inputs for sentiment scoring."""
    if ctx and "market" in ctx:
        market = ctx["market"]
    else:
        market = await _compute_market_data(session, trade_date)

    if ctx and "on_limit_codes" in ctx:
        on_limit = ts_code in ctx["on_limit_codes"]
    else:
        r = await session.execute(text("""
            SELECT 1 FROM limit_list_ths
            WHERE ts_code = :code AND trade_date = :td AND limit_type = '涨停池' LIMIT 1
        """), {"code": ts_code, "td": trade_date})
        on_limit = r.fetchone() is not None

    if ctx and "on_lhb_codes" in ctx:
        on_lhb = ts_code in ctx["on_lhb_codes"]
    else:
        r = await session.execute(text("""
            SELECT 1 FROM hm_detail WHERE ts_code = :code AND trade_date = :td LIMIT 1
        """), {"code": ts_code, "td": trade_date})
        on_lhb = r.fetchone() is not None

    if ctx and "hot_sectors" in ctx and "industry_map" in ctx:
        hot_sectors = ctx["hot_sectors"]
        industry = ctx["industry_map"].get(ts_code)
    else:
        hot_sectors = await _compute_hot_sectors(session, trade_date)
        r = await session.execute(text("""
            SELECT industry FROM stock_basic WHERE ts_code = :code
        """), {"code": ts_code})
        row = r.fetchone()
        industry = row[0] if row else None

    return {
        "market": market, "on_limit": on_limit, "on_lhb": on_lhb,
        "hot_sectors": hot_sectors, "industry": industry,
    }


async def fetch_fundamental_inputs(
    session: AsyncSession, ts_code: str, trade_date: str,
    ctx: dict | None = None,
) -> dict:
    """Fetch inputs for fundamental scoring."""
    if ctx and "fina_data" in ctx:
        fina_row = ctx["fina_data"].get(ts_code)
    else:
        r = await session.execute(text("""
            SELECT end_date, roe, netprofit_yoy, or_yoy
            FROM fina_indicator
            WHERE ts_code = :code AND ann_date <= :td
            ORDER BY end_date DESC LIMIT 1
        """), {"code": ts_code, "td": trade_date})
        fina_row = r.fetchone()

    if ctx and "industry_map" in ctx:
        industry = ctx["industry_map"].get(ts_code)
    else:
        r = await session.execute(text("""
            SELECT industry FROM stock_basic WHERE ts_code = :code
        """), {"code": ts_code})
        row = r.fetchone()
        industry = row[0] if row else None

    all_pe: list[float] = []
    own_pe = None
    if industry:
        if ctx and "industry_pe" in ctx and "pe_own" in ctx:
            all_pe = ctx["industry_pe"].get(industry, [])
            own_pe = _clean_float(ctx["pe_own"].get(ts_code))
        else:
            pe_r = await session.execute(text("""
                SELECT db.pe_ttm FROM daily_basic db
                JOIN stock_basic sb ON db.ts_code = sb.ts_code
                WHERE sb.industry = :ind AND sb.list_status = 'L'
                  AND db.trade_date = (SELECT MAX(trade_date) FROM daily_basic WHERE trade_date <= :td)
                  AND db.pe_ttm > 0 AND db.pe_ttm IS NOT NULL
                ORDER BY db.pe_ttm
            """), {"ind": industry, "td": trade_date})
            all_pe = [row[0] for row in pe_r.fetchall() if row[0] and not math.isnan(row[0])]

            own_pe_r = await session.execute(text("""
                SELECT pe_ttm FROM daily_basic
                WHERE ts_code = :code AND trade_date <= :td AND pe_ttm > 0
                ORDER BY trade_date DESC LIMIT 1
            """), {"code": ts_code, "td": trade_date})
            own_pe_row = own_pe_r.fetchone()
            own_pe = _clean_float(own_pe_row[0]) if own_pe_row else None

    return {"fina_row": fina_row, "industry": industry, "all_pe": all_pe, "own_pe": own_pe}


async def fetch_news_inputs(
    session: AsyncSession, ts_code: str, trade_date: str,
    ctx: dict | None = None,
) -> dict:
    """Fetch inputs for news scoring."""
    if ctx and "news_sentiment" in ctx:
        sent_map = ctx["news_sentiment"].get(ts_code, {})
        pos_count = sent_map.get("positive", 0)
        neg_count = sent_map.get("negative", 0)
    else:
        try:
            td = datetime.strptime(trade_date, "%Y%m%d")
            start_dt = (td - timedelta(days=4)).strftime("%Y-%m-%d") + " 00:00:00"
            end_dt = td.strftime("%Y-%m-%d") + " 23:59:59"
        except ValueError:
            return {"pos_count": 0, "neg_count": 0, "ann_rows": []}

        news_r = await session.execute(text("""
            SELECT nc.sentiment, COUNT(*) as cnt
            FROM news_classified nc
            JOIN stock_news n ON nc.news_id = n.id
            WHERE nc.related_codes @> :code_json
              AND n.datetime BETWEEN :start AND :end
            GROUP BY nc.sentiment
        """), {"code_json": f'["{ts_code}"]', "start": start_dt, "end": end_dt})
        pos_count = 0
        neg_count = 0
        for row in news_r.fetchall():
            if row[0] == "positive":
                pos_count = row[1]
            elif row[0] == "negative":
                neg_count = row[1]

    if ctx and "ann_data" in ctx:
        ann_rows = ctx["ann_data"].get(ts_code, [])
    else:
        ann_r = await session.execute(text("""
            SELECT ac.ann_type, ac.sentiment
            FROM anns_classified ac
            JOIN stock_anns a ON ac.anns_id = a.id
            WHERE a.ts_code = :code AND a.ann_date <= :td
            ORDER BY a.ann_date DESC LIMIT 10
        """), {"code": ts_code, "td": trade_date})
        ann_rows = ann_r.fetchall()

    return {"pos_count": pos_count, "neg_count": neg_count, "ann_rows": ann_rows}
