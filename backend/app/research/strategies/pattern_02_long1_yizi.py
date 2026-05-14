"""龙头隔夜模式 — Pattern02 一字涨停启动（事中）。

与 Pattern01 自然涨停启动的核心差异:
    Pattern01: 09:30 起事中扫"自身 ≥9% + 板块共识 ≥2 只 ≥6%"找 L1（自然涨停启动）
    Pattern02: 09:30 那根 K 线 open ≥ 涨停价（一字开） → 识别为龙 1（多只按板数排）
               板块若有 ≥1 只一字开 → 立即触发，发出板块所有跟风债（L_CB）
               龙 1 正股本身散户买不到 → buy_anchor="skip"

规则差异:
    - 取消 B 规则（开盘一字开作废板块）— Pattern02 反之，一字开是入场信号
    - 保留 D 规则（T-1 一字 + T 日没一字开 → 剔除）
    - 一字票必须不是"T-1 连板接力"：T-1 连板（板数 ≥ 2）的票排除；
      T-1 首板涨停（板数=1）或 T-1 没涨停的票，视为"新启动"，正常作为龙 1

其他逻辑（L2 / L_CB 升级隔夜 A/B/C/D / 买回 / 萌芽主线 / 偏离度过滤）与 Pattern01
完全一致，通过共享基类 BaseLongHeadStrategy。
"""
from __future__ import annotations

import logging
from datetime import datetime

from app.research.strategies.base_long_head_strategy import (
    EMERGING_SECTOR_PREFIX,
    BaseLongHeadStrategy,
    _CbHolding,
    _hhmm_label,
    _hhmmss,
    _parse_board_from_tag,
)
from app.research.strategies.base_pattern import PatternSignal

logger = logging.getLogger(__name__)


