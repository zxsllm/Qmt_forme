"""StockScorer — 信号聚合评分引擎.

Integrates four dimensions (tech / sentiment / fundamental / news)
into a single sortable composite score.  Uses SQL pre-filtering and
batch data pre-fetch to minimize DB round-trips.

Single-stock mode:  each scorer queries individually (~14 queries).
Batch mode (rank_stocks):  _prefetch_batch() loads all data up-front
  (~13 queries total), then scorers read from the ctx dict.

Endpoint:
  GET /api/v1/signals/ranked?trade_date=20260411&limit=50&min_score=60
"""

from __future__ import annotations

import json
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


# ── Batch pre-fetch ──────────────────────────────────────────────────────

async def _prefetch_batch(
    session: AsyncSession, trade_date: str, codes: list[str],
) -> dict:
    """Pre-fetch all scoring data for a batch of stocks.

    Reduces ~14 queries/stock × N stocks down to ~13 total queries.
    Returns a ctx dict consumed by the _score_* functions.
    """
    ctx: dict = {}
    codes_csv = ",".join(f"'{c}'" for c in codes)
    codes_set = set(codes)

    # ── Market-wide (shared for all stocks) ──────────────────────────────

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

    ctx["market"] = {
        "temperature": temperature,
        "limit_up": up_count,
        "limit_down": down_count,
        "broken": broken_count,
        "seal_rate": round(seal_rate, 1),
        "max_board": max_board,
    }

    sector_r = await session.execute(text("""
        SELECT sb.industry, COUNT(*) as cnt
        FROM limit_list_ths ll
        JOIN stock_basic sb ON ll.ts_code = sb.ts_code
        WHERE ll.trade_date = :td AND ll.limit_type = '涨停池'
        GROUP BY sb.industry ORDER BY cnt DESC LIMIT 5
    """), {"td": trade_date})
    ctx["hot_sectors"] = [row[0] for row in sector_r.fetchall() if row[0]]

    limit_set_r = await session.execute(text("""
        SELECT ts_code FROM limit_list_ths
        WHERE trade_date = :td AND limit_type = '涨停池'
    """), {"td": trade_date})
    ctx["on_limit_codes"] = {row[0] for row in limit_set_r.fetchall()}

    lhb_set_r = await session.execute(text("""
        SELECT DISTINCT ts_code FROM hm_detail WHERE trade_date = :td
    """), {"td": trade_date})
    ctx["on_lhb_codes"] = {row[0] for row in lhb_set_r.fetchall()}

    # ── Per-stock batch queries ──────────────────────────────────────────

    ind_r = await session.execute(text(f"""
        SELECT ts_code, industry FROM stock_basic WHERE ts_code IN ({codes_csv})
    """))
    ctx["industry_map"] = {row[0]: row[1] for row in ind_r.fetchall()}

    limit_r = await session.execute(text(f"""
        SELECT ts_code, trade_date, limit_type FROM (
            SELECT ts_code, trade_date, limit_type,
                   ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) as rn
            FROM limit_list_ths
            WHERE ts_code IN ({codes_csv}) AND trade_date <= :td
        ) sub WHERE rn <= 15
        ORDER BY ts_code, trade_date DESC
    """), {"td": trade_date})
    limit_hist: dict[str, list] = {}
    for row in limit_r.fetchall():
        limit_hist.setdefault(row[0], []).append((row[1], row[2]))
    ctx["limit_history"] = limit_hist

    bars_r = await session.execute(text(f"""
        SELECT ts_code, trade_date, open, high, low, close, pre_close, vol, pct_chg FROM (
            SELECT ts_code, trade_date, open, high, low, close, pre_close, vol, pct_chg,
                   ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) as rn
            FROM stock_daily
            WHERE ts_code IN ({codes_csv}) AND trade_date <= :td
        ) sub WHERE rn <= 60
        ORDER BY ts_code, trade_date DESC
    """), {"td": trade_date})
    bars_dict: dict[str, list] = {}
    for row in bars_r.fetchall():
        bars_dict.setdefault(row[0], []).append(row[1:])
    ctx["daily_bars"] = bars_dict

    fina_r = await session.execute(text(f"""
        SELECT ts_code, end_date, roe, netprofit_yoy, or_yoy FROM (
            SELECT ts_code, end_date, roe, netprofit_yoy, or_yoy,
                   ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY end_date DESC) as rn
            FROM fina_indicator
            WHERE ts_code IN ({codes_csv}) AND ann_date <= :td
        ) sub WHERE rn = 1
    """), {"td": trade_date})
    ctx["fina_data"] = {row[0]: row[1:] for row in fina_r.fetchall()}

    pe_r = await session.execute(text(f"""
        SELECT ts_code, pe_ttm FROM (
            SELECT ts_code, pe_ttm,
                   ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) as rn
            FROM daily_basic
            WHERE ts_code IN ({codes_csv}) AND trade_date <= :td AND pe_ttm > 0
        ) sub WHERE rn = 1
    """), {"td": trade_date})
    ctx["pe_own"] = {row[0]: row[1] for row in pe_r.fetchall()}

    industries = {v for v in ctx["industry_map"].values() if v}
    if industries:
        ind_csv = ",".join(f"'{i}'" for i in industries)
        ipe_r = await session.execute(text(f"""
            SELECT sb.industry, db.pe_ttm
            FROM daily_basic db
            JOIN stock_basic sb ON db.ts_code = sb.ts_code
            WHERE sb.industry IN ({ind_csv}) AND sb.list_status = 'L'
              AND db.trade_date = (SELECT MAX(trade_date) FROM daily_basic WHERE trade_date <= :td)
              AND db.pe_ttm > 0 AND db.pe_ttm IS NOT NULL
            ORDER BY sb.industry, db.pe_ttm
        """), {"td": trade_date})
        ind_pe: dict[str, list[float]] = {}
        for row in ipe_r.fetchall():
            if row[1] and not math.isnan(row[1]):
                ind_pe.setdefault(row[0], []).append(row[1])
        ctx["industry_pe"] = ind_pe
    else:
        ctx["industry_pe"] = {}

    # News + announcements
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
            # JSONB 列直接返回 list；兼容旧 Text 格式的 JSON 字符串
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

        ann_r = await session.execute(text(f"""
            SELECT sub.ts_code, ac.ann_type, ac.sentiment FROM (
                SELECT a.id, a.ts_code,
                       ROW_NUMBER() OVER (PARTITION BY a.ts_code ORDER BY a.ann_date DESC) as rn
                FROM stock_anns a
                WHERE a.ts_code IN ({codes_csv}) AND a.ann_date <= :td
            ) sub
            JOIN anns_classified ac ON ac.anns_id = sub.id
            WHERE sub.rn <= 10
        """), {"td": trade_date})
        ann_dict: dict[str, list] = {}
        for row in ann_r.fetchall():
            ann_dict.setdefault(row[0], []).append((row[1], row[2]))
        ctx["ann_data"] = ann_dict
    except Exception:
        logger.debug("batch news/ann prefetch failed", exc_info=True)
        ctx["news_sentiment"] = {}
        ctx["ann_data"] = {}

    return ctx


