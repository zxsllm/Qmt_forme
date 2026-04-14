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
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.shared.data.data_loader import DataLoader

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/plan", tags=["plan"])


# ---------------------------------------------------------------------------
# Helper: resolve trade date (roll back non-trading days)
# ---------------------------------------------------------------------------

async def _resolve_trade_date(session: AsyncSession, date_str: str) -> str:
    """如果 date_str 不是交易日，回退到最近的交易日。"""
    r = await session.execute(text("""
        SELECT cal_date FROM trade_cal
        WHERE is_open = '1' AND cal_date <= :d
        ORDER BY cal_date DESC LIMIT 1
    """), {"d": date_str})
    row = r.fetchone()
    return row[0] if row else date_str


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
# Helper: previous trade date from trade_cal
# ---------------------------------------------------------------------------

async def _get_prev_trade_date(session: AsyncSession, trade_date: str) -> str:
    """Get the most recent trading day strictly before trade_date."""
    r = await session.execute(text(
        "SELECT cal_date FROM trade_cal WHERE is_open='1' AND cal_date < :d "
        "ORDER BY cal_date DESC LIMIT 1"
    ), {"d": trade_date})
    row = r.fetchone()
    return row[0] if row else ""


# ---------------------------------------------------------------------------
# Helper: overnight global index data (index_global table)
# ---------------------------------------------------------------------------

# Codes consistent with data_sync.sync_index_global
_GLOBAL_INDEX_CODES = [
    "XIN9", "SPX", "DJI", "IXIC", "FTSE", "FCHI", "GDAXI",
    "N225", "KS11", "AS51", "SENSEX", "MXX",
    "HSI", "HSTECH",
]

_GLOBAL_INDEX_NAMES = {
    "XIN9": "富时A50", "SPX": "标普500", "DJI": "道琼斯",
    "IXIC": "纳斯达克", "FTSE": "富时100", "FCHI": "法国CAC40",
    "GDAXI": "德国DAX", "N225": "日经225", "KS11": "韩国KOSPI",
    "AS51": "澳洲标普200", "SENSEX": "印度SENSEX", "MXX": "墨西哥MXX",
    "HSI": "恒生指数", "HSTECH": "恒生科技",
}


async def _get_global_indices(session: AsyncSession, trade_date: str) -> list[dict]:
    """Fetch latest global index bars from index_global (before trade_date).

    Returns one row per index with close, pct_chg, etc.
    Uses a single query instead of per-index queries.
    """
    codes_csv = ",".join(f"'{c}'" for c in _GLOBAL_INDEX_CODES)
    r = await session.execute(text(f"""
        SELECT ts_code, trade_date, close, pct_chg, pre_close, open, high, low FROM (
            SELECT ts_code, trade_date, close, pct_chg, pre_close, open, high, low,
                   ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) as rn
            FROM index_global
            WHERE ts_code IN ({codes_csv}) AND trade_date < :td
        ) sub WHERE rn = 1
    """), {"td": trade_date})
    results = []
    for row in r.fetchall():
        results.append({
            "ts_code": row[0],
            "name": _GLOBAL_INDEX_NAMES.get(row[0], row[0]),
            "trade_date": row[1],
            "close": _clean_float(row[2]),
            "pct_chg": _clean_float(row[3]),
            "pre_close": _clean_float(row[4]),
            "open": _clean_float(row[5]),
            "high": _clean_float(row[6]),
            "low": _clean_float(row[7]),
        })
    return results


# ---------------------------------------------------------------------------
# Helper: today's key events (upcoming unlock, earnings, holder trades)
# ---------------------------------------------------------------------------

async def _get_key_events(session: AsyncSession, trade_date: str) -> dict:
    """Gather key events around trade_date: unlocks, forecasts, holder trades, disclosures."""
    events: dict = {"unlock": [], "forecast": [], "holdertrade": [], "disclosure": []}

    # Upcoming share unlocks within 5 days
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

    # Upcoming financial report disclosures (actual_date within 5 days)
    disc_r = await session.execute(text("""
        SELECT d.ts_code, b.name, d.end_date, d.actual_date, d.pre_date
        FROM disclosure_date d
        JOIN stock_basic b ON d.ts_code = b.ts_code
        WHERE d.actual_date BETWEEN :td AND :horizon
        ORDER BY d.actual_date ASC
        LIMIT 30
    """), {"td": trade_date, "horizon": horizon})
    for row in disc_r.fetchall():
        events["disclosure"].append({
            "ts_code": row[0], "name": row[1],
            "end_date": row[2], "actual_date": row[3],
            "pre_date": row[4],
        })

    return events


