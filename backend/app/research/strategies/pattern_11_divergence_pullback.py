"""模式 11 ｜ 新题材次日分歧低吸（前排核心）。

模式手册原文：第二天板块分歧（龙头开板/缩量），等量化砸到低点（~20s 窗口）→
**只买已被验证的前排核心**（首日已涨停的），杂毛会亏。

回测难点：
    - "20 秒窗口" 必须分钟级 + tick 数据才能准确模拟
    - 日级近似：T 日龙1 当日盘中开过板（open_times >= 1）= "分歧"信号

触发条件（日级近似）：
    - T-1 日某板块涨停 ≥ 4 只（首日有强度）
    - T 日同板块龙1 当日 limit_times >= 2（连续涨停 = 已被验证的前排）
    - T 日龙1 当日 open_times >= 1（盘中分歧/炸板）
    - 板块当日仍有 ≥ 2 只涨停（题材未死）

操作（回测口径）：
    - 买入：T 日 close（盘中分歧后的尾盘价位代理"砸盘低点"）
    - 卖出：T+1 open
    - holding = overnight

风险：
    - 日级 close ≠ 真实"砸盘低点"，承认买入价偏高
    - 假分歧 → 收盘前再次封死 close 反而是高点
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.research.signals.long_head_detector import detect_long_head
from app.research.strategies.base_pattern import (
    BasePattern,
    PatternSignal,
    load_sectors,
)

logger = logging.getLogger(__name__)


class Pattern11(BasePattern):
    pattern_id = "pattern_11"
    description = "次日分歧低吸前排核心（日级近似）"

    PREV_SECTOR_MIN = 4         # T-1 板块涨停数下限
    TODAY_SECTOR_MIN = 2        # T 日板块仍有涨停数
    LONG1_MIN_BOARDS = 2        # 龙1 至少 2 板（前排核心）
    LONG1_MIN_OPEN_TIMES = 1    # 当日开板次数下限（=分歧信号）

    async def _prev_trade_date(self, session: AsyncSession, td: str) -> str | None:
        r = await session.execute(text(
            "SELECT cal_date FROM trade_cal "
            "WHERE cal_date < :d AND is_open=1 "
            "ORDER BY cal_date DESC LIMIT 1"
        ), {"d": td})
        row = r.fetchone()
        return row[0] if row else None

    async def _prev_sector_size(
        self, session: AsyncSession, sector: str, prev_date: str
    ) -> int:
        r = await session.execute(text(
            "SELECT COUNT(*) FROM daily_sector_review "
            "WHERE trade_date=:d AND source='bankuai' "
            "AND raw_meta->>'scope'='daily' AND sector_name=:s"
        ), {"d": prev_date, "s": sector})
        return int(r.scalar() or 0)

    async def find_signals(
        self, session: AsyncSession, trade_date: str, source: str = "bankuai"
    ) -> list[PatternSignal]:
        sectors = await load_sectors(session, trade_date, source)
        if not sectors:
            return []
        prev_td = await self._prev_trade_date(session, trade_date)
        if not prev_td:
            return []

        signals: list[PatternSignal] = []
        for sec_name, codes in sectors.items():
            prev_size = await self._prev_sector_size(session, sec_name, prev_td)
            if prev_size < self.PREV_SECTOR_MIN:
                continue  # 昨天板块不够强 → 不算"延续"

            lh = await detect_long_head(session, trade_date, codes, sector_name=sec_name)
            today_size = len(lh.long1_group) + (1 if lh.long2 else 0) + len(lh.followers)
            if today_size < self.TODAY_SECTOR_MIN:
                continue
            long1 = lh.long1
            if not long1:
                continue
            if long1.limit_times < self.LONG1_MIN_BOARDS:
                continue
            if long1.open_times < self.LONG1_MIN_OPEN_TIMES:
                continue

            signals.append(PatternSignal(
                trade_date=trade_date,
                pattern=self.pattern_id,
                sector=sec_name,
                long1_code=long1.ts_code,
                long1_name=long1.name,
                long1_tag=long1.tag or f"{long1.limit_times}板",
                long1_first_time=long1.first_time,
                long1_open_times=long1.open_times,
                sector_size=today_size,
                pick_code=long1.ts_code,
                pick_name=long1.name,
                pick_role="long1",
                pick_tag=long1.tag or f"{long1.limit_times}板",
                reason=f"分歧（昨{prev_size}→今{today_size}+龙1开板{long1.open_times}次）",
                holding="overnight",
            ))
        return signals

    async def _check(self, lh, sector_size, ohlc_map, trade_date, prediction=None):
        return None
