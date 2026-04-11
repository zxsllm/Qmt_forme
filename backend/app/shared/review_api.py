"""Review API — daily post-market review endpoints and data aggregation.

Endpoints:
  GET  /api/v1/review/data/{trade_date}     — aggregate all review data
  POST /api/v1/review/save                  — save/upsert DailyReview
  GET  /api/v1/review/similar/{trade_date}  — cosine similarity search
  GET  /api/v1/review/history               — filtered history query
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime

from fastapi import APIRouter, Body, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/review", tags=["review"])

# 7 core indices — consistent with data_sync.CORE_INDICES
CORE_INDICES = [
    "000001.SH", "399001.SZ", "399006.SZ",
    "000300.SH", "000905.SH", "000688.SH", "899050.BJ",
]


def _clean_float(val):
    """Return None for NaN/Inf floats, otherwise the value."""
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


# ---------------------------------------------------------------------------
# Helper: index summary (7 core indices latest bar)
# ---------------------------------------------------------------------------

async def _get_index_summary(session: AsyncSession, trade_date: str) -> list[dict]:
    """Fetch latest index_daily bar for each core index on or before trade_date."""
    results = []
    for ts_code in CORE_INDICES:
        r = await session.execute(text("""
            SELECT ts_code, trade_date, close, open, high, low,
                   pct_chg, vol, amount, pre_close
            FROM index_daily
            WHERE ts_code = :code AND trade_date <= :td
            ORDER BY trade_date DESC
            LIMIT 1
        """), {"code": ts_code, "td": trade_date})
        row = r.fetchone()
        if row:
            results.append({
                "ts_code": row[0],
                "trade_date": row[1],
                "close": _clean_float(row[2]),
                "open": _clean_float(row[3]),
                "high": _clean_float(row[4]),
                "low": _clean_float(row[5]),
                "pct_chg": _clean_float(row[6]),
                "vol": _clean_float(row[7]),
                "amount": _clean_float(row[8]),
                "pre_close": _clean_float(row[9]),
            })
    return results


# ---------------------------------------------------------------------------
# Helper: market breadth (up/down/flat counts)
# ---------------------------------------------------------------------------

async def _get_market_breadth(session: AsyncSession, trade_date: str) -> dict:
    """Count up/down/flat stocks from stock_daily on trade_date."""
    r = await session.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE pct_chg > 0) AS up_count,
            COUNT(*) FILTER (WHERE pct_chg < 0) AS down_count,
            COUNT(*) FILTER (WHERE pct_chg = 0) AS flat_count,
            COUNT(*) FILTER (WHERE pct_chg >= 9.8) AS limit_up,
            COUNT(*) FILTER (WHERE pct_chg <= -9.8) AS limit_down,
            ROUND(AVG(pct_chg)::numeric, 2) AS avg_pct_chg,
            ROUND(SUM(amount)::numeric / 100000, 2) AS total_amount_yi
        FROM stock_daily
        WHERE trade_date = :td
    """), {"td": trade_date})
    row = r.fetchone()
    if not row or not row[0]:
        return {"trade_date": trade_date, "total": 0}
    return {
        "trade_date": trade_date,
        "total": row[0],
        "up_count": row[1],
        "down_count": row[2],
        "flat_count": row[3],
        "limit_up": row[4],
        "limit_down": row[5],
        "avg_pct_chg": _clean_float(float(row[6])) if row[6] is not None else None,
        "total_amount_yi": _clean_float(float(row[7])) if row[7] is not None else None,
    }


# ---------------------------------------------------------------------------
# Helper: sector ranking (SW industry daily)
# ---------------------------------------------------------------------------

