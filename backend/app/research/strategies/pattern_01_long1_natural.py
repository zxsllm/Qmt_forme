"""龙头隔夜模式 v6 — 严格事中扫描（与模拟盘对齐，无未来函数）。

阶段 1 重构：
    继承 BaseLongHeadStrategy（IStrategy 子类），只实现 _scan_minute；
    所有共享逻辑（warm_up / on_init / on_bar / CB 状态机 / 买回 / L1 / L2）已上移基类。
    find_signals(session, td) 由基类提供（thin wrapper：构造 ctx → on_init →
    按分钟循环 on_bar → 收集返回），回测和模拟盘走同一条主循环，永不发散。

事中算法（v6 — 未变，仅代码组织调整）：
    模拟盘里 rt_k 每分钟推一根 1min K 线，回测时预拉所有候选票全天 1min 数据。
    主循环（基类 on_bar 驱动）：
        每分钟：
            for 板块 in T-1 lookback + 萌芽主线:
                if 板块未触发 L1:
                    扫板块所有未涨停票，找第一个满足 "自身 ≥9% + ≥2 只 ≥6%"
                    → 触发 L1: 买这只票 + 板块所有跟风票的债
                if 板块已触发 L1 未触发 L2:
                    扫板块（除 L1 那只外），找第一个满足 "自身 ≥9% + ≥3 只 ≥8%"
                    → 触发 L2: 买这只票
            扫萌芽板块新增封板 → 累积 ≥3 只 → 触发萌芽主线发 L_CB
            更新 L_CB 持仓 sell_anchor（A/B/C/D + 板块崩复查）
            板块新增涨停 → 买回 L_CB
        14:55 收尾: 未 evaluated 的 L_CB → today_close
"""
from __future__ import annotations

import logging
from datetime import datetime

from app.research.strategies.base_long_head_strategy import (
    EMERGING_SECTOR_PREFIX,
    BaseLongHeadStrategy,
)
from app.research.strategies.base_pattern import PatternSignal
# 保留原模块下的常量导出，供旧脚本和 Pattern02 import 不破坏
from app.research.strategies.base_long_head_strategy import (  # noqa: F401
    EMERGING_CUTOFF,
    EMERGING_MIN_COUNT,
    INTRADAY_CONSENSUS_MIN_L1,
    INTRADAY_CONSENSUS_MIN_L1_EMERGING,
    INTRADAY_CONSENSUS_MIN_L2,
    INTRADAY_CONSENSUS_PCT_L1,
    INTRADAY_CONSENSUS_PCT_L2,
    L1_LARGE_MV_THRESHOLD_YI,
    L1_MA5_DEVIATION_LARGE_MV,
    L1_MA5_DEVIATION_MAX,
    L2_MA5_DEVIATION_MAX,
    L_CB_EVAL_WINDOW_MIN,
    L_CB_OVERNIGHT_LIMIT_MIN,
    L_CB_OVERNIGHT_OPEN_MAX,
    L_CB_RECHECK_BROKEN_MAX,
    L_CB_REBUY_DEADLINE,
    L_CB_REBUY_FIXED_STOP_RATIO,
    L_CB_REBUY_MAX_TIMES,
    L_CB_REBUY_MIN_GAP_MIN,
    L_CB_REBUY_NEW_LIMITS_MIN,
    L_CB_REBUY_PRICE_RATIO,
    SELF_TRIGGER_RATIO,
    _CbHolding,
    _fetch_cb_minute_close,
    _fetch_pre_t_circ_mv,
    _fetch_pre_t_ma5,
    _hhmm_label,
    _hhmmss,
    _set_sell_overnight,
    _set_sell_t0,
    _set_sell_today_close,
)
from app.research.strategies.pattern_01_params import PRESET_NAME  # noqa: F401

logger = logging.getLogger(__name__)


class Pattern01(BaseLongHeadStrategy):
    """自然涨停启动的龙头隔夜模式（事中）。"""
    name = "pattern_01"
    pattern_id = "pattern_01"
    description = "自然涨停启动的龙头隔夜模式（事中）"
    sector_min_size = 1
    needs_predictor = False

    def _on_open(self, open_minute: datetime) -> None:
        """Pattern01：B 规则（开盘一字开作废板块） + D 规则（T-1 一字 + 未一字开剔除）。"""
        self._apply_b_rule(open_minute)
        self._apply_d_rule(open_minute)

    def _scan_minute(self, minute_dt: datetime) -> list[PatternSignal]:
        """扫每个板块：未触发 L1 → 检查 L1；已 L1 未 L2 → 检查 L2。"""
        new_signals: list[PatternSignal] = []
        for sec_name, codes in self.sectors.items():
            if sec_name in self.invalidated:
                continue
            state = self.sector_state[sec_name]
            is_emerging = sec_name.startswith(EMERGING_SECTOR_PREFIX)
            if state["l1"] is None:
                triggered = self._check_and_trigger_l1(
                    sec_name, codes, minute_dt, new_signals, is_emerging,
                )
                if triggered:
                    state["l1"] = triggered
                    state["l1_excludes"] = {triggered[0]}
            elif state["l2"] is None and not is_emerging:
                exclude_codes = state.get("l1_excludes") or {state["l1"][0]}
                triggered = self._check_and_trigger_l2(
                    sec_name, codes, exclude_codes, minute_dt, new_signals,
                )
                if triggered:
                    state["l2"] = triggered
        return new_signals
