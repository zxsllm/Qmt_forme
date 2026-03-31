"""Fundamental analysis module.

Provides industry-level and company-level financial analysis
using fina_indicator, daily_basic, income, forecast, fina_mainbz, etc.
"""

from __future__ import annotations

import math
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def industry_list(session: AsyncSession) -> list[dict]:
    """Return distinct SW industry names from stock_basic."""
    r = await session.execute(text("""
        SELECT industry, COUNT(*) as cnt
        FROM stock_basic
        WHERE industry IS NOT NULL AND industry != '' AND list_status = 'L'
        GROUP BY industry
        ORDER BY cnt DESC
    """))
    return [{"industry": row[0], "count": row[1]} for row in r.fetchall()]


async def concept_list_all(session: AsyncSession) -> list[dict]:
    """Return all concept boards with stock counts."""
    r = await session.execute(text("""
        SELECT cl.code, cl.name, COUNT(cd.ts_code) as cnt
        FROM concept_list cl
        LEFT JOIN concept_detail cd ON cl.code = cd.concept_code
        GROUP BY cl.code, cl.name
        ORDER BY cnt DESC
    """))
    return [{"code": row[0], "name": row[1], "count": row[2]} for row in r.fetchall()]


async def industry_profile(session: AsyncSession, industry: str) -> list[dict]:
    """Get stocks in an industry with latest financial + valuation data."""
    r = await session.execute(text("""
        WITH latest_fina AS (
            SELECT DISTINCT ON (ts_code)
                ts_code, end_date, roe, netprofit_margin, grossprofit_margin,
                netprofit_yoy, or_yoy, eps, bps, debt_to_assets
            FROM fina_indicator
            ORDER BY ts_code, end_date DESC
        ),
        latest_val AS (
            SELECT DISTINCT ON (ts_code)
                ts_code, trade_date, pe, pe_ttm, pb, total_mv, circ_mv, turnover_rate
            FROM daily_basic
            ORDER BY ts_code, trade_date DESC
        )
        SELECT
            sb.ts_code, sb.name, sb.industry, sb.list_date,
            f.end_date as fina_period, f.roe, f.netprofit_margin, f.grossprofit_margin,
            f.netprofit_yoy, f.or_yoy, f.eps, f.bps, f.debt_to_assets,
            v.pe_ttm, v.pb, v.total_mv, v.circ_mv, v.turnover_rate
        FROM stock_basic sb
        LEFT JOIN latest_fina f ON sb.ts_code = f.ts_code
        LEFT JOIN latest_val v ON sb.ts_code = v.ts_code
        WHERE sb.industry = :industry AND sb.list_status = 'L'
        ORDER BY v.total_mv DESC NULLS LAST
    """), {"industry": industry})
    rows = r.fetchall()
    cols = [
        "ts_code", "name", "industry", "list_date",
        "fina_period", "roe", "netprofit_margin", "grossprofit_margin",
        "netprofit_yoy", "or_yoy", "eps", "bps", "debt_to_assets",
        "pe_ttm", "pb", "total_mv", "circ_mv", "turnover_rate",
    ]
    data = [dict(zip(cols, row)) for row in rows]
    for d in data:
        for k, v in d.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                d[k] = None
    return data


async def concept_stocks(session: AsyncSession, concept_code: str) -> list[dict]:
    """Get stocks in a concept board with latest financial + valuation data."""
    r = await session.execute(text("""
        WITH latest_fina AS (
            SELECT DISTINCT ON (ts_code)
                ts_code, end_date, roe, netprofit_margin, grossprofit_margin,
                netprofit_yoy, or_yoy, eps
            FROM fina_indicator
            ORDER BY ts_code, end_date DESC
        ),
        latest_val AS (
            SELECT DISTINCT ON (ts_code)
                ts_code, pe_ttm, pb, total_mv, circ_mv
            FROM daily_basic
            ORDER BY ts_code, trade_date DESC
        )
        SELECT
            sb.ts_code, sb.name, sb.industry,
            f.roe, f.netprofit_yoy, f.or_yoy, f.eps,
            v.pe_ttm, v.pb, v.total_mv
        FROM concept_detail cd
        JOIN stock_basic sb ON cd.ts_code = sb.ts_code
        LEFT JOIN latest_fina f ON sb.ts_code = f.ts_code
        LEFT JOIN latest_val v ON sb.ts_code = v.ts_code
        WHERE cd.concept_code = :code AND sb.list_status = 'L'
        ORDER BY v.total_mv DESC NULLS LAST
    """), {"code": concept_code})
    rows = r.fetchall()
    cols = [
        "ts_code", "name", "industry",
        "roe", "netprofit_yoy", "or_yoy", "eps",
        "pe_ttm", "pb", "total_mv",
    ]
    data = [dict(zip(cols, row)) for row in rows]
    for d in data:
        for k, v in d.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                d[k] = None
    return data