# ---------------------------------------------------------------------------
# Helper: 个股价格锚点（MA / 支撑阻力 / 涨跌停价）
# ---------------------------------------------------------------------------

async def _get_price_anchors(
    session: AsyncSession, ts_codes: list[str], trade_date: str
) -> list[dict]:
    """为关注个股计算价格锚点，供 AI 生成具体 target_price / stop_loss。

    每只股票返回: close, ma5, ma10, ma20, ma60, support/resistance,
    up_limit, down_limit, period_high, period_low。
    批量查询替代逐股 N+1。
    """
    if not ts_codes:
        return []
    codes_csv = ",".join(f"'{c}'" for c in ts_codes)

    # 批量加载 60 日 K 线（一次查询替代 N×2 次）
    bars_r = await session.execute(text(f"""
        SELECT ts_code, trade_date, high, low, close, vol FROM (
            SELECT ts_code, trade_date, high, low, close, vol,
                   ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) as rn
            FROM stock_daily
            WHERE ts_code IN ({codes_csv}) AND trade_date <= :td
        ) sub WHERE rn <= 60
        ORDER BY ts_code, trade_date DESC
    """), {"td": trade_date})
    bars_by_code: dict[str, list] = {}
    for row in bars_r.fetchall():
        bars_by_code.setdefault(row[0], []).append(row[1:])  # (date, high, low, close, vol)

    # 批量加载涨跌停价（一次查询替代 N 次）
    limit_r = await session.execute(text(f"""
        SELECT ts_code, up_limit, down_limit FROM stock_limit
        WHERE ts_code IN ({codes_csv}) AND trade_date = :td
    """), {"td": trade_date})
    limit_map = {row[0]: (row[1], row[2]) for row in limit_r.fetchall()}

    anchors = []
    for code in ts_codes:
        rows = bars_by_code.get(code, [])
        if not rows:
            anchors.append({"ts_code": code})
            continue

        # 从 bars 计算 S/R + MA（内联 support_resistance 逻辑）
        highs = [(_clean_float(r[1]), r[0]) for r in rows if _clean_float(r[1])]
        lows = [(_clean_float(r[2]), r[0]) for r in rows if _clean_float(r[2])]
        closes = [_clean_float(r[3]) for r in rows if _clean_float(r[3])]

        current_close = closes[0] if closes else None
        period_high = max(highs, key=lambda x: x[0]) if highs else None
        period_low = min(lows, key=lambda x: x[0]) if lows else None

        resistance = sorted(set(h[0] for h in highs if current_close and h[0] > current_close))[:3] if current_close else []
        support = sorted(set(l[0] for l in lows if current_close and l[0] < current_close), reverse=True)[:3] if current_close else []

        ma5 = round(sum(closes[:5]) / min(5, len(closes)), 2) if closes else None
        ma10 = round(sum(closes[:10]) / min(10, len(closes)), 2) if len(closes) >= 5 else None
        ma20 = round(sum(closes[:20]) / min(20, len(closes)), 2) if len(closes) >= 10 else None
        ma60 = None
        if len(closes) >= 60:
            ma60 = round(sum(closes[:60]) / 60, 2)
        elif len(closes) >= 30:
            ma60 = round(sum(closes[:30]) / 30, 2)

        lim = limit_map.get(code)
        anchors.append({
            "ts_code": code,
            "close": current_close,
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "ma60": ma60,
            "support_levels": support,
            "resistance_levels": resistance,
            "up_limit": _clean_float(lim[0]) if lim else None,
            "down_limit": _clean_float(lim[1]) if lim else None,
            "period_high": {"price": period_high[0], "date": period_high[1]} if period_high else None,
            "period_low": {"price": period_low[0], "date": period_low[1]} if period_low else None,
        })
    return anchors


# ---------------------------------------------------------------------------
# Helper: 历史预判回溯统计（学习闭环）
# ---------------------------------------------------------------------------

