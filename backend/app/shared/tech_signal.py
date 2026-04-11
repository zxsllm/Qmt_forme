"""Technical signal detection module.

Lightweight technical analysis focused on price + volume:
  - Consecutive limit-up count
  - Volume anomaly (vs 20-day average)
  - Gap detection (price gaps between trading days)
  - Simple support/resistance levels
  - Technical indicator snapshot (MACD/RSI/KDJ/BOLL)
"""

from __future__ import annotations

import math

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.research.indicators import macd, rsi, kdj, boll, ma


def _safe(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return float(v)


async def consecutive_limit_count(session: AsyncSession, ts_code: str, trade_date: str = "") -> dict:
    """Count current consecutive limit-up days for a stock."""
    date_filter = "AND trade_date <= :td" if trade_date else ""
    params: dict = {"code": ts_code}
    if trade_date:
        params["td"] = trade_date

    r = await session.execute(text(f"""
        SELECT trade_date, limit_type
        FROM limit_list_ths
        WHERE ts_code = :code {date_filter}
        ORDER BY trade_date DESC
        LIMIT 30
    """), params)

    streak = 0
    for row in r.fetchall():
        if row[1] == "U":
            streak += 1
        else:
            break

    return {"ts_code": ts_code, "consecutive_limit_up": streak}


async def volume_anomaly(session: AsyncSession, ts_code: str, trade_date: str = "") -> dict:
    """Detect volume anomaly vs 20-day average.

    Returns ratio: >2 = significant surge, <0.5 = significant shrinkage.
    """
    date_filter = "AND trade_date <= :td" if trade_date else ""
    params: dict = {"code": ts_code}
    if trade_date:
        params["td"] = trade_date

    r = await session.execute(text(f"""
        SELECT trade_date, vol, amount, close, pct_chg
        FROM stock_daily
        WHERE ts_code = :code {date_filter}
        ORDER BY trade_date DESC
        LIMIT 21
    """), params)

    rows = r.fetchall()
    if len(rows) < 2:
        return {"ts_code": ts_code, "data": None}

    latest = rows[0]
    today_vol = _safe(latest[1])

    hist_vols = [_safe(r[1]) for r in rows[1:] if _safe(r[1]) and _safe(r[1]) > 0]
    avg_vol = sum(hist_vols) / len(hist_vols) if hist_vols else None

    ratio = round(today_vol / avg_vol, 2) if today_vol and avg_vol and avg_vol > 0 else None

    signal = "normal"
    if ratio is not None:
        if ratio >= 3:
            signal = "extreme_surge"
        elif ratio >= 2:
            signal = "surge"
        elif ratio <= 0.3:
            signal = "extreme_shrink"
        elif ratio <= 0.5:
            signal = "shrink"

    return {
        "ts_code": ts_code,
        "trade_date": latest[0],
        "data": {
            "today_vol": today_vol,
            "avg_vol_20d": round(avg_vol, 0) if avg_vol else None,
            "ratio": ratio,
            "signal": signal,
            "today_close": _safe(latest[3]),
            "today_pct_chg": _safe(latest[4]),
        },
    }


async def gap_analysis(session: AsyncSession, ts_code: str, trade_date: str = "") -> dict:
    """Detect price gaps (跳空缺口) in recent trading days."""
    date_filter = "AND trade_date <= :td" if trade_date else ""
    params: dict = {"code": ts_code}
    if trade_date:
        params["td"] = trade_date

    r = await session.execute(text(f"""
        SELECT trade_date, open, high, low, close, pre_close
        FROM stock_daily
        WHERE ts_code = :code {date_filter}
        ORDER BY trade_date DESC
        LIMIT 30
    """), params)

    rows = r.fetchall()
    gaps = []

    for i in range(len(rows) - 1):
        curr = rows[i]
        prev = rows[i + 1]

        curr_low = _safe(curr[3])
        curr_high = _safe(curr[2])
        prev_high = _safe(prev[2])
        prev_low = _safe(prev[3])

        if curr_low is None or curr_high is None or prev_high is None or prev_low is None:
            continue

        if curr_low > prev_high:
            gap_size = round((curr_low - prev_high) / prev_high * 100, 2)
            gaps.append({
                "trade_date": curr[0],
                "type": "up",
                "gap_low": curr_low,
                "gap_high": prev_high,
                "gap_pct": gap_size,
                "filled": curr_high >= curr_low and curr_low <= prev_high,
            })
        elif curr_high < prev_low:
            gap_size = round((prev_low - curr_high) / prev_low * 100, 2)
            gaps.append({
                "trade_date": curr[0],
                "type": "down",
                "gap_low": curr_high,
                "gap_high": prev_low,
                "gap_pct": gap_size,
                "filled": False,
            })

    return {"ts_code": ts_code, "gaps": gaps}


async def support_resistance(session: AsyncSession, ts_code: str, days: int = 60) -> dict:
    """Calculate simple support and resistance levels from recent highs/lows."""
    r = await session.execute(text("""
        SELECT trade_date, high, low, close, vol
        FROM stock_daily
        WHERE ts_code = :code
        ORDER BY trade_date DESC
        LIMIT :days
    """), {"code": ts_code, "days": days})

    rows = r.fetchall()
    if not rows:
        return {"ts_code": ts_code, "data": None}

    highs = [(_safe(r[1]), r[0]) for r in rows if _safe(r[1])]
    lows = [(_safe(r[2]), r[0]) for r in rows if _safe(r[2])]
    closes = [_safe(r[3]) for r in rows if _safe(r[3])]

    if not highs or not lows or not closes:
        return {"ts_code": ts_code, "data": None}

    current_close = closes[0]
    period_high = max(highs, key=lambda x: x[0])
    period_low = min(lows, key=lambda x: x[0])

    resistance_levels = sorted(
        set(h[0] for h in highs if h[0] > current_close),
    )[:3]

    support_levels = sorted(
        set(l[0] for l in lows if l[0] < current_close),
        reverse=True,
    )[:3]

    ma5 = round(sum(closes[:5]) / min(5, len(closes)), 2) if closes else None
    ma10 = round(sum(closes[:10]) / min(10, len(closes)), 2) if len(closes) >= 5 else None
    ma20 = round(sum(closes[:20]) / min(20, len(closes)), 2) if len(closes) >= 10 else None

    return {
        "ts_code": ts_code,
        "data": {
            "current_close": current_close,
            "period_high": {"price": period_high[0], "date": period_high[1]},
            "period_low": {"price": period_low[0], "date": period_low[1]},
            "resistance": resistance_levels,
            "support": support_levels,
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "position_pct": round(
                (current_close - period_low[0]) / (period_high[0] - period_low[0]) * 100, 1
            ) if period_high[0] != period_low[0] else 50.0,
        },
    }


# ── Risk auxiliary rules ─────────────────────────────────────────

async def risk_check(session: AsyncSession, ts_code: str, trade_date: str = "") -> dict:
    """Aggregate technical risk signals for a stock.

    Rules:
      1. 断板预警: consecutive limit-ups + shrinking volume or broken board yesterday
      2. 天量见天价: volume hits N-day high near price peak + upper shadow
    """
    warnings: list[dict] = []

    # Fetch recent daily data
    date_filter = "AND trade_date <= :td" if trade_date else ""
    params: dict = {"code": ts_code}
    if trade_date:
        params["td"] = trade_date

    r = await session.execute(text(f"""
        SELECT trade_date, open, high, low, close, pre_close, vol, pct_chg
        FROM stock_daily
        WHERE ts_code = :code {date_filter}
        ORDER BY trade_date DESC LIMIT 25
    """), params)
    bars = r.fetchall()
    if len(bars) < 3:
        return {"ts_code": ts_code, "warnings": [], "risk_level": "low"}

    latest = bars[0]
    l_open, l_high, l_low, l_close = _safe(latest[1]), _safe(latest[2]), _safe(latest[3]), _safe(latest[4])
    l_vol = _safe(latest[6])
    l_pct = _safe(latest[7])

    # Rule 1: 断板预警 — check if stock has been on limit-up streak
    limit_r = await session.execute(text(f"""
        SELECT trade_date, limit_type FROM limit_list_ths
        WHERE ts_code = :code {date_filter}
        ORDER BY trade_date DESC LIMIT 10
    """), params)
    limit_rows = limit_r.fetchall()

    streak = 0
    just_broken = False
    for lr in limit_rows:
        if lr[1] == "U":
            streak += 1
        elif lr[1] == "Z" and streak == 0:
            just_broken = True
            break
        else:
            break

    if streak >= 2 and l_vol and bars[1]:
        prev_vol = _safe(bars[1][6])
        if prev_vol and prev_vol > 0 and l_vol / prev_vol < 0.7:
            warnings.append({
                "rule": "break_risk",
                "level": "high",
                "message": f"连板{streak}天后缩量({l_vol/prev_vol:.0%})，断板风险较高",
            })

    if just_broken:
        warnings.append({
            "rule": "post_break",
            "level": "high",
            "message": "昨日炸板，今日大幅低开风险",
        })

    if streak >= 4:
        warnings.append({
            "rule": "high_streak",
            "level": "medium",
            "message": f"已连板{streak}天，高位接力风险加大",
        })

    # Rule 2: 天量见天价
    if l_vol and len(bars) >= 20:
        hist_vols = [_safe(b[6]) for b in bars[1:21] if _safe(b[6])]
        if hist_vols:
            max_hist_vol = max(hist_vols)
            avg_hist_vol = sum(hist_vols) / len(hist_vols)

            if l_vol > max_hist_vol and l_high and l_close and l_high > 0:
                upper_shadow = (l_high - l_close) / l_high * 100
                if upper_shadow >= 2:
                    warnings.append({
                        "rule": "peak_volume",
                        "level": "high",
                        "message": f"天量({l_vol/avg_hist_vol:.1f}倍均量) + 长上影({upper_shadow:.1f}%)，见顶信号",
                    })
                elif l_vol > avg_hist_vol * 3:
                    warnings.append({
                        "rule": "extreme_volume",
                        "level": "medium",
                        "message": f"成交量异常放大({l_vol/avg_hist_vol:.1f}倍均量)，注意高位风险",
                    })

    # Rule 3: 大阴线 after rally
    if l_pct and l_pct <= -5:
        recent_gains = sum(_safe(b[7]) or 0 for b in bars[1:6])
        if recent_gains > 15:
            warnings.append({
                "rule": "reversal",
                "level": "high",
                "message": f"大阴线({l_pct:.1f}%)出现在近5日涨幅{recent_gains:.1f}%之后",
            })

    risk_level = "low"
    if any(w["level"] == "high" for w in warnings):
        risk_level = "high"
    elif any(w["level"] == "medium" for w in warnings):
        risk_level = "medium"

    return {
        "ts_code": ts_code,
        "trade_date": latest[0],
        "warnings": warnings,
        "risk_level": risk_level,
    }


# ── Technical indicator snapshot ───────────────────────────────


async def technical_snapshot(
    session: AsyncSession, ts_code: str, trade_date: str = ""
) -> dict:
    """Compute MACD / RSI / KDJ / BOLL snapshot and detect signals.

    Returns a structured dict with current indicator values and
    actionable signals (golden/death cross, overbought/oversold,
    Bollinger band position) for use in review/pre-market reports.
    """
    date_filter = "AND trade_date <= :td" if trade_date else ""
    params: dict = {"code": ts_code}
    if trade_date:
        params["td"] = trade_date

    r = await session.execute(text(f"""
        SELECT trade_date, open, high, low, close, vol
        FROM stock_daily
        WHERE ts_code = :code {date_filter}
        ORDER BY trade_date DESC
        LIMIT 120
    """), params)

    rows = r.fetchall()
    if len(rows) < 35:
        return {"ts_code": ts_code, "data": None, "signals": []}

    # Build DataFrame in chronological order (oldest first)
    cols = ["trade_date", "open", "high", "low", "close", "vol"]
    df = pd.DataFrame(rows, columns=cols).iloc[::-1].reset_index(drop=True)
    for c in ("open", "high", "low", "close", "vol"):
        df[c] = pd.to_numeric(df[c], errors="coerce")

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # ── Compute indicators ──────────────────────────────────
    dif, dea, macd_hist = macd(close)
    rsi_val = rsi(close, period=14)
    k_val, d_val, j_val = kdj(high, low, close)
    boll_mid, boll_upper, boll_lower = boll(close)
    ma5 = ma(close, window=5)
    ma10 = ma(close, window=10)
    ma20 = ma(close, window=20)

    # Latest values
    idx = len(df) - 1
    prev = idx - 1

    def _v(series: pd.Series, i: int = idx) -> float | None:
        val = series.iloc[i] if i < len(series) else None
        if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
            return None
        return round(float(val), 4)

    latest_close = _v(close)

    # ── Inline signal labels for each indicator ────────────
    # MACD signal
    cur_dif, cur_dea = _v(dif), _v(dea)
    pre_dif, pre_dea = _v(dif, prev), _v(dea, prev)
    macd_signal = ""
    if cur_dif is not None and cur_dea is not None and pre_dif is not None and pre_dea is not None:
        if pre_dif <= pre_dea and cur_dif > cur_dea:
            macd_signal = "金叉"
        elif pre_dif >= pre_dea and cur_dif < cur_dea:
            macd_signal = "死叉"
        elif cur_dif > cur_dea:
            macd_signal = "多头"
        else:
            macd_signal = "空头"

    # RSI signal
    cur_rsi = _v(rsi_val)
    if cur_rsi is not None:
        if cur_rsi >= 80:
            rsi_signal = "超买"
        elif cur_rsi >= 50:
            rsi_signal = "偏强"
        elif cur_rsi >= 20:
            rsi_signal = "偏弱"
        else:
            rsi_signal = "超卖"
    else:
        rsi_signal = ""

    # KDJ signal
    cur_k, cur_d, cur_j = _v(k_val), _v(d_val), _v(j_val)
    pre_k, pre_d = _v(k_val, prev), _v(d_val, prev)
    kdj_signal = ""
    if cur_k is not None and cur_d is not None:
        if cur_k > 80:
            kdj_signal = "超买"
        elif cur_k < 20:
            kdj_signal = "超卖"
        elif pre_k is not None and pre_d is not None:
            if pre_k <= pre_d and cur_k > cur_d:
                kdj_signal = "金叉"
            elif pre_k >= pre_d and cur_k < cur_d:
                kdj_signal = "死叉"
            else:
                kdj_signal = "中性"

    # BOLL position
    cur_upper, cur_lower, cur_mid = _v(boll_upper), _v(boll_lower), _v(boll_mid)
    boll_position = ""
    if latest_close is not None and cur_upper is not None and cur_lower is not None and cur_mid is not None:
        if latest_close >= cur_upper:
            boll_position = "突破上轨"
        elif latest_close <= cur_lower:
            boll_position = "跌破下轨"
        elif latest_close > cur_mid:
            boll_position = "中轨上方"
        else:
            boll_position = "中轨下方"

    data = {
        "trade_date": df.iloc[idx]["trade_date"],
        "close": latest_close,
        "macd": {
            "dif": _v(dif), "dea": _v(dea), "hist": _v(macd_hist),
            "prev_dif": _v(dif, prev), "prev_dea": _v(dea, prev),
            "signal": macd_signal,
        },
        "rsi": {"value": cur_rsi, "signal": rsi_signal},
        "kdj": {"k": cur_k, "d": cur_d, "j": cur_j, "signal": kdj_signal},
        "boll": {
            "upper": cur_upper, "mid": cur_mid, "lower": cur_lower,
            "position": boll_position,
        },
        "ma": {"ma5": _v(ma5), "ma10": _v(ma10), "ma20": _v(ma20)},
    }

    # ── Detailed signal list ──────────────────────────────────
    signals: list[dict] = []

    # MACD cross signals
    if macd_signal == "金叉":
        signals.append({"indicator": "MACD", "signal": "golden_cross",
                        "level": "bullish", "message": "MACD金叉（DIF上穿DEA）"})
    elif macd_signal == "死叉":
        signals.append({"indicator": "MACD", "signal": "death_cross",
                        "level": "bearish", "message": "MACD死叉（DIF下穿DEA）"})

    # MACD zero-axis cross
    if cur_dif is not None and pre_dif is not None:
        if pre_dif <= 0 and cur_dif > 0:
            signals.append({"indicator": "MACD", "signal": "above_zero",
                            "level": "bullish", "message": "MACD DIF上穿零轴，趋势转多"})
        elif pre_dif >= 0 and cur_dif < 0:
            signals.append({"indicator": "MACD", "signal": "below_zero",
                            "level": "bearish", "message": "MACD DIF下穿零轴，趋势转空"})

    # RSI signals
    if cur_rsi is not None:
        if cur_rsi >= 80:
            signals.append({"indicator": "RSI", "signal": "overbought",
                            "level": "bearish", "message": f"RSI={cur_rsi}，超买区间（≥80）"})
        elif cur_rsi >= 70:
            signals.append({"indicator": "RSI", "signal": "near_overbought",
                            "level": "caution", "message": f"RSI={cur_rsi}，接近超买（≥70）"})
        elif cur_rsi <= 20:
            signals.append({"indicator": "RSI", "signal": "oversold",
                            "level": "bullish", "message": f"RSI={cur_rsi}，超卖区间（≤20）"})
        elif cur_rsi <= 30:
            signals.append({"indicator": "RSI", "signal": "near_oversold",
                            "level": "bullish", "message": f"RSI={cur_rsi}，接近超卖（≤30）"})

    # KDJ signals
    if kdj_signal == "金叉":
        zone = "低位" if cur_k and cur_k < 30 else "高位" if cur_k and cur_k > 70 else "中位"
        signals.append({"indicator": "KDJ", "signal": "golden_cross",
                        "level": "bullish" if (cur_k or 50) < 50 else "caution",
                        "message": f"KDJ{zone}金叉（K={cur_k}, D={cur_d}）"})
    elif kdj_signal == "死叉":
        zone = "高位" if cur_k and cur_k > 70 else "低位" if cur_k and cur_k < 30 else "中位"
        signals.append({"indicator": "KDJ", "signal": "death_cross",
                        "level": "bearish" if (cur_k or 50) > 50 else "caution",
                        "message": f"KDJ{zone}死叉（K={cur_k}, D={cur_d}）"})
    if cur_j is not None:
        if cur_j > 100:
            signals.append({"indicator": "KDJ", "signal": "j_overbought",
                            "level": "bearish", "message": f"KDJ J值={cur_j}，超买钝化（>100）"})
        elif cur_j < 0:
            signals.append({"indicator": "KDJ", "signal": "j_oversold",
                            "level": "bullish", "message": f"KDJ J值={cur_j}，超卖钝化（<0）"})

    # Bollinger Band signals
    if boll_position == "突破上轨":
        signals.append({"indicator": "BOLL", "signal": "above_upper",
                        "level": "bearish", "message": f"股价({latest_close})突破布林上轨({cur_upper})，短期超强或回调风险"})
    elif boll_position == "跌破下轨":
        signals.append({"indicator": "BOLL", "signal": "below_lower",
                        "level": "bullish", "message": f"股价({latest_close})跌破布林下轨({cur_lower})，超跌或支撑位"})
    if cur_upper and cur_lower and cur_mid and cur_mid > 0:
        bandwidth = (cur_upper - cur_lower) / cur_mid * 100
        if bandwidth < 5:
            signals.append({"indicator": "BOLL", "signal": "squeeze",
                            "level": "caution", "message": f"布林带收窄({bandwidth:.1f}%)，变盘临近"})

    # MA trend
    cur_ma5, cur_ma10, cur_ma20 = _v(ma5), _v(ma10), _v(ma20)
    ma_signal = ""
    if cur_ma5 is not None and cur_ma10 is not None and cur_ma20 is not None:
        if cur_ma5 > cur_ma10 > cur_ma20:
            ma_signal = "多头排列"
            signals.append({"indicator": "MA", "signal": "bullish_alignment",
                            "level": "bullish", "message": "均线多头排列（MA5>MA10>MA20）"})
        elif cur_ma5 < cur_ma10 < cur_ma20:
            ma_signal = "空头排列"
            signals.append({"indicator": "MA", "signal": "bearish_alignment",
                            "level": "bearish", "message": "均线空头排列（MA5<MA10<MA20）"})

    # ── Generate summary for Claude CLI ────────────────────
    bullish_count = sum(1 for s in signals if s["level"] == "bullish")
    bearish_count = sum(1 for s in signals if s["level"] == "bearish")

    parts = []
    if macd_signal:
        parts.append(f"MACD{macd_signal}")
    if rsi_signal:
        parts.append(f"RSI{rsi_signal}")
    if kdj_signal:
        parts.append(f"KDJ{kdj_signal}")
    if boll_position:
        parts.append(f"BOLL{boll_position}")
    if ma_signal:
        parts.append(f"均线{ma_signal}")

    if bullish_count > bearish_count:
        tone = "技术面偏多"
    elif bearish_count > bullish_count:
        tone = "技术面偏空"
    else:
        tone = "技术面中性"

    caution_parts = []
    if rsi_signal in ("超买", "超卖"):
        caution_parts.append(f"RSI{rsi_signal}")
    if kdj_signal in ("超买", "超卖"):
        caution_parts.append(f"KDJ{kdj_signal}")
    if boll_position in ("突破上轨", "跌破下轨"):
        caution_parts.append(f"BOLL{boll_position}")

    summary = f"{tone}，{'，'.join(parts)}"
    if caution_parts:
        summary += f"，注意{'和'.join(caution_parts)}风险"

    return {
        "ts_code": ts_code,
        "data": data,
        "signals": signals,
        "summary": summary,
    }


async def batch_technical_signals(
    session: AsyncSession, ts_codes: list[str], trade_date: str = ""
) -> list[dict]:
    """Batch technical snapshot for multiple stocks.

    Returns a list of compact signal summaries for use in review reports.
    Skips stocks with insufficient data.
    """
    results = []
    for code in ts_codes:
        snap = await technical_snapshot(session, code, trade_date)
        if snap.get("data") is None:
            continue
        results.append({
            "ts_code": code,
            "trade_date": snap["data"]["trade_date"],
            "macd_signal": snap["data"]["macd"]["signal"],
            "rsi_value": snap["data"]["rsi"]["value"],
            "rsi_signal": snap["data"]["rsi"]["signal"],
            "kdj_signal": snap["data"]["kdj"]["signal"],
            "boll_position": snap["data"]["boll"]["position"],
            "summary": snap["summary"],
            "bullish_signals": sum(1 for s in snap["signals"] if s["level"] == "bullish"),
            "bearish_signals": sum(1 for s in snap["signals"] if s["level"] == "bearish"),
        })
    return results
