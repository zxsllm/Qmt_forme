"""龙头隔夜模式 v6 — 严格事中扫描（与模拟盘对齐，无未来函数）。

老师课件原话（docs/100_AI课件.md:105-117）：
    （1）龙头时间: A:龙1低进 / B:跟风/影子龙低进 / B债:低进
    （2）跟风时间: B:低进（影子龙 15min 内有机会，别的跟风更长）/ B债:低进
    （3）转债时间: b:低进，可以拿到尾盘隔夜

事中算法（v6 重写）：
    模拟盘里 rt_k 每分钟推一根 1min K 线。回测时一次预拉所有候选票全天 1min
    数据进内存，扫描结束后释放（用户原话："回测预拉可以，后面释放掉就行"）。
    两套数据源、同一套扫描逻辑。

    主循环：
        for 分钟 in [09:30, 09:31, ..., 14:55]:
            for 板块 in T-1 lookback + 萌芽主线:
                if 板块未触发 L1:
                    扫板块所有未涨停票，找第一个满足 "自身 ≥9% + ≥2 只 ≥6%"
                    → 触发 L1: 买这只票 + 板块所有跟风票的债
                if 板块已触发 L1 未触发 L2:
                    扫板块（除 L1 那只外），找第一个满足 "自身 ≥9% + ≥3 只 ≥8%"
                    → 触发 L2: 买这只票
            扫描这一分钟新增封板的票 → 萌芽行业累积 ≥3 只 → 触发萌芽主线发 L_CB
            更新所有 L_CB 持仓的 sell_anchor:
                - underlying 当前分钟首次封板 → 评估升级（板块涨停 ≥3 + 炸板 ≤1）
                  * 升级 → sell_anchor=next_open（隔夜）
                  * 不升级 → sell_anchor=intraday_at + 当前分钟（T+0 立即卖）
                - underlying 全天未封板 + close 跌破日内均价 → T+0 止损卖
        14:55 收尾: 仍未 evaluated 的 L_CB → 默认按 close T+0 卖（保守）

事中没有"龙1/影子龙"概念，只有"哪只票最先满足入场条件"。事后回看时，触发
L1 的票通常 = 真龙1，触发 L2 的票通常 = 真影子龙，但严格事中下不绑定。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import text

from app.research.data.cb_resolver import find_cb_for_stock
from app.research.signals.long_head_detector import (
    QuoteMap,
    compute_vwap_until,
    count_codes_above_pct_intraday,
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
    BasePattern,
    PatternSignal,
    load_sectors,
)

logger = logging.getLogger(__name__)

# ── 共识阈值（分层）──
INTRADAY_CONSENSUS_MIN_L1 = 2    # L1 板块第一次触发最少票数（已知主线）
INTRADAY_CONSENSUS_MIN_L1_EMERGING = 3  # 萌芽板块 L1 加严：≥3 只 ≥6%（避免板块未真共振就触发）
INTRADAY_CONSENSUS_MIN_L2 = 3    # L2 板块第二次触发最少票数
INTRADAY_CONSENSUS_PCT_L1 = 6.0  # L1 共识阈值（不按板块缩放，"普涨"语义跨板块统一）
INTRADAY_CONSENSUS_PCT_L2 = 8.0  # L2 共识阈值
# 自身涨幅触发线："接近封板"语义，按板块涨停限制按比例缩放：
#   主板 ±10% → 9%   创业/科创 ±20% → 18%   北交所 ±30% → 27%   ST ±5% → 4.5%
SELF_TRIGGER_RATIO = 0.9         # = up_limit_pct × 0.9

# ── L_CB 升级隔夜条件（持仓 underlying 首次封板时评估）──
L_CB_OVERNIGHT_LIMIT_MIN = 3     # 板块累计涨停 ≥ 3 只（共识强）
L_CB_OVERNIGHT_OPEN_MAX = 1      # 板块累计炸板 ≤ 1 只（情绪稳）
# ── 漏① 修复（思路 B）：升级隔夜后不锁死，每分钟复查板块炸板 ──
# 升级时阈值是 broken ≤ 1，后续累计炸板再增加到 ≥ 3 即"题材开始崩" → 回退 T+0
L_CB_RECHECK_BROKEN_MAX = 3

# ── 萌芽主线 ──
EMERGING_CUTOFF = "113000"             # 早盘结束前都监控
EMERGING_MIN_COUNT = 3                 # 同行业 ≥ 3 只名单外涨停
EMERGING_SECTOR_PREFIX = "(萌芽-"


@dataclass
class _CbHolding:
    """L_CB 持仓状态（事中维护，用于决定 sell_anchor）。"""
    signal: PatternSignal           # 关联的 PatternSignal（最后回填 sell_anchor）
    underlying: str                 # 正股代码
    sector: str                     # 板块名
    sector_codes: list[str]         # 板块成员（升级判定用）
    buy_minute: datetime
    ever_limit: bool = False        # underlying 是否曾封板
    evaluated: bool = False         # 是否已决定 sell_anchor


def _hhmmss(dt: datetime) -> str:
    return dt.strftime("%H%M%S")


def _hhmm_label(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _set_sell_overnight(hold: _CbHolding) -> None:
    hold.signal.sell_anchor = "next_open"
    hold.signal.sell_anchor_time = None


def _set_sell_t0(hold: _CbHolding, when: datetime) -> None:
    hold.signal.sell_anchor = "intraday_at"
    hold.signal.sell_anchor_time = _hhmmss(when)


def _set_sell_today_close(hold: _CbHolding) -> None:
    hold.signal.sell_anchor = "today_close"
    hold.signal.sell_anchor_time = None


class Pattern01(BasePattern):
    pattern_id = "pattern_01"
    description = "自然涨停启动的龙头隔夜模式（事中）"
    sector_min_size = 1
    needs_predictor = False

    async def find_signals(
        self,
        session: AsyncSession,
        trade_date: str,
        source: str = "bankuai",
    ) -> list[PatternSignal]:
        # 1. 板块名单（盘前可知）
        sectors = await load_sectors(session, trade_date, source)
        if not sectors:
            logger.info("pattern_01 funnel %s: no sectors loaded", trade_date)
            return []

        # 2. 萌芽主线候选（按行业预分组，但触发依赖事中扫描的实际封板顺序）
        known_codes = {c for cs in sectors.values() for c in cs}
        emerging_map = await detect_emerging_sectors(
            session, trade_date, known_codes,
            cutoff_hhmmss=EMERGING_CUTOFF,
            min_count=EMERGING_MIN_COUNT,
        )
        emerging_codes_by_industry: dict[str, set[str]] = {
            ind: set(codes) for ind, (codes, _) in emerging_map.items()
        }
        # 把萌芽板块加进 sectors（虚拟板块）
        for industry, (em_codes, _) in emerging_map.items():
            virtual_name = f"{EMERGING_SECTOR_PREFIX}{industry})"
            sectors[virtual_name] = em_codes
            logger.info(
                "pattern_01 emerging candidate %s: %s with %d codes",
                trade_date, virtual_name, len(em_codes),
            )

        # 3. 预拉所有候选票全天分钟数据 + 行业映射 + 当日封板时刻
        all_codes = list({c for cs in sectors.values() for c in cs})
        quotes = await fetch_minute_quotes(session, trade_date, all_codes)
        first_limit_times = await fetch_first_limit_times(session, trade_date)
        # 萌芽 fallback：股票→行业映射（用于扫描时归类新增封板）
        industries = await fetch_industries(session, all_codes)
        # 展示元数据：中文名 / 板数标签 / 真实 first_time / 炸板数（仅输出用，不影响决策）
        meta = await fetch_stock_meta(session, trade_date, all_codes)

        # ── B 规则：板块级闸门（开盘 09:30 板块内任何成员"开盘瞬间"封板 → 板块作废）──
        # 用 is_limit_at_open（基于 9:30 那根的 open 字段）而不是 close —— 集合竞价封死
        # 后秒级炸开的票（如 5/7 博敏电子 open=18.76=涨停 / close=18.68）也会被正确识别
        open_minute = datetime.strptime(trade_date, "%Y%m%d").replace(hour=9, minute=30)
        invalidated: set[str] = set()
        for sec_name, codes in sectors.items():
            for code in codes:
                q = quotes.get((code, open_minute))
                if q and q.is_limit_at_open:
                    invalidated.add(sec_name)
                    logger.info(
                        "pattern_01 funnel %s sector=%s INVALIDATED: %s 09:30 一字/秒板启动 "
                        "(open=%.2f≥涨停%.2f)",
                        trade_date, sec_name, code, q.open, q.up_limit,
                    )
                    break

        # ── C/D 规则：T-1 严格一字票名单 ──
        # C：T-1 一字 + T 日一字开 → 归模式 3、4（B 规则已作废板块）
        # D：T-1 一字 + T 日没一字开（09:30 close < up_limit）→ 从板块剔除，
        #    不参与共识、不作 L1/L2 候选、不发跟风债
        t1_date = await self._prev_trade_date(session, trade_date)
        t1_one_word = (
            await fetch_t1_solid_one_word_limits(session, t1_date) if t1_date else set()
        )
        if t1_one_word:
            logger.info(
                "pattern_01 funnel %s T-1=%s 严格一字 %d 只: %s",
                trade_date, t1_date, len(t1_one_word),
                sorted(t1_one_word)[:20],
            )
        # D 规则：从每个板块的 codes 里剔除"T-1 一字 + T 日 09:30 没一字开"的票
        # 同样用 is_limit_at_open 判定"一字开" — 与 B 规则口径一致
        for sec_name in list(sectors.keys()):
            original = list(sectors[sec_name])
            kept = []
            for code in original:
                if code in t1_one_word:
                    q = quotes.get((code, open_minute))
                    if q is None or not q.is_limit_at_open:
                        # T-1 一字接力但 T 日 9:30 open 没到涨停 → 整个剔除
                        logger.info(
                            "pattern_01 funnel %s sector=%s 剔除 %s (T-1 一字 + T 日 09:30 未一字开)",
                            trade_date, sec_name, code,
                        )
                        continue
                kept.append(code)
            sectors[sec_name] = kept

        # 4. 状态机
        # 每个板块: {"l1": (code, minute) | None, "l2": (code, minute) | None}
        sector_state: dict[str, dict] = {sec: {"l1": None, "l2": None} for sec in sectors}
        # 萌芽主线：每个行业当前累积的"已封板"萌芽票（事中观察）
        # 注：emerging_map 已经预分组了候选，但触发要等事中真正看到 ≥3 只封板才算
        emerging_observed: dict[str, set[str]] = {ind: set() for ind in emerging_codes_by_industry}
        emerging_triggered: set[str] = set()  # 已触发的虚拟板块名
        # L_CB 持仓
        cb_holdings: list[_CbHolding] = []

        signals: list[PatternSignal] = []
        minutes = iter_trading_minutes(trade_date)

        # 5. 主扫描循环
        for minute_dt in minutes:
            # ── 板块 L1 / L2 触发检查 ──
            for sec_name, codes in sectors.items():
                if sec_name in invalidated:
                    continue   # B 规则：板块开盘已封板 → 整体作废
                state = sector_state[sec_name]
                is_emerging = sec_name.startswith(EMERGING_SECTOR_PREFIX)

                if state["l1"] is None:
                    # L1 检查：板块第一次触发
                    triggered = await self._check_and_trigger_l1(
                        session, trade_date, sec_name, codes, minute_dt,
                        quotes, meta, signals, cb_holdings, is_emerging,
                        t1_one_word,
                    )
                    if triggered:
                        state["l1"] = triggered  # (code, minute)
                elif state["l2"] is None and not is_emerging:
                    # L2 检查（萌芽不发 L2 正股）
                    l1_code = state["l1"][0]
                    triggered = await self._check_and_trigger_l2(
                        sec_name, codes, l1_code, minute_dt, quotes, meta, signals,
                        t1_one_word,
                    )
                    if triggered:
                        state["l2"] = triggered

            # ── 萌芽主线：检查这一分钟是否有新增封板的萌芽票 ──
            for industry, em_codes in emerging_codes_by_industry.items():
                virtual_name = f"{EMERGING_SECTOR_PREFIX}{industry})"
                if virtual_name in invalidated:
                    continue   # B 规则同样作用于萌芽板块
                if virtual_name in emerging_triggered:
                    continue
                # 看哪些萌芽票在这一分钟首次封板
                observed = emerging_observed[industry]
                for code in em_codes:
                    if code in observed:
                        continue
                    q = quotes.get((code, minute_dt))
                    if q and q.is_limit:
                        observed.add(code)
                if len(observed) >= EMERGING_MIN_COUNT:
                    # 萌芽触发！该虚拟板块在事中正式成立
                    emerging_triggered.add(virtual_name)
                    logger.info(
                        "pattern_01 funnel %s emerging triggered: %s observed=%d at %s",
                        trade_date, virtual_name, len(observed), _hhmm_label(minute_dt),
                    )
                    # （对应虚拟板块的 L1 检查已经在上面循环里触发了，这里只记日志）

            # ── L_CB 持仓状态更新 ──
            for hold in cb_holdings:
                if hold.evaluated:
                    continue
                # 买入当分钟不做评估，至少推迟到下一分钟（避免买卖同分钟手续费白扣）
                if minute_dt <= hold.buy_minute:
                    continue
                q = quotes.get((hold.underlying, minute_dt))
                if q is None:
                    continue
                if q.is_limit and not hold.ever_limit:
                    # underlying 当前分钟首次封板 → 评估升级
                    hold.ever_limit = True
                    sec_limit_n, sec_broken_n = count_sector_limit_state_intraday(
                        quotes, hold.sector_codes, minute_dt,
                    )
                    upgrade = (
                        sec_limit_n >= L_CB_OVERNIGHT_LIMIT_MIN
                        and sec_broken_n <= L_CB_OVERNIGHT_OPEN_MAX
                    )
                    logger.info(
                        "pattern_01 L_CB eval %s sector=%s underlying=%s at=%s "
                        "limits=%d/%d broken=%d/%d → %s",
                        trade_date, hold.sector, hold.underlying, _hhmm_label(minute_dt),
                        sec_limit_n, L_CB_OVERNIGHT_LIMIT_MIN,
                        sec_broken_n, L_CB_OVERNIGHT_OPEN_MAX,
                        "overnight (待复查)" if upgrade else "T+0",
                    )
                    if upgrade:
                        _set_sell_overnight(hold)
                        # 漏① 修复：暂定隔夜，不锁死 evaluated，每分钟继续监控板块
                    else:
                        _set_sell_t0(hold, minute_dt)
                        hold.evaluated = True
                elif hold.ever_limit and not hold.evaluated:
                    # 漏① 修复：A 分支已暂定隔夜，每分钟复查板块炸板
                    # 累计炸板 ≥ L_CB_RECHECK_BROKEN_MAX → 题材开始崩 → 回退 T+0
                    sec_limit_n, sec_broken_n = count_sector_limit_state_intraday(
                        quotes, hold.sector_codes, minute_dt,
                    )
                    if sec_broken_n >= L_CB_RECHECK_BROKEN_MAX:
                        logger.info(
                            "pattern_01 L_CB recheck-fallback %s sector=%s underlying=%s "
                            "at=%s limits=%d broken=%d≥%d → 回退 T+0",
                            trade_date, hold.sector, hold.underlying,
                            _hhmm_label(minute_dt),
                            sec_limit_n, sec_broken_n, L_CB_RECHECK_BROKEN_MAX,
                        )
                        _set_sell_t0(hold, minute_dt)
                        hold.evaluated = True
                elif not hold.ever_limit:
                    # 还没封板 → 检查止损：close 跌破当日均价
                    vwap = compute_vwap_until(quotes, hold.underlying, minute_dt)
                    if vwap is not None and q.close < vwap:
                        logger.info(
                            "pattern_01 L_CB stoploss %s sector=%s underlying=%s at=%s "
                            "close=%.2f < vwap=%.2f → T+0 cut",
                            trade_date, hold.sector, hold.underlying,
                            _hhmm_label(minute_dt), q.close, vwap,
                        )
                        _set_sell_t0(hold, minute_dt)
                        hold.evaluated = True

        # 6. 收尾：未 evaluated 的 L_CB
        #   - ever_limit=True：A 分支暂定隔夜后板块没崩到回退阈值 → 维持 next_open
        #   - ever_limit=False：全天没封过板也没跌破 VWAP → 保守 today_close
        for hold in cb_holdings:
            if hold.evaluated:
                continue
            if hold.ever_limit:
                logger.info(
                    "pattern_01 L_CB confirm-overnight %s sector=%s underlying=%s "
                    "→ 板块未崩，维持 next_open",
                    trade_date, hold.sector, hold.underlying,
                )
                # sell_anchor 已在 A 分支设为 next_open，不动
            else:
                logger.info(
                    "pattern_01 L_CB default %s sector=%s underlying=%s → today_close",
                    trade_date, hold.sector, hold.underlying,
                )
                _set_sell_today_close(hold)
            hold.evaluated = True

        # 7. 释放预拉数据（用户原话："回测预拉可以，后面释放掉就行"）
        quotes.clear()
        first_limit_times.clear()
        industries.clear()
        meta.clear()

        return signals

    # ───────────────────────────────────────────────────────────────────────
    # L1 触发：板块第一次找到 "某只票 ≥9% + 板块 ≥2 只 ≥6%"
    # 触发时同步发 L_CB（板块所有跟风票的债）
    # ───────────────────────────────────────────────────────────────────────
    async def _check_and_trigger_l1(
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
        is_emerging: bool,
        t1_one_word: set[str],
    ) -> tuple[str, datetime] | None:
        # 板块共识：≥6% 票数（萌芽板块 ≥3 只 / 已知主线 ≥2 只）
        min_required = (
            INTRADAY_CONSENSUS_MIN_L1_EMERGING if is_emerging
            else INTRADAY_CONSENSUS_MIN_L1
        )
        consensus_n = count_codes_above_pct_intraday(
            quotes, codes, minute_dt, INTRADAY_CONSENSUS_PCT_L1
        )
        if consensus_n < min_required:
            return None
        # 收集所有满足"自身 ≥ 涨停限制×0.9"的候选（C 规则：T-1 严格一字票剔除）
        candidates = []
        for cand_code in codes:
            if cand_code in t1_one_word:
                continue   # T-1 一字接力，不买它本身
            q_cand = quotes.get((cand_code, minute_dt))
            if q_cand is None:
                continue
            up_limit_pct_cand = (q_cand.up_limit / q_cand.pre_close - 1) * 100
            self_threshold_cand = up_limit_pct_cand * SELF_TRIGGER_RATIO
            if q_cand.pct < self_threshold_cand:
                continue
            candidates.append((cand_code, q_cand))
        if not candidates:
            return None
        # 按"龙1度"排序（老师"龙1=第一只涨停"的事中代理）：
        #   1) 当前已封板的优先（is_limit=True）— 事中可见的"已涨停"事实
        #   2) 涨幅高的优先 — tie-breaker
        # 不引入 open_times（当日累计字段，避免未来函数风险；炸板"扣分"逻辑预留）
        candidates.sort(key=lambda x: (0 if x[1].is_limit else 1, -x[1].pct))
        cand, q = candidates[0]
        # 触发！
        logger.info(
            "pattern_01 funnel %s sector=%s L1 trigger at=%s code=%s "
            "self_pct=%.2f%% is_limit=%s consensus=%d/%d candidates=%d",
            trade_date, sec_name, _hhmm_label(minute_dt), cand,
            q.pct, q.is_limit, consensus_n, min_required, len(candidates),
        )
        buy_time_str = _hhmmss(minute_dt)
        l1_meta = meta.get(cand, {})
        l1_name = l1_meta.get("name") or cand
        l1_tag = l1_meta.get("tag") or f"{q.pct:.1f}%"
        l1_first_time = l1_meta.get("first_time") or buy_time_str
        l1_open_times = l1_meta.get("open_times", 0)
        base = dict(
            trade_date=trade_date,
            pattern=self.pattern_id,
            sector=sec_name,
            long1_code=cand,
            long1_name=l1_name,
            long1_tag=l1_tag,
            long1_first_time=l1_first_time,
            long1_open_times=l1_open_times,
            sector_size=consensus_n,
            holding="overnight",
            sell_anchor="next_open",
        )
        # L1 信号（萌芽主线不发 L1 正股）
        if not is_emerging:
            signals.append(PatternSignal(
                **base,
                pick_code=cand,
                pick_name=l1_name,
                pick_role="long1",
                pick_tag=l1_tag,
                reason=(
                    f"事中L1 自身{q.pct:.1f}%≥9% 板块共识{consensus_n}只≥6% "
                    f"触发{_hhmm_label(minute_dt)} [L1 正股]"
                ),
                pick_kind="stock",
                buy_anchor="intraday_at",
                buy_anchor_time=buy_time_str,
            ))
        # L_CB 同步：板块所有跟风（除 L1 自己外）的债
        role_prefix = "萌芽-" if is_emerging else ""
        for follower_code in codes:
            if follower_code == cand:
                continue
            # 错①修复：跟风当前已涨停 = 老师"卖点"，不能在卖点买它的债
            f_q = quotes.get((follower_code, minute_dt))
            if f_q is not None and f_q.is_limit:
                logger.info(
                    "pattern_01 funnel %s sector=%s skip cb of %s (已涨停=卖点)",
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
                **{**base, "sell_anchor": "next_open"},  # placeholder，主循环回填
                pick_code=cb_code,
                pick_name=f"{f_name}转债",
                pick_role="follower_cb",
                pick_tag=f_tag,
                reason=(
                    f"事中L1同步发债 板块共识{consensus_n}只≥6% "
                    f"买{_hhmm_label(minute_dt)} underlying={f_name}({follower_code}) "
                    f"[L_CB {role_prefix}跟风债]"
                ),
                pick_kind="cb",
                underlying_code=follower_code,
                buy_anchor="intraday_at",
                buy_anchor_time=buy_time_str,
            )
            signals.append(cb_sig)
            cb_holdings.append(_CbHolding(
                signal=cb_sig,
                underlying=follower_code,
                sector=sec_name,
                sector_codes=codes,
                buy_minute=minute_dt,
            ))
        return (cand, minute_dt)

    # ───────────────────────────────────────────────────────────────────────
    # L2 触发：板块第二次（不同票）"≥9% + 板块 ≥3 只 ≥8%"
    # 不发新 L_CB（已在 L1 时全部买齐）
    # ───────────────────────────────────────────────────────────────────────
    async def _check_and_trigger_l2(
        self,
        sec_name: str,
        codes: list[str],
        l1_code: str,
        minute_dt: datetime,
        quotes: QuoteMap,
        meta: dict[str, dict],
        signals: list[PatternSignal],
        t1_one_word: set[str],
    ) -> tuple[str, datetime] | None:
        consensus_n = count_codes_above_pct_intraday(
            quotes, codes, minute_dt, INTRADAY_CONSENSUS_PCT_L2
        )
        if consensus_n < INTRADAY_CONSENSUS_MIN_L2:
            return None
        # 收集 L2 候选（排除 L1 + C 规则 T-1 一字）
        candidates = []
        for cand_code in codes:
            if cand_code == l1_code or cand_code in t1_one_word:
                continue
            q_cand = quotes.get((cand_code, minute_dt))
            if q_cand is None:
                continue
            up_limit_pct_cand = (q_cand.up_limit / q_cand.pre_close - 1) * 100
            self_threshold_cand = up_limit_pct_cand * SELF_TRIGGER_RATIO
            if q_cand.pct < self_threshold_cand:
                continue
            candidates.append((cand_code, q_cand))
        if not candidates:
            return None
        # 按"龙2度"排序：1) 已封板优先；2) 涨幅高的 tie-breaker
        candidates.sort(key=lambda x: (0 if x[1].is_limit else 1, -x[1].pct))
        cand, q = candidates[0]
        logger.info(
            "pattern_01 funnel sector=%s L2 trigger at=%s code=%s "
            "self_pct=%.2f%% is_limit=%s consensus=%d/%d candidates=%d",
            sec_name, _hhmm_label(minute_dt), cand,
            q.pct, q.is_limit, consensus_n, INTRADAY_CONSENSUS_MIN_L2, len(candidates),
        )
        buy_time_str = _hhmmss(minute_dt)
        l1_meta = meta.get(l1_code, {})
        cand_meta = meta.get(cand, {})
        cand_name = cand_meta.get("name") or cand
        cand_tag = cand_meta.get("tag") or f"{q.pct:.1f}%"
        cand_first = cand_meta.get("first_time") or buy_time_str
        cand_open = cand_meta.get("open_times", 0)
        signals.append(PatternSignal(
            trade_date=minute_dt.strftime("%Y%m%d"),
            pattern=self.pattern_id,
            sector=sec_name,
            long1_code=l1_code,
            long1_name=l1_meta.get("name") or l1_code,
            long1_tag=l1_meta.get("tag") or "",
            long1_first_time=l1_meta.get("first_time") or "",
            long1_open_times=l1_meta.get("open_times", 0),
            sector_size=consensus_n,
            pick_code=cand,
            pick_name=cand_name,
            pick_role="shadow",
            pick_tag=cand_tag,
            reason=(
                f"事中L2 自身{q.pct:.1f}%≥9% 板块共识{consensus_n}只≥8% "
                f"触发{_hhmm_label(minute_dt)} 首封{cand_first[:2]}:{cand_first[2:4]} "
                f"炸{cand_open}次 [L2 正股]"
            ),
            pick_kind="stock",
            buy_anchor="intraday_at",
            buy_anchor_time=buy_time_str,
            holding="overnight",
            sell_anchor="next_open",
        ))
        return (cand, minute_dt)

    # ───────────────────────────────────────────────────────────────────────
    # 工具：取 T-1 交易日（用于拉一字票名单）
    # ───────────────────────────────────────────────────────────────────────
    @staticmethod
    async def _prev_trade_date(session: AsyncSession, td: str) -> str | None:
        r = await session.execute(text(
            "SELECT cal_date FROM trade_cal "
            "WHERE cal_date < :d AND is_open=1 "
            "ORDER BY cal_date DESC LIMIT 1"
        ), {"d": td})
        row = r.fetchone()
        return row[0] if row else None