class Pattern02(BaseLongHeadStrategy):
    """一字涨停启动的龙头隔夜模式（事中）。

    09:30 那根 K 线扫板块所有 is_limit_at_open=True 的票，多只一字时按板数从高
    到低排为 long1/long2/long3...。所有一字票 buy_anchor="skip"（散户买不到），
    但板块所有非一字成员的转债在 09:30 立即发出 L_CB，进入与 Pattern01 一致的
    A/B/C/D 升级隔夜流程。萌芽板块的 L1 触发与 Pattern01 一致（自然涨停启动）。
    """
    name = "pattern_02"
    pattern_id = "pattern_02"
    description = "一字涨停启动的龙头隔夜模式（事中）"

    def _on_open(self, open_minute: datetime) -> None:
        """Pattern02：取消 B 规则（一字开是入场信号），只跑 D 规则。"""
        self._apply_d_rule(open_minute)

    def _scan_minute(self, minute_dt: datetime) -> list[PatternSignal]:
        new_signals: list[PatternSignal] = []
        open_minute = self._open_minute()
        for sec_name, codes in self.sectors.items():
            state = self.sector_state[sec_name]
            is_emerging = sec_name.startswith(EMERGING_SECTOR_PREFIX)

            if state["l1"] is None:
                if is_emerging:
                    # 萌芽板块走 Pattern01 自然涨停启动（午前才浮现，无一字逻辑）
                    triggered = self._check_and_trigger_l1(
                        sec_name, codes, minute_dt, new_signals, is_emerging=True,
                    )
                    if triggered:
                        state["l1"] = triggered
                        state["l1_excludes"] = {triggered[0]}
                else:
                    # Pattern02 一字启动：只在 09:30 那根 K 线检查
                    if minute_dt == open_minute:
                        triggered = self._check_and_trigger_l1_yizi(
                            sec_name, codes, minute_dt, new_signals,
                        )
                        if triggered:
                            state["l1"] = (triggered[0], triggered[1])
                            state["l1_excludes"] = triggered[2]
            elif state["l2"] is None and not is_emerging:
                exclude_codes = state["l1_excludes"] or {state["l1"][0]}
                triggered = self._check_and_trigger_l2(
                    sec_name, codes, exclude_codes, minute_dt, new_signals,
                )
                if triggered:
                    state["l2"] = triggered
        return new_signals

    # ──────────────────────────────────────────────────────────────────────
    # 一字启动 L1：09:30 扫板块所有 is_limit_at_open=True 的票
    # ──────────────────────────────────────────────────────────────────────
    def _check_and_trigger_l1_yizi(
        self,
        sec_name: str,
        codes: list[str],
        minute_dt: datetime,
        signals: list[PatternSignal],
    ) -> tuple[str, datetime, set[str]] | None:
        # 排除 T-1 连板接力一字（板数 ≥ 2）；首板涨停或未涨停的票视为"新启动"
        yizi_candidates: list[tuple[str, int]] = []
        for code in codes:
            q = self._quotes.get((code, minute_dt))
            if q and q.is_limit_at_open:
                t1_board = self.t1_boards.get(code, 0)
                if t1_board >= 2:
                    logger.info(
                        "%s funnel %s sector=%s skip yizi %s (T-1 连板 %d 板=接力一字)",
                        self.pattern_id, self.trade_date, sec_name, code, t1_board,
                    )
                    continue
                board = _parse_board_from_tag(self.meta.get(code, {}).get("tag"))
                yizi_candidates.append((code, board))
        if not yizi_candidates:
            return None
        yizi_candidates.sort(key=lambda x: (-x[1], x[0]))
        yizi_codes = {c for c, _ in yizi_candidates}

        logger.info(
            "%s funnel %s sector=%s L1-yizi trigger at=%s yizi_n=%d codes=%s",
            self.pattern_id, self.trade_date, sec_name, _hhmm_label(minute_dt),
            len(yizi_candidates), [(c, b) for c, b in yizi_candidates],
        )

        buy_time_str = _hhmmss(minute_dt)
        first_long1 = yizi_candidates[0][0]
        l1_meta = self.meta.get(first_long1, {})
        l1_name = l1_meta.get("name") or first_long1
        l1_tag = l1_meta.get("tag") or "首板"
        l1_first_time = l1_meta.get("first_time") or buy_time_str
        l1_open_times = l1_meta.get("open_times", 0)

        # 每只一字票发 long1/long2/long3... 信号（buy_anchor="skip"）
        for idx, (code, board) in enumerate(yizi_candidates):
            role = f"long{idx + 1}"
            c_meta = self.meta.get(code, {})
            c_name = c_meta.get("name") or code
            c_tag = c_meta.get("tag") or f"{board}板"
            signals.append(PatternSignal(
                trade_date=self.trade_date,
                pattern=self.pattern_id,
                sector=sec_name,
                long1_code=first_long1,
                long1_name=l1_name,
                long1_tag=l1_tag,
                long1_first_time=l1_first_time,
                long1_open_times=l1_open_times,
                sector_size=len(yizi_candidates),
                pick_code=code,
                pick_name=c_name,
                pick_role=role,
                pick_tag=c_tag,
                reason=(
                    f"事中L1一字启动 09:30 一字开 板数={board} "
                    f"(板块一字共 {len(yizi_candidates)} 只) "
                    f"[{role} 一字票-散户买不到-放弃买入]"
                ),
                pick_kind="stock",
                buy_anchor="skip",
                buy_anchor_time=buy_time_str,
                holding="overnight",
                sell_anchor="next_open",
            ))

        # 发板块跟风债（除一字龙 1 集合外的所有非涨停票）
        for follower_code in codes:
            if follower_code in yizi_codes:
                continue
            f_q = self._quotes.get((follower_code, minute_dt))
            if f_q is not None and f_q.is_limit:
                logger.info(
                    "%s funnel %s sector=%s skip cb of %s (已涨停=卖点)",
                    self.pattern_id, self.trade_date, sec_name, follower_code,
                )
                continue
            cb_code = self.cb_resolver_cache.get(follower_code)
            if not cb_code:
                continue
            f_meta = self.meta.get(follower_code, {})
            f_name = f_meta.get("name") or follower_code
            f_tag = f_meta.get("tag") or "未涨停"
            cb_sig = PatternSignal(
                trade_date=self.trade_date,
                pattern=self.pattern_id,
                sector=sec_name,
                long1_code=first_long1,
                long1_name=l1_name,
                long1_tag=l1_tag,
                long1_first_time=l1_first_time,
                long1_open_times=l1_open_times,
                sector_size=len(yizi_candidates),
                pick_code=cb_code,
                pick_name=f"{f_name}转债",
                pick_role="follower_cb",
                pick_tag=f_tag,
                reason=(
                    f"事中L1一字启动同步发债 板块一字 {len(yizi_candidates)} 只 "
                    f"买{_hhmm_label(minute_dt)} underlying={f_name}({follower_code}) "
                    f"[L_CB 跟风债]"
                ),
                holding="overnight",
                sell_anchor="next_open",
                pick_kind="cb",
                underlying_code=follower_code,
                buy_anchor="intraday_at",
                buy_anchor_time=buy_time_str,
            )
            signals.append(cb_sig)
            self.cb_holdings.append(_CbHolding(
                signal=cb_sig,
                underlying=follower_code,
                sector=sec_name,
                sector_codes=codes,
                buy_minute=minute_dt,
                cb_minute_close=self.cb_minute_close_cache.get(cb_code, {}),
            ))

        return (first_long1, minute_dt, yizi_codes)