async def _get_retrospect_summary(
    session: AsyncSession, trade_date: str, lookback: int = 10
) -> dict:
    """获取近 N 次已回溯的预判记录，计算准确率统计。

    用于注入 prompt，让 AI 参考自身历史预判偏差做适度校正。
    """
    r = await session.execute(text("""
        SELECT trade_date, predicted_direction, predicted_temperature,
               actual_result, accuracy_score, retrospect_note
        FROM daily_plan
        WHERE trade_date < :td AND actual_result IS NOT NULL
        ORDER BY trade_date DESC
        LIMIT :lookback
    """), {"td": trade_date, "lookback": lookback})
    rows = r.fetchall()
    if not rows:
        return {"stats": None, "recent_predictions": []}

    cols = ["trade_date", "predicted_direction", "predicted_temperature",
            "actual_result", "accuracy_score", "retrospect_note"]
    predictions = []
    scores = []
    correct = partial = wrong = 0
    for row in rows:
        rec = dict(zip(cols, row))
        predictions.append(rec)
        if rec["accuracy_score"] is not None:
            scores.append(float(rec["accuracy_score"]))
        result = rec["actual_result"]
        if result == "正确":
            correct += 1
        elif result == "部分正确":
            partial += 1
        elif result == "错误":
            wrong += 1

    total = len(rows)
    avg_score = round(sum(scores) / len(scores), 1) if scores else None

    # 判断近期系统性偏差：连续同向预判
    directions = [p["predicted_direction"] for p in predictions if p["predicted_direction"]]
    recent_bias = None
    if len(directions) >= 3 and len(set(directions[:3])) == 1:
        # 最近3次预判方向一致，检查实际结果是否相反
        actual_results = [p["actual_result"] for p in predictions[:3]]
        if actual_results.count("错误") >= 2:
            recent_bias = f"连续预判{directions[0]}但多数错误，可能存在{directions[0]}偏差"

    return {
        "stats": {
            "total_count": total,
            "correct_count": correct,
            "partial_count": partial,
            "wrong_count": wrong,
            "accuracy_rate": round(correct / total * 100, 1) if total else 0,
            "avg_score": avg_score,
            "recent_bias": recent_bias,
        },
        "recent_predictions": predictions,
    }


# ---------------------------------------------------------------------------
# Helper: 昨日计划执行回顾
# ---------------------------------------------------------------------------

async def _get_yesterday_plan(session: AsyncSession, trade_date: str) -> dict | None:
    """获取选定日期 D 当天的早盘计划记录。

    命名保留 yesterday_plan 以保持前端兼容，但语义是"当日的 daily_plan"。
    ActionBanner 从这里取 predicted_direction / predicted_temperature 等。
    如果 D 当天没有计划，则回退取上一个交易日的计划。
    """
    r = await session.execute(text("""
        SELECT trade_date, predicted_direction, predicted_temperature, confidence_score,
               watch_sectors_json, watch_stocks_json, entry_plan_json,
               key_logic, actual_result, accuracy_score, retrospect_note
        FROM daily_plan
        WHERE trade_date <= :td
        ORDER BY trade_date DESC
        LIMIT 1
    """), {"td": trade_date})
    row = r.fetchone()
    if not row:
        return None

    cols = ["trade_date", "predicted_direction", "predicted_temperature",
            "confidence_score", "watch_sectors_json", "watch_stocks_json",
            "entry_plan_json", "key_logic", "actual_result", "accuracy_score",
            "retrospect_note"]
    rec = dict(zip(cols, row))
    # 清理 float
    for k, v in rec.items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            rec[k] = None
    # 解析 JSON 字段
    for json_col in ("watch_sectors_json", "watch_stocks_json", "entry_plan_json"):
        raw = rec.get(json_col)
        if isinstance(raw, str):
            try:
                rec[json_col] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
    return rec


# ---------------------------------------------------------------------------
# Helper: accuracy_history — 近 N 天准确率趋势
# ---------------------------------------------------------------------------

