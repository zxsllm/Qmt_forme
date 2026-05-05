"""模式 5 ｜ 龙1一字跌停，预期次日打开（跟风债隔夜）。

模式手册原文操作主品种是**跟风可转债**，但 CB 撮合层未接入。
回测先用"板块内其它跌停跟风正股"作为代理（Phase 6 接 CB 后切换）。

触发条件（简化版）：
    - 板块内龙1（或前期最强者）一字跌停（pct_chg ≤ -9.5%, OHLC 全等）
    - 板块内同时还有 ≥ 1 只其它跌停股（"跟风跌停"）
    - 跟风股不是一字跌停（low/pre_close > -10% 容差，可以买入）

操作（回测口径）：
    - 买入：板块内"跌幅深但非一字"的跟风股（T 日 close 入场）
    - 卖出：T+1 open（博次日高开反弹）

风险：
    - 次日继续杀跌 / 一字跌停
    - 没有 CB 数据 → 弹性不如真实跟风债
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.research.strategies.base_pattern import (
    BasePattern,
    PatternSignal,
    fetch_daily_ohlc,
    is_yizi_down,
    load_sectors,
)

logger = logging.getLogger(__name__)


class Pattern05(BasePattern):
    pattern_id = "pattern_05"
    description = "龙1一字跌停 + 跟风正股代理（隔夜博反弹）"

    PCT_DROP_DEEP = -7.0          # 跟风跌幅阈值（跌得深才有反弹空间）
    PCT_NOT_LIMIT_DOWN = -9.5     # 排除一字跌停（无法买）

    async def _find_dropping_in_sector(
        self, session: AsyncSession, trade_date: str, codes: list[str]
    ) -> list[dict]:
        """找板块内当日跌幅深的票。"""
        if not codes:
            return []
        rows = (await session.execute(text(
            "SELECT d.ts_code, sb.name, d.open, d.high, d.low, d.close, "
            "       d.pre_close, d.pct_chg "
            "FROM stock_daily d "
            "JOIN stock_basic sb ON sb.ts_code=d.ts_code "
            "WHERE d.trade_date=:td AND d.ts_code = ANY(:codes)"
        ), {"td": trade_date, "codes": codes})).fetchall()
        return [
            {"ts_code": r[0], "name": (r[1] or "").replace(" ", ""),
             "open": r[2], "high": r[3], "low": r[4], "close": r[5],
             "pre_close": r[6], "pct_chg": r[7]}
            for r in rows
        ]

    async def find_signals(
        self, session: AsyncSession, trade_date: str, source: str = "bankuai"
    ) -> list[PatternSignal]:
        sectors = await load_sectors(session, trade_date, source)
        if not sectors:
            return []

        signals: list[PatternSignal] = []
        for sec_name, codes in sectors.items():
            stocks = await self._find_dropping_in_sector(session, trade_date, codes)
            if not stocks:
                continue
            # 找板块内一字跌停的（"龙1 跌停"判定的代理）
            yizi_down = [s for s in stocks if is_yizi_down(s)]
            if not yizi_down:
                continue
            # 找跌幅深但非一字的跟风
            followers = [
                s for s in stocks
                if s.get("pct_chg") is not None
                and s["pct_chg"] <= self.PCT_DROP_DEEP
                and s["pct_chg"] > self.PCT_NOT_LIMIT_DOWN
                and not is_yizi_down(s)
            ]
            if not followers:
                continue
            followers.sort(key=lambda s: s["pct_chg"])  # 跌得最多的优先
            for f in followers[:3]:
                base = dict(
                    trade_date=trade_date,
                    pattern=self.pattern_id,
                    sector=sec_name,
                    long1_code=yizi_down[0]["ts_code"],
                    long1_name=yizi_down[0]["name"],
                    long1_tag=f"一字跌停{yizi_down[0]['pct_chg']:.1f}%",
                    long1_first_time="",
                    long1_open_times=0,
                    sector_size=len(stocks),
                    pick_role="follower",
                    pick_tag=f"跌{f['pct_chg']:.1f}%",
                    holding="overnight",
                    sell_anchor="next_open",
                )
                # 主腿 A: 跟风正股
                signals.append(PatternSignal(
                    **base,
                    pick_code=f["ts_code"],
                    pick_name=f["name"],
                    reason=f"龙1一字跌停 跟风{f['name']}{f['pct_chg']:.1f}% [腿A 正股]",
                    pick_kind="stock",
                ))
                # 主腿 B: 跟风债（核心收益，恐慌日折价更深 → 反弹弹性更大）
                from app.research.data.cb_resolver import find_cb_for_stock
                cb_code = await find_cb_for_stock(session, f["ts_code"], trade_date)
                if cb_code:
                    signals.append(PatternSignal(
                        **base,
                        pick_code=cb_code,
                        pick_name=f"{f['name']}转债",
                        reason=f"龙1一字跌停 跟风债{f['name']} [腿B CB 折价反弹]",
                        pick_kind="cb",
                        underlying_code=f["ts_code"],
                    ))
        return signals

    async def _check(self, lh, sector_size, ohlc_map, trade_date, prediction=None):
        return None