async def company_profile(session: AsyncSession, ts_code: str) -> dict:
    """Get comprehensive company profile: basic info + financials + main biz."""
    basic_r = await session.execute(text("""
        SELECT ts_code, name, industry, area, market, list_date, fullname
        FROM stock_basic WHERE ts_code = :code
    """), {"code": ts_code})
    basic_row = basic_r.fetchone()
    if not basic_row:
        return {"error": "stock not found"}

    basic = dict(zip(
        ["ts_code", "name", "industry", "area", "market", "list_date", "fullname"],
        basic_row,
    ))

    fina_r = await session.execute(text("""
        SELECT end_date, roe, netprofit_margin, grossprofit_margin,
               netprofit_yoy, or_yoy, eps, bps, debt_to_assets,
               current_ratio, quick_ratio, roa, ocfps
        FROM fina_indicator
        WHERE ts_code = :code
        ORDER BY end_date DESC LIMIT 8
    """), {"code": ts_code})
    fina_cols = [
        "end_date", "roe", "netprofit_margin", "grossprofit_margin",
        "netprofit_yoy", "or_yoy", "eps", "bps", "debt_to_assets",
        "current_ratio", "quick_ratio", "roa", "ocfps",
    ]
    fina_data = [dict(zip(fina_cols, row)) for row in fina_r.fetchall()]

    mainbz_r = await session.execute(text("""
        SELECT end_date, bz_item, bz_sales, bz_profit, bz_cost
        FROM fina_mainbz
        WHERE ts_code = :code
        ORDER BY end_date DESC, bz_sales DESC NULLS LAST
        LIMIT 20
    """), {"code": ts_code})
    mainbz_data = [
        dict(zip(["end_date", "bz_item", "bz_sales", "bz_profit", "bz_cost"], row))
        for row in mainbz_r.fetchall()
    ]

    forecast_r = await session.execute(text("""
        SELECT ann_date, end_date, type, p_change_min, p_change_max,
               net_profit_min, net_profit_max, summary
        FROM forecast
        WHERE ts_code = :code
        ORDER BY ann_date DESC LIMIT 5
    """), {"code": ts_code})
    forecast_data = [
        dict(zip(["ann_date", "end_date", "type", "p_change_min", "p_change_max",
                   "net_profit_min", "net_profit_max", "summary"], row))
        for row in forecast_r.fetchall()
    ]

    concepts_r = await session.execute(text("""
        SELECT concept_name FROM concept_detail WHERE ts_code = :code
    """), {"code": ts_code})
    concepts = [row[0] for row in concepts_r.fetchall() if row[0]]

    val_r = await session.execute(text("""
        SELECT trade_date, pe_ttm, pb, total_mv, circ_mv, turnover_rate
        FROM daily_basic WHERE ts_code = :code
        ORDER BY trade_date DESC LIMIT 1
    """), {"code": ts_code})
    val_row = val_r.fetchone()
    valuation = dict(zip(
        ["trade_date", "pe_ttm", "pb", "total_mv", "circ_mv", "turnover_rate"],
        val_row,
    )) if val_row else {}

    def clean(items):
        for d in items:
            for k, v in d.items():
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    d[k] = None
        return items

    return {
        "basic": basic,
        "valuation": valuation,
        "fina_history": clean(fina_data),
        "main_business": clean(mainbz_data),
        "forecasts": clean(forecast_data),
        "concepts": concepts,
    }


async def event_calendar(session: AsyncSession, start_date: str, end_date: str) -> dict:
    """Get upcoming disclosure dates and recent forecasts."""
    disc_r = await session.execute(text("""
        SELECT d.ts_code, sb.name, d.end_date, d.actual_date, d.pre_date
        FROM disclosure_date d
        JOIN stock_basic sb ON d.ts_code = sb.ts_code
        WHERE (d.actual_date BETWEEN :start AND :end)
           OR (d.pre_date BETWEEN :start AND :end)
        ORDER BY COALESCE(d.actual_date, d.pre_date)
        LIMIT 200
    """), {"start": start_date, "end": end_date})
    disclosures = [
        dict(zip(["ts_code", "name", "end_date", "actual_date", "pre_date"], row))
        for row in disc_r.fetchall()
    ]

    fc_r = await session.execute(text("""
        SELECT f.ts_code, sb.name, f.ann_date, f.end_date, f.type,
               f.p_change_min, f.p_change_max, f.summary
        FROM forecast f
        JOIN stock_basic sb ON f.ts_code = sb.ts_code
        WHERE f.ann_date BETWEEN :start AND :end
        ORDER BY f.ann_date DESC
        LIMIT 200
    """), {"start": start_date, "end": end_date})
    forecasts = [
        dict(zip(["ts_code", "name", "ann_date", "end_date", "type",
                   "p_change_min", "p_change_max", "summary"], row))
        for row in fc_r.fetchall()
    ]

    def clean(items):
        for d in items:
            for k, v in d.items():
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    d[k] = None
        return items

    return {
        "disclosures": clean(disclosures),
        "forecasts": clean(forecasts),
    }