async def _get_accuracy_history(
    session: AsyncSession, trade_date: str, days: int = 10
) -> dict:
    """查询最近 N 天已验证计划的准确率，计算趋势。

    Returns: {"avg_accuracy": 65.2, "trend": "improving", "recent_scores": [70, 55, ...]}
    """
    r = await session.execute(text("""
        SELECT trade_date, accuracy_score
        FROM daily_plan
        WHERE trade_date < :td AND accuracy_score IS NOT NULL
        ORDER BY trade_date DESC
        LIMIT :days
    """), {"td": trade_date, "days": days})
    rows = r.fetchall()

    if not rows:
        return {"avg_accuracy": None, "trend": "unknown", "recent_scores": []}

    scores = [float(row[1]) for row in rows if row[1] is not None]
    if not scores:
        return {"avg_accuracy": None, "trend": "unknown", "recent_scores": []}

    avg = round(sum(scores) / len(scores), 1)

    # Trend: compare first half vs second half (recent scores are DESC order)
    trend = "stable"
    if len(scores) >= 4:
        mid = len(scores) // 2
        recent_avg = sum(scores[:mid]) / mid         # more recent
        older_avg = sum(scores[mid:]) / (len(scores) - mid)  # older
        diff = recent_avg - older_avg
        if diff > 5:
            trend = "improving"
        elif diff < -5:
            trend = "declining"

    return {
        "avg_accuracy": avg,
        "trend": trend,
        "recent_scores": scores,  # most recent first
    }


# ---------------------------------------------------------------------------
# Helper: similar_days — 相似交易日计划 + 实际结果
# ---------------------------------------------------------------------------

async def _get_similar_days(
    session: AsyncSession, trade_date: str, top_k: int = 3
) -> list[dict]:
    """利用 pgvector 相似搜索找到最相似的 N 个历史交易日。

    Returns: [{date, plan_summary, actual_result, accuracy_score, similarity}]
    容错: pgvector 未安装或无特征向量时返回空列表。
    """
    try:
        # Get target vector
        target_r = await session.execute(text("""
            SELECT env_feature_vector
            FROM daily_plan
            WHERE trade_date = :td AND env_feature_vector IS NOT NULL
        """), {"td": trade_date})
        target_row = target_r.fetchone()

        if not target_row or target_row[0] is None:
            return []

        target_vec = target_row[0]

        r = await session.execute(text("""
            SELECT trade_date, predicted_direction, predicted_temperature,
                   key_logic, actual_result, accuracy_score,
                   retrospect_note,
                   1 - (env_feature_vector <=> :target) AS similarity
            FROM daily_plan
            WHERE trade_date != :td
              AND env_feature_vector IS NOT NULL
              AND actual_result IS NOT NULL
            ORDER BY env_feature_vector <=> :target ASC
            LIMIT :k
        """), {"target": str(target_vec), "td": trade_date, "k": top_k})

        rows = r.fetchall()
        results = []
        for row in rows:
            plan_summary = f"方向:{row[1] or '?'} 温度:{row[2] or '?'}"
            if row[3]:
                # Truncate key_logic to first 100 chars
                logic = row[3][:100] + ("..." if len(row[3]) > 100 else "")
                plan_summary += f" 逻辑:{logic}"

            results.append({
                "date": row[0],
                "plan_summary": plan_summary,
                "actual_result": row[4],
                "accuracy_score": _clean_float(row[5]),
                "retrospect_note": row[6][:200] if row[6] else None,
                "similarity": round(float(row[7]), 4) if row[7] is not None else None,
            })
        return results
    except Exception as e:
        logger.warning("similar_days query failed (pgvector?): %s", e)
        return []


# ---------------------------------------------------------------------------
# Helper: yesterday's dragon-tiger list for morning plan
# ---------------------------------------------------------------------------

