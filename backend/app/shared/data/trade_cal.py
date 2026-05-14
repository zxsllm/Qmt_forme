"""交易日历查询工具 — 用于 sell_anchor_date 等"下一交易日"场景。

提供 async 查询（实时打 DB）+ sync 查找（用预拉缓存，OMS apply_fill 走这条）。
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


async def get_trade_dates_from(start_date: str, n: int = 60) -> list[str]:
    """从 trade_cal 取 cal_date >= start_date 的前 n 个开盘日。

    Args:
        start_date: YYYYMMDD（trade_cal 表的格式）
        n: 取多少个连续开盘日

    Returns:
        list of YYYY-MM-DD 字符串（engine 的内部日期格式，与 entry_date 一致）
    """
    from app.core.database import async_session
    async with async_session() as s:
        rows = (await s.execute(text(
            "SELECT cal_date FROM trade_cal "
            "WHERE cal_date >= :sd AND is_open=1 "
            "ORDER BY cal_date LIMIT :n"
        ), {"sd": start_date, "n": n})).fetchall()
    return [
        f"{r[0][:4]}-{r[0][4:6]}-{r[0][6:8]}"
        for r in rows
    ]


def next_trade_date_from_cache(entry_date: str, cache: list[str]) -> str | None:
    """entry_date YYYY-MM-DD → cache 中第一个严格 > entry_date 的日期。

    Returns None when cache is empty or entry_date 超出 cache 末端。调用方应 fallback
    到 naive +1 (skip weekends) 逻辑。
    """
    for d in cache:
        if d > entry_date:
            return d
    return None
