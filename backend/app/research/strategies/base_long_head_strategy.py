"""龙头隔夜策略基类 — IStrategy 子类，事中扫描走 streaming 主循环。

设计目标（阶段 1）：
    回测和模拟盘走同一条 on_bar 主循环 — 永远不会发散。

生命周期：
    1. warm_up(session, trade_date)  — async，盘前一次性预拉【静态】数据：
       板块名单 / 萌芽候选 / T-1 一字票 / T-1 板数 / MA5 / 流通市值 / 涨停价 /
       候选 CB 映射 / CB 全天分钟 close（回测/streaming 都从这里查）
    2. on_init(ctx)                   — 初始化运行时状态（sector_state, cb_holdings,
       streaming 索引 _quotes/_minutes_by_code/_close_cumsum_by_code/_first_limit_minute）
    3. on_bar(bar_date, bars)         — 每个分钟边界调一次：
       a. _ingest_bars            BarData → MinuteQuote，增量更新索引
       b. _on_open(open_minute)   只在 09:30 这根调一次：B/D 规则
       c. _scan_minute(minute_dt) 子类实现：扫板块 L1/L2 → 返回 PatternSignal
       d. _update_cb_holdings     共享：A/B/C/D 升级隔夜状态机
       e. _handle_rebuy           共享：板块新增涨停 → 买回，返回新 PatternSignal
       f. _finalize_cb_holdings   只在 15:00 这根调一次：未 evaluated 的 fallback
       g. _to_signal              过滤 buy_anchor="skip"，转换 PatternSignal → Signal
    4. find_signals(session, trade_date) — 回测 thin wrapper：
       warm_up → on_init → 按分钟循环 on_bar → 收集 self._pattern_signals 返回

子类要实现的方法：
    _scan_minute(minute_dt) -> list[PatternSignal]
        扫一分钟内板块 L1/L2，返回新增的 PatternSignal（rebuy 不在这里发）
    _on_open(open_minute)   -> None  （可选 override，默认只跑 D 规则）
        Pattern01 加 B 规则（开盘一字开作废板块）
        Pattern02 D 规则即可
"""
from __future__ import annotations

import logging
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.research.data.cb_resolver import find_cb_for_stock
from app.research.signals.long_head_detector import (
    MinuteQuote,
    QuoteMap,
    compute_vwap_until,
    count_codes_above_pct_intraday,
    count_sector_limit_state_intraday,
    detect_emerging_sectors,
    fetch_industries,
    fetch_stock_meta,
    fetch_t1_solid_one_word_limits,
    iter_trading_minutes,
)
from app.research.strategies.base_pattern import PatternSignal, load_sectors
from app.shared.interfaces.models import (
    BacktestConfig,
    BacktestContext,
    BarData,
    Signal,
)
from app.shared.interfaces.strategy import IStrategy
from app.shared.interfaces.types import OrderSide, OrderType

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# 从 pattern_01_params 读 — 共享同一份预设
from app.research.strategies.pattern_01_params import ACTIVE as _P

INTRADAY_CONSENSUS_MIN_L1 = _P["INTRADAY_CONSENSUS_MIN_L1"]
INTRADAY_CONSENSUS_MIN_L1_EMERGING = _P["INTRADAY_CONSENSUS_MIN_L1_EMERGING"]
INTRADAY_CONSENSUS_MIN_L2 = _P["INTRADAY_CONSENSUS_MIN_L2"]
INTRADAY_CONSENSUS_PCT_L1 = _P["INTRADAY_CONSENSUS_PCT_L1"]
INTRADAY_CONSENSUS_PCT_L2 = _P["INTRADAY_CONSENSUS_PCT_L2"]
SELF_TRIGGER_RATIO = _P["SELF_TRIGGER_RATIO"]

L_CB_OVERNIGHT_LIMIT_MIN = _P["L_CB_OVERNIGHT_LIMIT_MIN"]
L_CB_OVERNIGHT_OPEN_MAX = _P["L_CB_OVERNIGHT_OPEN_MAX"]
L_CB_RECHECK_BROKEN_MAX = _P["L_CB_RECHECK_BROKEN_MAX"]
L_CB_EVAL_WINDOW_MIN = _P["L_CB_EVAL_WINDOW_MIN"]

L_CB_REBUY_MAX_TIMES = _P["L_CB_REBUY_MAX_TIMES"]
L_CB_REBUY_NEW_LIMITS_MIN = _P["L_CB_REBUY_NEW_LIMITS_MIN"]
L_CB_REBUY_PRICE_RATIO = _P["L_CB_REBUY_PRICE_RATIO"]
L_CB_REBUY_MIN_GAP_MIN = _P["L_CB_REBUY_MIN_GAP_MIN"]
L_CB_REBUY_DEADLINE = _P["L_CB_REBUY_DEADLINE"]
L_CB_REBUY_FIXED_STOP_RATIO = _P["L_CB_REBUY_FIXED_STOP_RATIO"]

L1_MA5_DEVIATION_MAX = _P["L1_MA5_DEVIATION_MAX"]
L1_MA5_DEVIATION_LARGE_MV = _P["L1_MA5_DEVIATION_LARGE_MV"]
L1_LARGE_MV_THRESHOLD_YI = _P["L1_LARGE_MV_THRESHOLD_YI"]
L2_MA5_DEVIATION_MAX = _P["L2_MA5_DEVIATION_MAX"]

EMERGING_CUTOFF = _P["EMERGING_CUTOFF"]
EMERGING_MIN_COUNT = _P["EMERGING_MIN_COUNT"]
EMERGING_SECTOR_PREFIX = "(萌芽-"


# ──────────────────────────────────────────────────────────────────────────────
# CB 持仓状态（事中 A/B/C/D 升级 + 买回判定用）
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class _CbHolding:
    """L_CB 持仓状态（事中维护，用于决定 sell_anchor）。"""
    signal: PatternSignal
    underlying: str
    sector: str
    sector_codes: list[str]
    buy_minute: datetime
    ever_limit: bool = False
    evaluated: bool = False
    upgraded: bool = False
    first_limit_minute: datetime | None = None
    last_close_below_vwap: bool = False
    sell_minute: datetime | None = None
    sell_price: float | None = None
    sell_sector_limits: int = 0
    rebuy_count: int = 0
    cb_minute_close: dict = field(default_factory=dict)
    is_rebuy: bool = False
    rebuy_price: float | None = None
    # 通知 on_bar：state machine 刚把这个 hold 切到 sell 分支（intraday_at / today_close），
    # 需要派一个 SELL Signal 给 OMS。on_bar 派完后清回 False。
    # next_open 不走这条路，由 OMS 端的 auto_close_check 在 T+1 触发（lot.sell_anchor
    # 在 BUY 成交时已写入 "next_open"）。
    _needs_sell_emit: bool = False


