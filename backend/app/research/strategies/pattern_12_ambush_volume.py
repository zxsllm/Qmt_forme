"""模式 12 ｜ 埋伏的板块核心股启动 + 放量确认。

触发条件（回测近似）：
    - 板块当日涨停 ≥ 3 只（共振）
    - 板块前一日涨停 ≥ 1 只（不是新题材，是延续题材）
    - 龙1 首板（limit_times == 1 或 days_to_board <= 2）→ "刚启动"
    - 龙1 当日成交额 > 5 日均额 × 1.8（放量启动）

操作（回测口径）：
    - 买入：龙1（板块核心 + 放量启动信号）
    - T+1 open 卖出（趋势策略本应持仓 N 天，回测先用 T+1 对比，holding=overnight）

模式手册原文：放量 + 板块共振 → 直接加仓而不是观望。

风险：
    - 缩量假启动 / 单兵作战（板块没共振）
    - 趋势策略短线化导致的收益偏低（应做 T+5 / T+10 持仓）
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.research.signals.long_head_detector import LongHeadResult
from app.research.strategies.base_pattern import (
    BasePattern,
    PatternSignal,
)

logger = logging.getLogger(__name__)


class Pattern12(BasePattern):
    pattern_id = "pattern_12"
    description = "埋伏核心股启动 + 放量 + 板块共振"
    sector_min_size = 3

    VOL_RATIO_MIN = 1.8         # 当日量额 / 5日均量额 阈值

    async def _amount_ratio(
        self, session: AsyncSession, trade_date: str, ts_code: str
    ) -> float | None:
        """当日成交额 / 前5日均成交额。"""
        r = await session.execute(text(
            "SELECT trade_date, amount FROM stock_daily "
            "WHERE ts_code=:c AND trade_date <= :d "
            "ORDER BY trade_date DESC LIMIT 6"
        ), {"c": ts_code, "d": trade_date})
        rows = r.fetchall()
        if len(rows) < 6:
            return None
        today_amt = rows[0][1] or 0
        prev_5 = [r[1] or 0 for r in rows[1:]]
        avg5 = sum(prev_5) / 5
        if avg5 <= 0:
            return None
        return today_amt / avg5

    async def _prev_sector_size(
        self, session: AsyncSession, sector: str, prev_date: str
    ) -> int:
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

    async def _check(
        self,
        lh: LongHeadResult,
        sector_size: int,
        ohlc_map: dict,
        trade_date: str,
        prediction=None,
    ) -> PatternSignal | None:
        long1 = lh.long1
        if not long1:
            return None
        # 启动信号：首板（≤ 2 板）。已经是连板高标 → 不是"启动"
        if long1.limit_times > 2:
            return None
        return PatternSignal(
            trade_date=trade_date,
            pattern=self.pattern_id,
            sector=lh.sector,
            long1_code=long1.ts_code,
            long1_name=long1.name,
            long1_tag=long1.tag or f"{long1.limit_times}板",
            long1_first_time=long1.first_time,
            long1_open_times=long1.open_times,
            sector_size=sector_size,
            pick_code=long1.ts_code,
            pick_name=long1.name,
            pick_role="long1",
            pick_tag=long1.tag or f"{long1.limit_times}板",
            reason=f"核心股启动+板块共振{sector_size}只",
            holding="overnight",
        )

    async def find_signals(
        self, session: AsyncSession, trade_date: str, source: str = "bankuai"
    ) -> list[PatternSignal]:
        # 复用基类逻辑做 _check 初筛，再做放量 + 延续题材二次过滤
        prelim = await super().find_signals(session, trade_date, source)
        if not prelim:
            return []

        prev_td = await self._prev_trade_date(session, trade_date)
        if not prev_td:
            return []

        out: list[PatternSignal] = []
        for sig in prelim:
            # 延续题材过滤（不是新题材）
            prev_size = await self._prev_sector_size(session, sig.sector, prev_td)
            if prev_size < 1:
                continue
            # 放量过滤
            ratio = await self._amount_ratio(session, trade_date, sig.pick_code)
            if ratio is None or ratio < self.VOL_RATIO_MIN:
                continue
            sig.reason += f" 量比{ratio:.1f}x"
            out.append(sig)
        return out
