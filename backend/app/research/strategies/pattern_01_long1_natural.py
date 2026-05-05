"""龙头隔夜模式（合并原模式1/2）— 老师课件"情况①" 操作清单。

老师课件原话（docs/100_AI课件.md:105-117）：
    （1）龙头时间: A:龙1低进 / B:跟风/影子龙低进 / B债:低进
    （2）跟风时间: B:低进（影子龙 15min 内有机会，别的跟风更长）/ B债:低进
    （3）转债时间: b:低进，可以拿到尾盘隔夜
    "如果跟风没法涨停，低进赢面大，尾盘回落/第二天低开 程度小（龙一跨一字可以带）"

入口（事中可见信号，不用未来函数）：
    - 龙1 自然涨停（盘中封板，非一字开盘）— 一字情况走模式 3
    - 板块涨停 ≥ 3 只
    - **不用预测器过滤** — 实盘里事中无法可靠判断次日是否一字

多腿信号（每个板块发若干腿，事后统计哪些腿稳）：
    - L1 龙1 正股        : 买在 long1.first_time（封板瞬间排队）→ 卖 T+1 09:30
    - L2 影子龙正股       : 买在 shadow.first_time → 卖 T+1 09:30
    - L_CB 影子龙债       : 买在 T 日 14:55（老师"转债时间尾盘隔夜"）→ 卖 T+1 09:30

事中决策依据（输出展示，不当过滤）：
    - 板块最高板（高度位风险）
    - 龙1 板高 / first_time（封得早 = 强）
    - 影子龙 first_time 是否在 15min 上车窗口内（lh.shadow_within_15min）
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.research.data.cb_resolver import find_cb_for_stock
from app.research.signals.long_head_detector import LongHeadResult
from app.research.strategies.base_pattern import (
    BasePattern,
    PatternSignal,
    is_natural_limit,
)

logger = logging.getLogger(__name__)


class Pattern01(BasePattern):
    pattern_id = "pattern_01"
    description = "龙头隔夜模式 — 龙1正股+影子龙正股+影子龙债（不预测次日）"
    sector_min_size = 3
    needs_predictor = False  # 不再用预测器分流

    async def _check(self, lh, sector_size, ohlc_map, trade_date, prediction=None):
        return None  # 多腿信号在 find_signals 里组装

    async def find_signals(
        self,
        session: AsyncSession,
        trade_date: str,
        source: str = "bankuai",
    ) -> list[PatternSignal]:
        from app.research.strategies.base_pattern import (
            detect_long_head, fetch_daily_ohlc, load_sectors,
        )

        sectors = await load_sectors(session, trade_date, source)
        if not sectors:
            return []

        signals: list[PatternSignal] = []
        for sec_name, codes in sectors.items():
            lh = await detect_long_head(session, trade_date, codes, sector_name=sec_name)
            if not lh.long1:
                continue
            sector_size = (
                len(lh.long1_group)
                + (1 if lh.long2 else 0)
                + len(lh.followers)
            )
            if sector_size < self.sector_min_size:
                continue

            check_codes = [lh.long1.ts_code]
            if lh.shadow and lh.shadow.ts_code not in check_codes:
                check_codes.append(lh.shadow.ts_code)
            ohlc_map = await fetch_daily_ohlc(session, trade_date, check_codes)

            long1 = lh.long1
            if not is_natural_limit(long1, ohlc_map.get(long1.ts_code)):
                continue  # 一字 → 模式 3

            base = dict(
                trade_date=trade_date,
                pattern=self.pattern_id,
                sector=sec_name,
                long1_code=long1.ts_code,
                long1_name=long1.name,
                long1_tag=long1.tag or f"{long1.limit_times}板",
                long1_first_time=long1.first_time,
                long1_open_times=long1.open_times,
                sector_size=sector_size,
                holding="overnight",
                sell_anchor="next_open",
            )
            reason_base = (
                f"龙头隔夜 板块{sector_size}只 龙1首封"
                f"{long1.first_time[:2]}:{long1.first_time[2:4]}"
            )

            # L1 龙1 正股
            signals.append(PatternSignal(
                **base,
                pick_code=long1.ts_code,
                pick_name=long1.name,
                pick_role="long1",
                pick_tag=long1.tag or f"{long1.limit_times}板",
                reason=reason_base + " [L1 龙1正股]",
                pick_kind="stock",
                buy_anchor="intraday_at",
                buy_anchor_time=long1.first_time,
            ))

            # L2 / L_CB：影子龙正股 + 影子龙债
            if lh.shadow:
                shadow = lh.shadow
                window_tag = "≤15min" if lh.shadow_within_15min else ">15min"

                # L2 影子龙正股 — 在影子龙 first_time 那分钟买
                signals.append(PatternSignal(
                    **base,
                    pick_code=shadow.ts_code,
                    pick_name=shadow.name,
                    pick_role="shadow",
                    pick_tag=shadow.tag or f"{shadow.limit_times}板",
                    reason=reason_base + f" [L2 影子龙正股 上车窗口{window_tag}]",
                    pick_kind="stock",
                    buy_anchor="intraday_at",
                    buy_anchor_time=shadow.first_time,
                ))

                # L_CB 影子龙债 — 尾盘隔夜（老师"转债时间"）
                cb_code = await find_cb_for_stock(session, shadow.ts_code, trade_date)
                if cb_code:
                    signals.append(PatternSignal(
                        **base,
                        pick_code=cb_code,
                        pick_name=f"{shadow.name}转债",
                        pick_role="shadow_cb",
                        pick_tag=shadow.tag or f"{shadow.limit_times}板",
                        reason=reason_base + " [L_CB 影子龙债 尾盘隔夜]",
                        pick_kind="cb",
                        underlying_code=shadow.ts_code,
                        buy_anchor="today_close",
                    ))
        return signals
