"""算法 B：从当日涨停池反推主线题材。

核心思路：
1. 当日涨停池（limit_stats where limit='U'）→ 拿 ts_code、连板数 limit_times
2. join concept_detail 取每只股票的所有概念
3. 黑名单过滤（资金属性 / 宽基类标签）
4. 按概念聚合：
   - count = 该概念下涨停股票数
   - hot_score = sum( (limit_times)^1.5 )  连板权重
5. 取 top-N

输出格式与 daily_sector_review 表对齐，便于直接对照人工标签。

严格 no-lookahead：只用 trade_date 当日及以前的数据。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.research.signals.concept_blacklist import is_blacklisted

logger = logging.getLogger(__name__)


@dataclass
class StockInSector:
    ts_code: str
    name: str
    limit_times: int
    first_time: str | None
    float_mv: float | None
    amount: float | None


@dataclass
class SectorMainLine:
    sector_name: str
    rank: int  # 1-based, 1 最强
    count: int  # 该板块涨停只数
    hot_score: float  # 连板加权热度
    stocks: list[StockInSector]


async def compute_main_line(
    session: AsyncSession,
    trade_date: str,
    top_n: int = 15,
    min_count: int = 2,
) -> list[SectorMainLine]:
    """计算 trade_date 当日主线板块。

    Args:
        trade_date: YYYYMMDD
        top_n: 返回前 N 个板块
        min_count: 板块至少包含的涨停只数（过滤偶发组合）
    """
    # 1) 涨停池
    rows = (
        await session.execute(
            text(
                "SELECT ts_code, name, COALESCE(limit_times, 1) AS limit_times, "
                "       first_time, float_mv, amount "
                "FROM limit_stats "
                "WHERE trade_date=:d AND \"limit\"='U'"
            ),
            {"d": trade_date},
        )
    ).fetchall()

    if not rows:
        logger.warning("trade_date=%s 没有涨停股", trade_date)
        return []

    pool: dict[str, StockInSector] = {}
    for r in rows:
        pool[r[0]] = StockInSector(
            ts_code=r[0],
            name=r[1] or "",
            limit_times=int(r[2] or 1),
            first_time=r[3],
            float_mv=r[4],
            amount=r[5],
        )

    ts_codes = list(pool.keys())

    # 2) 概念归属（一次性 join 出来，避免 N+1）
    cd_rows = (
        await session.execute(
            text(
                "SELECT ts_code, concept_name "
                "FROM concept_detail "
                "WHERE ts_code = ANY(:codes) AND concept_name IS NOT NULL"
            ),
            {"codes": ts_codes},
        )
    ).fetchall()

    # concept -> [ts_code, ...]
    concept_to_stocks: dict[str, list[str]] = {}
    for ts_code, concept in cd_rows:
        if is_blacklisted(concept):
            continue
        concept_to_stocks.setdefault(concept, []).append(ts_code)

    # 3) 聚合 + 排序
    sectors: list[SectorMainLine] = []
    for concept, codes in concept_to_stocks.items():
        if len(codes) < min_count:
            continue
        stocks = sorted(
            (pool[c] for c in codes),
            key=lambda s: (-s.limit_times, s.first_time or "99:99"),
        )
        hot = sum((s.limit_times ** 1.5) for s in stocks)
        sectors.append(
            SectorMainLine(
                sector_name=concept,
                rank=0,  # 后面填
                count=len(stocks),
                hot_score=hot,
                stocks=stocks,
            )
        )

    # 排序键：先按热度降序、再按只数降序
    sectors.sort(key=lambda x: (-x.hot_score, -x.count))
    sectors = sectors[:top_n]
    for i, s in enumerate(sectors, 1):
        s.rank = i

    return sectors


def format_main_line_report(sectors: list[SectorMainLine]) -> str:
    """生成可读字符串，便于人工对照人工标签。"""
    lines = []
    for s in sectors:
        head = f"#{s.rank} {s.sector_name} (count={s.count}, hot={s.hot_score:.1f})"
        lines.append(head)
        for stk in s.stocks[:6]:
            lines.append(
                f"   {stk.limit_times}板  {stk.ts_code} {stk.name}  "
                f"first={stk.first_time}  mv={stk.float_mv}"
            )
    return "\n".join(lines)