async def _get_sector_ranking(session: AsyncSession, trade_date: str,
                              top_n: int = 10) -> dict:
    """Top/bottom sectors from sw_daily on trade_date."""
    r = await session.execute(text("""
        SELECT ts_code, name, pct_change, amount,
               close, open, vol
        FROM sw_daily
        WHERE trade_date = :td AND pct_change IS NOT NULL
        ORDER BY pct_change DESC
    """), {"td": trade_date})
    rows = r.fetchall()
    if not rows:
        return {"trade_date": trade_date, "top": [], "bottom": []}

    all_sectors = []
    for row in rows:
        all_sectors.append({
            "ts_code": row[0],
            "name": row[1] or row[0],
            "pct_change": _clean_float(row[2]),
            "amount": _clean_float(row[3]),
            "close": _clean_float(row[4]),
            "open": _clean_float(row[5]),
            "vol": _clean_float(row[6]),
        })

    return {
        "trade_date": trade_date,
        "top": all_sectors[:top_n],
        "bottom": list(reversed(all_sectors[-top_n:])),
        "count": len(all_sectors),
    }


# ---------------------------------------------------------------------------
# Helper: 为龙头股/关注股补充 MA 位置信息
# ---------------------------------------------------------------------------

async def _enrich_leaders_with_ma(
    session: AsyncSession, leaders: dict
) -> dict:
    """为 board_leader 返回的龙头股列表补充 MA5/MA10/MA20 位置数据。

    方便 AI 判断龙头股当前处于均线之上还是之下。
    """
    from app.shared.tech_signal import support_resistance

    stocks = leaders.get("data", []) if isinstance(leaders, dict) else []
    if not stocks:
        return leaders

    # 只为前 10 只龙头股计算（避免过多查询）
    for stock in stocks[:10]:
        code = stock.get("ts_code")
        if not code:
            continue
        try:
            sr = await support_resistance(session, code, days=60)
            sr_data = sr.get("data")
            if sr_data:
                stock["ma5"] = sr_data.get("ma5")
                stock["ma10"] = sr_data.get("ma10")
                stock["ma20"] = sr_data.get("ma20")
                stock["position_pct"] = sr_data.get("position_pct")
        except Exception:
            pass  # 个别股票查询失败不影响整体

    return leaders


# ---------------------------------------------------------------------------
# Main aggregation: collect all review data for a given trade_date
# ---------------------------------------------------------------------------