# ── Dimension scorers ────────────────────────────────────────────────────

async def _score_tech(
    session: AsyncSession, ts_code: str, trade_date: str,
    ctx: dict | None = None,
) -> tuple[float, dict, list[str]]:
    """Technical dimension score (0-100)."""
    score = 50.0
    detail: dict = {}
    signals: list[str] = []

    # -- consecutive limit-up ------------------------------------------------
    if ctx and "limit_history" in ctx:
        limit_rows = ctx["limit_history"].get(ts_code, [])
    else:
        r = await session.execute(text("""
            SELECT trade_date, limit_type
            FROM limit_list_ths
            WHERE ts_code = :code AND trade_date <= :td
            ORDER BY trade_date DESC LIMIT 15
        """), {"code": ts_code, "td": trade_date})
        limit_rows = r.fetchall()

    streak = 0
    for row in limit_rows:
        if row[1] == "涨停池":
            streak += 1
        else:
            break
    limit_pts = min(streak * 20, 100)
    detail["consecutive_limit_up"] = streak
    if streak >= 1:
        signals.append("limit_board")

    # -- volume anomaly + gap + indicator snapshot from recent bars ----------
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
    pos_pct = 0.5
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
                    sr_pts = 20
                elif pos_pct > 0.8:
                    sr_pts = -20
    detail["position_pct"] = round(pos_pct * 100, 1)

    # RSI / MACD quick calc
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

    score = 50.0 + (limit_pts - 50) * 0.3 + vol_pts * 0.25 + gap_pts * 0.15 + sr_pts * 0.15 + rsi_pts * 0.1 + macd_pts * 0.05
    return _clamp(score), detail, signals


async def _score_sentiment(
    session: AsyncSession, ts_code: str, trade_date: str,
    ctx: dict | None = None,
) -> tuple[float, dict, list[str]]:
    """Sentiment dimension score (0-100)."""
    score = 50.0
    detail: dict = {}
    signals: list[str] = []

    # -- market temperature --------------------------------------------------
    if ctx and "market" in ctx:
        mkt = ctx["market"]
        temperature = mkt["temperature"]
        up_count = mkt["limit_up"]
        down_count = mkt["limit_down"]
        seal_rate = mkt["seal_rate"]
    else:
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
        seal_rate = round(seal_rate, 1)

    detail["temperature"] = temperature
    detail["limit_up"] = up_count
    detail["limit_down"] = down_count
    detail["seal_rate"] = seal_rate

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
    if ctx and "on_limit_codes" in ctx:
        on_limit = ts_code in ctx["on_limit_codes"]
    else:
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
    if ctx and "on_lhb_codes" in ctx:
        on_lhb = ts_code in ctx["on_lhb_codes"]
    else:
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
    if ctx and "hot_sectors" in ctx and "industry_map" in ctx:
        hot_sectors = ctx["hot_sectors"]
        stock_industry = ctx["industry_map"].get(ts_code)
    else:
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