async def _get_yesterday_dragon_tiger(session: AsyncSession, prev_td: str) -> dict:
    """前一交易日龙虎榜：上榜股票 + 机构净买入，辅助次日标的筛选。"""
    if not prev_td:
        return {"trade_date": "", "top_stocks": [], "inst_flow": []}

    tl_r = await session.execute(text("""
        SELECT ts_code, name, close, pct_change, net_amount, reason
        FROM top_list
        WHERE trade_date = :td
        ORDER BY ABS(COALESCE(net_amount, 0)) DESC
        LIMIT 20
    """), {"td": prev_td})
    top_stocks = []
    for row in tl_r.fetchall():
        top_stocks.append({
            "ts_code": row[0], "name": row[1],
            "close": _clean_float(row[2]),
            "pct_change": _clean_float(row[3]),
            "net_amount": _clean_float(row[4]),
            "reason": row[5],
        })

    ti_r = await session.execute(text("""
        SELECT ts_code,
               SUM(CASE WHEN buy > 0 THEN buy ELSE 0 END) AS inst_buy,
               SUM(CASE WHEN sell > 0 THEN sell ELSE 0 END) AS inst_sell
        FROM top_inst
        WHERE trade_date = :td
        GROUP BY ts_code
        ORDER BY SUM(COALESCE(buy, 0)) - SUM(COALESCE(sell, 0)) DESC
        LIMIT 15
    """), {"td": prev_td})
    inst_flow = []
    for row in ti_r.fetchall():
        inst_buy = float(row[1] or 0)
        inst_sell = float(row[2] or 0)
        inst_flow.append({
            "ts_code": row[0],
            "inst_buy": round(inst_buy, 2),
            "inst_sell": round(inst_sell, 2),
            "inst_net": round(inst_buy - inst_sell, 2),
        })

    return {"trade_date": prev_td, "top_stocks": top_stocks, "inst_flow": inst_flow}


# ---------------------------------------------------------------------------
# Helper: watchlist/holding announcements for morning plan
# ---------------------------------------------------------------------------

async def _get_watchlist_anns(
    session: AsyncSession, watch_codes: list[str], prev_td: str
) -> list[dict]:
    """仅获取 watchlist/持仓股票的盘后公告（前一交易日），避免全市场噪音。"""
    if not watch_codes or not prev_td:
        return []

    r = await session.execute(text("""
        SELECT a.ts_code, b.name, a.title, a.ann_date
        FROM stock_anns a
        JOIN stock_basic b ON a.ts_code = b.ts_code
        WHERE a.ts_code = ANY(:codes)
          AND a.ann_date = :td
        ORDER BY a.ann_date DESC
        LIMIT 30
    """), {"codes": watch_codes, "td": prev_td})

    results = []
    for row in r.fetchall():
        results.append({
            "ts_code": row[0],
            "name": row[1],
            "title": (row[2] or "").strip()[:120],
            "ann_date": row[3],
        })
    return results


# ---------------------------------------------------------------------------
# Main aggregation: collect all morning plan data
# ---------------------------------------------------------------------------

async def aggregate_plan_data(session: AsyncSession, trade_date: str) -> dict:
    """Aggregate all data sources needed for the morning plan.

    Combines: yesterday's review + global indices + premarket signals
    + risk alerts + key events + margin + valuation
    + 价格锚点 + 历史回溯 + 昨日计划（学习闭环）。
    """
    from app.shared.premarket import generate_premarket_plan
    from app.shared.risk_alerts import generate_risk_alerts
    from app.shared.fundamental import margin_analysis, index_valuation_position

    prev_td = await _get_prev_trade_date(session, trade_date)

    yesterday_review = await _get_yesterday_review(session, trade_date)
    global_indices = await _get_global_indices(session, trade_date)
    premarket = await generate_premarket_plan(session, trade_date)
    risk = await generate_risk_alerts(session, trade_date)
    key_events = await _get_key_events(session, trade_date)
    margin = await margin_analysis(session, prev_td or trade_date)
    valuation = await index_valuation_position(session, prev_td or trade_date)

    # --- Task 2: 学习闭环 —— 历史回溯 + 昨日计划 ---
    retrospect = await _get_retrospect_summary(session, trade_date)
    yesterday_plan = await _get_yesterday_plan(session, trade_date)

    # --- Task 3: 闭环验证 —— 准确率趋势 + 相似日参考 ---
    accuracy_history = await _get_accuracy_history(session, trade_date)
    similar_days = await _get_similar_days(session, trade_date)

    # --- Task 1: 价格锚点 —— 从昨日计划 / premarket 提取关注股票代码 ---
    watch_codes: list[str] = []
    # 优先从昨日计划的 watch_stocks 取
    if yesterday_plan:
        ws = yesterday_plan.get("watch_stocks_json")
        if isinstance(ws, list):
            for item in ws:
                code = item.get("ts_code") if isinstance(item, dict) else item
                if isinstance(code, str) and code not in watch_codes:
                    watch_codes.append(code)
    # 再从 premarket 龙头股补充
    if premarket and isinstance(premarket, dict):
        for key in ("watchlist", "dragon_stocks", "leaders", "hot_stocks"):
            items = premarket.get(key, [])
            if isinstance(items, list):
                for item in items:
                    code = item.get("ts_code") if isinstance(item, dict) else item
                    if isinstance(code, str) and code not in watch_codes:
                        watch_codes.append(code)
    # 限制数量，避免过多查询（覆盖完整 watchlist，上限 50）
    watch_codes = watch_codes[:50]
    price_anchors = await _get_price_anchors(session, watch_codes, prev_td or trade_date) if watch_codes else []

    # 前一交易日龙虎榜：机构 vs 游资，辅助次日标的筛选
    dragon_tiger = await _get_yesterday_dragon_tiger(session, prev_td)

    # watchlist/持仓股票的盘后公告
    watchlist_anns = await _get_watchlist_anns(session, watch_codes, prev_td)

    return {
        "trade_date": trade_date,
        "prev_trade_date": prev_td,
        "yesterday_review": yesterday_review,
        "global_indices": global_indices,
        "premarket": premarket,
        "risk_alerts": risk,
        "key_events": key_events,
        "margin": margin,
        "valuation": valuation,
        "price_anchors": price_anchors,
        "retrospect": retrospect,
        "yesterday_plan": yesterday_plan,
        "accuracy_history": accuracy_history,
        "similar_days": similar_days,
        "dragon_tiger": dragon_tiger,
        "watchlist_anns": watchlist_anns,
    }


