"""模式 2 ｜ 龙1首日自然涨停，预期次日"不能"一字（情况 ② 一日游，只龙头时间）。

入口分类：
    - 龙1 自然涨停
    - **龙1 次日一字预测器**给出 decision="break" 或 "uncertain"
      → 主信号：跟风涨停数 ≤1（孤龙）→ 板块次日必砸竞价

操作（合规口径，分钟级精确撮合）：
    - 在龙1 first_time（涨停瞬间）那分钟挂涨停价买
    - sell_anchor=next_open（T+1 09:30，原文"竞价游"出货）
    - holding=overnight（隔夜持仓 → 用 T+1 竞价那一下出货）

回测假设：
    - 在 first_time 那分钟"封板瞬间"成交 = 排队挤进去（乐观偏差）
    - 比"14:55 买"合理 — 14:55 早封死

风险：
    - 跟风必跳水（板块情绪烂）→ 但模式 2 操作的是龙1 不是跟风
    - 排队挤不进去（实盘）
"""
from __future__ import annotations

from app.research.signals.long_head_detector import LongHeadResult
from app.research.strategies.base_pattern import (
    BasePattern,
    PatternSignal,
    is_natural_limit,
)


class Pattern02(BasePattern):
    pattern_id = "pattern_02"
    description = "情况②：龙1自然涨停 + 次日预测开板（一日游 只龙头时间）"
    sector_min_size = 2  # 板块更弱，门槛降低
    needs_predictor = True

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

        long1_ohlc = ohlc_map.get(long1.ts_code)
        if not is_natural_limit(long1, long1_ohlc):
            return None  # 一字 → 走模式 4

        # 入口分类：预测器判定次日开板（孤龙）或不确定
        if not prediction or prediction.decision == "yizi":
            return None  # 真一字 → 走模式 1

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
            reason=f"自然+预测开板 跟风{prediction.follower_limit_count}只 评分{prediction.score}",
            holding="overnight",
            buy_anchor="intraday_at",
            buy_anchor_time=long1.first_time,  # 龙1 涨停瞬间排队买
            sell_anchor="next_open",
        )
