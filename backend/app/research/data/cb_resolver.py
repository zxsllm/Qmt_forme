"""可转债 CB 撮合辅助：
- stk_code → 当日有交易的 CB ts_code
- CB 日级 OHLC
- CB 分钟级 OHLC（用于精确卖出锚点）
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def find_cb_for_stock(
    session: AsyncSession, stk_code: str, trade_date: str
) -> str | None:
    """正股 stk_code → 当日活跃 CB ts_code（有交易、按成交额最大者优先）。

    一只正股可能有多只 CB，取当日最活跃的那只。
    无 CB 或 CB 当日无交易 → 返回 None。
    """
    r = await session.execute(text(
        "SELECT cb.ts_code FROM cb_basic cb "
        "JOIN cb_daily cd ON cd.ts_code=cb.ts_code AND cd.trade_date=:td "
        "WHERE cb.stk_code=:c AND cd.vol > 0 "
        "ORDER BY cd.amount DESC LIMIT 1"
    ), {"td": trade_date, "c": stk_code})
    row = r.fetchone()
    return row[0] if row else None


async def fetch_cb_close_open(
    session: AsyncSession, cb_code: str, td: str, t1: str
) -> tuple[float | None, float | None]:
    """CB T 日 close 和 T+1 open。"""
    r1 = await session.execute(text(
        "SELECT close FROM cb_daily WHERE trade_date=:d AND ts_code=:c AND vol > 0"
    ), {"d": td, "c": cb_code})
    r2 = await session.execute(text(
        "SELECT open FROM cb_daily WHERE trade_date=:d AND ts_code=:c AND vol > 0"
    ), {"d": t1, "c": cb_code})
    a = r1.fetchone()
    b = r2.fetchone()
    return (a[0] if a else None, b[0] if b else None)


def _hhmmss_to_dt(td: str, hhmmss: str) -> datetime | None:
    """'20260429' + '101530' → datetime(2026, 4, 29, 10, 15, 30)。"""
    if not hhmmss or len(hhmmss) < 4:
        return None
    h, m = int(hhmmss[:2]), int(hhmmss[2:4])
    s = int(hhmmss[4:6]) if len(hhmmss) >= 6 else 0
    try:
        return datetime.strptime(td, "%Y%m%d").replace(hour=h, minute=m, second=s)
    except ValueError:
        return None


async def fetch_min_close_at(
    session: AsyncSession, ts_code: str, td: str, hhmmss: str,
    table: str = "stock_min_kline",
) -> float | None:
    """T 日某时刻的分钟级 close（取 hhmmss 那一分钟的 close）。

    table: 'stock_min_kline' 或 'cb_min_kline'。
    分钟级表按月分区，主表代理走分区路由。
    """
    target = _hhmmss_to_dt(td, hhmmss)
    if not target:
        return None
    # 找该分钟（或之后最近一根）的 close
    td_start = datetime.strptime(td, "%Y%m%d").replace(hour=9, minute=30)
    td_end = datetime.strptime(td, "%Y%m%d").replace(hour=15, minute=0)
    r = await session.execute(text(
        f"SELECT close, trade_time FROM {table} "
        f"WHERE ts_code=:c AND freq='1min' "
        f"AND trade_time >= :start AND trade_time <= :end "
        f"AND trade_time >= :target "
        f"ORDER BY trade_time ASC LIMIT 1"
    ), {"c": ts_code, "start": td_start, "end": td_end, "target": target})
    row = r.fetchone()
    return float(row[0]) if row else None


async def fetch_min_open_at(
    session: AsyncSession, ts_code: str, td: str, hhmmss: str,
    table: str = "stock_min_kline",
) -> float | None:
    """T 日某时刻的分钟级 open（取 hhmmss 那一分钟或之后第一根的 open）。"""
    target = _hhmmss_to_dt(td, hhmmss)
    if not target:
        return None
    td_start = datetime.strptime(td, "%Y%m%d").replace(hour=9, minute=30)
    td_end = datetime.strptime(td, "%Y%m%d").replace(hour=15, minute=0)
    r = await session.execute(text(
        f"SELECT open FROM {table} "
        f"WHERE ts_code=:c AND freq='1min' "
        f"AND trade_time >= :start AND trade_time <= :end "
        f"AND trade_time >= :target "
        f"ORDER BY trade_time ASC LIMIT 1"
    ), {"c": ts_code, "start": td_start, "end": td_end, "target": target})
    row = r.fetchone()
    return float(row[0]) if row else None
