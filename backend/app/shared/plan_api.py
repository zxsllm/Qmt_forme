"""Plan API — daily pre-market plan endpoints and data aggregation.

Endpoints:
  GET   /api/v1/plan/data/{trade_date}          — aggregate morning plan data
  POST  /api/v1/plan/save                       — save/upsert DailyPlan
  PATCH /api/v1/plan/retrospect/{trade_date}    — backfill plan verification
  GET   /api/v1/plan/history                    — filtered history query
  GET   /api/v1/plan/similar/{trade_date}       — cosine similarity search
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

router = APIRouter(prefix="/api/v1/plan", tags=["plan"])


def _clean_float(val):
    """Return None for NaN/Inf floats, otherwise the value."""
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


# ---------------------------------------------------------------------------
# Helper: get yesterday's review summary for morning plan context
# ---------------------------------------------------------------------------

async def _get_yesterday_review(session: AsyncSession, trade_date: str) -> dict | None:
    """Fetch yesterday's DailyReview summary fields relative to trade_date.

    Looks for the most recent review BEFORE trade_date.
    """
    r = await session.execute(text("""
        SELECT trade_date, sh_close, sh_pct_chg, sz_pct_chg, cy_pct_chg,
               total_amount, amount_chg_pct, temperature,
               limit_up_count, limit_down_count, broken_count,
               seal_rate, max_board, up_count, down_count, up_down_ratio,
               margin_balance, margin_net_buy,
               dominant_strategy, strategy_switch_signal,
               top_sectors_json, dragon_stocks_json, limit_ladder_json,
               market_summary, strategy_conclusion
        FROM daily_review
        WHERE trade_date < :td
        ORDER BY trade_date DESC
        LIMIT 1
    """), {"td": trade_date})
    row = r.fetchone()
    if not row:
        return None

    cols = [
        "trade_date", "sh_close", "sh_pct_chg", "sz_pct_chg", "cy_pct_chg",
        "total_amount", "amount_chg_pct", "temperature",
        "limit_up_count", "limit_down_count", "broken_count",
        "seal_rate", "max_board", "up_count", "down_count", "up_down_ratio",
        "margin_balance", "margin_net_buy",
        "dominant_strategy", "strategy_switch_signal",
        "top_sectors_json", "dragon_stocks_json", "limit_ladder_json",
        "market_summary", "strategy_conclusion",
    ]
    rec = dict(zip(cols, row))
    for k, v in rec.items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            rec[k] = None
    # Parse JSON text fields back to objects for downstream consumption
    for json_col in ("top_sectors_json", "dragon_stocks_json", "limit_ladder_json"):
        raw = rec.get(json_col)
        if isinstance(raw, str):
            try:
                rec[json_col] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
    return rec


# ---------------------------------------------------------------------------
# Helper: overnight foreign market data
# ---------------------------------------------------------------------------

async def _get_overnight_markets(session: AsyncSession, trade_date: str) -> dict:
    """Fetch overnight foreign-market index data for morning context.

    Uses index_daily for A50 (XIN9.FI) and global index proxies if synced,
    otherwise returns an empty structure.
    """
    result: dict = {}

    # A50 night session — most recent bar before trade_date
    a50_r = await session.execute(text("""
        SELECT trade_date, close, pct_chg, pre_close
        FROM index_daily
        WHERE ts_code = 'XIN9.FI' AND trade_date < :td
        ORDER BY trade_date DESC
        LIMIT 1
    """), {"td": trade_date})
    a50_row = a50_r.fetchone()
    if a50_row:
        result["a50"] = {
            "trade_date": a50_row[0],
            "close": _clean_float(a50_row[1]),
            "pct_chg": _clean_float(a50_row[2]),
            "pre_close": _clean_float(a50_row[3]),
        }

    return result


# ---------------------------------------------------------------------------
# Helper: today's key events (upcoming unlock, earnings, holder trades)
# ---------------------------------------------------------------------------

async def _get_key_events(session: AsyncSession, trade_date: str) -> dict:
    """Gather key events around trade_date: unlocks, forecasts, holder trades."""
    events: dict = {"unlock": [], "forecast": [], "holdertrade": []}

    # Upcoming share unlocks within 5 days
    from datetime import timedelta
    try:
        dt = datetime.strptime(trade_date, "%Y%m%d")
    except ValueError:
        return events
    horizon = (dt + timedelta(days=5)).strftime("%Y%m%d")

    unlock_r = await session.execute(text("""
        SELECT f.ts_code, b.name, f.float_date, f.float_share, f.float_ratio
        FROM share_float f
        JOIN stock_basic b ON f.ts_code = b.ts_code
        WHERE f.float_date BETWEEN :td AND :horizon
          AND f.float_share IS NOT NULL
        ORDER BY COALESCE(f.float_ratio, 0) DESC
        LIMIT 20
    """), {"td": trade_date, "horizon": horizon})
    for row in unlock_r.fetchall():
        events["unlock"].append({
            "ts_code": row[0], "name": row[1],
            "float_date": row[2],
            "float_share": _clean_float(row[3]),
            "float_ratio": _clean_float(row[4]),
        })

    # Recent earnings forecasts (last 7 days)
    cutoff = (dt - timedelta(days=7)).strftime("%Y%m%d")
    fc_r = await session.execute(text("""
        SELECT f.ts_code, b.name, f.type, f.ann_date, f.end_date,
               f.p_change_min, f.p_change_max
        FROM forecast f
        JOIN stock_basic b ON f.ts_code = b.ts_code
        WHERE f.ann_date BETWEEN :cutoff AND :td
        ORDER BY f.ann_date DESC
        LIMIT 20
    """), {"cutoff": cutoff, "td": trade_date})
    for row in fc_r.fetchall():
        events["forecast"].append({
            "ts_code": row[0], "name": row[1], "type": row[2],
            "ann_date": row[3], "end_date": row[4],
            "p_change_min": _clean_float(row[5]),
            "p_change_max": _clean_float(row[6]),
        })

    # Recent holder trades (last 7 days)
    ht_r = await session.execute(text("""
        SELECT h.ts_code, b.name, h.ann_date, h.holder_name, h.in_de,
               h.change_vol, h.change_ratio
        FROM stk_holdertrade h
        JOIN stock_basic b ON h.ts_code = b.ts_code
        WHERE h.ann_date BETWEEN :cutoff AND :td
        ORDER BY h.ann_date DESC, ABS(COALESCE(h.change_ratio, 0)) DESC
        LIMIT 20
    """), {"cutoff": cutoff, "td": trade_date})
    for row in ht_r.fetchall():
        events["holdertrade"].append({
            "ts_code": row[0], "name": row[1], "ann_date": row[2],
            "holder_name": row[3], "in_de": row[4],
            "change_vol": _clean_float(row[5]),
            "change_ratio": _clean_float(row[6]),
        })

    return events


# ---------------------------------------------------------------------------
# Main aggregation: collect all morning plan data
# ---------------------------------------------------------------------------

async def aggregate_plan_data(session: AsyncSession, trade_date: str) -> dict:
    """Aggregate all data sources needed for the morning plan.

    Combines: yesterday's review + overnight markets + premarket signals
    + risk alerts + key events + sentiment context.
    """
    from app.shared.premarket import generate_premarket_plan
    from app.shared.risk_alerts import generate_risk_alerts
    from app.shared.fundamental import margin_analysis

    yesterday_review = await _get_yesterday_review(session, trade_date)
    overnight = await _get_overnight_markets(session, trade_date)
    premarket = await generate_premarket_plan(session, trade_date)
    risk = await generate_risk_alerts(session, trade_date)
    key_events = await _get_key_events(session, trade_date)
    margin = await margin_analysis(session, trade_date)

    return {
        "trade_date": trade_date,
        "yesterday_review": yesterday_review,
        "overnight_markets": overnight,
        "premarket": premarket,
        "risk_alerts": risk,
        "key_events": key_events,
        "margin": margin,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/plan/data/{trade_date}
# ---------------------------------------------------------------------------

@router.get("/data/{trade_date}")
async def get_plan_data(trade_date: str):
    """Aggregate all morning plan data for a given trade date (YYYYMMDD)."""
    async with async_session() as session:
        data = await aggregate_plan_data(session, trade_date)
    return data


# ---------------------------------------------------------------------------
# POST /api/v1/plan/save
# ---------------------------------------------------------------------------

@router.post("/save")
async def save_plan(payload: dict = Body(...)):
    """Save or update a DailyPlan record.

    Expects a JSON body with trade_date (required) and any DailyPlan fields.
    Uses ON CONFLICT (trade_date) DO UPDATE for upsert semantics.
    Automatically computes env_feature_vector if sufficient data present.
    """
    trade_date = payload.get("trade_date")
    if not trade_date:
        return {"ok": False, "error": "trade_date is required"}

    # Build environment feature vector from the payload
    vector_val = None
    try:
        from app.shared.review_engine import build_env_feature_vector
        vec = build_env_feature_vector(payload)
        if vec and len(vec) == 16:
            vector_val = vec
    except Exception as e:
        logger.warning("build_env_feature_vector failed: %s", e)

    # Define the columns we accept (matching DailyPlan model)
    allowed_cols = {
        "trade_date",
        # overnight environment
        "us_sp500_pct", "us_nasdaq_pct", "a50_night_pct", "hk_hsi_pct",
        # predictions
        "predicted_temperature", "predicted_direction", "confidence_score",
        # structured JSON
        "watch_sectors_json", "watch_stocks_json", "avoid_sectors_json",
        "key_events_json", "auction_signals_json", "strategy_weights_json",
        # operation plans
        "position_plan_json", "entry_plan_json", "exit_plan_json",
        # text fields
        "overnight_summary", "board_play_plan", "swing_trade_plan",
        "value_invest_plan", "key_logic", "risk_notes",
    }

    # Filter payload to only allowed columns
    cols = {}
    for k, v in payload.items():
        if k in allowed_cols:
            if isinstance(v, (dict, list)):
                cols[k] = json.dumps(v, ensure_ascii=False)
            else:
                cols[k] = v

    if not cols.get("trade_date"):
        cols["trade_date"] = trade_date

    # Build dynamic INSERT ... ON CONFLICT DO UPDATE
    col_names = list(cols.keys())
    placeholders = [f":{c}" for c in col_names]
    update_set = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in col_names if c != "trade_date"
    )

    # Add vector column if available
    if vector_val is not None:
        col_names.append("env_feature_vector")
        placeholders.append(":evec")
        cols["evec"] = str(vector_val)
        if update_set:
            update_set += ", env_feature_vector = EXCLUDED.env_feature_vector"
        else:
            update_set = "env_feature_vector = EXCLUDED.env_feature_vector"

    sql = f"""
        INSERT INTO daily_plan ({', '.join(col_names)})
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
# PATCH /api/v1/plan/retrospect/{trade_date}
# ---------------------------------------------------------------------------

