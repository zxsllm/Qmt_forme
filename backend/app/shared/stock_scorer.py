"""StockScorer — 信号聚合评分引擎.

Integrates four dimensions (tech / sentiment / fundamental / news)
into a single sortable composite score.  Uses SQL pre-filtering to
avoid iterating the full 5 000+ stock universe.

Endpoint:
  GET /api/v1/signals/ranked?trade_date=20260411&limit=50&min_score=60
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session

logger = logging.getLogger(__name__)

scorer_router = APIRouter(prefix="/api/v1/signals", tags=["scorer"])


# ── Helpers ───────────────────────────────────────────────────────────────

def _clean_float(val):
    """Return None for NaN/Inf floats, otherwise the value."""
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ── Dimension scorers ────────────────────────────────────────────────────

async def _score_tech(session: AsyncSession, ts_code: str, trade_date: str) -> tuple[float, dict, list[str]]:
    """Technical dimension score (0-100).

    Reuses logic from tech_signal.py without importing heavy functions
    that each issue their own SQL; instead we batch-fetch what we need.
    """
    score = 50.0  # neutral baseline
    detail: dict = {}
    signals: list[str] = []

    # -- consecutive limit-up ------------------------------------------------
    r = await session.execute(text("""
        SELECT trade_date, limit_type
        FROM limit_list_ths
        WHERE ts_code = :code AND trade_date <= :td
        ORDER BY trade_date DESC LIMIT 15
    """), {"code": ts_code, "td": trade_date})
    streak = 0
    for row in r.fetchall():
        if row[1] == "涨停池":
            streak += 1
        else:
            break
    limit_pts = min(streak * 20, 100)
    detail["consecutive_limit_up"] = streak
    if streak >= 1:
        signals.append("limit_board")

    # -- volume anomaly + gap + indicator snapshot from recent bars ----------
    r = await session.execute(text("""
        SELECT trade_date, open, high, low, close, pre_close, vol, pct_chg
        FROM stock_daily
        WHERE ts_code = :code AND trade_date <= :td
        ORDER BY trade_date DESC LIMIT 60
    """), {"code": ts_code, "td": trade_date})
    bars = r.fetchall()
    if len(bars) < 5:
        return _clamp(score), detail, signals

    latest = bars[0]
    today_vol = _clean_float(latest[6])

    # volume ratio
    hist_vols = [_clean_float(b[6]) for b in bars[1:21] if _clean_float(b[6]) and _clean_float(b[6]) > 0]
    avg_vol = sum(hist_vols) / len(hist_vols) if hist_vols else None
    vol_ratio = round(today_vol / avg_vol, 2) if today_vol and avg_vol and avg_vol > 0 else None
    detail["vol_ratio"] = vol_ratio

    vol_pts = 0.0
    if vol_ratio is not None:
        if vol_ratio > 2:
            vol_pts = 80
            signals.append("volume_surge")
        elif vol_ratio > 1.5:
            vol_pts = 60
            signals.append("volume_up")
        elif vol_ratio > 1:
            vol_pts = 40

    # gap detection (latest bar only)
    gap_pts = 0.0
    if len(bars) >= 2:
        curr_low = _clean_float(latest[3])
        prev_high = _clean_float(bars[1][2])
        curr_high = _clean_float(latest[2])
        prev_low = _clean_float(bars[1][3])
        if curr_low is not None and prev_high is not None and curr_low > prev_high:
            gap_pts = 30
            signals.append("gap_up")
        elif curr_high is not None and prev_low is not None and curr_high < prev_low:
            gap_pts = -30
            signals.append("gap_down")
    detail["gap_pts"] = gap_pts

    # support / resistance proximity
    sr_pts = 0.0
    pos_pct = 0.5  # default: mid-range
    closes = [_clean_float(b[4]) for b in bars if _clean_float(b[4])]
    if closes:
        current_close = closes[0]
        highs_60 = [_clean_float(b[2]) for b in bars if _clean_float(b[2])]
        lows_60 = [_clean_float(b[3]) for b in bars if _clean_float(b[3])]
        if highs_60 and lows_60:
            period_high = max(highs_60)
            period_low = min(lows_60)
            rng = period_high - period_low
            if rng > 0:
                pos_pct = (current_close - period_low) / rng
                if pos_pct < 0.2:
                    sr_pts = 20  # near support
                elif pos_pct > 0.8:
                    sr_pts = -20  # near resistance
    detail["position_pct"] = round(pos_pct * 100, 1)

    # RSI / MACD quick calc from close series (use indicators module)
    rsi_pts = 0.0
    macd_pts = 0.0
    try:
        import pandas as pd
        from app.research.indicators import macd as _macd_fn, rsi as _rsi_fn

        close_series = pd.Series([_clean_float(b[4]) for b in reversed(bars) if _clean_float(b[4])], dtype=float)
        if len(close_series) >= 35:
            rsi_val = _rsi_fn(close_series, period=14)
            cur_rsi = float(rsi_val.iloc[-1]) if not math.isnan(float(rsi_val.iloc[-1])) else None
            detail["rsi"] = round(cur_rsi, 2) if cur_rsi else None
            if cur_rsi is not None:
                if cur_rsi < 30:
                    rsi_pts = 30
                    signals.append("rsi_oversold")
                elif cur_rsi > 70:
                    rsi_pts = -30
                    signals.append("rsi_overbought")

            dif, dea, _ = _macd_fn(close_series)
            idx = len(dif) - 1
            prev = idx - 1
            cur_dif = float(dif.iloc[idx]) if not math.isnan(float(dif.iloc[idx])) else None
            cur_dea = float(dea.iloc[idx]) if not math.isnan(float(dea.iloc[idx])) else None
            pre_dif = float(dif.iloc[prev]) if prev >= 0 and not math.isnan(float(dif.iloc[prev])) else None
            pre_dea = float(dea.iloc[prev]) if prev >= 0 and not math.isnan(float(dea.iloc[prev])) else None
            if cur_dif is not None and cur_dea is not None and pre_dif is not None and pre_dea is not None:
                if pre_dif <= pre_dea and cur_dif > cur_dea:
                    macd_pts = 20
                    signals.append("macd_golden_cross")
                    detail["macd_signal"] = "金叉"
                elif pre_dif >= pre_dea and cur_dif < cur_dea:
                    macd_pts = -20
                    detail["macd_signal"] = "死叉"
                else:
                    detail["macd_signal"] = "多头" if cur_dif > cur_dea else "空头"
    except Exception:
        logger.debug("indicator calc failed for %s", ts_code, exc_info=True)

    # Weighted combination of sub-scores
    # limit_pts already 0-100; others are bonus/penalty on base 50
    score = 50.0 + (limit_pts - 50) * 0.3 + vol_pts * 0.25 + gap_pts * 0.15 + sr_pts * 0.15 + rsi_pts * 0.1 + macd_pts * 0.05
    return _clamp(score), detail, signals


async def _score_sentiment(session: AsyncSession, ts_code: str, trade_date: str) -> tuple[float, dict, list[str]]:
    """Sentiment dimension score (0-100).

    Reuses market_temperature logic inline, checks limit/dragon-tiger boards.
    """
    score = 50.0
    detail: dict = {}
    signals: list[str] = []

    # -- market temperature --------------------------------------------------
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

    detail["temperature"] = temperature
    detail["limit_up"] = up_count
    detail["limit_down"] = down_count
    detail["seal_rate"] = round(seal_rate, 1)

    temp_pts = 0.0
    if temperature in ("极热",):
        temp_pts = 80
    elif temperature == "偏热":
        temp_pts = 60
    elif temperature == "冰点":
        temp_pts = -30
    elif temperature == "偏冷":
        temp_pts = -15

    # -- is stock on limit board today? -------------------------------------
    on_limit_r = await session.execute(text("""
        SELECT 1 FROM limit_list_ths
        WHERE ts_code = :code AND trade_date = :td AND limit_type = '涨停池'
        LIMIT 1
    """), {"code": ts_code, "td": trade_date})
    on_limit = on_limit_r.fetchone() is not None
    limit_pts = 40 if on_limit else 0
    if on_limit:
        signals.append("limit_board")
    detail["on_limit_board"] = on_limit

    # -- is stock on dragon-tiger board? ------------------------------------
    lhb_r = await session.execute(text("""
        SELECT 1 FROM hm_detail
        WHERE ts_code = :code AND trade_date = :td
        LIMIT 1
    """), {"code": ts_code, "td": trade_date})
    on_lhb = lhb_r.fetchone() is not None
    lhb_pts = 30 if on_lhb else 0
    if on_lhb:
        signals.append("dragon_tiger")
    detail["on_dragon_tiger"] = on_lhb

    # -- is stock's sector hot today? (top-5 by limit-up count) -------------
    sector_r = await session.execute(text("""
        SELECT sb.industry, COUNT(*) as cnt
        FROM limit_list_ths ll
        JOIN stock_basic sb ON ll.ts_code = sb.ts_code
        WHERE ll.trade_date = :td AND ll.limit_type = '涨停池'
        GROUP BY sb.industry
        ORDER BY cnt DESC LIMIT 5
    """), {"td": trade_date})
    hot_sectors = [row[0] for row in sector_r.fetchall() if row[0]]

    stock_ind_r = await session.execute(text("""
        SELECT industry FROM stock_basic WHERE ts_code = :code
    """), {"code": ts_code})
    stock_ind_row = stock_ind_r.fetchone()
    stock_industry = stock_ind_row[0] if stock_ind_row else None

    sector_pts = 0
    if stock_industry and stock_industry in hot_sectors:
        sector_pts = 20
        signals.append("hot_sector")
    detail["stock_industry"] = stock_industry
    detail["hot_sectors"] = hot_sectors

    score = 50.0 + temp_pts * 0.3 + limit_pts * 0.25 + lhb_pts * 0.2 + sector_pts * 0.25
    return _clamp(score), detail, signals


async def _score_fundamental(session: AsyncSession, ts_code: str, trade_date: str) -> tuple[float, dict, list[str]]:
    """Fundamental dimension score (0-100).

    Uses fina_indicator + daily_basic for PE/ROE/growth.
    """
    score = 50.0
    detail: dict = {}
    signals: list[str] = []

    # -- latest financials --------------------------------------------------
    fina_r = await session.execute(text("""
        SELECT end_date, roe, netprofit_yoy, or_yoy
        FROM fina_indicator
        WHERE ts_code = :code
        ORDER BY end_date DESC LIMIT 1
    """), {"code": ts_code})
    fina_row = fina_r.fetchone()

    roe = _clean_float(fina_row[1]) if fina_row else None
    np_yoy = _clean_float(fina_row[2]) if fina_row else None
    or_yoy = _clean_float(fina_row[3]) if fina_row else None
    detail["roe"] = roe
    detail["netprofit_yoy"] = np_yoy
    detail["or_yoy"] = or_yoy
    detail["fina_period"] = fina_row[0] if fina_row else None

    roe_pts = 0.0
    if roe is not None:
        if roe > 15:
            roe_pts = 80
            signals.append("roe_high")
        elif roe > 10:
            roe_pts = 60
        elif roe > 5:
            roe_pts = 40

    or_pts = 0.0
    if or_yoy is not None:
        if or_yoy > 20:
            or_pts = 70
            signals.append("revenue_growth")
        elif or_yoy > 10:
            or_pts = 50

    np_pts = 0.0
    if np_yoy is not None:
        if np_yoy > 30:
            np_pts = 80
            signals.append("profit_surge")
        elif np_yoy > 10:
            np_pts = 50

    # -- PE_TTM percentile within industry ----------------------------------
    pe_pts = 0.0
    # First get the stock's industry
    ind_r = await session.execute(text("""
        SELECT industry FROM stock_basic WHERE ts_code = :code
    """), {"code": ts_code})
    ind_row = ind_r.fetchone()
    industry = ind_row[0] if ind_row else None

    if industry:
        pe_r = await session.execute(text("""
            SELECT db.pe_ttm
            FROM daily_basic db
            JOIN stock_basic sb ON db.ts_code = sb.ts_code
            WHERE sb.industry = :ind AND sb.list_status = 'L'
              AND db.trade_date = (
                  SELECT MAX(trade_date) FROM daily_basic WHERE trade_date <= :td
              )
              AND db.pe_ttm > 0 AND db.pe_ttm IS NOT NULL
            ORDER BY db.pe_ttm
        """), {"ind": industry, "td": trade_date})
        all_pe = [row[0] for row in pe_r.fetchall() if row[0] and not math.isnan(row[0])]

        # Get this stock's PE
        own_pe_r = await session.execute(text("""
            SELECT pe_ttm FROM daily_basic
            WHERE ts_code = :code AND trade_date <= :td AND pe_ttm > 0
            ORDER BY trade_date DESC LIMIT 1
        """), {"code": ts_code, "td": trade_date})
        own_pe_row = own_pe_r.fetchone()
        own_pe = _clean_float(own_pe_row[0]) if own_pe_row else None
        detail["pe_ttm"] = own_pe

        if own_pe and all_pe:
            below = sum(1 for v in all_pe if v < own_pe)
            pct = below / len(all_pe) * 100
            detail["pe_percentile"] = round(pct, 1)
            if pct < 30:
                pe_pts = 70
                signals.append("pe_low")
            elif pct < 50:
                pe_pts = 50

    score = 50.0 + (roe_pts - 50) * 0.3 + (pe_pts - 50) * 0.25 + (or_pts - 50) * 0.25 + (np_pts - 50) * 0.2
    return _clamp(score), detail, signals


async def _score_news(session: AsyncSession, ts_code: str, trade_date: str) -> tuple[float, dict, list[str]]:
    """News dimension score (0-100).

    Uses news_classified for recent 3-day sentiment and announcements.
    """
    score = 50.0
    detail: dict = {}
    signals: list[str] = []

    # Compute date range: trade_date minus ~3 calendar days (safe approximation)
    try:
        td = datetime.strptime(trade_date, "%Y%m%d")
        start_dt = (td - timedelta(days=4)).strftime("%Y-%m-%d") + " 00:00:00"
        end_dt = td.strftime("%Y-%m-%d") + " 23:59:59"
    except ValueError:
        return score, detail, signals

    # -- recent news sentiment for this stock --------------------------------
    news_r = await session.execute(text("""
        SELECT nc.sentiment, COUNT(*) as cnt
        FROM news_classified nc
        JOIN stock_news n ON nc.news_id = n.id
        WHERE nc.related_codes LIKE :code_pat
          AND n.datetime BETWEEN :start AND :end
        GROUP BY nc.sentiment
    """), {"code_pat": f"%{ts_code}%", "start": start_dt, "end": end_dt})

    pos_count = 0
    neg_count = 0
    for row in news_r.fetchall():
        if row[0] == "positive":
            pos_count = row[1]
        elif row[0] == "negative":
            neg_count = row[1]

    net_positive = pos_count - neg_count
    news_pts = min(net_positive * 15, 60) if net_positive > 0 else max(net_positive * 15, -60)
    detail["positive_news"] = pos_count
    detail["negative_news"] = neg_count
    detail["net_sentiment"] = net_positive

    if net_positive >= 2:
        signals.append("news_positive")
    elif net_positive <= -2:
        signals.append("news_negative")

    # -- major announcements (业绩预增/中标/战略合作) --------------------------
    ann_r = await session.execute(text("""
        SELECT ac.ann_type, ac.sentiment
        FROM anns_classified ac
        JOIN stock_anns a ON ac.anns_id = a.id
        WHERE a.ts_code = :code
          AND a.ann_date >= :start_date
        ORDER BY a.ann_date DESC LIMIT 10
    """), {"code": ts_code, "start_date": trade_date[:8] if len(trade_date) >= 8 else trade_date})

    # Fallback: check with wider date range if no results
    ann_rows = ann_r.fetchall()
    if not ann_rows:
        ann_r2 = await session.execute(text("""
            SELECT ac.ann_type, ac.sentiment
            FROM anns_classified ac
            JOIN stock_anns a ON ac.anns_id = a.id
            WHERE a.ts_code = :code
            ORDER BY a.ann_date DESC LIMIT 5
        """), {"code": ts_code})
        ann_rows = ann_r2.fetchall()

    major_pts = 0
    major_types = {"earnings_forecast", "contract", "restructure"}
    for row in ann_rows:
        ann_type = row[0]
        ann_sent = row[1]
        if ann_type in major_types and ann_sent == "positive":
            major_pts = 40
            signals.append("major_announcement")
            detail["major_ann_type"] = ann_type
            break

    score = 50.0 + news_pts * 0.6 + major_pts * 0.4
    return _clamp(score), detail, signals


# ── Core scoring class ────────────────────────────────────────────────────

# Weight config
WEIGHTS = {
    "tech": 0.30,
    "sentiment": 0.25,
    "fundamental": 0.25,
    "news": 0.20,
}


async def score_stock(
    session: AsyncSession,
    ts_code: str,
    trade_date: str,
    name: str = "",
) -> dict:
    """Compute composite score for a single stock."""
    tech_score, tech_detail, tech_signals = await _score_tech(session, ts_code, trade_date)
    sent_score, sent_detail, sent_signals = await _score_sentiment(session, ts_code, trade_date)
    fund_score, fund_detail, fund_signals = await _score_fundamental(session, ts_code, trade_date)
    news_score, news_detail, news_signals = await _score_news(session, ts_code, trade_date)

    total = (
        tech_score * WEIGHTS["tech"]
        + sent_score * WEIGHTS["sentiment"]
        + fund_score * WEIGHTS["fundamental"]
        + news_score * WEIGHTS["news"]
    )

    all_signals = list(dict.fromkeys(tech_signals + sent_signals + fund_signals + news_signals))

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
    """Score and rank pre-filtered stocks for a given trade date.

    Pre-filter via SQL:
      - 当日有交易 (stock_daily 存在)
      - 非停牌、非ST (除非在涨停池)
      - 换手率 > 1% 或 成交额 > 5000万
    """
    # Step 1: SQL pre-filter — returns ~500-1000 candidates
    candidates_r = await session.execute(text("""
        SELECT DISTINCT sd.ts_code, sb.name
        FROM stock_daily sd
        JOIN stock_basic sb ON sd.ts_code = sb.ts_code
        LEFT JOIN daily_basic db ON sd.ts_code = db.ts_code AND sd.trade_date = db.trade_date
        LEFT JOIN limit_list_ths ll ON sd.ts_code = ll.ts_code
            AND ll.trade_date = :td AND ll.limit_type = '涨停池'
        WHERE sd.trade_date = :td
          AND sb.list_status = 'L'
          AND (
              sb.name NOT LIKE '%ST%'
              OR ll.ts_code IS NOT NULL
          )
          AND (
              COALESCE(db.turnover_rate, 0) > 1
              OR sd.amount > 50000
          )
        ORDER BY sd.ts_code
    """), {"td": trade_date})

    candidates = candidates_r.fetchall()
    logger.info("rank_stocks: %d candidates after pre-filter for %s", len(candidates), trade_date)

    if not candidates:
        return {
            "trade_date": trade_date,
            "scored_stocks": [],
            "market_overview": {"temperature": "无数据", "avg_score": 0, "high_score_count": 0},
        }

    # Step 2: Score each candidate
    scored: list[dict] = []
    for ts_code, name in candidates:
        try:
            result = await score_stock(session, ts_code, trade_date, name or "")
            if result["total_score"] >= min_score:
                scored.append(result)
        except Exception:
            logger.debug("scoring failed for %s", ts_code, exc_info=True)
            continue

    # Step 3: Sort by total_score descending, take top N
    scored.sort(key=lambda x: x["total_score"], reverse=True)
    top = scored[:limit]

    # Step 4: Market overview
    all_scores = [s["total_score"] for s in scored]
    avg_score = round(sum(all_scores) / len(all_scores), 1) if all_scores else 0
    high_count = sum(1 for s in all_scores if s >= 70)

    # Temperature from sentiment detail (use first stock's cached data, or re-query)
    temperature = "中性"
    if top and "sentiment_detail" in top[0]:
        temperature = top[0]["sentiment_detail"].get("temperature", "中性")

    return {
        "trade_date": trade_date,
        "scored_stocks": top,
        "market_overview": {
            "temperature": temperature,
            "avg_score": avg_score,
            "high_score_count": high_count,
        },
    }


# ── API endpoint ──────────────────────────────────────────────────────────

@scorer_router.get("/ranked")
async def get_ranked_stocks(
    trade_date: str = Query("", description="YYYYMMDD, default=today"),
    limit: int = Query(50, ge=1, le=200, description="Top N results"),
    min_score: float = Query(0, ge=0, le=100, description="Minimum total score"),
):
    """Return ranked stock scores for a given trading day."""
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")

    async with async_session() as session:
        result = await rank_stocks(session, trade_date, limit, min_score)

    return result


@scorer_router.get("/score/{ts_code}")
async def get_stock_score(
    ts_code: str,
    trade_date: str = Query("", description="YYYYMMDD, default=today"),
):
    """Return composite score for a single stock."""
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")

    # Look up name
    async with async_session() as session:
        name_r = await session.execute(text(
            "SELECT name FROM stock_basic WHERE ts_code = :code"
        ), {"code": ts_code})
        name_row = name_r.fetchone()
        name = name_row[0] if name_row else ""

        result = await score_stock(session, ts_code, trade_date, name)

    return result
