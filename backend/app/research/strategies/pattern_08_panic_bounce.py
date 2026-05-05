"""模式 8 ｜ 退潮主杀期：高标杀跌后博次日转强（隔夜抄底）。

模式手册原文操作主品种是**可转债**，但 CB 撮合层未接入。
回测先用"前期高标正股"作为代理（Phase 6 接 CB 后切换到债）。

触发条件（简化版）：
    - T 日某只 stock 当日 pct_chg ≤ -5%（深度杀跌）
    - 该 stock 在前 5 个交易日内出现过 limit_times ≥ 4 板（前期高标）
    - 该 stock 当日 pct_chg > -9.5%（不是一字跌停 → 还有买入机会）

操作（回测口径）：
    - 买入：T 日 close（杀跌末段抄底）
    - 卖出：T+1 open（次日竞价高开兑现，博"打开转强"）
    - holding = overnight

风险：
    - 题材继续杀跌 → 隔夜套牢
    - 没有板块过滤 → 误抄个股
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.research.strategies.base_pattern import (
    BasePattern,
    PatternSignal,
)

logger = logging.getLogger(__name__)


class Pattern08(BasePattern):
    pattern_id = "pattern_08"
    description = "前期高标深度杀跌 + 次日博转强（隔夜）"

    PCT_DROP_DEEP = -5.0          # 深度杀跌阈值
    PCT_NOT_LIMIT_DOWN = -9.5     # 排除一字跌停（无法买）
    LOOKBACK_DAYS = 5             # 回看 5 日找前期高标
    HIGH_BOARD_THRESHOLD = 4      # 历史 ≥ N 板视为高标

    async def find_signals(
        self, session: AsyncSession, trade_date: str, source: str = "bankuai"
    ) -> list[PatternSignal]:
        # 找出当日满足条件的前期高标杀跌票
        rows = (await session.execute(text(
            "WITH recent_high AS ("
            "    SELECT DISTINCT ls.ts_code "
            "    FROM limit_stats ls "
            "    LEFT JOIN limit_list_ths lt "
            "         ON lt.trade_date=ls.trade_date AND lt.ts_code=ls.ts_code "
            "         AND lt.limit_type='涨停池' "
            "    JOIN trade_cal tc ON tc.cal_date=ls.trade_date AND tc.is_open=1 "
            "    WHERE ls.trade_date < :td "
            "      AND ls.trade_date >= :lookback_min "
            "      AND ("
            "          ls.limit_times >= :hb "
            "          OR (lt.tag IS NOT NULL AND lt.tag ~ '\\d+天\\d+板' "
            "              AND CAST(SUBSTRING(lt.tag FROM '天(\\d+)板') AS INT) >= :hb)"
            "      )"
            ") "
            "SELECT d.ts_code, sb.name, d.pct_chg, d.close "
            "FROM stock_daily d "
            "JOIN recent_high rh ON rh.ts_code=d.ts_code "
            "JOIN stock_basic sb ON sb.ts_code=d.ts_code "
            "WHERE d.trade_date=:td "
            "  AND d.pct_chg <= :drop_deep "
            "  AND d.pct_chg > :not_limit_down "
            "ORDER BY d.pct_chg ASC"
        ), {
            "td": trade_date,
            "lookback_min": self._lookback_min(trade_date),
            "hb": self.HIGH_BOARD_THRESHOLD,
            "drop_deep": self.PCT_DROP_DEEP,
            "not_limit_down": self.PCT_NOT_LIMIT_DOWN,
        })).fetchall()

        signals: list[PatternSignal] = []
        for ts_code, name, pct_chg, close in rows:
            signals.append(PatternSignal(
                trade_date=trade_date,
                pattern=self.pattern_id,
                sector="(前期高标杀跌)",
                long1_code=ts_code,
                long1_name=(name or "").replace(" ", ""),
                long1_tag="(前期≥4板)",
                long1_first_time="",
                long1_open_times=0,
                sector_size=1,
                pick_code=ts_code,
                pick_name=(name or "").replace(" ", ""),
                pick_role="long1",
                pick_tag=f"杀跌{pct_chg:.1f}%",
                reason=f"前期高标当日杀跌 {pct_chg:.1f}% close={close}",
                holding="overnight",
            ))
        return signals

    def _lookback_min(self, td: str) -> str:
        """近似回看起点（不卡严格交易日数，用日历日 -10 天作为窗口下界）。"""
        from datetime import datetime, timedelta
        d = datetime.strptime(td, "%Y%m%d")
        return (d - timedelta(days=self.LOOKBACK_DAYS * 2)).strftime("%Y%m%d")

    async def _check(self, lh, sector_size, ohlc_map, trade_date, prediction=None):
        return None