@router.patch("/retrospect/{trade_date}")
async def retrospect_plan(trade_date: str, payload: dict = Body(...)):
    """Backfill plan verification results for a given trade date.

    Accepts:
      actual_result: "正确" | "部分正确" | "错误"
      accuracy_score: 0-100 float
      retrospect_note: free-text analysis of what went right/wrong
    """
    actual_result = payload.get("actual_result")
    accuracy_score = payload.get("accuracy_score")
    retrospect_note = payload.get("retrospect_note", "")

    if actual_result and actual_result not in ("正确", "部分正确", "错误"):
        return {"ok": False, "error": "actual_result must be 正确/部分正确/错误"}
    if accuracy_score is not None:
        try:
            accuracy_score = float(accuracy_score)
            if not (0 <= accuracy_score <= 100):
                return {"ok": False, "error": "accuracy_score must be 0-100"}
        except (ValueError, TypeError):
            return {"ok": False, "error": "accuracy_score must be numeric"}

    # Build SET clause dynamically — only update provided fields
    updates = []
    params: dict = {"td": trade_date}
    if actual_result is not None:
        updates.append("actual_result = :ar")
        params["ar"] = actual_result
    if accuracy_score is not None:
        updates.append("accuracy_score = :asc")
        params["asc"] = accuracy_score
    if retrospect_note:
        updates.append("retrospect_note = :rn")
        params["rn"] = retrospect_note

    if not updates:
        return {"ok": False, "error": "no fields to update"}

    sql = f"""
        UPDATE daily_plan
        SET {', '.join(updates)}
        WHERE trade_date = :td
        RETURNING id, trade_date, actual_result, accuracy_score
    """

    async with async_session() as session:
        r = await session.execute(text(sql), params)
        row = r.fetchone()
        await session.commit()

    if not row:
        return {"ok": False, "error": f"no plan found for trade_date={trade_date}"}

    return {
        "ok": True,
        "id": row[0],
        "trade_date": row[1],
        "actual_result": row[2],
        "accuracy_score": _clean_float(row[3]),
    }


