"""龙头隔夜模式（合并原模式1/2）— 老师课件"情况①" 操作清单。

老师课件原话（docs/100_AI课件.md:105-117）：
    （1）龙头时间: A:龙1低进 / B:跟风/影子龙低进 / B债:低进
    （2）跟风时间: B:低进（影子龙 15min 内有机会，别的跟风更长）/ B债:低进
    （3）转债时间: b:低进，可以拿到尾盘隔夜
    "如果跟风没法涨停，低进赢面大，尾盘回落/第二天低开 程度小（龙一跨一字可以带）"

入口（**严格事中可见，无未来函数**）：
    - 龙1 自然涨停（盘中封板，非一字开盘）— 一字情况走模式 3
    - **共识检查（事中代理）**：在龙1/影子龙 first_time 那一分钟，板块成员中
      涨幅 ≥ 阈值的票数 ≥ INTRADAY_CONSENSUS_MIN（默认 3）
        L1 龙1 锚点：≥6%（盘中显著拉升即可）
        L2 影子龙锚点：≥8%（影子龙时跟风已发酵，要求更硬的同步）
    - **不用预测器过滤** — 实盘里事中无法可靠判断次日是否一字

多腿信号（每个板块发若干腿，事后统计哪些腿稳）：
    - L1 龙1 正股   : 买在 long1.first_time（封板瞬间排队）→ 卖 T+1 09:30
    - L2 影子龙正股  : 买在 shadow.first_time → 卖 T+1 09:30
    - L_CB 影子龙债  : 买在 long1.first_time（与 L1 同步，债流动性好能买到）
                     卖点动态判定（影子龙 first_time 那分钟，看升级条件）：
                       * 升级隔夜（板块涨停 ≥ 3 + 炸板 ≤ 1）→ T+1 09:30
                       * 不升级（默认）→ T+0 影子龙 first_time 立即卖
                     依据：老师课件情况 1+2 转债买卖时点（情况 1 隔夜，情况 2 跟风
                     涨停立即砸；事中分不清就按更保守的情况 2 兜底，宁可少赚不亏）

事中决策依据（输出展示，不当过滤）：
    - 板块最高板（高度位风险）
    - 龙1 板高 / first_time（封得早 = 强）
    - 影子龙 first_time 是否在 15min 上车窗口内（lh.shadow_within_15min）
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.research.data.cb_resolver import find_cb_for_stock
from app.research.signals.long_head_detector import (
    LongHeadResult,
    count_near_limit_at_minute,
    count_sector_limit_state,
    detect_emerging_sectors,
    detect_long_head,
    find_entry_trigger,
)
from app.research.strategies.base_pattern import (
    BasePattern,
    PatternSignal,
    fetch_daily_ohlc,
    is_natural_limit,
    load_sectors,
)

logger = logging.getLogger(__name__)

# ── 共识阈值（分层）──
INTRADAY_CONSENSUS_MIN = 3       # 事中共识最少票数（含龙1自己/影子龙自己）
INTRADAY_CONSENSUS_PCT_L1 = 6.0  # L1 龙1 锚点阈值（盘中显著拉升即可）
INTRADAY_CONSENSUS_PCT_L2 = 8.0  # L2 影子龙锚点阈值（跟风已发酵，要求更硬）

# ── L_CB 升级隔夜条件（影子龙 first_time 那分钟评估）──
L_CB_OVERNIGHT_LIMIT_MIN = 3     # 板块累计涨停 ≥ 3 只（共识强）
L_CB_OVERNIGHT_OPEN_MAX = 1      # 板块累计炸板 ≤ 1 只（情绪稳）

# ── 萌芽主线（盘中按行业分组识别 T-1 名单外同步爆发，只发 L_CB 控风险）──
EMERGING_CUTOFF_TIME = "094500"        # 09:45 前累积识别（事中可见）
EMERGING_MIN_COUNT = 3                 # 同一行业名单外涨停 ≥ 3 只 → 萌芽
EMERGING_SECTOR_PREFIX = "(萌芽-"      # 虚拟板块名前缀（如 "(萌芽-电气设备)"）


class Pattern01(BasePattern):
    pattern_id = "pattern_01"
    description = "龙头隔夜模式 — 事中共识 + 龙1/影子龙正股 +（影子龙债）"
    sector_min_size = 1              # 占位（事中共识替代），保留为基类兼容字段
    needs_predictor = False

    async def find_signals(
        self,
        session: AsyncSession,
        trade_date: str,
        source: str = "bankuai",
    ) -> list[PatternSignal]:
        sectors = await load_sectors(session, trade_date, source)
        if not sectors:
            logger.info("pattern_01 funnel %s: no sectors loaded", trade_date)
            return []

        # ── 萌芽主线探测（T 日 09:45 前同一行业 ≥3 只名单外涨停 → 加虚拟板块）──
        # 按 stock_basic.industry 分组，避免把杂鱼涨停股混成一个伪板块
        # 主循环对该类板块特殊处理：跳过 L1/L2 正股，只发 L_CB（风险控制）
        known_codes = {code for codes in sectors.values() for code in codes}
        emerging_map = await detect_emerging_sectors(
            session, trade_date, known_codes,
            cutoff_hhmmss=EMERGING_CUTOFF_TIME,
            min_count=EMERGING_MIN_COUNT,
        )
        for industry, em_codes in emerging_map.items():
            virtual_name = f"{EMERGING_SECTOR_PREFIX}{industry})"
            logger.info(
                "pattern_01 funnel %s emerging detected: %s with %d codes",
                trade_date, virtual_name, len(em_codes),
            )
            sectors[virtual_name] = em_codes

        signals: list[PatternSignal] = []
        for sec_name, codes in sectors.items():
            is_emerging = sec_name.startswith(EMERGING_SECTOR_PREFIX)
            lh = await detect_long_head(session, trade_date, codes, sector_name=sec_name)
            if not lh.long1:
                logger.info(
                    "pattern_01 funnel %s sector=%s size=%d has_long1=False decision=skip_no_long1",
                    trade_date, sec_name, len(codes),
                )
                continue

            check_codes = [lh.long1.ts_code]
            if lh.shadow and lh.shadow.ts_code not in check_codes:
                check_codes.append(lh.shadow.ts_code)
            ohlc_map = await fetch_daily_ohlc(session, trade_date, check_codes)

            long1 = lh.long1
            if not is_natural_limit(long1, ohlc_map.get(long1.ts_code)):
                logger.info(
                    "pattern_01 funnel %s sector=%s long1=%s decision=skip_yizi",
                    trade_date, sec_name, long1.ts_code,
                )
                continue  # 一字 → 模式 3

            # ── L1 共识检查（龙1 first_time 那分钟，板块涨幅 ≥6% 的票数 ≥3）──
            l1_consensus_n, _, l1_coverage = await count_near_limit_at_minute(
                session, trade_date, codes, long1.first_time, INTRADAY_CONSENSUS_PCT_L1
            )
            l1_pass = l1_consensus_n >= INTRADAY_CONSENSUS_MIN
            logger.info(
                "pattern_01 funnel %s sector=%s long1=%s ft=%s L1_consensus=%d/%d "
                "(≥%.0f%%) coverage=%.2f decision=%s",
                trade_date, sec_name, long1.ts_code, long1.first_time,
                l1_consensus_n, INTRADAY_CONSENSUS_MIN, INTRADAY_CONSENSUS_PCT_L1,
                l1_coverage, "L1_pass" if l1_pass else "L1_skip_no_consensus",
            )

            base = dict(
                trade_date=trade_date,
                pattern=self.pattern_id,
                sector=sec_name,
                long1_code=long1.ts_code,
                long1_name=long1.name,
                long1_tag=long1.tag or f"{long1.limit_times}板",
                long1_first_time=long1.first_time,
                long1_open_times=long1.open_times,
                sector_size=l1_consensus_n,   # 改为事中共识数
                holding="overnight",
                sell_anchor="next_open",
            )
            reason_base = (
                f"龙头隔夜 L1共识{l1_consensus_n}只≥{INTRADAY_CONSENSUS_PCT_L1:.0f}% "
                f"龙1首封{long1.first_time[:2]}:{long1.first_time[2:4]}"
            )

            # L1 龙1 正股（共识达标才发；买入用 entry_trigger 替代 first_time，
            # 触发时刻通常在封板前 1~5 分钟，价格 +9% 左右未到涨停 → 能买到）
            l1_entry_time, l1_entry_close = await find_entry_trigger(
                session, trade_date, long1.ts_code, codes, long1.first_time
            )
            logger.info(
                "pattern_01 funnel %s sector=%s long1=%s entry=%s (vs first=%s) "
                "entry_close=%s",
                trade_date, sec_name, long1.ts_code, l1_entry_time, long1.first_time,
                f"{l1_entry_close:.2f}" if l1_entry_close else "None",
            )
            if l1_pass and not is_emerging:
                # 萌芽主线只发 L_CB（正股风险大），L1 正股仅在常规主线发
                signals.append(PatternSignal(
                    **base,
                    pick_code=long1.ts_code,
                    pick_name=long1.name,
                    pick_role="long1",
                    pick_tag=long1.tag or f"{long1.limit_times}板",
                    reason=reason_base + f" [L1 龙1正股 触发{l1_entry_time[:2]}:{l1_entry_time[2:4]}]",
                    pick_kind="stock",
                    buy_anchor="intraday_at",
                    buy_anchor_time=l1_entry_time,
                ))

            # L2 / L_CB：影子龙正股 + 影子龙债
            if lh.shadow:
                shadow = lh.shadow
                window_tag = "≤15min" if lh.shadow_within_15min else ">15min"

                # L2 共识：影子龙 first_time 那分钟，板块涨幅 ≥8% 的票数 ≥3（更硬）
                sh_consensus_n, _, sh_coverage = await count_near_limit_at_minute(
                    session, trade_date, codes, shadow.first_time, INTRADAY_CONSENSUS_PCT_L2
                )
                sh_pass = sh_consensus_n >= INTRADAY_CONSENSUS_MIN
                logger.info(
                    "pattern_01 funnel %s sector=%s shadow=%s ft=%s L2_consensus=%d/%d "
                    "(≥%.0f%%) coverage=%.2f decision=%s",
                    trade_date, sec_name, shadow.ts_code, shadow.first_time,
                    sh_consensus_n, INTRADAY_CONSENSUS_MIN, INTRADAY_CONSENSUS_PCT_L2,
                    sh_coverage, "L2_pass" if sh_pass else "L2_skip_no_consensus",
                )
                if not sh_pass:
                    continue

                # L2 影子龙正股 — 入场用 entry_trigger（封板前夕能买到的价格）
                l2_entry_time, l2_entry_close = await find_entry_trigger(
                    session, trade_date, shadow.ts_code, codes, shadow.first_time
                )
                logger.info(
                    "pattern_01 funnel %s sector=%s shadow=%s entry=%s (vs first=%s) "
                    "entry_close=%s",
                    trade_date, sec_name, shadow.ts_code, l2_entry_time, shadow.first_time,
                    f"{l2_entry_close:.2f}" if l2_entry_close else "None",
                )
                if not is_emerging:
                    # 萌芽主线只发 L_CB（正股风险大），L2 正股仅在常规主线发
                    signals.append(PatternSignal(
                        **{**base, "sector_size": sh_consensus_n},
                        pick_code=shadow.ts_code,
                        pick_name=shadow.name,
                        pick_role="shadow",
                        pick_tag=shadow.tag or f"{shadow.limit_times}板",
                        reason=(
                            f"龙头隔夜 L2共识{sh_consensus_n}只≥{INTRADAY_CONSENSUS_PCT_L2:.0f}% "
                            f"影子龙首封{shadow.first_time[:2]}:{shadow.first_time[2:4]} "
                            f"触发{l2_entry_time[:2]}:{l2_entry_time[2:4]} "
                            f"[L2 影子龙正股 上车窗口{window_tag}]"
                        ),
                        pick_kind="stock",
                        buy_anchor="intraday_at",
                        buy_anchor_time=l2_entry_time,
                    ))

                # ── L_CB 影子龙债 ──
                # 买点：与 L1 同步在龙1 first_time（债流动性好能买到）
                # 卖点：影子龙 first_time 那分钟评估升级条件
                #   - 升级（板块涨停 ≥ 3 + 炸板 ≤ 1）→ 持有到 T+1 09:30
                #   - 不升级（默认）→ T+0 影子龙 first_time 立即卖（情况 2 兜底）
                cb_code = await find_cb_for_stock(session, shadow.ts_code, trade_date)
                if cb_code:
                    # 萌芽主线最早 09:45 才能识别，所以买点/升级判定都不能早于 09:45
                    if is_emerging:
                        cb_buy_time = EMERGING_CUTOFF_TIME
                        cb_eval_time = EMERGING_CUTOFF_TIME
                    else:
                        cb_buy_time = l1_entry_time
                        cb_eval_time = shadow.first_time

                    sec_limit_n, sec_broken_n = await count_sector_limit_state(
                        session, trade_date, codes, cb_eval_time
                    )
                    upgrade_overnight = (
                        sec_limit_n >= L_CB_OVERNIGHT_LIMIT_MIN
                        and sec_broken_n <= L_CB_OVERNIGHT_OPEN_MAX
                    )
                    logger.info(
                        "pattern_01 funnel %s sector=%s L_CB eval=%s "
                        "limits=%d/%d broken=%d/%d decision=%s",
                        trade_date, sec_name, cb_eval_time,
                        sec_limit_n, L_CB_OVERNIGHT_LIMIT_MIN,
                        sec_broken_n, L_CB_OVERNIGHT_OPEN_MAX,
                        "L_CB_overnight" if upgrade_overnight else "L_CB_T0",
                    )
                    role_prefix = "萌芽-" if is_emerging else ""
                    if upgrade_overnight:
                        sell_anchor_kw = {"sell_anchor": "next_open"}
                        cb_tag = f"[L_CB {role_prefix}影子龙债 升级隔夜]"
                    else:
                        sell_anchor_kw = {
                            "sell_anchor": "intraday_at",
                            "sell_anchor_time": cb_eval_time,
                        }
                        cb_tag = f"[L_CB {role_prefix}影子龙债 T+0 出]"
                    cb_base = {**base, "sector_size": sh_consensus_n}
                    cb_base.pop("sell_anchor", None)
                    signals.append(PatternSignal(
                        **cb_base,
                        pick_code=cb_code,
                        pick_name=f"{shadow.name}转债",
                        pick_role="shadow_cb",
                        pick_tag=shadow.tag or f"{shadow.limit_times}板",
                        reason=(
                            f"龙头隔夜 板块涨停{sec_limit_n}只 炸板{sec_broken_n}只 "
                            f"买{cb_buy_time[:2]}:{cb_buy_time[2:4]} {cb_tag}"
                        ),
                        pick_kind="cb",
                        underlying_code=shadow.ts_code,
                        buy_anchor="intraday_at",
                        buy_anchor_time=cb_buy_time,
                        **sell_anchor_kw,
                    ))
        return signals
