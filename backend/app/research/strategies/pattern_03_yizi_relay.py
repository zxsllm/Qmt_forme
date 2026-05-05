"""模式 3 ｜ 龙1一字涨停，预期次日仍一字（情况 ③ 只跟风时间）。

入口分类：
    - 龙1 是一字涨停（OHLC 全等且涨幅 ≥ 9.5%）
    - **龙1 次日一字预测器**给出 decision="yizi"

操作（A 股合规口径 — 只发 CB 信号）：
    - 主腿 = 跟风债 CB（T 日 open 买入 → 跟风涨停瞬间分钟级 close 卖出）
    - **不发正股**：A 股 T+1 制度 → 当日买的正股当日不能卖；CB 才支持 T+0

跟风目标优先级（T+0 操作里的"跟风"）：
    1. 严格影子龙（lh.shadow，龙1 后 15min 内首封） → CB 名 = shadow_cb
    2. 退回当日第二只封板（lh.long2） → CB 名 = follower_cb
    没有任何跟风涨停 → 跳过（板块只有龙1 = 弱共识）

为什么必须用分钟级卖出：
    一字到一字带不了次日竞价 → 跟风 CB 隔夜大概率低开（-3%~-8%）
    必须在跟风涨停瞬间就跑（日内最高点）

风险：
    - 跟风涨停时刻 CB 也封死 → 卖不出去
    - 跟风首封时间在 9:30 = 一字开盘 → 没有"跟风时间"窗口
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.research.data.cb_resolver import find_cb_for_stock
from app.research.signals.long_head_detector import LongHeadResult
from app.research.strategies.base_pattern import (
    BasePattern,
    PatternSignal,
    is_yizi,
)

logger = logging.getLogger(__name__)


class Pattern03(BasePattern):
    pattern_id = "pattern_03"
    description = "情况③：龙1一字 + 跟风正股/跟风债（影子龙涨停瞬间卖）"
    sector_min_size = 3
    needs_predictor = True

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
        from app.research.signals.long1_yizi_predictor import predict_long1_yizi

        sectors = await load_sectors(session, trade_date, source)
        if not sectors:
            return []

        signals: list[PatternSignal] = []
        for sec_name, codes in sectors.items():
            lh = await detect_long_head(session, trade_date, codes, sector_name=sec_name)
            if not lh.long1 or not lh.shadow:
                continue
            sector_size = len(lh.long1_group) + (1 if lh.long2 else 0) + len(lh.followers)
            if sector_size < self.sector_min_size:
                continue

            check_codes = list({s.ts_code for s in lh.long1_group})
            if lh.shadow.ts_code not in check_codes:
                check_codes.append(lh.shadow.ts_code)
            ohlc_map = await fetch_daily_ohlc(session, trade_date, check_codes)

            long1 = lh.long1
            long1_ohlc = ohlc_map.get(long1.ts_code)
            if not is_yizi(long1_ohlc):
                continue

            prediction = await predict_long1_yizi(session, trade_date, codes, lh)
            if not prediction or prediction.decision != "yizi":
                continue

            # 跟风目标：严格影子龙优先，退回 long2
            if lh.shadow:
                target = lh.shadow
                role_label = "shadow_cb"
                role_desc = f"影子龙{target.tag or target.limit_times}板"
            elif lh.long2:
                target = lh.long2
                role_label = "follower_cb"
                role_desc = f"跟风{target.tag or target.limit_times}板(后启)"
            else:
                continue

            target_first = target.first_time  # HHMMSS
            # 跟风首封时刻 = 卖出锚点；但若 = 一字开盘 → 跟风时间为零，跳过
            if target_first <= "093100":
                logger.info("pattern_03 skip %s: target yizi at %s", sec_name, target_first)
                continue

            # 只发 CB 腿（A 股 T+1 不允许当日买正股当日卖）
            cb_code = await find_cb_for_stock(session, target.ts_code, trade_date)
            if not cb_code:
                logger.info("pattern_03 skip %s: no CB for %s", sec_name, target.ts_code)
                continue

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
                holding="intraday",
                buy_anchor="today_open",     # 跟风时间低进 = T 日 open 入场
                sell_anchor="intraday_at",
                sell_anchor_time=target_first,
            )
            reason = (f"龙1一字 {role_desc} 跟风{prediction.follower_limit_count}只 "
                      f"评分{prediction.score} [CB sell@{target_first}]")

            signals.append(PatternSignal(
                **base,
                pick_code=cb_code,
                pick_name=f"{target.name}转债",
                pick_role=role_label,
                pick_tag=target.tag or f"{target.limit_times}板",
                reason=reason,
                pick_kind="cb",
                underlying_code=target.ts_code,
            ))
        return signals
