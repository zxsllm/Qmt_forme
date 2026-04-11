"""Risk alert engine — generates warnings for ST, earnings forecast, CB forced
redemption, share unlock, and shareholder increase/decrease.

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
    """A. ST warnings: newly ST-listed stocks + forecast-based consecutive-loss risk."""
    alerts: list[dict] = []

    # 1) 近期新增ST：对比最早可用日期 vs 最新日期，找出期间新增的ST股票
    diff_r = await session.execute(text("""
        WITH earliest AS (
            SELECT DISTINCT ts_code FROM stock_st
            WHERE trade_date = (SELECT MIN(trade_date) FROM stock_st)
        ),
        latest AS (
            SELECT DISTINCT ON (ts_code) ts_code, name, type_name
            FROM stock_st
            WHERE trade_date = (SELECT MAX(trade_date) FROM stock_st)
        ),
        first_seen AS (
            SELECT ts_code, MIN(trade_date) AS since_date
            FROM stock_st GROUP BY ts_code
        )
        SELECT l.ts_code, l.name, l.type_name, f.since_date
        FROM latest l
        JOIN first_seen f ON l.ts_code = f.ts_code
        WHERE l.ts_code NOT IN (SELECT ts_code FROM earliest)
        ORDER BY f.since_date DESC
    """))
    for row in diff_r.fetchall():
        since = row[3] or ""
        alerts.append({
            "type": "ST预警",
            "level": "high",
            "ts_code": row[0],
            "name": row[1],
            "detail": f"新增风险警示: {row[2] or 'ST'}（{since}起）",
            "time": f"{since[:4]}-{since[4:6]}-{since[6:]}" if len(since) == 8 else since,
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
            profit_str = f"净利润 {np_min / 10000:.2f}~{np_max / 10000:.2f} 亿"

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


async def _unlock_alerts(session: AsyncSession, trade_date: str = "",
                         days: int = 5) -> list[dict]:
    """D. 限售解禁预警：未来N天内有大额解禁的个股。

    Args:
        trade_date: 起始日期(YYYYMMDD)，默认今天
        days: 向前看N天
    """
    alerts: list[dict] = []
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")
    horizon = (datetime.strptime(trade_date, "%Y%m%d") + timedelta(days=days)).strftime("%Y%m%d")

    r = await session.execute(text("""
        SELECT f.ts_code, b.name, f.float_date, f.float_share, f.float_ratio,
               f.holder_name, f.share_type,
               d.close, d.total_mv
        FROM share_float f
        JOIN stock_basic b ON f.ts_code = b.ts_code
        LEFT JOIN daily_basic d ON f.ts_code = d.ts_code
             AND d.trade_date = (
                 SELECT MAX(trade_date) FROM daily_basic
                 WHERE ts_code = f.ts_code AND trade_date <= :td
             )
        WHERE f.float_date BETWEEN :td AND :horizon
          AND f.float_share IS NOT NULL
        ORDER BY COALESCE(f.float_ratio, 0) DESC, f.float_date ASC
        LIMIT 100
    """), {"td": trade_date, "horizon": horizon})

    for row in r.fetchall():
        ts_code, name = row[0], row[1]
        float_date, float_share, float_ratio = row[2], row[3], row[4]
        holder_name, share_type = row[5], row[6]
        close_price, total_mv = row[7], row[8]

        ratio = float_ratio or 0
        if ratio >= 10:
            risk_level = "高"
            level = "high"
        elif ratio >= 5:
            risk_level = "中"
            level = "warning"
        else:
            risk_level = "低"
            level = "info"

        # 估算解禁市值(亿)
        unlock_value = None
        if float_share and close_price:
            unlock_value = float_share * close_price / 1e8  # float_share单位万股→亿元

        fd = float_date or ""
        fd_fmt = f"{fd[:4]}-{fd[4:6]}-{fd[6:]}" if len(fd) == 8 else fd

        msg_parts = [f"{fd_fmt}解禁{ratio:.1f}%"]
        if unlock_value is not None:
            msg_parts.append(f"约{unlock_value:.1f}亿元")
        if share_type:
            msg_parts.append(share_type)
        message = "，".join(msg_parts)

        alerts.append({
            "type": "解禁预警",
            "level": level,
            "ts_code": ts_code,
            "name": name,
            "float_date": float_date,
            "float_share": float_share,
            "float_ratio": float_ratio,
            "risk_level": risk_level,
            "message": message,
            "detail": message,
            "time": fd_fmt,
        })

    return alerts


async def _holdertrade_alerts(session: AsyncSession, trade_date: str = "",
                              days: int = 7) -> list[dict]:
    """E. 股东增减持预警：近N天大额减持/增持。

    Args:
        trade_date: 截止日期(YYYYMMDD)，默认今天
        days: 向前回溯N天
    """
    alerts: list[dict] = []
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")
    cutoff = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=days)).strftime("%Y%m%d")

    r = await session.execute(text("""
        SELECT h.ts_code, b.name, h.ann_date, h.holder_name, h.holder_type,
               h.in_de, h.change_vol, h.change_ratio, h.avg_price, h.after_ratio
        FROM stk_holdertrade h
        JOIN stock_basic b ON h.ts_code = b.ts_code
        WHERE h.ann_date BETWEEN :cutoff AND :td
        ORDER BY h.ann_date DESC, ABS(COALESCE(h.change_ratio, 0)) DESC
        LIMIT 100
    """), {"cutoff": cutoff, "td": trade_date})

    for row in r.fetchall():
        ts_code, name, ann_date = row[0], row[1], row[2]
        holder_name, holder_type = row[3], row[4]
        in_de, change_vol, change_ratio = row[5], row[6], row[7]
        avg_price, after_ratio = row[8], row[9]

        is_decrease = in_de and "减" in in_de
        abs_ratio = abs(change_ratio) if change_ratio else 0

        if is_decrease:
            alert_type = "股东减持"
            if abs_ratio >= 5:
                risk_level, level = "高", "high"
            elif abs_ratio >= 1:
                risk_level, level = "中", "warning"
            else:
                risk_level, level = "低", "info"
        else:
            alert_type = "股东增持"
            risk_level, level = "利好", "info"

        holder_short = (holder_name[:10] + "…") if holder_name and len(holder_name) > 10 else (holder_name or "未知")
        direction = "减持" if is_decrease else "增持"
        msg_parts = [f"股东{holder_short}近{days}日{direction}{abs_ratio:.2f}%"]
        if change_vol:
            msg_parts.append(f"{abs(change_vol) / 10000:.2f}万股")
        if avg_price:
            msg_parts.append(f"均价{avg_price:.2f}")
        message = "，".join(msg_parts)

        ad = ann_date or ""
        alerts.append({
            "type": alert_type,
            "level": level,
            "ts_code": ts_code,
            "name": name,
            "holder_name": holder_name,
            "in_de": in_de,
            "change_vol": -abs(change_vol) if is_decrease and change_vol else change_vol,
            "change_ratio": -abs_ratio if is_decrease else abs_ratio,
            "ann_date": ann_date,
            "risk_level": risk_level,
            "message": message,
            "detail": message,
            "time": f"{ad[:4]}-{ad[4:6]}-{ad[6:]}" if len(ad) == 8 else ad,
        })

    return alerts


async def generate_risk_alerts(session: AsyncSession, trade_date: str = "") -> dict:
    """Main entry: generate all risk alerts.

    Args:
        trade_date: 基准日期(YYYYMMDD)，默认今天。传递给需要日期的子函数。
    """
    st = await _st_alerts(session)
    fc = await _forecast_alerts(session)
    cb = await _cb_call_alerts(session)
    unlock = await _unlock_alerts(session, trade_date=trade_date, days=5)
    holder = await _holdertrade_alerts(session, trade_date=trade_date, days=7)
    all_alerts = st + fc + cb + unlock + holder
    return {
        "count": len(all_alerts),
        "data": _clean(all_alerts),
        "summary": {
            "st": len(st),
            "forecast": len(fc),
            "cb_call": len(cb),
            "unlock": len(unlock),
            "holdertrade": len(holder),
        },
    }
