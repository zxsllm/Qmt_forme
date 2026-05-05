"""模式 10 ｜ 新题材 / 大题材首日上车（核心 + 杂毛全员）。

触发条件：
    - 当日某板块涨停 ≥ 4 只
    - 该板块在 T-1 日"几乎没出现"（昨天涨停 ≤ 1 只）→ 新题材首日特征
    - 板块在 daily_sector_review (source='bankuai' AND scope='daily') 里有标签

操作：
    - 买入板块**全员**涨停股（核心 + 杂毛都上）
    - T+1 open 卖出
    - holding = overnight

模式手册原文：新题材首日，杂毛会被资金外溢拉起来，**首日的容错率最高**。

风险：
    - 题材夭折 / 一日游 → 杂毛先死
    - "新题材"判定依赖人工标签 → 用 daily_sector_review 的人工口径模拟
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.research.signals.long_head_detector import detect_long_head
from app.research.strategies.base_pattern import (
    BasePattern,
    PatternSignal,
    fetch_daily_ohlc,
    load_sectors,
)

logger = logging.getLogger(__name__)


class Pattern10(BasePattern):
    pattern_id = "pattern_10"
    description = "新题材首日 + 全员上车（核心+杂毛）"

    SECTOR_TODAY_MIN = 4         # 当日板块至少 N 只涨停
    SECTOR_PREV_MAX = 1          # 前一日该板块最多 M 只涨停（视为"新")

    async def _prev_sector_size(
        self, session: AsyncSession, sector: str, prev_date: str
    ) -> int:
        """前一日该板块涨停数（只看 source=bankuai daily 标签）。"""
        r = await session.execute(text(
            "SELECT COUNT(*) FROM daily_sector_review "
            "WHERE trade_date=:d AND source='bankuai' "
            "AND raw_meta->>'scope'='daily' AND sector_name=:s"
        ), {"d": prev_date, "s": sector})
        return int(r.scalar() or 0)

    async def _prev_trade_date(self, session: AsyncSession, td: str) -> str | None:
        r = await session.execute(text(
            "SELECT cal_date FROM trade_cal "
            "WHERE cal_date < :d AND is_open=1 "
            "ORDER BY cal_date DESC LIMIT 1"
        ), {"d": td})
        row = r.fetchone()
        return row[0] if row else None

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
            lh = await detect_long_head(session, trade_date, codes, sector_name=sec_name)
            today_size = len(lh.long1_group) + (1 if lh.long2 else 0) + len(lh.followers)
            if today_size < self.SECTOR_TODAY_MIN:
                continue
            prev_size = await self._prev_sector_size(session, sec_name, prev_td)
            if prev_size > self.SECTOR_PREV_MAX:
                continue  # 不是新题材，是延续题材

            # 全员上车：龙1群组 + 龙2 + 影子龙 + 跟风
            members = []
            for s in lh.long1_group:
                members.append(("long1", s))
            if lh.long2:
                members.append(("long2", lh.long2))
            if lh.shadow and lh.shadow.ts_code not in {s.ts_code for s in lh.long1_group} \
                    and (not lh.long2 or lh.shadow.ts_code != lh.long2.ts_code):
                members.append(("shadow", lh.shadow))
            for f in lh.followers:
                members.append(("follower", f))

            for role, stk in members:
                signals.append(PatternSignal(
                    trade_date=trade_date,
                    pattern=self.pattern_id,
                    sector=sec_name,
                    long1_code=lh.long1.ts_code,
                    long1_name=lh.long1.name,
                    long1_tag=lh.long1.tag or f"{lh.long1.limit_times}板",
                    long1_first_time=lh.long1.first_time,
                    long1_open_times=lh.long1.open_times,
                    sector_size=today_size,
                    pick_code=stk.ts_code,
                    pick_name=stk.name,
                    pick_role=role,
                    pick_tag=stk.tag or f"{stk.limit_times}板",
                    reason=f"新题材首日（昨天{prev_size}只→今天{today_size}只）",
                    holding="overnight",
                ))
        return signals

    async def _check(self, lh, sector_size, ohlc_map, trade_date, prediction=None):
        # 不使用，find_signals 已重写
        return None
