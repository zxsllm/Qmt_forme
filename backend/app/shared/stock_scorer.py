"""StockScorer — signal aggregation scoring engine.

Thin orchestration layer: delegates data fetching to scorer_data.py
and scoring computation to scorer_rules.py.

Endpoint:
  GET /api/v1/signals/ranked?trade_date=20260411&limit=50&min_score=60
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.shared.scorer_data import (
    prefetch_batch,
    fetch_tech_inputs,
    fetch_sentiment_inputs,
    fetch_fundamental_inputs,
    fetch_news_inputs,
)
from app.shared.scorer_rules import (
    score_tech,
    score_sentiment,
    score_fundamental,
    score_news,
)

logger = logging.getLogger(__name__)

scorer_router = APIRouter(prefix="/api/v1/signals", tags=["scorer"])

WEIGHTS = {
    "tech": 0.30,
    "sentiment": 0.25,
    "fundamental": 0.25,
    "news": 0.20,
}


# ── Core scoring ─────────────────────────────────────────────────────────

async def score_stock(
    session: AsyncSession,
    ts_code: str,
    trade_date: str,
    name: str = "",
    ctx: dict | None = None,
) -> dict:
    """Compute composite score for a single stock."""
    tech_in = await fetch_tech_inputs(session, ts_code, trade_date, ctx)
    tech_score, tech_detail, tech_signals = score_tech(**tech_in)

    sent_in = await fetch_sentiment_inputs(session, ts_code, trade_date, ctx)
    sent_score, sent_detail, sent_signals = score_sentiment(**sent_in)

    fund_in = await fetch_fundamental_inputs(session, ts_code, trade_date, ctx)
    fund_score, fund_detail, fund_signals = score_fundamental(**fund_in)

    news_in = await fetch_news_inputs(session, ts_code, trade_date, ctx)
    news_score, news_detail, news_signals = score_news(**news_in)

    total = (
        tech_score * WEIGHTS["tech"]
        + sent_score * WEIGHTS["sentiment"]
        + fund_score * WEIGHTS["fundamental"]
        + news_score * WEIGHTS["news"]
    )

    all_signals = list(dict.fromkeys(
        tech_signals + sent_signals + fund_signals + news_signals
    ))

    return {
        "ts_code": ts_code,
        "name": name,
        "total_score": round(total, 1),
        "tech_score": round(tech_score, 1),
        "sentiment_score": round(sent_score, 1),
        "fundamental_score": round(fund_score, 1),
        "news_score": round(news_score, 1),
        "signals": all_signals,
        "tech_detail": tech_detail,
        "sentiment_detail": sent_detail,
        "fundamental_detail": fund_detail,
        "news_detail": news_detail,
    }


async def rank_stocks(
    session: AsyncSession,
    trade_date: str,
    limit: int = 50,
    min_score: float = 0.0,
) -> dict:
    """Score and rank pre-filtered stocks for a given trade date."""
    candidates_r = await session.execute(text("""
        SELECT DISTINCT sd.ts_code, sb.name
        FROM stock_daily sd
        JOIN stock_basic sb ON sd.ts_code = sb.ts_code
        LEFT JOIN daily_basic db ON sd.ts_code = db.ts_code AND sd.trade_date = db.trade_date
        LEFT JOIN limit_list_ths ll ON sd.ts_code = ll.ts_code
            AND ll.trade_date = :td AND ll.limit_type = '涨停池'
        WHERE sd.trade_date = :td
          AND sb.list_status = 'L'
          AND (sb.name NOT LIKE '%ST%' OR ll.ts_code IS NOT NULL)
          AND (COALESCE(db.turnover_rate, 0) > 1 OR sd.amount > 50000)
        ORDER BY sd.ts_code
    """), {"td": trade_date})

    candidates = candidates_r.fetchall()
    logger.info("rank_stocks: %d candidates for %s", len(candidates), trade_date)

    if not candidates:
        return {
            "trade_date": trade_date,
            "scored_stocks": [],
            "market_overview": {"temperature": "无数据", "avg_score": 0, "high_score_count": 0},
        }

    codes = [row[0] for row in candidates]
    ctx = await prefetch_batch(session, trade_date, codes)
    logger.info("rank_stocks: prefetch done for %d candidates", len(codes))

    scored: list[dict] = []
    for ts_code, name in candidates:
        try:
            result = await score_stock(session, ts_code, trade_date, name or "", ctx)
            if result["total_score"] >= min_score:
                scored.append(result)
        except Exception:
            logger.debug("scoring failed for %s", ts_code, exc_info=True)

    scored.sort(key=lambda x: x["total_score"], reverse=True)
    top = scored[:limit]

    all_scores = [s["total_score"] for s in scored]
    avg_score = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0
    high_count = sum(1 for s in all_scores if s >= 70)
    temperature = ctx["market"]["temperature"] if ctx and "market" in ctx else "中性"

    return {
        "trade_date": trade_date,
        "scored_stocks": top,
        "market_overview": {
            "temperature": temperature,
            "avg_score": avg_score,
            "high_score_count": high_count,
        },
    }


# ── API endpoints ────────────────────────────────────────────────────────

@scorer_router.get("/ranked")
async def get_ranked_stocks(
    trade_date: str = Query("", description="YYYYMMDD, default=today"),
    limit: int = Query(50, ge=1, le=200),
    min_score: float = Query(0, ge=0, le=100),
):
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")
    async with async_session() as session:
        return await rank_stocks(session, trade_date, limit, min_score)


@scorer_router.get("/score/{ts_code}")
async def get_stock_score(
    ts_code: str,
    trade_date: str = Query("", description="YYYYMMDD, default=today"),
):
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")
    async with async_session() as session:
        name_r = await session.execute(text(
            "SELECT name FROM stock_basic WHERE ts_code = :code"
        ), {"code": ts_code})
        name_row = name_r.fetchone()
        return await score_stock(session, ts_code, trade_date, name_row[0] if name_row else "")
