"""Scorer rules — pure scoring computation, no DB access.

Each function takes pre-fetched data and returns (score, detail, signals).
Data fetching: scorer_data.py | Orchestration: stock_scorer.py
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)


def _clean_float(val):
    """Return None for NaN/Inf floats, otherwise the value."""
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ── Technical ────────────────────────────────────────────────────────────

def score_tech(limit_rows: list, bars: list) -> tuple[float, dict, list[str]]:
    """Technical dimension score (0-100)."""
    score = 50.0
    detail: dict = {}
    signals: list[str] = []

    # consecutive limit-up
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

    # gap detection
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

    # RSI / MACD
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
        logger.debug("indicator calc failed", exc_info=True)

    score = 50.0 + (limit_pts - 50) * 0.3 + vol_pts * 0.25 + gap_pts * 0.15 + sr_pts * 0.15 + rsi_pts * 0.1 + macd_pts * 0.05
    return _clamp(score), detail, signals


# ── Sentiment ────────────────────────────────────────────────────────────

def score_sentiment(
    market: dict, on_limit: bool, on_lhb: bool,
    hot_sectors: list, industry: str | None,
) -> tuple[float, dict, list[str]]:
    """Sentiment dimension score (0-100)."""
    detail: dict = {}
    signals: list[str] = []

    temperature = market["temperature"]
    detail["temperature"] = temperature
    detail["limit_up"] = market["limit_up"]
    detail["limit_down"] = market["limit_down"]
    detail["seal_rate"] = market["seal_rate"]

    temp_pts = 0.0
    if temperature in ("极热",):
        temp_pts = 80
    elif temperature == "偏热":
        temp_pts = 60
    elif temperature == "冰点":
        temp_pts = -30
    elif temperature == "偏冷":
        temp_pts = -15

    limit_pts = 40 if on_limit else 0
    if on_limit:
        signals.append("limit_board")
    detail["on_limit_board"] = on_limit

    lhb_pts = 30 if on_lhb else 0
    if on_lhb:
        signals.append("dragon_tiger")
    detail["on_dragon_tiger"] = on_lhb

    sector_pts = 0
    if industry and industry in hot_sectors:
        sector_pts = 20
        signals.append("hot_sector")
    detail["stock_industry"] = industry
    detail["hot_sectors"] = hot_sectors

    score = 50.0 + temp_pts * 0.3 + limit_pts * 0.25 + lhb_pts * 0.2 + sector_pts * 0.25
    return _clamp(score), detail, signals


# ── Fundamental ──────────────────────────────────────────────────────────

def score_fundamental(
    fina_row, industry: str | None, all_pe: list, own_pe,
) -> tuple[float, dict, list[str]]:
    """Fundamental dimension score (0-100)."""
    detail: dict = {}
    signals: list[str] = []

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

    pe_pts = 0.0
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


# ── News ─────────────────────────────────────────────────────────────────

def score_news(
    pos_count: int, neg_count: int, ann_rows: list,
) -> tuple[float, dict, list[str]]:
    """News dimension score (0-100)."""
    detail: dict = {}
    signals: list[str] = []

    net_positive = pos_count - neg_count
    news_pts = min(net_positive * 15, 60) if net_positive > 0 else max(net_positive * 15, -60)
    detail["positive_news"] = pos_count
    detail["negative_news"] = neg_count
    detail["net_sentiment"] = net_positive

    if net_positive >= 2:
        signals.append("news_positive")
    elif net_positive <= -2:
        signals.append("news_negative")

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
