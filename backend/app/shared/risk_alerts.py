"""Risk alert engine — generates warnings for ST, earnings forecast, CB forced redemption.

Called by GET /api/v1/risk/alerts. All queries are async via SQLAlchemy session.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _clean(rows: list[dict]) -> list[dict]:
    """Replace NaN/None with JSON-safe values."""
    for row in rows:
        for k, v in row.items():
            if v is None or (isinstance(v, float) and str(v) == "nan"):
                row[k] = None
    return rows


async def _st_alerts(session: AsyncSession) -> list[dict]:
    """A. ST warnings: stocks newly added to ST list within last 30 days."""
    alerts: list[dict] = []

    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    r = await session.execute(text("""
        WITH dated AS (
            SELECT DISTINCT trade_date FROM stock_st
            WHERE trade_date >= :cutoff
            ORDER BY trade_date
        ),
        pairs AS (
            SELECT trade_date,
                   LAG(trade_date) OVER (ORDER BY trade_date) AS prev_date
            FROM dated
        )
        SELECT p.trade_date, s.ts_code, s.name, s.type_name
        FROM pairs p
        JOIN stock_st s ON s.trade_date = p.trade_date
        WHERE p.prev_date IS NOT NULL
          AND s.ts_code NOT IN (
              SELECT ts_code FROM stock_st WHERE trade_date = p.prev_date
          )
        ORDER BY p.trade_date DESC
    """), {"cutoff": cutoff})

    for row in r.fetchall():
        td = row[0]
        alerts.append({
            "type": "公告ST",
            "level": "high",
            "ts_code": row[1],
            "name": row[2],
            "detail": f"新增风险警示: {row[3] or 'ST'}（{td}）",
            "time": f"{td[:4]}-{td[4:6]}-{td[6:]}",
        })

    return alerts


async def _forecast_alerts(session: AsyncSession) -> list[dict]:
    """B. Earnings forecast alerts: recent announcements within last 30 days."""
    alerts: list[dict] = []
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")

    r = await session.execute(text("""
        SELECT f.ts_code, b.name, f.type, f.ann_date, f.end_date,
               f.p_change_min, f.p_change_max, f.net_profit_min, f.net_profit_max
        FROM forecast f
        JOIN stock_basic b ON f.ts_code = b.ts_code
        WHERE f.ann_date >= :cutoff
        ORDER BY f.ann_date DESC
        LIMIT 100
    """), {"cutoff": cutoff})

    level_map = {
        "预增": "info", "略增": "info", "扭亏": "info", "续盈": "info",
        "预减": "warning", "略减": "warning", "首亏": "warning", "续亏": "warning",
    }

    for row in r.fetchall():
        ts_code, name, ftype, ann_date, end_date = row[0], row[1], row[2], row[3], row[4]
        p_min, p_max = row[5], row[6]
        np_min, np_max = row[7], row[8]

        pct_range = ""
        if p_min is not None and p_max is not None:
            pct_range = f"{p_min:.0f}%~{p_max:.0f}%"

        profit_str = ""
        if np_min is not None and np_max is not None:
            profit_str = f"净利润 {np_min / 10000:.0f}~{np_max / 10000:.0f} 亿"

        detail_parts = [f"{ftype} — 报告期{end_date}"]
        if pct_range:
            detail_parts.append(f"同比{pct_range}")
        if profit_str:
            detail_parts.append(profit_str)

        alerts.append({
            "type": "业绩预告",
            "level": level_map.get(ftype, "info"),
            "ts_code": ts_code,
            "name": name,
            "forecast_type": ftype,
            "pct_range": pct_range,
            "detail": ", ".join(detail_parts),
            "time": f"{ann_date[:4]}-{ann_date[4:6]}-{ann_date[6:]}" if ann_date and len(ann_date) == 8 else ann_date,
        })

    return alerts


async def _cb_call_alerts(session: AsyncSession) -> list[dict]:
    """C. Convertible bond forced redemption alerts."""
    alerts: list[dict] = []

    r = await session.execute(text("""
        SELECT c.ts_code, b.bond_short_name, b.stk_code, b.stk_short_name,
               c.call_type, c.is_call, c.ann_date, c.call_date, c.call_price
        FROM cb_call c
        JOIN cb_basic b ON c.ts_code = b.ts_code
        WHERE c.is_call LIKE '%满足强赎%'
           OR c.is_call LIKE '%公告提示强赎%'
           OR c.is_call LIKE '%公告实施强赎%'
        ORDER BY c.ann_date DESC NULLS LAST
        LIMIT 50
    """))

    for row in r.fetchall():
        bond_code, bond_name = row[0], row[1]
        stk_code, stk_name = row[2], row[3]
        call_type, is_call = row[4], row[5]
        ann_date, call_date, call_price = row[6], row[7], row[8]

        detail_parts = [f"{bond_name}({bond_code})"]
        if stk_name:
            detail_parts.append(f"正股 {stk_name}({stk_code})")
        detail_parts.append(f"状态: {is_call}")
        if call_date:
            detail_parts.append(f"赎回日 {call_date}")
        if call_price:
            detail_parts.append(f"赎回价 {call_price}")

        alerts.append({
            "type": "可转债强赎",
            "level": "warning",
            "ts_code": stk_code or bond_code,
            "bond_code": bond_code,
            "bond_name": bond_name,
            "stk_code": stk_code,
            "is_call": is_call,
            "call_date": call_date,
            "detail": " | ".join(detail_parts),
            "time": f"{ann_date[:4]}-{ann_date[4:6]}-{ann_date[6:]}" if ann_date and len(ann_date) == 8 else ann_date,
        })

    return alerts


async def generate_risk_alerts(session: AsyncSession) -> dict:
    """Main entry: generate all risk alerts."""
    st = await _st_alerts(session)
    fc = await _forecast_alerts(session)
    cb = await _cb_call_alerts(session)
    all_alerts = st + fc + cb
    return {
        "count": len(all_alerts),
        "data": _clean(all_alerts),
        "summary": {
            "st": len(st),
            "forecast": len(fc),
            "cb_call": len(cb),
        },
    }
