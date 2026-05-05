"""模式 4 ｜ 龙1一字涨停，预期次日"不能"一字（情况 ④ 板块团灭 必死）。

入口分类：
    - 龙1 一字涨停
    - **龙1 次日一字预测器**给出 decision="break"
      → 主信号：跟风涨停数 ≤1

老师在视频里强调："情况 ④ 是板块团灭，做什么亏什么必亏，删掉了"。
保留这个模式纯粹为了对照实验——验证"必亏"是否真的成立。

操作（回测口径）：
    - T 日 close 买影子龙（如有）；没影子龙就放弃
    - T+1 open 卖（必低开 → 验证"团灭"假设）
    - holding = intraday

预期结果：胜率 < 30%、负 PnL —— 用于反向验证"模式 4 别玩"。
"""
from __future__ import annotations

from app.research.signals.long_head_detector import LongHeadResult
from app.research.strategies.base_pattern import (
    BasePattern,
    PatternSignal,
    is_yizi,
)


class Pattern04(BasePattern):
    pattern_id = "pattern_04"
    description = "情况④：龙1一字 + 次日预测开板（团灭，对照实验）"
    sector_min_size = 1  # 不限制（情况 ④ 一定弱）
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
        if not is_yizi(long1_ohlc):
            return None

        # 入口分类：预测器判定次日开板
        if not prediction or prediction.decision == "yizi":
            return None  # 一字 → 模式 3

        shadow = lh.shadow
        if not shadow:
            return None  # 没影子龙 = 完全孤龙 = 不进

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
            pick_code=shadow.ts_code,
            pick_name=shadow.name,
            pick_role="shadow",
            pick_tag=shadow.tag or f"{shadow.limit_times}板",
            reason=f"龙1一字+预测开板 跟风{prediction.follower_limit_count}只 评分{prediction.score}",
            holding="intraday",
        )
