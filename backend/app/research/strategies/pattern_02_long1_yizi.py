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
      T-1 首板涨停（板数 = 1）或 T-1 没涨停的票，视为"新启动"，正常作为龙 1

其他逻辑（L2 / L_CB 升级隔夜 A/B/C/D / 买回 / 萌芽主线 / 偏离度过滤）与 Pattern01
完全一致，通过继承 Pattern01 复用 _check_and_trigger_l1（萌芽板块）/
_check_and_trigger_l2 / _prev_trade_date。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.research.data.cb_resolver import find_cb_for_stock
from app.research.signals.long_head_detector import (
    QuoteMap,
    build_quote_indices,
    compute_vwap_until,
    count_sector_limit_state_intraday,
    detect_emerging_sectors,
    fetch_first_limit_times,
    fetch_industries,
    fetch_minute_quotes,
    fetch_stock_meta,
    fetch_t1_solid_one_word_limits,
    iter_trading_minutes,
)
from app.research.strategies.base_pattern import (
    PatternSignal,
    load_sectors,
)
from app.research.strategies.pattern_01_long1_natural import (
    EMERGING_CUTOFF,
    EMERGING_MIN_COUNT,
    EMERGING_SECTOR_PREFIX,
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
    Pattern01,
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

logger = logging.getLogger(__name__)


_TAG_BOARD_RE = re.compile(r"(\d+)天(\d+)板")


def _parse_board_from_tag(tag: str | None) -> int:
    """从 limit_list_ths.tag 解析连板数。"""
    if not tag:
        return 1
    if tag == "首板":
        return 1
    m = _TAG_BOARD_RE.match(tag)
    return int(m.group(2)) if m else 1


async def _fetch_t1_limit_up_boards(
    session: AsyncSession, t1_date: str,
) -> dict[str, int]:
    """T-1 当日全市场涨停股 → 板数 dict。

    板数从 limit_list_ths.tag 解析（"2天2板"→2，"首板"→1）；
    若 tag 缺失，fallback 用 limit_stats.limit_times（连板次数）。

    用于 Pattern02 过滤"接力一字"：T-1 连板（板数 ≥ 2）+ T 日一字开 → 排除；
    T-1 首板涨停 + T 日一字开 → 视为"新启动"，不排除。
    """
    rows = (await session.execute(text(
        "SELECT ls.ts_code, lt.tag, COALESCE(ls.limit_times, 1) AS lt_times "
        "FROM limit_stats ls "
        "LEFT JOIN limit_list_ths lt ON lt.trade_date=ls.trade_date "
        "     AND lt.ts_code=ls.ts_code AND lt.limit_type='涨停池' "
        "WHERE ls.trade_date=:td AND ls.\"limit\"='U'"
    ), {"td": t1_date})).fetchall()
    out: dict[str, int] = {}
    for ts_code, tag, lt_times in rows:
        if tag:
            out[ts_code] = _parse_board_from_tag(tag)
        else:
            out[ts_code] = int(lt_times or 1)
    return out


class Pattern02(Pattern01):
    """一字涨停启动的龙头隔夜模式（事中）。

    继承 Pattern01 复用萌芽板块 L1 触发 / L2 触发 / 上一交易日查询。重写
    find_signals，在 09:30 那根 K 线扫描板块所有 is_limit_at_open=True 的票，
    多只一字时按 limit_list_ths.tag 解析的连板数从高到低排为 long1/long2/long3...
    所有一字票 buy_anchor="skip"（散户买不到），但板块所有非一字成员的转债在
    09:30 立即发出 L_CB，进入与 Pattern01 一致的 A/B/C/D 升级隔夜流程。
    """
    pattern_id = "pattern_02"
    description = "一字涨停启动的龙头隔夜模式（事中）"

    async def find_signals(
        self,
        session: AsyncSession,
        trade_date: str,
    ) -> list[PatternSignal]:
        # 1. 板块名单
        sectors = await load_sectors(session, trade_date)
        if not sectors:
            logger.info("pattern_02 funnel %s: no sectors loaded", trade_date)
            return []

        # 2. 萌芽主线候选（与 Pattern01 一致，事中触发）
        known_codes = {c for cs in sectors.values() for c in cs}
        emerging_map = await detect_emerging_sectors(
            session, trade_date, known_codes,
            cutoff_hhmmss=EMERGING_CUTOFF,
            min_count=EMERGING_MIN_COUNT,
        )
        emerging_codes_by_industry: dict[str, set[str]] = {
            ind: set(codes) for ind, (codes, _) in emerging_map.items()
        }
        for industry, (em_codes, _) in emerging_map.items():
            virtual_name = f"{EMERGING_SECTOR_PREFIX}{industry})"
            sectors[virtual_name] = em_codes
            logger.info(
                "pattern_02 emerging candidate %s: %s with %d codes",
                trade_date, virtual_name, len(em_codes),
            )

        # 3. 预拉所有候选票全天分钟数据 + 行业映射 + 当日封板时刻
        all_codes = list({c for cs in sectors.values() for c in cs})
        quotes = await fetch_minute_quotes(session, trade_date, all_codes)
        first_limit_times = await fetch_first_limit_times(session, trade_date)
        industries = await fetch_industries(session, all_codes)
        meta = await fetch_stock_meta(session, trade_date, all_codes)
        ma5_map = await _fetch_pre_t_ma5(session, trade_date, all_codes)
        circ_mv_map = await _fetch_pre_t_circ_mv(session, trade_date, all_codes)
        minutes_by_code, first_limit_minute, close_cumsum_by_code = build_quote_indices(quotes)

        def _count_state(secs, mt):
            return count_sector_limit_state_intraday(
                quotes, secs, mt, first_limit_minute=first_limit_minute,
            )

        def _vwap(code, mt):
            return compute_vwap_until(
                quotes, code, mt, minutes_by_code=minutes_by_code,
                close_cumsum_by_code=close_cumsum_by_code,
            )

        open_minute = datetime.strptime(trade_date, "%Y%m%d").replace(hour=9, minute=30)

        # ── 取消 B 规则（开盘一字开是 Pattern02 入场信号，不再作废板块）──
        # ── D 规则：T-1 一字 + T 日 09:30 没一字开 → 剔除（保留）──
        # ── C 规则不剔除（T-1 一字 + T 日一字开 = 接力一字 = Pattern02 核心场景）──
        t1_date = await self._prev_trade_date(session, trade_date)
        t1_one_word = (
            await fetch_t1_solid_one_word_limits(session, t1_date) if t1_date else set()
        )
        if t1_one_word:
            logger.info(
                "pattern_02 funnel %s T-1=%s 严格一字 %d 只（接力候选）: %s",
                trade_date, t1_date, len(t1_one_word),
                sorted(t1_one_word)[:20],
            )
        # T-1 涨停股 → 板数 dict（用于过滤接力一字；首板涨停不算接力，仍可作为龙 1）
        t1_boards = (
            await _fetch_t1_limit_up_boards(session, t1_date) if t1_date else {}
        )
        if t1_boards:
            connect_n = sum(1 for b in t1_boards.values() if b >= 2)
            logger.info(
                "pattern_02 funnel %s T-1=%s 涨停 %d 只（其中连板 %d 只，一字启动将排除连板）",
                trade_date, t1_date, len(t1_boards), connect_n,
            )
        for sec_name in list(sectors.keys()):
            original = list(sectors[sec_name])
            kept = []
            for code in original:
                if code in t1_one_word:
                    q = quotes.get((code, open_minute))
                    if q is None or not q.is_limit_at_open:
                        logger.info(
                            "pattern_02 funnel %s sector=%s 剔除 %s "
                            "(T-1 一字 + T 日 09:30 未一字开)",
                            trade_date, sec_name, code,
                        )
                        continue
                kept.append(code)
            sectors[sec_name] = kept

        # 4. 状态机
        # 每个板块: {"l1": (code, minute) | None, "l2": (code, minute) | None,
        #            "l1_excludes": set[str]（所有一字龙 1 票，用于 L2 排除）}
        sector_state: dict[str, dict] = {
            sec: {"l1": None, "l2": None, "l1_excludes": None}
            for sec in sectors
        }
        emerging_observed: dict[str, set[str]] = {
            ind: set() for ind in emerging_codes_by_industry
        }
        emerging_triggered: set[str] = set()
        cb_holdings: list[_CbHolding] = []

        signals: list[PatternSignal] = []
        minutes = iter_trading_minutes(trade_date)

        # 5. 主扫描循环
        for minute_dt in minutes:
            # ── 板块 L1 / L2 触发检查 ──
            for sec_name, codes in sectors.items():
                state = sector_state[sec_name]
                is_emerging = sec_name.startswith(EMERGING_SECTOR_PREFIX)

                if state["l1"] is None:
                    if is_emerging:
                        # 萌芽板块仍按 Pattern01 事中触发（午前才浮现，没一字逻辑）
                        triggered = await self._check_and_trigger_l1(
                            session, trade_date, sec_name, codes, minute_dt,
                            quotes, meta, signals, cb_holdings, is_emerging,
                            t1_one_word, ma5_map, circ_mv_map,
                        )
                        if triggered:
                            state["l1"] = triggered
                            state["l1_excludes"] = {triggered[0]}
                    else:
                        # Pattern02 一字启动：只在 09:30 那根 K 线检查
                        if minute_dt == open_minute:
                            triggered = await self._check_and_trigger_l1_yizi(
                                session, trade_date, sec_name, codes, minute_dt,
                                quotes, meta, signals, cb_holdings, t1_boards,
                            )
                            if triggered:
                                state["l1"] = (triggered[0], triggered[1])
                                state["l1_excludes"] = triggered[2]
                elif state["l2"] is None and not is_emerging:
                    exclude_codes = state["l1_excludes"] or {state["l1"][0]}
                    triggered = await self._check_and_trigger_l2(
                        sec_name, codes, exclude_codes, minute_dt, quotes, meta,
                        signals, t1_one_word, ma5_map, trade_date,
                    )
                    if triggered:
                        state["l2"] = triggered

            # ── 萌芽主线触发（与 Pattern01 一致）──
            for industry, em_codes in emerging_codes_by_industry.items():
                virtual_name = f"{EMERGING_SECTOR_PREFIX}{industry})"
                if virtual_name in emerging_triggered:
                    continue
                observed = emerging_observed[industry]
                for code in em_codes:
                    if code in observed:
                        continue
                    q = quotes.get((code, minute_dt))
                    if q and q.is_limit:
                        observed.add(code)
                if len(observed) >= EMERGING_MIN_COUNT:
                    emerging_triggered.add(virtual_name)
                    logger.info(
                        "pattern_02 funnel %s emerging triggered: %s observed=%d at %s",
                        trade_date, virtual_name, len(observed),
                        _hhmm_label(minute_dt),
                    )

            # ── L_CB 持仓状态更新（与 Pattern01 一致）──
            for hold in cb_holdings:
                if hold.evaluated:
                    continue
                if minute_dt <= hold.buy_minute:
                    continue
                q = quotes.get((hold.underlying, minute_dt))
                if q is None:
                    continue

                # [1] 止损监控（最高优先级）
                if hold.is_rebuy and hold.rebuy_price is not None:
                    cb_now = hold.cb_minute_close.get(minute_dt)
                    rebuy_stop = hold.rebuy_price * L_CB_REBUY_FIXED_STOP_RATIO
                    if cb_now is not None and cb_now < rebuy_stop:
                        sec_lim_at_sell, _ = _count_state(hold.sector_codes, minute_dt)
                        hold.sell_sector_limits = sec_lim_at_sell
                        logger.info(
                            "pattern_02 L_CB rebuy-stoploss-fixed %s sector=%s "
                            "underlying=%s at=%s cb_close=%.2f < 买回价 %.2f × %.2f = %.2f → 固定止损",
                            trade_date, hold.sector, hold.underlying,
                            _hhmm_label(minute_dt), cb_now,
                            hold.rebuy_price, L_CB_REBUY_FIXED_STOP_RATIO, rebuy_stop,
                        )
                        _set_sell_t0(hold, minute_dt, reason="C_rebuy_fixed_stop")
                        hold.evaluated = True
                        continue
                else:
                    vwap = _vwap(hold.underlying, minute_dt)
                    current_below = (vwap is not None and q.close < vwap)
                    buffer_cutoff = minute_dt.replace(hour=9, minute=35, second=0)
                    use_buffer = minute_dt < buffer_cutoff
                    if current_below:
                        if use_buffer and not hold.last_close_below_vwap:
                            logger.info(
                                "pattern_02 L_CB vwap-buffer %s sector=%s underlying=%s "
                                "at=%s close=%.2f < vwap=%.2f → 09:35 前缓冲，等下分钟确认",
                                trade_date, hold.sector, hold.underlying,
                                _hhmm_label(minute_dt), q.close, vwap,
                            )
                        else:
                            reason_label = (
                                "连续 2min 跌破（缓冲生效内）" if use_buffer
                                else "09:35+ 立卖（无缓冲）"
                            )
                            sec_lim_at_sell, _ = _count_state(hold.sector_codes, minute_dt)
                            hold.sell_sector_limits = sec_lim_at_sell
                            logger.info(
                                "pattern_02 L_CB stoploss-vwap %s sector=%s underlying=%s "
                                "at=%s close=%.2f < vwap=%.2f → C 止损（%s, "
                                "ever_limit=%s, 板块涨停=%d）",
                                trade_date, hold.sector, hold.underlying,
                                _hhmm_label(minute_dt), q.close, vwap,
                                reason_label, hold.ever_limit, sec_lim_at_sell,
                            )
                            _set_sell_t0(hold, minute_dt, reason="C_vwap")
                            hold.evaluated = True
                            continue
                    hold.last_close_below_vwap = current_below

                # [2] underlying 还没封过板
                if not hold.ever_limit:
                    if q.is_limit:
                        hold.ever_limit = True
                        hold.first_limit_minute = minute_dt
                        sec_limit_n, sec_broken_n = _count_state(
                            hold.sector_codes, minute_dt
                        )
                        if (sec_limit_n >= L_CB_OVERNIGHT_LIMIT_MIN
                                and sec_broken_n <= L_CB_OVERNIGHT_OPEN_MAX):
                            logger.info(
                                "pattern_02 L_CB upgrade-immediate %s sector=%s "
                                "underlying=%s at=%s limits=%d broken=%d → A 隔夜（首封即达标）",
                                trade_date, hold.sector, hold.underlying,
                                _hhmm_label(minute_dt), sec_limit_n, sec_broken_n,
                            )
                            _set_sell_overnight(hold)
                            hold.upgraded = True
                        else:
                            logger.info(
                                "pattern_02 L_CB eval-window-start %s sector=%s "
                                "underlying=%s at=%s limits=%d/%d broken=%d/%d → 进入 %dmin 评估窗",
                                trade_date, hold.sector, hold.underlying,
                                _hhmm_label(minute_dt),
                                sec_limit_n, L_CB_OVERNIGHT_LIMIT_MIN,
                                sec_broken_n, L_CB_OVERNIGHT_OPEN_MAX,
                                L_CB_EVAL_WINDOW_MIN,
                            )
                    continue

                # [3] 已升级隔夜 → 复查板块崩
                if hold.upgraded:
                    sec_limit_n, sec_broken_n = _count_state(hold.sector_codes, minute_dt)
                    if sec_broken_n >= L_CB_RECHECK_BROKEN_MAX:
                        hold.sell_sector_limits = sec_limit_n
                        logger.info(
                            "pattern_02 L_CB recheck-fallback %s sector=%s underlying=%s "
                            "at=%s limits=%d broken=%d≥%d → 回退 T+0",
                            trade_date, hold.sector, hold.underlying,
                            _hhmm_label(minute_dt),
                            sec_limit_n, sec_broken_n, L_CB_RECHECK_BROKEN_MAX,
                        )
                        _set_sell_t0(hold, minute_dt, reason="A_then_recheck_fallback")
                        hold.evaluated = True
                    continue

                # [4] 评估窗内
                if hold.first_limit_minute is None:
                    continue
                elapsed_sec = (minute_dt - hold.first_limit_minute).total_seconds()
                in_window = elapsed_sec <= L_CB_EVAL_WINDOW_MIN * 60
                sec_limit_n, sec_broken_n = _count_state(hold.sector_codes, minute_dt)
                if (sec_limit_n >= L_CB_OVERNIGHT_LIMIT_MIN
                        and sec_broken_n <= L_CB_OVERNIGHT_OPEN_MAX):
                    logger.info(
                        "pattern_02 L_CB upgrade-late %s sector=%s underlying=%s "
                        "at=%s limits=%d broken=%d 窗口内+%dmin → A 隔夜",
                        trade_date, hold.sector, hold.underlying,
                        _hhmm_label(minute_dt), sec_limit_n, sec_broken_n,
                        int(elapsed_sec // 60),
                    )
                    _set_sell_overnight(hold)
                    hold.upgraded = True
                    continue
                if not in_window:
                    hold.sell_sector_limits = sec_limit_n
                    logger.info(
                        "pattern_02 L_CB t0-window-timeout %s sector=%s underlying=%s "
                        "at=%s limits=%d/%d broken=%d/%d 窗口超时 → B 立卖",
                        trade_date, hold.sector, hold.underlying,
                        _hhmm_label(minute_dt),
                        sec_limit_n, L_CB_OVERNIGHT_LIMIT_MIN,
                        sec_broken_n, L_CB_OVERNIGHT_OPEN_MAX,
                    )
                    _set_sell_t0(hold, minute_dt, reason="B_window_timeout")
                    hold.evaluated = True

            # ── 买回判定（与 Pattern01 一致）──
            to_rebuy: list[dict] = []
            cur_hhmmss = _hhmmss(minute_dt)
            for hold in cb_holdings:
                if not hold.evaluated:
                    continue
                if hold.rebuy_count >= L_CB_REBUY_MAX_TIMES:
                    continue
                if hold.sell_minute is None or hold.sell_price is None:
                    continue
                gap_sec = (minute_dt - hold.sell_minute).total_seconds()
                if gap_sec < L_CB_REBUY_MIN_GAP_MIN * 60:
                    continue
                if cur_hhmmss > L_CB_REBUY_DEADLINE:
                    continue
                sec_lim_now, _ = _count_state(hold.sector_codes, minute_dt)
                new_limits = sec_lim_now - hold.sell_sector_limits
                if new_limits < L_CB_REBUY_NEW_LIMITS_MIN:
                    continue
                cb_now_close = hold.cb_minute_close.get(minute_dt)
                price_threshold = hold.sell_price * L_CB_REBUY_PRICE_RATIO
                if cb_now_close is None or cb_now_close > price_threshold:
                    continue
                hold.rebuy_count += 1
                to_rebuy.append({
                    "hold": hold, "sec_lim_now": sec_lim_now,
                    "new_limits": new_limits, "cb_now_close": cb_now_close,
                })

            for r in to_rebuy:
                old = r["hold"]
                cb_code = old.signal.pick_code
                u_name = old.signal.pick_name.replace("转债", "")
                logger.info(
                    "pattern_02 L_CB rebuy %s sector=%s underlying=%s at=%s "
                    "原卖价=%.2f → 买回价=%.2f / 板块涨停 %d→%d (+%d)",
                    trade_date, old.sector, old.underlying, _hhmm_label(minute_dt),
                    old.sell_price, r["cb_now_close"],
                    old.sell_sector_limits, r["sec_lim_now"], r["new_limits"],
                )
                new_sig = PatternSignal(
                    trade_date=trade_date,
                    pattern=old.signal.pattern,
                    sector=old.sector,
                    long1_code=old.signal.long1_code,
                    long1_name=old.signal.long1_name,
                    long1_tag=old.signal.long1_tag,
                    long1_first_time=old.signal.long1_first_time,
                    long1_open_times=old.signal.long1_open_times,
                    sector_size=r["sec_lim_now"],
                    pick_code=cb_code,
                    pick_name=old.signal.pick_name,
                    pick_role="follower_cb_rebuy",
                    pick_tag=old.signal.pick_tag,
                    reason=(
                        f"事后买回 板块涨停 {old.sell_sector_limits}→{r['sec_lim_now']}"
                        f"(+{r['new_limits']}) 原卖价={old.sell_price:.2f} → "
                        f"买回={r['cb_now_close']:.2f} 买{_hhmm_label(minute_dt)} "
                        f"underlying={u_name}({old.underlying}) [L_CB 跟风债-买回]"
                    ),
                    holding="overnight",
                    sell_anchor="next_open",
                    pick_kind="cb",
                    underlying_code=old.underlying,
                    buy_anchor="intraday_at",
                    buy_anchor_time=_hhmmss(minute_dt),
                )
                signals.append(new_sig)
                cb_holdings.append(_CbHolding(
                    signal=new_sig,
                    underlying=old.underlying,
                    sector=old.sector,
                    sector_codes=old.sector_codes,
                    buy_minute=minute_dt,
                    cb_minute_close=old.cb_minute_close,
                    rebuy_count=L_CB_REBUY_MAX_TIMES,
                    is_rebuy=True,
                    rebuy_price=r["cb_now_close"],
                ))

        # 6. 收尾
        for hold in cb_holdings:
            if hold.evaluated:
                continue
            if hold.upgraded:
                logger.info(
                    "pattern_02 L_CB confirm-overnight %s sector=%s underlying=%s "
                    "→ 板块未崩，维持 next_open",
                    trade_date, hold.sector, hold.underlying,
                )
            else:
                logger.info(
                    "pattern_02 L_CB default %s sector=%s underlying=%s "
                    "(ever_limit=%s) → today_close",
                    trade_date, hold.sector, hold.underlying, hold.ever_limit,
                )
                _set_sell_today_close(hold)
            hold.evaluated = True

        # 7. 释放预拉数据
        quotes.clear()
        first_limit_times.clear()
        industries.clear()
        meta.clear()

        return signals

    # ───────────────────────────────────────────────────────────────────────
    # L1 一字启动触发：09:30 那根 K 线扫板块所有 is_limit_at_open=True 的票。
    # 多只时按板数从高到低排为 long1/long2/long3...（板数相同按 code 字典序）。
    # 龙 1 正股本身 buy_anchor="skip"（散户买不到），同时发出板块所有非一字
    # 成员的转债（L_CB），进入与 Pattern01 一致的 A/B/C/D 升级隔夜流程。
    # 返回 (first_long1_code, minute_dt, all_yizi_codes_set) | None
    # ───────────────────────────────────────────────────────────────────────
    async def _check_and_trigger_l1_yizi(
        self,
        session: AsyncSession,
        trade_date: str,
        sec_name: str,
        codes: list[str],
        minute_dt: datetime,
        quotes: QuoteMap,
        meta: dict[str, dict],
        signals: list[PatternSignal],
        cb_holdings: list[_CbHolding],
        t1_boards: dict[str, int],
    ) -> tuple[str, datetime, set[str]] | None:
        # Pattern02 排除"T-1 连板接力一字"：T-1 连板（板数 ≥ 2）+ T 日一字开 → 跳过
        # T-1 首板涨停（板数=1）或 T-1 没涨停 → 视为"新启动"，正常作为龙 1
        yizi_candidates: list[tuple[str, int]] = []  # (code, board_count)
        for code in codes:
            q = quotes.get((code, minute_dt))
            if q and q.is_limit_at_open:
                t1_board = t1_boards.get(code, 0)
                if t1_board >= 2:
                    logger.info(
                        "pattern_02 funnel %s sector=%s skip yizi %s "
                        "(T-1 连板 %d 板=接力一字)",
                        trade_date, sec_name, code, t1_board,
                    )
                    continue
                board = _parse_board_from_tag(meta.get(code, {}).get("tag"))
                yizi_candidates.append((code, board))
        if not yizi_candidates:
            return None
        # 按板数从高到低排（板数相同按代码字典序保确定性）
        yizi_candidates.sort(key=lambda x: (-x[1], x[0]))
        yizi_codes = {c for c, _ in yizi_candidates}

        logger.info(
            "pattern_02 funnel %s sector=%s L1-yizi trigger at=%s yizi_n=%d codes=%s",
            trade_date, sec_name, _hhmm_label(minute_dt), len(yizi_candidates),
            [(c, b) for c, b in yizi_candidates],
        )

        buy_time_str = _hhmmss(minute_dt)
        first_long1 = yizi_candidates[0][0]
        l1_meta = meta.get(first_long1, {})
        l1_name = l1_meta.get("name") or first_long1
        l1_tag = l1_meta.get("tag") or "首板"
        l1_first_time = l1_meta.get("first_time") or buy_time_str
        l1_open_times = l1_meta.get("open_times", 0)

        # 发出每只一字票的 long1/long2/long3... 信号（buy_anchor="skip"）
        for idx, (code, board) in enumerate(yizi_candidates):
            role = f"long{idx + 1}"
            c_meta = meta.get(code, {})
            c_name = c_meta.get("name") or code
            c_tag = c_meta.get("tag") or f"{board}板"
            signals.append(PatternSignal(
                trade_date=trade_date,
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
            f_q = quotes.get((follower_code, minute_dt))
            if f_q is not None and f_q.is_limit:
                # 跟风当前已涨停（非一字）= 老师"卖点"，不能在卖点买它的债
                logger.info(
                    "pattern_02 funnel %s sector=%s skip cb of %s (已涨停=卖点)",
                    trade_date, sec_name, follower_code,
                )
                continue
            cb_code = await find_cb_for_stock(session, follower_code, trade_date)
            if not cb_code:
                continue
            f_meta = meta.get(follower_code, {})
            f_name = f_meta.get("name") or follower_code
            f_tag = f_meta.get("tag") or "未涨停"
            cb_sig = PatternSignal(
                trade_date=trade_date,
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
            cb_minute_close = await _fetch_cb_minute_close(session, cb_code, trade_date)
            cb_holdings.append(_CbHolding(
                signal=cb_sig,
                underlying=follower_code,
                sector=sec_name,
                sector_codes=codes,
                buy_minute=minute_dt,
                cb_minute_close=cb_minute_close,
            ))

        return (first_long1, minute_dt, yizi_codes)