async def aggregate_review_data(session: AsyncSession, trade_date: str) -> dict:
    """Aggregate all data sources needed for the daily review report.

    Calls sentiment, fundamental, risk modules + the 3 SQL helpers above.
    This is the data payload that feeds into claude-sg for AI analysis.
    """
    from app.shared.sentiment import market_temperature, board_leader, hot_money_signal
    from app.shared.risk_alerts import generate_risk_alerts
    from app.shared.fundamental import margin_analysis, index_valuation_position

    # Run all data collection in sequence (all share the same session)
    temperature = await market_temperature(session, trade_date)
    leaders = await board_leader(session, trade_date)
    hot_money = await hot_money_signal(session, trade_date)
    risk = await generate_risk_alerts(session, trade_date)
    margin = await margin_analysis(session, trade_date)
    valuation = await index_valuation_position(session, trade_date)

    index_summary = await _get_index_summary(session, trade_date)
    breadth = await _get_market_breadth(session, trade_date)
    sectors = await _get_sector_ranking(session, trade_date)

    # Task 1: 为龙头股补充 MA 位置，辅助价格锚点分析
    leaders = await _enrich_leaders_with_ma(session, leaders)

    return {
        "trade_date": trade_date,
        "index_summary": index_summary,
        "market_breadth": breadth,
        "temperature": temperature,
        "leaders": leaders,
        "hot_money": hot_money,
        "risk_alerts": risk,
        "margin": margin,
        "valuation": valuation,
        "sector_ranking": sectors,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/review/data/{trade_date}
# ---------------------------------------------------------------------------

@router.get("/data/{trade_date}")
async def get_review_data(trade_date: str):
    """Aggregate all review data for a given trade date (YYYYMMDD)."""
    async with async_session() as session:
        data = await aggregate_review_data(session, trade_date)
    return data


# ---------------------------------------------------------------------------
# POST /api/v1/review/save
# ---------------------------------------------------------------------------

@router.post("/save")
async def save_review(payload: dict = Body(...)):
    """Save or update a DailyReview record.

    Expects a JSON body with trade_date (required) and any DailyReview fields.
    Uses ON CONFLICT (trade_date) DO UPDATE for upsert semantics.
    Automatically computes market_feature_vector if sufficient data present.
    """
    trade_date = payload.get("trade_date")
    if not trade_date:
        return {"ok": False, "error": "trade_date is required"}

    # Build feature vector from the payload
    vector_val = None
    try:
        from app.shared.review_engine import build_market_feature_vector
        vec = build_market_feature_vector(payload)
        if vec and len(vec) == 36:
            vector_val = vec
    except Exception as e:
        logger.warning("build_market_feature_vector failed: %s", e)

    # Define the columns we accept (matching DailyReview model)
    allowed_cols = {
        "trade_date", "sh_close", "sh_pct_chg", "sz_close", "sz_pct_chg",
        "cy_close", "cy_pct_chg", "total_amount", "amount_chg_pct",
        "temperature", "limit_up_count", "limit_down_count", "broken_count",
        "seal_rate", "max_board", "up_count", "down_count", "up_down_ratio",
        "margin_balance", "margin_net_buy", "hot_money_net", "inst_net_buy",
        "top_sectors_json", "bottom_sectors_json", "dragon_stocks_json",
        "hot_money_json", "limit_ladder_json", "risk_alerts_json",
        "market_summary", "sector_analysis", "sentiment_narrative",
        "board_play_summary", "swing_trade_summary", "value_invest_summary",
        "strategy_conclusion", "risk_summary", "dominant_strategy",
        "strategy_switch_signal",
    }

    # Filter payload: only include non-None allowed columns
    cols = {}
    for k, v in payload.items():
        if k in allowed_cols and v is not None:
            if isinstance(v, (dict, list)):
                cols[k] = json.dumps(v, ensure_ascii=False)
            else:
                cols[k] = v

    if not cols.get("trade_date"):
        cols["trade_date"] = trade_date

    # Build dynamic INSERT ... ON CONFLICT DO UPDATE
    col_names = list(cols.keys())
    placeholders = [f":{c}" for c in col_names]
    # COALESCE: only overwrite if new value is non-null, else keep existing
    update_set = ", ".join(
        f"{c} = COALESCE(EXCLUDED.{c}, daily_review.{c})"
        for c in col_names if c != "trade_date"
    )

    # Add vector column if available
    if vector_val is not None:
        col_names.append("market_feature_vector")
        placeholders.append(":mvec")
        cols["mvec"] = str(vector_val)
        update_set += ", market_feature_vector = EXCLUDED.market_feature_vector"

    sql = f"""
        INSERT INTO daily_review ({', '.join(col_names)})
        VALUES ({', '.join(placeholders)})
        ON CONFLICT (trade_date) DO UPDATE SET {update_set}
        RETURNING id, trade_date
    """

    async with async_session() as session:
        r = await session.execute(text(sql), cols)
        row = r.fetchone()
        await session.commit()

    return {
        "ok": True,
        "id": row[0] if row else None,
        "trade_date": row[1] if row else trade_date,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/review/similar/{trade_date}
# ---------------------------------------------------------------------------

@router.get("/similar/{trade_date}")
async def get_similar_reviews(
    trade_date: str,
    top_k: int = Query(5, ge=1, le=20),
):
    """Find historically similar trading days using cosine similarity on
    the 36-dim market_feature_vector via pgvector <=> operator.
    """
    async with async_session() as session:
        # Get the target vector
        target_r = await session.execute(text("""
            SELECT market_feature_vector
            FROM daily_review
            WHERE trade_date = :td AND market_feature_vector IS NOT NULL
        """), {"td": trade_date})
        target_row = target_r.fetchone()

        if not target_row or target_row[0] is None:
            return {
                "trade_date": trade_date,
                "error": "no feature vector found for this date",
                "data": [],
            }

        target_vec = target_row[0]

        # Cosine similarity: 1 - cosine_distance
        r = await session.execute(text("""
            SELECT trade_date, temperature, dominant_strategy,
                   sh_pct_chg, total_amount, limit_up_count, limit_down_count,
                   1 - (market_feature_vector <=> :target) AS similarity
            FROM daily_review
            WHERE trade_date != :td
              AND market_feature_vector IS NOT NULL
            ORDER BY market_feature_vector <=> :target ASC
            LIMIT :k
        """), {"target": str(target_vec), "td": trade_date, "k": top_k})

        rows = r.fetchall()

    data = []
    for row in rows:
        data.append({
            "trade_date": row[0],
            "temperature": row[1],
            "dominant_strategy": row[2],
            "sh_pct_chg": _clean_float(row[3]),
            "total_amount": _clean_float(row[4]),
            "limit_up_count": row[5],
            "limit_down_count": row[6],
            "similarity": round(float(row[7]), 4) if row[7] is not None else None,
        })

    return {
        "trade_date": trade_date,
        "count": len(data),
        "data": data,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/review/history
# ---------------------------------------------------------------------------

@router.get("/history")
async def get_review_history(
    start: str = Query("", description="YYYYMMDD start date"),
    end: str = Query("", description="YYYYMMDD end date"),
    temperature: str = Query("", description="Filter by temperature label"),
    dominant_strategy: str = Query("", description="Filter by strategy"),
    limit: int = Query(30, ge=1, le=100),
):
    """Query historical DailyReview records with optional filters."""
    wheres = ["1=1"]
    params: dict = {"lim": limit}

    if start:
        wheres.append("trade_date >= :start")
        params["start"] = start
    if end:
        wheres.append("trade_date <= :end")
        params["end"] = end
    if temperature:
        wheres.append("temperature = :temp")
        params["temp"] = temperature
    if dominant_strategy:
        wheres.append("dominant_strategy = :ds")
        params["ds"] = dominant_strategy

    where_sql = " AND ".join(wheres)

    async with async_session() as session:
        r = await session.execute(text(f"""
            SELECT id, trade_date, sh_close, sh_pct_chg, sz_pct_chg, cy_pct_chg,
                   total_amount, amount_chg_pct, temperature,
                   limit_up_count, limit_down_count, broken_count,
                   seal_rate, max_board, up_count, down_count, up_down_ratio,
                   margin_balance, margin_net_buy,
                   top_sectors_json, bottom_sectors_json, dragon_stocks_json,
                   hot_money_json, limit_ladder_json, risk_alerts_json,
                   market_summary, sector_analysis, sentiment_narrative,
                   board_play_summary, swing_trade_summary, value_invest_summary,
                   strategy_conclusion, risk_summary,
                   dominant_strategy, strategy_switch_signal,
                   created_at
            FROM daily_review
            WHERE {where_sql}
            ORDER BY trade_date DESC
            LIMIT :lim
        """), params)
        rows = r.fetchall()

    cols = [
        "id", "trade_date", "sh_close", "sh_pct_chg", "sz_pct_chg", "cy_pct_chg",
        "total_amount", "amount_chg_pct", "temperature",
        "limit_up_count", "limit_down_count", "broken_count",
        "seal_rate", "max_board", "up_count", "down_count", "up_down_ratio",
        "margin_balance", "margin_net_buy",
        "top_sectors_json", "bottom_sectors_json", "dragon_stocks_json",
        "hot_money_json", "limit_ladder_json", "risk_alerts_json",
        "market_summary", "sector_analysis", "sentiment_narrative",
        "board_play_summary", "swing_trade_summary", "value_invest_summary",
        "strategy_conclusion", "risk_summary",
        "dominant_strategy", "strategy_switch_signal",
        "created_at",
    ]
    data = []
    for row in rows:
        rec = dict(zip(cols, row))
        for k, v in rec.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                rec[k] = None
            elif isinstance(v, datetime):
                rec[k] = v.isoformat()
        data.append(rec)

    return {"count": len(data), "data": data}