# ---------------------------------------------------------------------------
# GET /api/v1/plan/history
# ---------------------------------------------------------------------------

@router.get("/history")
async def get_plan_history(
    start: str = Query("", description="YYYYMMDD start date"),
    end: str = Query("", description="YYYYMMDD end date"),
    predicted_direction: str = Query("", description="Filter by direction"),
    actual_result: str = Query("", description="Filter by retrospect result"),
    limit: int = Query(30, ge=1, le=100),
):
    """Query historical DailyPlan records with optional filters."""
    wheres = ["1=1"]
    params: dict = {"lim": limit}

    if start:
        wheres.append("trade_date >= :start")
        params["start"] = start
    if end:
        wheres.append("trade_date <= :end")
        params["end"] = end
    if predicted_direction:
        wheres.append("predicted_direction = :pd")
        params["pd"] = predicted_direction
    if actual_result:
        wheres.append("actual_result = :ar")
        params["ar"] = actual_result

    where_sql = " AND ".join(wheres)

    async with async_session() as session:
        r = await session.execute(text(f"""
            SELECT id, trade_date,
                   predicted_temperature, predicted_direction, confidence_score,
                   watch_sectors_json, avoid_sectors_json,
                   strategy_weights_json, position_plan_json,
                   key_logic, risk_notes,
                   actual_result, accuracy_score, retrospect_note,
                   created_at
            FROM daily_plan
            WHERE {where_sql}
            ORDER BY trade_date DESC
            LIMIT :lim
        """), params)
        rows = r.fetchall()

    cols = [
        "id", "trade_date",
        "predicted_temperature", "predicted_direction", "confidence_score",
        "watch_sectors_json", "avoid_sectors_json",
        "strategy_weights_json", "position_plan_json",
        "key_logic", "risk_notes",
        "actual_result", "accuracy_score", "retrospect_note",
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
        # Parse JSON text fields for readability
        for json_col in ("watch_sectors_json", "avoid_sectors_json",
                         "strategy_weights_json", "position_plan_json"):
            raw = rec.get(json_col)
            if isinstance(raw, str):
                try:
                    rec[json_col] = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    pass
        data.append(rec)

    return {"count": len(data), "data": data}


# ---------------------------------------------------------------------------
# GET /api/v1/plan/similar/{trade_date}
# ---------------------------------------------------------------------------

@router.get("/similar/{trade_date}")
async def get_similar_plans(
    trade_date: str,
    top_k: int = Query(5, ge=1, le=20),
):
    """Find historically similar morning environments using cosine similarity
    on the 16-dim env_feature_vector via pgvector <=> operator.
    """
    async with async_session() as session:
        target_r = await session.execute(text("""
            SELECT env_feature_vector
            FROM daily_plan
            WHERE trade_date = :td AND env_feature_vector IS NOT NULL
        """), {"td": trade_date})
        target_row = target_r.fetchone()

        if not target_row or target_row[0] is None:
            return {
                "trade_date": trade_date,
                "error": "no feature vector found for this date",
                "data": [],
            }

        target_vec = target_row[0]

        r = await session.execute(text("""
            SELECT trade_date, predicted_temperature, predicted_direction,
                   confidence_score, actual_result, accuracy_score,
                   key_logic,
                   1 - (env_feature_vector <=> :target) AS similarity
            FROM daily_plan
            WHERE trade_date != :td
              AND env_feature_vector IS NOT NULL
            ORDER BY env_feature_vector <=> :target ASC
            LIMIT :k
        """), {"target": str(target_vec), "td": trade_date, "k": top_k})

        rows = r.fetchall()

    data = []
    for row in rows:
        data.append({
            "trade_date": row[0],
            "predicted_temperature": row[1],
            "predicted_direction": row[2],
            "confidence_score": _clean_float(row[3]),
            "actual_result": row[4],
            "accuracy_score": _clean_float(row[5]),
            "key_logic": row[6],
            "similarity": round(float(row[7]), 4) if row[7] is not None else None,
        })

    return {
        "trade_date": trade_date,
        "count": len(data),
        "data": data,
    }
