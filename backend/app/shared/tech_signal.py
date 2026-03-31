"""Technical signal detection module.

Lightweight technical analysis focused on price + volume:
  - Consecutive limit-up count
  - Volume anomaly (vs 20-day average)
  - Gap detection (price gaps between trading days)
  - Simple support/resistance levels
"""

from __future__ import annotations

import math
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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