# ──────────────────────────────────────────────────────────────────────────────
# 时间格式 & sell_anchor 写入
# ──────────────────────────────────────────────────────────────────────────────

def _hhmmss(dt: datetime) -> str:
    return dt.strftime("%H%M%S")


def _hhmm_label(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _set_sell_overnight(hold: _CbHolding, reason: str = "A_overnight") -> None:
    hold.signal.sell_anchor = "next_open"
    hold.signal.sell_anchor_time = None
    hold.signal.sell_reason = reason


def _set_sell_t0(hold: _CbHolding, when: datetime, reason: str = "") -> None:
    hold.signal.sell_anchor = "intraday_at"
    hold.signal.sell_anchor_time = _hhmmss(when)
    if reason:
        hold.signal.sell_reason = reason
    hold.sell_minute = when
    hold.sell_price = hold.cb_minute_close.get(when)
    hold._needs_sell_emit = True  # type: ignore[attr-defined]


def _set_sell_today_close(hold: _CbHolding, reason: str = "D_today_close") -> None:
    hold.signal.sell_anchor = "today_close"
    hold.signal.sell_anchor_time = None
    hold.signal.sell_reason = reason
    hold._needs_sell_emit = True  # type: ignore[attr-defined]


# ──────────────────────────────────────────────────────────────────────────────
# Pre-T 数据拉取（warm_up 用）
# ──────────────────────────────────────────────────────────────────────────────

async def _fetch_pre_t_circ_mv(
    session: AsyncSession, trade_date: str, codes: list[str],
) -> dict[str, float]:
    if not codes:
        return {}
    rows = (await session.execute(text(
        "WITH t1 AS ("
        "  SELECT cal_date FROM trade_cal "
        "  WHERE cal_date < :td AND is_open=1 "
        "  ORDER BY cal_date DESC LIMIT 1"
        ") "
        "SELECT ts_code, (circ_mv/10000.0)::float AS circ_mv_yi "
        "FROM daily_basic "
        "WHERE trade_date IN (SELECT cal_date FROM t1) "
        "  AND ts_code = ANY(:codes) "
        "  AND circ_mv IS NOT NULL"
    ), {"td": trade_date, "codes": codes})).fetchall()
    return {r[0]: float(r[1]) for r in rows}


async def _fetch_pre_t_ma5(
    session: AsyncSession, trade_date: str, codes: list[str],
) -> dict[str, float]:
    if not codes:
        return {}
    rows = (await session.execute(text(
        "WITH pre_dates AS ("
        "  SELECT cal_date FROM trade_cal "
        "  WHERE cal_date < :td AND is_open=1 "
        "  ORDER BY cal_date DESC LIMIT 5"
        ") "
        "SELECT ts_code, AVG(close)::float AS ma5 "
        "FROM stock_daily "
        "WHERE trade_date IN (SELECT cal_date FROM pre_dates) "
        "  AND ts_code = ANY(:codes) "
        "GROUP BY ts_code "
        "HAVING COUNT(*) = 5"
    ), {"td": trade_date, "codes": codes})).fetchall()
    return {r[0]: float(r[1]) for r in rows}


async def _fetch_cb_minute_close(
    session: AsyncSession, cb_code: str, trade_date: str,
) -> dict:
    st = datetime.strptime(trade_date, "%Y%m%d").replace(hour=9, minute=0)
    et = datetime.strptime(trade_date, "%Y%m%d").replace(hour=15, minute=30)
    rows = (await session.execute(text(
        "SELECT trade_time, close FROM cb_min_kline "
        "WHERE ts_code=:c AND freq='1min' "
        "AND trade_time >= :st AND trade_time <= :et "
        "ORDER BY trade_time"
    ), {"c": cb_code, "st": st, "et": et})).fetchall()
    return {r[0]: float(r[1]) for r in rows if r[1] is not None}


async def _fetch_up_limit_map(
    session: AsyncSession, trade_date: str, codes: list[str],
) -> dict[str, float]:
    """T 日所有候选票的涨停价（含主板 10% / 创业科创 20% / 北交所 30% / ST 5%）。"""
    if not codes:
        return {}
    rows = (await session.execute(text(
        "SELECT ts_code, up_limit FROM stock_limit "
        "WHERE trade_date=:td AND ts_code = ANY(:codes)"
    ), {"td": trade_date, "codes": codes})).fetchall()
    return {r[0]: float(r[1]) for r in rows if r[1] is not None}


async def _prev_trade_date(session: AsyncSession, td: str) -> str | None:
    r = await session.execute(text(
        "SELECT cal_date FROM trade_cal "
        "WHERE cal_date < :d AND is_open=1 "
        "ORDER BY cal_date DESC LIMIT 1"
    ), {"d": td})
    row = r.fetchone()
    return row[0] if row else None


# Pattern02 用：T-1 涨停股 → 板数 dict
import re as _re

_TAG_BOARD_RE = _re.compile(r"(\d+)天(\d+)板")


def _parse_board_from_tag(tag: str | None) -> int:
    if not tag:
        return 1
    if tag == "首板":
        return 1
    m = _TAG_BOARD_RE.match(tag)
    return int(m.group(2)) if m else 1


async def _fetch_t1_limit_up_boards(
    session: AsyncSession, t1_date: str,
) -> dict[str, int]:
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


# ──────────────────────────────────────────────────────────────────────────────
# 基类
# ──────────────────────────────────────────────────────────────────────────────

class BaseLongHeadStrategy(IStrategy):
    """龙头隔夜策略基类（IStrategy 实现）。

    子类必须实现 _scan_minute；可选 override _on_open。
    """
    name: str = ""
    pattern_id: str = ""
    description: str = ""
    sector_min_size: int = 1
    needs_predictor: bool = False
    default_params: dict = {}

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        # warm_up() 填充
        self.trade_date: str = ""
        self.sectors: dict[str, list[str]] = {}
        self.emerging_codes_by_industry: dict[str, set[str]] = {}
        self.meta: dict[str, dict] = {}
        self.ma5_map: dict[str, float] = {}
        self.circ_mv_map: dict[str, float] = {}
        self.industries: dict[str, str] = {}
        self.t1_one_word: set[str] = set()
        self.t1_boards: dict[str, int] = {}
        self.up_limit_map: dict[str, float] = {}
        self.cb_resolver_cache: dict[str, str] = {}
        self.cb_minute_close_cache: dict[str, dict[datetime, float]] = {}
        self._warmed: bool = False

        # on_init() 填充（运行时状态）
        self.sector_state: dict[str, dict] = {}
        self.emerging_observed: dict[str, set[str]] = {}
        self.emerging_triggered: set[str] = set()
        self.cb_holdings: list[_CbHolding] = []
        self.invalidated: set[str] = set()
        self._quotes: QuoteMap = {}
        self._minutes_by_code: dict[str, list[datetime]] = {}
        self._close_cumsum_by_code: dict[str, list[float]] = {}
        self._first_limit_minute: dict[str, datetime | None] = {}
        self._open_processed: bool = False
        self._finalized: bool = False
        self._pattern_signals: list[PatternSignal] = []
        self._seen_minutes: set[datetime] = set()

    # ──────────────────────────────────────────────────────────────────────
    # 盘前 async 预拉
    # ──────────────────────────────────────────────────────────────────────
    async def warm_up(self, session: AsyncSession, trade_date: str) -> None:
        """盘前一次性预拉静态数据。"""
        self.trade_date = trade_date
        sectors = await load_sectors(session, trade_date)
        if not sectors:
            self._warmed = True
            return
        known_codes = {c for cs in sectors.values() for c in cs}
        emerging_map = await detect_emerging_sectors(
            session, trade_date, known_codes,
            cutoff_hhmmss=EMERGING_CUTOFF, min_count=EMERGING_MIN_COUNT,
        )
        emerging_codes_by_industry = {
            ind: set(codes) for ind, (codes, _) in emerging_map.items()
        }
        for industry, (em_codes, _) in emerging_map.items():
            virtual_name = f"{EMERGING_SECTOR_PREFIX}{industry})"
            sectors[virtual_name] = em_codes
            logger.info(
                "%s emerging candidate %s: %s with %d codes",
                self.pattern_id, trade_date, virtual_name, len(em_codes),
            )

        all_codes = list({c for cs in sectors.values() for c in cs})
        meta = await fetch_stock_meta(session, trade_date, all_codes)
        ma5_map = await _fetch_pre_t_ma5(session, trade_date, all_codes)
        circ_mv_map = await _fetch_pre_t_circ_mv(session, trade_date, all_codes)
        industries = await fetch_industries(session, all_codes)
        up_limit_map = await _fetch_up_limit_map(session, trade_date, all_codes)

        t1_date = await _prev_trade_date(session, trade_date)
        t1_one_word = (
            await fetch_t1_solid_one_word_limits(session, t1_date) if t1_date else set()
        )
        t1_boards = (
            await _fetch_t1_limit_up_boards(session, t1_date) if t1_date else {}
        )

        # 预拉所有候选 stock → CB 映射 + 各 CB 全天分钟 close
        # 回测和 streaming 都从这里查（streaming 也只在盘前 warm_up 一次）
        cb_resolver_cache: dict[str, str] = {}
        for code in all_codes:
            cb = await find_cb_for_stock(session, code, trade_date)
            if cb:
                cb_resolver_cache[code] = cb
        cb_minute_close_cache: dict[str, dict[datetime, float]] = {}
        for cb_code in set(cb_resolver_cache.values()):
            cb_minute_close_cache[cb_code] = await _fetch_cb_minute_close(
                session, cb_code, trade_date,
            )

        self.sectors = sectors
        self.emerging_codes_by_industry = emerging_codes_by_industry
        self.meta = meta
        self.ma5_map = ma5_map
        self.circ_mv_map = circ_mv_map
        self.industries = industries
        self.up_limit_map = up_limit_map
        self.t1_one_word = t1_one_word
        self.t1_boards = t1_boards
        self.cb_resolver_cache = cb_resolver_cache
        self.cb_minute_close_cache = cb_minute_close_cache
        self._warmed = True

        if t1_one_word:
            logger.info(
                "%s funnel %s T-1 严格一字 %d 只",
                self.pattern_id, trade_date, len(t1_one_word),
            )

    # ──────────────────────────────────────────────────────────────────────
    # IStrategy 接口
    # ──────────────────────────────────────────────────────────────────────
    def on_init(self, ctx: BacktestContext) -> None:
        """warm_up 之后调用 — 初始化运行时状态。"""
        self.sector_state = {
            sec: {"l1": None, "l2": None, "l1_excludes": None}
            for sec in self.sectors
        }
        self.emerging_observed = {
            ind: set() for ind in self.emerging_codes_by_industry
        }
        self.emerging_triggered = set()
        self.cb_holdings = []
        self.invalidated = set()
        self._quotes = {}
        self._minutes_by_code = {}
        self._close_cumsum_by_code = {}
        self._first_limit_minute = {}
        self._open_processed = False
        self._finalized = False
        self._pattern_signals = []
        self._seen_minutes = set()

    def on_bar(self, bar_date: str, bars: dict[str, BarData]) -> list[Signal]:
        """每个分钟边界调用一次（同一分钟重复 dispatch 自动幂等）。"""
        if not self._warmed or not self.sectors or not bars:
            return []
        sample = next(iter(bars.values()))
        minute_dt = sample.timestamp.replace(second=0, microsecond=0)
        if minute_dt in self._seen_minutes:
            return []
        self._seen_minutes.add(minute_dt)

        self._ingest_bars(minute_dt, bars)

        open_minute = self._open_minute()
        if minute_dt == open_minute and not self._open_processed:
            self._on_open(open_minute)
            self._open_processed = True

        new_pss: list[PatternSignal] = []
        new_pss.extend(self._scan_minute(minute_dt) or [])

        # 萌芽主线观察（共享）
        self._update_emerging_observed(minute_dt)

        # CB 持仓状态机
        self._update_cb_holdings(minute_dt)

        # 买回判定（返回新 PatternSignal）
        new_pss.extend(self._handle_rebuy(minute_dt))

        # 收盘兜底（14:55 minute — 让 today_close SELL 在 14:56 撮合）
        if minute_dt >= self._finalize_minute() and not self._finalized:
            self._finalize_cb_holdings()
            self._finalized = True

        self._pattern_signals.extend(new_pss)

        # BUY signals — _scan_minute / _handle_rebuy 产出，buy_anchor=skip 过滤
        out_signals: list[Signal] = [
            self._to_signal(ps) for ps in new_pss if ps.buy_anchor != "skip"
        ]

        # SELL signals — state machine 刚切到 sell 分支的 lot（intraday_at / today_close）
        # next_open 不走这条路，由 OMS auto_close_check 在 T+1 触发
        for hold in self.cb_holdings:
            if not getattr(hold, "_needs_sell_emit", False):
                continue
            # 防 race：hold 与 SELL 同分钟创建（如 14:55 finalize 把新触发的 hold 设
            # today_close）→ BUY 还没在 OMS 撮合，pre_trade 拿到 holding=0 会 REJECT
            # SELL。推迟到下一根 bar emit（_needs_sell_emit 保持 True，下次 on_bar
            # 末尾再扫）；BUY 会在下根 bar.open 撮合，那时 lot 已存在。
            if hold.buy_minute == minute_dt:
                continue
            if hold.signal.sell_anchor in ("intraday_at", "today_close"):
                out_signals.append(self._to_sell_signal(hold))
            hold._needs_sell_emit = False

        return out_signals

    # ──────────────────────────────────────────────────────────────────────
    # 子类钩子
    # ──────────────────────────────────────────────────────────────────────
    @abstractmethod
    def _scan_minute(self, minute_dt: datetime) -> list[PatternSignal]:
        """子类扫描这一分钟的板块 L1/L2 触发。"""

    def _on_open(self, open_minute: datetime) -> None:
        """09:30 那根 K 线特殊处理（默认只跑 D 规则）。Pattern01 override 加 B。"""
        self._apply_d_rule(open_minute)

    # ──────────────────────────────────────────────────────────────────────
    # 回测 thin wrapper（保持 find_signals API 不变）
    # ──────────────────────────────────────────────────────────────────────
    async def find_signals(
        self,
        session: AsyncSession,
        trade_date: str,
    ) -> list[PatternSignal]:
        """回测入口：warm_up → on_init → 按分钟循环 on_bar → 收集结果返回。"""
        await self.warm_up(session, trade_date)
        if not self._warmed or not self.sectors:
            logger.info("%s funnel %s: no sectors loaded", self.pattern_id, trade_date)
            return []

        # 拉所有候选股 + 所有 CB 的全天 1min bar，按分钟分组
        all_codes = list({c for cs in self.sectors.values() for c in cs})
        all_cbs = list(set(self.cb_resolver_cache.values()))
        by_minute = await self._fetch_full_day_bars(session, trade_date, all_codes, all_cbs)

        config = BacktestConfig(
            strategy_name=self.name or self.pattern_id,
            start_date=trade_date, end_date=trade_date,
        )
        ctx = BacktestContext(
            config=config, trade_dates=[trade_date], universe_codes=all_codes,
        )
        self.on_init(ctx)

        for minute_dt in iter_trading_minutes(trade_date):
            bars_at = by_minute.get(minute_dt, {})
            self.on_bar(trade_date, bars_at)

        # 防御：若 15:00 那根 bars 为空（数据缺失），on_bar 会 early-return
        # 不触发 _finalize_cb_holdings，这里兜底（与原 find_signals 末尾循环一致）
        if not self._finalized:
            self._finalize_cb_holdings()
            self._finalized = True

        return list(self._pattern_signals)

    def on_stop(self) -> None:
        """Strategy 停止 — 确保未 evaluated 的 CB 持仓走 fallback。"""
        if not self._finalized:
            self._finalize_cb_holdings()
            self._finalized = True

    def get_universe(self) -> list[str]:
        """warm_up 之后可用：返回策略关注的所有 ts_code（股票 + CB）。"""
        if not getattr(self, "_warmed", False):
            return []
        stock_codes = {c for cs in self.sectors.values() for c in cs}
        cb_codes = set(self.cb_resolver_cache.values())
        return sorted(stock_codes | cb_codes)

    async def _fetch_full_day_bars(
        self,
        session: AsyncSession,
        trade_date: str,
        stock_codes: list[str],
        cb_codes: list[str],
    ) -> dict[datetime, dict[str, BarData]]:
        """从 stock_min_kline + cb_min_kline 一次拉全天，按 minute_dt 分组。"""
        by_minute: dict[datetime, dict[str, BarData]] = {}
        open_dt = datetime.strptime(trade_date, "%Y%m%d").replace(hour=9, minute=30)
        close_dt = datetime.strptime(trade_date, "%Y%m%d").replace(hour=15, minute=0)

        if stock_codes:
            rows = (await session.execute(text(
                "SELECT m.ts_code, m.trade_time, m.open, m.high, m.low, m.close, "
                "       m.vol, m.amount, d.pre_close "
                "FROM stock_min_kline m "
                "LEFT JOIN stock_daily d ON d.trade_date=:td AND d.ts_code=m.ts_code "
                "WHERE m.ts_code = ANY(:codes) "
                "  AND m.trade_time >= :open_dt AND m.trade_time <= :close_dt "
                "  AND m.freq='1min'"
            ), {
                "td": trade_date, "codes": stock_codes,
                "open_dt": open_dt, "close_dt": close_dt,
            })).fetchall()
            for ts_code, tt, o, h, l, c, v, amt, pre in rows:
                if c is None:
                    continue
                mt = tt.replace(second=0, microsecond=0)
                bar = BarData(
                    ts_code=ts_code, timestamp=mt,
                    open=float(o) if o is not None else float(c),
                    high=float(h) if h is not None else float(c),
                    low=float(l) if l is not None else float(c),
                    close=float(c),
                    vol=float(v) if v is not None else 0.0,
                    amount=float(amt) if amt is not None else 0.0,
                    pre_close=float(pre) if pre is not None else None,
                    freq="1min",
                )
                by_minute.setdefault(mt, {})[ts_code] = bar

        # CB 1min bar（让 on_bar 知道 CB 价格 — 当前实现走 cb_minute_close_cache，
        # 这里读出来主要给未来扩展用；阶段 1 不影响等价性）
        if cb_codes:
            rows = (await session.execute(text(
                "SELECT m.ts_code, m.trade_time, m.open, m.high, m.low, m.close, "
                "       m.vol, m.amount, cd.pre_close "
                "FROM cb_min_kline m "
                "LEFT JOIN cb_daily cd ON cd.trade_date=:td AND cd.ts_code=m.ts_code "
                "WHERE m.ts_code = ANY(:codes) "
                "  AND m.trade_time >= :open_dt AND m.trade_time <= :close_dt "
                "  AND m.freq='1min'"
            ), {
                "td": trade_date, "codes": cb_codes,
                "open_dt": open_dt, "close_dt": close_dt,
            })).fetchall()
            for ts_code, tt, o, h, l, c, v, amt, pre in rows:
                if c is None:
                    continue
                mt = tt.replace(second=0, microsecond=0)
                bar = BarData(
                    ts_code=ts_code, timestamp=mt,
                    open=float(o) if o is not None else float(c),
                    high=float(h) if h is not None else float(c),
                    low=float(l) if l is not None else float(c),
                    close=float(c),
                    vol=float(v) if v is not None else 0.0,
                    amount=float(amt) if amt is not None else 0.0,
                    pre_close=float(pre) if pre is not None else None,
                    freq="1min",
                )
                by_minute.setdefault(mt, {})[ts_code] = bar

        return by_minute

    # ──────────────────────────────────────────────────────────────────────
    # 内部：BarData → MinuteQuote + 增量索引
    # ──────────────────────────────────────────────────────────────────────
    def _ingest_bars(self, minute_dt: datetime, bars: dict[str, BarData]) -> None:
        """把这一分钟的 bars 转 MinuteQuote 灌进 _quotes 并增量更新索引。"""
        for code, bar in bars.items():
            # 只处理候选股（不处理 CB，CB 价格走 cb_minute_close_cache）
            up_limit = self.up_limit_map.get(code)
            pre = bar.pre_close
            if pre is None or pre <= 0:
                # 没有 pre_close 无法判定，跳过（数据问题）
                continue
            if up_limit is None:
                # 这只票不在候选池（可能是 CB） — 跳过
                continue
            o = bar.open
            c = bar.close
            pct = (c - pre) / pre * 100.0
            is_limit = c >= up_limit - 0.005
            is_limit_at_open = o >= up_limit - 0.005
            q = MinuteQuote(
                open=o, close=c, pre_close=pre, up_limit=up_limit, pct=pct,
                is_limit=is_limit, is_limit_at_open=is_limit_at_open,
            )
            self._quotes[(code, minute_dt)] = q

            # 增量更新索引（bars 按时间顺序进，append 即保证有序）
            lst_min = self._minutes_by_code.setdefault(code, [])
            cum = self._close_cumsum_by_code.setdefault(code, [])
            if lst_min and lst_min[-1] >= minute_dt:
                # 同一分钟重复 ingest（理论上 _seen_minutes 已挡掉），跳过
                continue
            lst_min.append(minute_dt)
            cum.append((cum[-1] if cum else 0.0) + c)
            if is_limit and self._first_limit_minute.get(code) is None:
                self._first_limit_minute[code] = minute_dt

    # ──────────────────────────────────────────────────────────────────────
    # 内部：09:30 时机的 B/D 规则
    # ──────────────────────────────────────────────────────────────────────
    def _open_minute(self) -> datetime:
        return datetime.strptime(self.trade_date, "%Y%m%d").replace(hour=9, minute=30)

    def _close_minute(self) -> datetime:
        return datetime.strptime(self.trade_date, "%Y%m%d").replace(hour=15, minute=0)

    def _finalize_minute(self) -> datetime:
        """L_CB today_close 兜底的触发时刻（14:55，让 SELL 14:56 撮合 ≈ 14:55 close）。"""
        return datetime.strptime(self.trade_date, "%Y%m%d").replace(hour=14, minute=55)

    def _apply_b_rule(self, open_minute: datetime) -> None:
        """B 规则：09:30 板块内任何成员"开盘瞬间"封板 → 板块作废。"""
        for sec_name, codes in self.sectors.items():
            for code in codes:
                q = self._quotes.get((code, open_minute))
                if q and q.is_limit_at_open:
                    self.invalidated.add(sec_name)
                    logger.info(
                        "%s funnel %s sector=%s INVALIDATED: %s 09:30 一字/秒板启动 "
                        "(open=%.2f≥涨停%.2f)",
                        self.pattern_id, self.trade_date, sec_name,
                        code, q.open, q.up_limit,
                    )
                    break

    def _apply_d_rule(self, open_minute: datetime) -> None:
        """D 规则：T-1 一字 + T 日 09:30 未一字开 → 从板块剔除。"""
        if not self.t1_one_word:
            return
        for sec_name in list(self.sectors.keys()):
            original = list(self.sectors[sec_name])
            kept = []
            for code in original:
                if code in self.t1_one_word:
                    q = self._quotes.get((code, open_minute))
                    if q is None or not q.is_limit_at_open:
                        logger.info(
                            "%s funnel %s sector=%s 剔除 %s "
                            "(T-1 一字 + T 日 09:30 未一字开)",
                            self.pattern_id, self.trade_date, sec_name, code,
                        )
                        continue
                kept.append(code)
            self.sectors[sec_name] = kept

    # ──────────────────────────────────────────────────────────────────────
    # 内部：count_state / vwap 速记（用 streaming 索引）
    # ──────────────────────────────────────────────────────────────────────
    def _count_state(self, codes: list[str], minute_dt: datetime) -> tuple[int, int]:
        return count_sector_limit_state_intraday(
            self._quotes, codes, minute_dt,
            first_limit_minute=self._first_limit_minute,
        )

    def _vwap(self, code: str, minute_dt: datetime) -> float | None:
        return compute_vwap_until(
            self._quotes, code, minute_dt,
            minutes_by_code=self._minutes_by_code,
            close_cumsum_by_code=self._close_cumsum_by_code,
        )

    # ──────────────────────────────────────────────────────────────────────
    # 内部：萌芽板块观察（每分钟 tick）
    # ──────────────────────────────────────────────────────────────────────
    def _update_emerging_observed(self, minute_dt: datetime) -> None:
        for industry, em_codes in self.emerging_codes_by_industry.items():
            virtual_name = f"{EMERGING_SECTOR_PREFIX}{industry})"
            if virtual_name in self.invalidated:
                continue
            if virtual_name in self.emerging_triggered:
                continue
            observed = self.emerging_observed[industry]
            for code in em_codes:
                if code in observed:
                    continue
                q = self._quotes.get((code, minute_dt))
                if q and q.is_limit:
                    observed.add(code)
            if len(observed) >= EMERGING_MIN_COUNT:
                self.emerging_triggered.add(virtual_name)
                logger.info(
                    "%s funnel %s emerging triggered: %s observed=%d at %s",
                    self.pattern_id, self.trade_date, virtual_name,
                    len(observed), _hhmm_label(minute_dt),
                )

    # ──────────────────────────────────────────────────────────────────────
    # 内部：CB 持仓状态机（共享 — Pattern01/02 完全一致）
    # ──────────────────────────────────────────────────────────────────────
    def _update_cb_holdings(self, minute_dt: datetime) -> None:
        for hold in self.cb_holdings:
            if hold.evaluated:
                continue
            if minute_dt <= hold.buy_minute:
                continue
            q = self._quotes.get((hold.underlying, minute_dt))
            if q is None:
                continue

            # [1] 止损监控
            if hold.is_rebuy and hold.rebuy_price is not None:
                cb_now = hold.cb_minute_close.get(minute_dt)
                rebuy_stop = hold.rebuy_price * L_CB_REBUY_FIXED_STOP_RATIO
                if cb_now is not None and cb_now < rebuy_stop:
                    sec_lim_at_sell, _ = self._count_state(hold.sector_codes, minute_dt)
                    hold.sell_sector_limits = sec_lim_at_sell
                    logger.info(
                        "%s L_CB rebuy-stoploss-fixed %s sector=%s underlying=%s "
                        "at=%s cb_close=%.2f < 买回价 %.2f × %.2f = %.2f → 固定止损",
                        self.pattern_id, self.trade_date, hold.sector, hold.underlying,
                        _hhmm_label(minute_dt), cb_now,
                        hold.rebuy_price, L_CB_REBUY_FIXED_STOP_RATIO, rebuy_stop,
                    )
                    _set_sell_t0(hold, minute_dt, reason="C_rebuy_fixed_stop")
                    hold.evaluated = True
                    continue
            else:
                vwap = self._vwap(hold.underlying, minute_dt)
                current_below = (vwap is not None and q.close < vwap)
                buffer_cutoff = minute_dt.replace(hour=9, minute=35, second=0)
                use_buffer = minute_dt < buffer_cutoff
                if current_below:
                    if use_buffer and not hold.last_close_below_vwap:
                        logger.info(
                            "%s L_CB vwap-buffer %s sector=%s underlying=%s at=%s "
                            "close=%.2f < vwap=%.2f → 09:35 前缓冲，等下分钟确认",
                            self.pattern_id, self.trade_date, hold.sector,
                            hold.underlying, _hhmm_label(minute_dt), q.close, vwap,
                        )
                    else:
                        reason_label = (
                            "连续 2min 跌破（缓冲生效内）" if use_buffer
                            else "09:35+ 立卖（无缓冲）"
                        )
                        sec_lim_at_sell, _ = self._count_state(hold.sector_codes, minute_dt)
                        hold.sell_sector_limits = sec_lim_at_sell
                        logger.info(
                            "%s L_CB stoploss-vwap %s sector=%s underlying=%s at=%s "
                            "close=%.2f < vwap=%.2f → C 止损（%s, ever_limit=%s, "
                            "板块涨停=%d）",
                            self.pattern_id, self.trade_date, hold.sector,
                            hold.underlying, _hhmm_label(minute_dt), q.close, vwap,
                            reason_label, hold.ever_limit, sec_lim_at_sell,
                        )
                        _set_sell_t0(hold, minute_dt, reason="C_vwap")
                        hold.evaluated = True
                        continue
                hold.last_close_below_vwap = current_below

            # [2] 未封过板
            if not hold.ever_limit:
                if q.is_limit:
                    hold.ever_limit = True
                    hold.first_limit_minute = minute_dt
                    sec_limit_n, sec_broken_n = self._count_state(
                        hold.sector_codes, minute_dt,
                    )
                    if (sec_limit_n >= L_CB_OVERNIGHT_LIMIT_MIN
                            and sec_broken_n <= L_CB_OVERNIGHT_OPEN_MAX):
                        logger.info(
                            "%s L_CB upgrade-immediate %s sector=%s underlying=%s "
                            "at=%s limits=%d broken=%d → A 隔夜（首封即达标）",
                            self.pattern_id, self.trade_date, hold.sector,
                            hold.underlying, _hhmm_label(minute_dt),
                            sec_limit_n, sec_broken_n,
                        )
                        _set_sell_overnight(hold)
                        hold.upgraded = True
                    else:
                        logger.info(
                            "%s L_CB eval-window-start %s sector=%s underlying=%s "
                            "at=%s limits=%d/%d broken=%d/%d → 进入 %dmin 评估窗",
                            self.pattern_id, self.trade_date, hold.sector,
                            hold.underlying, _hhmm_label(minute_dt),
                            sec_limit_n, L_CB_OVERNIGHT_LIMIT_MIN,
                            sec_broken_n, L_CB_OVERNIGHT_OPEN_MAX,
                            L_CB_EVAL_WINDOW_MIN,
                        )
                continue

            # [3] 已升级隔夜 → 复查板块崩
            if hold.upgraded:
                sec_limit_n, sec_broken_n = self._count_state(hold.sector_codes, minute_dt)
                if sec_broken_n >= L_CB_RECHECK_BROKEN_MAX:
                    hold.sell_sector_limits = sec_limit_n
                    logger.info(
                        "%s L_CB recheck-fallback %s sector=%s underlying=%s "
                        "at=%s limits=%d broken=%d≥%d → 回退 T+0",
                        self.pattern_id, self.trade_date, hold.sector,
                        hold.underlying, _hhmm_label(minute_dt),
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
            sec_limit_n, sec_broken_n = self._count_state(hold.sector_codes, minute_dt)
            if (sec_limit_n >= L_CB_OVERNIGHT_LIMIT_MIN
                    and sec_broken_n <= L_CB_OVERNIGHT_OPEN_MAX):
                logger.info(
                    "%s L_CB upgrade-late %s sector=%s underlying=%s "
                    "at=%s limits=%d broken=%d 窗口内+%dmin → A 隔夜",
                    self.pattern_id, self.trade_date, hold.sector,
                    hold.underlying, _hhmm_label(minute_dt), sec_limit_n, sec_broken_n,
                    int(elapsed_sec // 60),
                )
                _set_sell_overnight(hold)
                hold.upgraded = True
                continue
            if not in_window:
                hold.sell_sector_limits = sec_limit_n
                logger.info(
                    "%s L_CB t0-window-timeout %s sector=%s underlying=%s "
                    "at=%s limits=%d/%d broken=%d/%d 窗口超时 → B 立卖",
                    self.pattern_id, self.trade_date, hold.sector,
                    hold.underlying, _hhmm_label(minute_dt),
                    sec_limit_n, L_CB_OVERNIGHT_LIMIT_MIN,
                    sec_broken_n, L_CB_OVERNIGHT_OPEN_MAX,
                )
                _set_sell_t0(hold, minute_dt, reason="B_window_timeout")
                hold.evaluated = True

    # ──────────────────────────────────────────────────────────────────────
    # 内部：买回判定（共享）
    # ──────────────────────────────────────────────────────────────────────
    def _handle_rebuy(self, minute_dt: datetime) -> list[PatternSignal]:
        to_rebuy: list[dict] = []
        cur_hhmmss = _hhmmss(minute_dt)
        for hold in self.cb_holdings:
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
            sec_lim_now, _ = self._count_state(hold.sector_codes, minute_dt)
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

        new_signals: list[PatternSignal] = []
        for r in to_rebuy:
            old = r["hold"]
            cb_code = old.signal.pick_code
            u_name = old.signal.pick_name.replace("转债", "")
            logger.info(
                "%s L_CB rebuy %s sector=%s underlying=%s at=%s "
                "原卖价=%.2f → 买回价=%.2f / 板块涨停 %d→%d (+%d)",
                self.pattern_id, self.trade_date, old.sector, old.underlying,
                _hhmm_label(minute_dt), old.sell_price, r["cb_now_close"],
                old.sell_sector_limits, r["sec_lim_now"], r["new_limits"],
            )
            new_sig = PatternSignal(
                trade_date=self.trade_date,
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
            new_signals.append(new_sig)
            self.cb_holdings.append(_CbHolding(
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
        return new_signals

    # ──────────────────────────────────────────────────────────────────────
    # 内部：14:55 / 15:00 收尾兜底
    # ──────────────────────────────────────────────────────────────────────
    def _finalize_cb_holdings(self) -> None:
        for hold in self.cb_holdings:
            if hold.evaluated:
                continue
            if hold.upgraded:
                logger.info(
                    "%s L_CB confirm-overnight %s sector=%s underlying=%s "
                    "→ 板块未崩，维持 next_open",
                    self.pattern_id, self.trade_date, hold.sector, hold.underlying,
                )
            else:
                logger.info(
                    "%s L_CB default %s sector=%s underlying=%s "
                    "(ever_limit=%s) → today_close",
                    self.pattern_id, self.trade_date, hold.sector, hold.underlying,
                    hold.ever_limit,
                )
                _set_sell_today_close(hold)
            hold.evaluated = True

    # ──────────────────────────────────────────────────────────────────────
    # PatternSignal → Signal
    # ──────────────────────────────────────────────────────────────────────
    def _to_signal(self, ps: PatternSignal) -> Signal:
        return Signal(
            signal_id=uuid4(),
            ts_code=ps.pick_code,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=self._calc_qty(ps),
            reason=ps.reason,
            sell_anchor=ps.sell_anchor,
            sell_anchor_time=ps.sell_anchor_time,
            sell_reason=ps.sell_reason,
            pick_kind=ps.pick_kind,
            pick_role=ps.pick_role,
            buy_anchor=ps.buy_anchor,
            buy_anchor_time=ps.buy_anchor_time,
            underlying_code=ps.underlying_code,
            metadata={
                "sector": ps.sector,
                "long1_code": ps.long1_code,
                "long1_name": ps.long1_name,
                "long1_tag": ps.long1_tag,
                "sector_size": ps.sector_size,
                "pattern": ps.pattern,
            },
        )

    # 单笔目标仓位 ≈ ¥10,000 / price，向下取整到整手（与回测 calc_qty 同口径）
    TARGET_NOTIONAL = 10_000

    def _calc_qty(self, ps: PatternSignal) -> int:
        """与 backtest 的 calc_qty 同口径：单笔目标 ¥10k，向下取整到 lot_size。"""
        is_cb = ps.pick_kind == "cb"
        lot_size = 10 if is_cb else 100
        # entry price 取 _quotes（正股）或 cb_minute_close_cache（CB）的当前分钟 close
        price = self._entry_price(ps)
        if not price or price <= 0:
            return lot_size
        import math
        one_lot_value = price * lot_size
        n_lots = max(1, math.floor(self.TARGET_NOTIONAL / one_lot_value))
        return n_lots * lot_size

    def _entry_price(self, ps: PatternSignal) -> float | None:
        """ps.buy_anchor_time 那一分钟的 close（CB 走 cb_minute_close_cache，正股走 _quotes）。"""
        if not ps.buy_anchor_time:
            return None
        try:
            ts = datetime.strptime(ps.buy_anchor_time, "%H%M%S")
            mt = datetime.strptime(self.trade_date, "%Y%m%d").replace(
                hour=ts.hour, minute=ts.minute, second=0, microsecond=0,
            )
        except ValueError:
            return None
        if ps.pick_kind == "cb":
            cb_closes = self.cb_minute_close_cache.get(ps.pick_code, {})
            return cb_closes.get(mt)
        q = self._quotes.get((ps.pick_code, mt))
        return q.close if q else None

    def _to_sell_signal(self, hold: _CbHolding) -> Signal:
        """state machine 切到 sell 后派一个 SELL Signal 给 OMS（FIFO 卖该 ts_code 的 lot）。"""
        # 计算 qty 与 BUY 相同口径（让 SELL 全量卖出该 lot）
        sell_qty = self._calc_qty(hold.signal)
        return Signal(
            signal_id=uuid4(),
            ts_code=hold.signal.pick_code,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=sell_qty,
            reason=f"sm:{hold.signal.sell_anchor}:{hold.signal.sell_reason}",
            sell_anchor=hold.signal.sell_anchor,
            sell_anchor_time=hold.signal.sell_anchor_time,
            sell_reason=hold.signal.sell_reason,
            pick_kind=hold.signal.pick_kind,
            pick_role=hold.signal.pick_role,
            buy_anchor="state_machine_sell",
            underlying_code=hold.signal.underlying_code,
            metadata={
                "sector": hold.signal.sector,
                "lot_id": "",  # FIFO — OMS 按 entry_date 顺序卖
            },
        )

    # ──────────────────────────────────────────────────────────────────────
    # L1 自然涨停启动触发（Pattern01 主流程 + Pattern02 萌芽板 fallback）
    # 同步实现 — find_cb_for_stock/cb_minute_close 已在 warm_up 预拉
    # ──────────────────────────────────────────────────────────────────────
    def _check_and_trigger_l1(
        self,
        sec_name: str,
        codes: list[str],
        minute_dt: datetime,
        signals: list[PatternSignal],
        is_emerging: bool,
    ) -> tuple[str, datetime] | None:
        """L1 共识 + 自身 ≥9%，触发 L1 信号 + 板块跟风债 L_CB（写入 signals 列表）。"""
        min_required = (
            INTRADAY_CONSENSUS_MIN_L1_EMERGING if is_emerging
            else INTRADAY_CONSENSUS_MIN_L1
        )
        consensus_n = count_codes_above_pct_intraday(
            self._quotes, codes, minute_dt, INTRADAY_CONSENSUS_PCT_L1,
        )
        if consensus_n < min_required:
            return None
        candidates = []
        for cand_code in codes:
            if cand_code in self.t1_one_word:
                continue
            q_cand = self._quotes.get((cand_code, minute_dt))
            if q_cand is None:
                continue
            up_limit_pct_cand = (q_cand.up_limit / q_cand.pre_close - 1) * 100
            self_threshold_cand = up_limit_pct_cand * SELF_TRIGGER_RATIO
            if q_cand.pct < self_threshold_cand:
                continue
            candidates.append((cand_code, q_cand))
        if not candidates:
            return None
        candidates.sort(key=lambda x: (0 if x[1].is_limit else 1, -x[1].pct))
        cand, q = candidates[0]
        logger.info(
            "%s funnel %s sector=%s L1 trigger at=%s code=%s "
            "self_pct=%.2f%% is_limit=%s consensus=%d/%d candidates=%d",
            self.pattern_id, self.trade_date, sec_name, _hhmm_label(minute_dt), cand,
            q.pct, q.is_limit, consensus_n, min_required, len(candidates),
        )
        buy_time_str = _hhmmss(minute_dt)
        l1_meta = self.meta.get(cand, {})
        l1_name = l1_meta.get("name") or cand
        l1_tag = l1_meta.get("tag") or f"{q.pct:.1f}%"
        l1_first_time = l1_meta.get("first_time") or buy_time_str
        l1_open_times = l1_meta.get("open_times", 0)
        base = dict(
            trade_date=self.trade_date,
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
        # L1 偏离度检查
        l1_dev_over = False
        l1_dev = None
        l1_ma5 = self.ma5_map.get(cand)
        cand_mv = self.circ_mv_map.get(cand)
        is_large_mv = (cand_mv is not None and cand_mv >= L1_LARGE_MV_THRESHOLD_YI)
        l1_threshold = L1_MA5_DEVIATION_LARGE_MV if is_large_mv else L1_MA5_DEVIATION_MAX
        if l1_ma5 is not None and l1_ma5 > 0:
            l1_dev = (q.close - l1_ma5) / l1_ma5
            if l1_dev > l1_threshold:
                l1_dev_over = True
                mv_label = (
                    f"大市值{cand_mv:.0f}亿" if is_large_mv
                    else (f"市值{cand_mv:.0f}亿" if cand_mv else "市值未知")
                )
                logger.info(
                    "%s funnel %s sector=%s L1 trigger-but-skip %s at=%s "
                    "close=%.2f ma5=%.2f 偏离%.1f%%>阈值%.1f%%(%s) → 假装触发不买（L_CB 照发）",
                    self.pattern_id, self.trade_date, sec_name, cand,
                    _hhmm_label(minute_dt), q.close, l1_ma5,
                    l1_dev * 100, l1_threshold * 100, mv_label,
                )

        if not is_emerging:
            if l1_dev_over:
                mv_tag = (
                    f"大市值{cand_mv:.0f}亿" if is_large_mv
                    else (f"市值{cand_mv:.0f}亿" if cand_mv else "市值未知")
                )
                signals.append(PatternSignal(
                    **base,
                    pick_code=cand,
                    pick_name=l1_name,
                    pick_role="long1",
                    pick_tag=l1_tag,
                    reason=(
                        f"L1偏离度{l1_dev*100:.1f}%>阈值{l1_threshold*100:.0f}%"
                        f"({mv_tag}) close=¥{q.close:.2f}/MA5=¥{l1_ma5:.2f} "
                        f"触发{_hhmm_label(minute_dt)} [假装触发-放弃买入]"
                    ),
                    pick_kind="stock",
                    buy_anchor="skip",
                    buy_anchor_time=buy_time_str,
                ))
            else:
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

        # L_CB 同步发板块跟风债
        role_prefix = "萌芽-" if is_emerging else ""
        for follower_code in codes:
            if follower_code == cand:
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
                **{**base, "sell_anchor": "next_open"},
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
            self.cb_holdings.append(_CbHolding(
                signal=cb_sig,
                underlying=follower_code,
                sector=sec_name,
                sector_codes=codes,
                buy_minute=minute_dt,
                cb_minute_close=self.cb_minute_close_cache.get(cb_code, {}),
            ))
        return (cand, minute_dt)

    # ──────────────────────────────────────────────────────────────────────
    # L2 触发（共享）
    # ──────────────────────────────────────────────────────────────────────
    def _check_and_trigger_l2(
        self,
        sec_name: str,
        codes: list[str],
        exclude_codes: set[str],
        minute_dt: datetime,
        signals: list[PatternSignal],
    ) -> tuple[str, datetime] | None:
        l1_code = next(iter(exclude_codes))
        consensus_n = count_codes_above_pct_intraday(
            self._quotes, codes, minute_dt, INTRADAY_CONSENSUS_PCT_L2,
        )
        if consensus_n < INTRADAY_CONSENSUS_MIN_L2:
            return None
        candidates = []
        for cand_code in codes:
            if cand_code in exclude_codes or cand_code in self.t1_one_word:
                continue
            q_cand = self._quotes.get((cand_code, minute_dt))
            if q_cand is None:
                continue
            up_limit_pct_cand = (q_cand.up_limit / q_cand.pre_close - 1) * 100
            self_threshold_cand = up_limit_pct_cand * SELF_TRIGGER_RATIO
            if q_cand.pct < self_threshold_cand:
                continue
            candidates.append((cand_code, q_cand))
        if not candidates:
            return None
        candidates.sort(key=lambda x: (0 if x[1].is_limit else 1, -x[1].pct))
        cand, q = candidates[0]
        ma5 = self.ma5_map.get(cand)
        if ma5 is not None and ma5 > 0:
            dev = (q.close - ma5) / ma5
            if dev > L2_MA5_DEVIATION_MAX:
                logger.info(
                    "%s funnel %s sector=%s L2 trigger-but-skip %s at=%s "
                    "close=%.2f ma5=%.2f 偏离%.1f%%>阈值%.1f%% → 假装触发不买",
                    self.pattern_id, self.trade_date, sec_name, cand,
                    _hhmm_label(minute_dt), q.close, ma5,
                    dev * 100, L2_MA5_DEVIATION_MAX * 100,
                )
                buy_time_str = _hhmmss(minute_dt)
                l1_meta_skip = self.meta.get(l1_code, {})
                cand_meta_skip = self.meta.get(cand, {})
                cand_name_skip = cand_meta_skip.get("name") or cand
                cand_tag_skip = cand_meta_skip.get("tag") or f"{q.pct:.1f}%"
                signals.append(PatternSignal(
                    trade_date=self.trade_date,
                    pattern=self.pattern_id,
                    sector=sec_name,
                    long1_code=l1_code,
                    long1_name=l1_meta_skip.get("name") or l1_code,
                    long1_tag=l1_meta_skip.get("tag") or "",
                    long1_first_time=l1_meta_skip.get("first_time") or "",
                    long1_open_times=l1_meta_skip.get("open_times", 0),
                    sector_size=consensus_n,
                    pick_code=cand,
                    pick_name=cand_name_skip,
                    pick_role="shadow",
                    pick_tag=cand_tag_skip,
                    reason=(
                        f"L2偏离度{dev*100:.1f}%>阈值{L2_MA5_DEVIATION_MAX*100:.0f}% "
                        f"close=¥{q.close:.2f}/MA5=¥{ma5:.2f} "
                        f"触发{_hhmm_label(minute_dt)} [假装触发-放弃买入]"
                    ),
                    pick_kind="stock",
                    buy_anchor="skip",
                    buy_anchor_time=buy_time_str,
                    holding="overnight",
                    sell_anchor="next_open",
                ))
                return (cand, minute_dt)
        logger.info(
            "%s funnel sector=%s L2 trigger at=%s code=%s "
            "self_pct=%.2f%% is_limit=%s consensus=%d/%d candidates=%d",
            self.pattern_id, sec_name, _hhmm_label(minute_dt), cand,
            q.pct, q.is_limit, consensus_n, INTRADAY_CONSENSUS_MIN_L2, len(candidates),
        )
        buy_time_str = _hhmmss(minute_dt)
        l1_meta = self.meta.get(l1_code, {})
        cand_meta = self.meta.get(cand, {})
        cand_name = cand_meta.get("name") or cand
        cand_tag = cand_meta.get("tag") or f"{q.pct:.1f}%"
        cand_first = cand_meta.get("first_time") or buy_time_str
        cand_open = cand_meta.get("open_times", 0)
        signals.append(PatternSignal(
            trade_date=self.trade_date,
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