# ---------------------------------------------------------------------------
# GET /api/v1/plan/data/{trade_date}
# ---------------------------------------------------------------------------

@router.get("/data/{trade_date}")
async def get_plan_data(trade_date: str):
    """Aggregate all morning plan data for a given trade date (YYYYMMDD).

    如果 trade_date 是非交易日（周末/节假日），自动回退到最近的交易日。
    返回数据中 resolved_trade_date 标明实际使用的交易日。
    """
    async with async_session() as session:
        resolved = await _resolve_trade_date(session, trade_date)
        data = await aggregate_plan_data(session, resolved)
        data["resolved_trade_date"] = resolved
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
        "us_sp500_pct", "us_nasdaq_pct", "a50_night_pct", "hk_hsi_pct",
        "predicted_temperature", "predicted_direction", "confidence_score",
        "watch_sectors_json", "watch_stocks_json", "avoid_sectors_json",
        "key_events_json", "auction_signals_json", "strategy_weights_json",
        "position_plan_json", "entry_plan_json", "exit_plan_json",
        "overnight_summary", "board_play_plan", "swing_trade_plan",
        "value_invest_plan", "key_logic", "risk_notes",
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
        f"{c} = COALESCE(EXCLUDED.{c}, daily_plan.{c})"
        for c in col_names if c != "trade_date"
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
                   us_sp500_pct, us_nasdaq_pct, a50_night_pct, hk_hsi_pct,
                   predicted_temperature, predicted_direction, confidence_score,
                   watch_sectors_json, watch_stocks_json, avoid_sectors_json,
                   key_events_json, auction_signals_json,
                   strategy_weights_json, position_plan_json,
                   entry_plan_json, exit_plan_json,
                   overnight_summary, board_play_plan, swing_trade_plan,
                   value_invest_plan, key_logic, risk_notes,
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
        "us_sp500_pct", "us_nasdaq_pct", "a50_night_pct", "hk_hsi_pct",
        "predicted_temperature", "predicted_direction", "confidence_score",
        "watch_sectors_json", "watch_stocks_json", "avoid_sectors_json",
        "key_events_json", "auction_signals_json",
        "strategy_weights_json", "position_plan_json",
        "entry_plan_json", "exit_plan_json",
        "overnight_summary", "board_play_plan", "swing_trade_plan",
        "value_invest_plan", "key_logic", "risk_notes",
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
        for json_col in ("watch_sectors_json", "watch_stocks_json",
                         "avoid_sectors_json", "key_events_json",
                         "auction_signals_json", "strategy_weights_json",
                         "position_plan_json", "entry_plan_json",
                         "exit_plan_json"):
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