async def _score_fundamental(
    session: AsyncSession, ts_code: str, trade_date: str,
    ctx: dict | None = None,
) -> tuple[float, dict, list[str]]:
    """Fundamental dimension score (0-100)."""
    score = 50.0
    detail: dict = {}
    signals: list[str] = []

    # -- latest financials --------------------------------------------------
    if ctx and "fina_data" in ctx:
        fina_row = ctx["fina_data"].get(ts_code)
    else:
        fina_r = await session.execute(text("""
            SELECT end_date, roe, netprofit_yoy, or_yoy
            FROM fina_indicator
            WHERE ts_code = :code AND ann_date <= :td
            ORDER BY end_date DESC LIMIT 1
        """), {"code": ts_code, "td": trade_date})
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
    if ctx and "industry_map" in ctx:
        industry = ctx["industry_map"].get(ts_code)
    else:
        ind_r = await session.execute(text("""
            SELECT industry FROM stock_basic WHERE ts_code = :code
        """), {"code": ts_code})
        ind_row = ind_r.fetchone()
        industry = ind_row[0] if ind_row else None

    if industry:
        if ctx and "industry_pe" in ctx and "pe_own" in ctx:
            all_pe = ctx["industry_pe"].get(industry, [])
            own_pe = _clean_float(ctx["pe_own"].get(ts_code))
        else:
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


async def _score_news(
    session: AsyncSession, ts_code: str, trade_date: str,
    ctx: dict | None = None,
) -> tuple[float, dict, list[str]]:
    """News dimension score (0-100)."""
    score = 50.0
    detail: dict = {}
    signals: list[str] = []

    # -- recent news sentiment for this stock --------------------------------
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
            return score, detail, signals

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

    net_positive = pos_count - neg_count
    news_pts = min(net_positive * 15, 60) if net_positive > 0 else max(net_positive * 15, -60)
    detail["positive_news"] = pos_count
    detail["negative_news"] = neg_count
    detail["net_sentiment"] = net_positive

    if net_positive >= 2:
        signals.append("news_positive")
    elif net_positive <= -2:
        signals.append("news_negative")

    # -- major announcements -------------------------------------------------
    if ctx and "ann_data" in ctx:
        ann_rows = ctx["ann_data"].get(ts_code, [])
    else:
        try:
            td = datetime.strptime(trade_date, "%Y%m%d")
            start_dt = (td - timedelta(days=4)).strftime("%Y-%m-%d") + " 00:00:00"
        except ValueError:
            return _clamp(50.0 + news_pts * 0.6), detail, signals

        ann_r = await session.execute(text("""
            SELECT ac.ann_type, ac.sentiment
            FROM anns_classified ac
            JOIN stock_anns a ON ac.anns_id = a.id
            WHERE a.ts_code = :code
              AND a.ann_date >= :start_date
              AND a.ann_date <= :td
            ORDER BY a.ann_date DESC LIMIT 10
        """), {"code": ts_code, "start_date": trade_date, "td": trade_date})
        ann_rows = ann_r.fetchall()

        if not ann_rows:
            ann_r2 = await session.execute(text("""
                SELECT ac.ann_type, ac.sentiment
                FROM anns_classified ac
                JOIN stock_anns a ON ac.anns_id = a.id
                WHERE a.ts_code = :code AND a.ann_date <= :td
                ORDER BY a.ann_date DESC LIMIT 5
            """), {"code": ts_code, "td": trade_date})
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
    ctx: dict | None = None,
) -> dict:
    """Compute composite score for a single stock."""
    tech_score, tech_detail, tech_signals = await _score_tech(session, ts_code, trade_date, ctx)
    sent_score, sent_detail, sent_signals = await _score_sentiment(session, ts_code, trade_date, ctx)
    fund_score, fund_detail, fund_signals = await _score_fundamental(session, ts_code, trade_date, ctx)
    news_score, news_detail, news_signals = await _score_news(session, ts_code, trade_date, ctx)

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

    Pre-filter via SQL then batch-score using pre-fetched data.
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

    # Step 2: Batch pre-fetch all scoring data
    codes = [row[0] for row in candidates]
    ctx = await _prefetch_batch(session, trade_date, codes)
    logger.info("rank_stocks: batch prefetch done for %d candidates", len(codes))

    # Step 3: Score each candidate (uses cached data, no extra DB queries)
    scored: list[dict] = []
    for ts_code, name in candidates:
        try:
            result = await score_stock(session, ts_code, trade_date, name or "", ctx)
            if result["total_score"] >= min_score:
                scored.append(result)
        except Exception:
            logger.debug("scoring failed for %s", ts_code, exc_info=True)
            continue

    # Step 4: Sort by total_score descending, take top N
    scored.sort(key=lambda x: x["total_score"], reverse=True)
    top = scored[:limit]

    # Step 5: Market overview
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
