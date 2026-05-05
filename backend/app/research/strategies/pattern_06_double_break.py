"""模式 6 ｜ 龙1一字跌停，赌"二次打开"反弹（龙头正股）。

模式手册原文：第一天隔夜**正股的债**；第二天竞价砸出，等正股再次封回涨停后再买入，
预期"封 → 开 → 封"的反复，吃两段开板溢价。

回测难点：
    - 完整模式需分钟级数据 + CB 撮合 + 多次买卖逻辑
    - 简化版只做"第一天隔夜买正股"段，与模式 5 区别在于**买的是龙1正股**而非跟风

触发条件（简化版）：
    - 板块内某只一字跌停且当日 limit_times >= 4 之前是连板高标（前期高标）
    - 用 limit_step 或 limit_list_ths 历史判定（前 5 日内出现过 ≥ 4 板）

操作（回测口径）：
    - 买入：T 日 close 买**该高标正股**（一字跌停意味着 close = 跌停价，承认买不到的撮合假设）
    - 卖出：T+1 open

风险：
    - 一字跌停 close 实际买不到（封单完全压住）
    - 次日继续一字 → 持仓被锁
    - 完整版"二次打开"逻辑需后续接入分钟级才能模拟
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.research.strategies.base_pattern import (
    BasePattern,
    PatternSignal,
    is_yizi_down,
)

logger = logging.getLogger(__name__)


class Pattern06(BasePattern):
    pattern_id = "pattern_06"
    description = "龙1一字跌停 + 龙头正股隔夜（简化二次打开）"

    LOOKBACK_DAYS = 5
    HIGH_BOARD_THRESHOLD = 4

    def _lookback_min(self, td: str) -> str:
        from datetime import datetime, timedelta
        d = datetime.strptime(td, "%Y%m%d")
        return (d - timedelta(days=self.LOOKBACK_DAYS * 2)).strftime("%Y%m%d")

    async def find_signals(
        self, session: AsyncSession, trade_date: str, source: str = "bankuai"
    ) -> list[PatternSignal]:
        rows = (await session.execute(text(
            "WITH recent_high AS ("
            "    SELECT DISTINCT ls.ts_code "
            "    FROM limit_stats ls "
            "    LEFT JOIN limit_list_ths lt "
            "         ON lt.trade_date=ls.trade_date AND lt.ts_code=ls.ts_code "
            "         AND lt.limit_type='涨停池' "
            "    WHERE ls.trade_date < :td AND ls.trade_date >= :lookback "
            "      AND ("
            "          ls.limit_times >= :hb "
            "          OR (lt.tag IS NOT NULL AND lt.tag ~ '\\d+天\\d+板' "
            "              AND CAST(SUBSTRING(lt.tag FROM '天(\\d+)板') AS INT) >= :hb)"
            "      )"
            ") "
            "SELECT d.ts_code, sb.name, d.open, d.high, d.low, d.close, "
            "       d.pre_close, d.pct_chg "
            "FROM stock_daily d "
            "JOIN recent_high rh ON rh.ts_code=d.ts_code "
            "JOIN stock_basic sb ON sb.ts_code=d.ts_code "
            "WHERE d.trade_date=:td AND d.pct_chg <= -9.5"
        ), {
            "td": trade_date, "lookback": self._lookback_min(trade_date),
            "hb": self.HIGH_BOARD_THRESHOLD,
        })).fetchall()

        from app.research.data.cb_resolver import find_cb_for_stock
        signals: list[PatternSignal] = []
        for r in rows:
            ohlc = {"open": r[2], "high": r[3], "low": r[4], "close": r[5],
                    "pre_close": r[6]}
            if not is_yizi_down(ohlc):
                continue
            base = dict(
                trade_date=trade_date,
                pattern=self.pattern_id,
                sector="(前期高标一字跌停)",
                long1_code=r[0],
                long1_name=(r[1] or "").replace(" ", ""),
                long1_tag=f"一字跌停{r[7]:.1f}%",
                long1_first_time="",
                long1_open_times=0,
                sector_size=1,
                pick_role="long1",
                pick_tag=f"前期≥{self.HIGH_BOARD_THRESHOLD}板",
                holding="overnight",
                sell_anchor="next_open",
            )
            # 主腿 A: 龙头正股（一字跌停封死，承认买不到的撮合假设）
            signals.append(PatternSignal(
                **base,
                pick_code=r[0],
                pick_name=(r[1] or "").replace(" ", ""),
                reason=f"前期高标一字跌停 close={r[5]} 博二次打开 [腿A 正股]",
                pick_kind="stock",
            ))
            # 主腿 B: 龙头债（核心利润，CB 在一字跌停时折价更深 → 隔夜反弹弹性大）
            cb_code = await find_cb_for_stock(session, r[0], trade_date)
            if cb_code:
                signals.append(PatternSignal(
                    **base,
                    pick_code=cb_code,
                    pick_name=f"{(r[1] or '').replace(' ','')}转债",
                    reason=f"前期高标一字跌停 [腿B 龙头债 折价隔夜]",
                    pick_kind="cb",
                    underlying_code=r[0],
                ))
        return signals

    async def _check(self, lh, sector_size, ohlc_map, trade_date, prediction=None):
        return None
