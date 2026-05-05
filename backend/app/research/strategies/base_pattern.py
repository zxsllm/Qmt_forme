"""12 模式策略公共基类。

每个模式的核心流程：
    1. 给定 T 日 → 取当日板块主线 + 成员（来自 daily_sector_review）
    2. 对每个板块跑 long_head_detector → 龙1 / 影子龙 / 跟风
    3. 模式特定触发条件 → 决定是否买入、买什么
    4. 输出 PatternSignal（含 T+1 计划：开盘卖）

回测口径（简化版，文档化承认的假设）：
    - 买入价：T 日 daily.close（模拟"尾盘低进"，承认涨停封板可能买不到）
    - 卖出价：T+1 日 daily.open（"博次日高开"）
    - 严格的撮合需要分钟级数据 + 涨停封单判断，本回测不做。

依赖：
    - daily_sector_review (source='bankuai' AND scope='daily')  — 板块主线 + 成员
    - limit_stats / limit_step / limit_list_ths                  — 龙头识别
    - stock_daily                                                — 买入/卖出价
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.research.signals.long_head_detector import (
    LimitUpStock,
    LongHeadResult,
    detect_long_head,
)

logger = logging.getLogger(__name__)


@dataclass
class PatternSignal:
    """模式触发信号。"""
    trade_date: str              # T 日（YYYYMMDD）
    pattern: str                 # "pattern_01" 等
    sector: str                  # 主线名
    long1_code: str
    long1_name: str
    long1_tag: str               # "10天8板" / "首板"
    long1_first_time: str
    long1_open_times: int
    sector_size: int             # 板块涨停数
    pick_code: str               # 实际买入标的（pick_kind=stock 时是正股 ts_code，cb 时是 CB ts_code）
    pick_name: str
    pick_role: str               # "long1" / "shadow" / "follower" / "all"
    pick_tag: str
    reason: str = ""
    holding: str = "overnight"

    # 标的类型 + CB 关联
    pick_kind: str = "stock"     # "stock" | "cb"
    underlying_code: str | None = None  # 当 pick_kind="cb" 时记录正股 ts_code（用于显示）

    # 买入锚点（分钟级精确撮合用）
    buy_anchor: str = "today_close"      # "today_close" | "today_open" | "intraday_at"
    buy_anchor_time: str | None = None   # HHMMSS，仅当 buy_anchor="intraday_at"

    # 卖出锚点（分钟级精确撮合用）
    sell_anchor: str = "next_open"      # "next_open" | "today_close" | "intraday_at"
    sell_anchor_time: str | None = None # HHMMSS，仅当 sell_anchor="intraday_at"


@dataclass
class PatternTrade:
    """回测层一笔交易记录（信号 + 实际成交价）。"""
    signal: PatternSignal
    next_date: str               # T+1
    buy_price: float | None      # T 日 close
    sell_price: float | None     # T+1 open
    qty: int = 100
    fee: float = 0.0
    pnl: float = 0.0
    ret_pct: float = 0.0
    skip_reason: str = ""        # 非空表示该笔被跳过


# ---------------------------------------------------------------------------
# 形态判定辅助
# ---------------------------------------------------------------------------

async def fetch_daily_ohlc(
    session: AsyncSession, trade_date: str, ts_codes: list[str] | None = None
) -> dict[str, dict]:
    """拉一批股票当日 OHLC（用于一字判定 + 收盘价）。"""
    if not ts_codes:
        return {}
    rows = (await session.execute(text(
        "SELECT ts_code, open, high, low, close, pre_close "
        "FROM stock_daily WHERE trade_date=:d AND ts_code = ANY(:codes)"
    ), {"d": trade_date, "codes": ts_codes})).fetchall()
    return {
        r[0]: {"open": r[1], "high": r[2], "low": r[3], "close": r[4], "pre_close": r[5]}
        for r in rows
    }


def is_yizi(ohlc: dict | None) -> bool:
    """一字板判定：open == high == low == close 且涨幅接近 +10%。

    严格：open/high/low/close 完全一致；涨幅 ≥ 9.5%（容忍 ST 5% 涨停的话另算）。
    """
    if not ohlc:
        return False
    o, h, l, c = ohlc["open"], ohlc["high"], ohlc["low"], ohlc["close"]
    if o is None or h is None or l is None or c is None:
        return False
    if abs(o - h) > 0.001 or abs(o - l) > 0.001 or abs(o - c) > 0.001:
        return False
    pre = ohlc.get("pre_close") or 0
    if pre <= 0:
        return False
    pct = (c - pre) / pre * 100
    return pct >= 9.5  # 主板 +10%（容差 0.5%）


def is_yizi_down(ohlc: dict | None) -> bool:
    """一字跌停：open == high == low == close 且跌幅 ≤ -9.5%。"""
    if not ohlc:
        return False
    o, h, l, c = ohlc["open"], ohlc["high"], ohlc["low"], ohlc["close"]
    if o is None or h is None or l is None or c is None:
        return False
    if abs(o - h) > 0.001 or abs(o - l) > 0.001 or abs(o - c) > 0.001:
        return False
    pre = ohlc.get("pre_close") or 0
    if pre <= 0:
        return False
    pct = (c - pre) / pre * 100
    return pct <= -9.5


def is_intraday_open_recover(ohlc: dict | None, drop_then_recover_pct: float = 4.0) -> bool:
    """盘中触跌停后被打开 + 修复一定幅度。

    判定：当日最低跌幅 ≤ -9.5%（碰到跌停价附近）且 close 比 low 高 drop_then_recover_pct%。
    """
    if not ohlc:
        return False
    pre = ohlc.get("pre_close") or 0
    o, l, c = ohlc["open"], ohlc["low"], ohlc["close"]
    if pre <= 0 or l is None or c is None:
        return False
    low_pct = (l - pre) / pre * 100
    if low_pct > -9.0:
        return False  # 没碰过跌停区间
    recover = (c - l) / l * 100
    return recover >= drop_then_recover_pct


def is_natural_limit(stock: LimitUpStock, ohlc: dict | None) -> bool:
    """自然涨停判定：盘中封板 = 非一字。

    判定逻辑：first_time > "0930xx"（首封时间不在开盘 ±1 分钟）OR ohlc 显示有日内波动。
    """
    if ohlc and not is_yizi(ohlc):
        return True
    # ohlc 缺失时 fallback 到 first_time
    ft = stock.first_time
    return ft > "093100"


# ---------------------------------------------------------------------------
# 板块加载
# ---------------------------------------------------------------------------

async def load_sectors(
    session: AsyncSession, trade_date: str, source: str = "bankuai"
) -> dict[str, list[str]]:
    """拉当日板块 → 成员映射。默认用板块必读 daily 标签。"""
    if source == "bankuai":
        sql = (
            "SELECT sector_name, array_agg(ts_code ORDER BY board_count DESC) "
            "FROM daily_sector_review "
            "WHERE trade_date=:d AND source='bankuai' "
            "AND raw_meta->>'scope'='daily' "
            "AND sector_name NOT IN ('一季报预增','反弹','公告','其他') "
            "AND ts_code IS NOT NULL "
            "GROUP BY sector_name"
        )
    else:
        sql = (
            "SELECT sector_name, array_agg(ts_code) "
            "FROM daily_sector_review "
            "WHERE trade_date=:d AND source=:s AND ts_code IS NOT NULL "
            "GROUP BY sector_name"
        )
    rows = (await session.execute(text(sql), {"d": trade_date, "s": source})).fetchall()
    return {r[0]: list(r[1]) for r in rows}


# ---------------------------------------------------------------------------
# 基类
# ---------------------------------------------------------------------------

class BasePattern(ABC):
    """所有模式策略的基类。"""
    pattern_id: str = ""
    description: str = ""
    sector_min_size: int = 3      # 板块至少几只涨停才参与
    needs_predictor: bool = False  # 是否需要"龙1次日一字预测"

    async def find_signals(
        self, session: AsyncSession, trade_date: str, source: str = "bankuai"
    ) -> list[PatternSignal]:
        sectors = await load_sectors(session, trade_date, source)
        if not sectors:
            logger.warning("%s %s: no sectors", self.pattern_id, trade_date)
            return []

        signals: list[PatternSignal] = []
        for sec_name, codes in sectors.items():
            lh = await detect_long_head(session, trade_date, codes, sector_name=sec_name)
            if not lh.long1:
                continue
            sector_size = len(lh.long1_group) + (1 if lh.long2 else 0) + len(lh.followers)
            if sector_size < self.sector_min_size:
                continue
            # 拉龙1群组 + 龙2 + 影子龙的 OHLC（一字判定要用）
            check_codes = list({s.ts_code for s in lh.long1_group})
            if lh.long2 and lh.long2.ts_code not in check_codes:
                check_codes.append(lh.long2.ts_code)
            if lh.shadow and lh.shadow.ts_code not in check_codes:
                check_codes.append(lh.shadow.ts_code)
            ohlc_map = await fetch_daily_ohlc(session, trade_date, check_codes)

            # 跑预测器（仅当模式声明需要）
            prediction = None
            if self.needs_predictor:
                from app.research.signals.long1_yizi_predictor import predict_long1_yizi
                prediction = await predict_long1_yizi(session, trade_date, codes, lh)

            sig = await self._check(lh, sector_size, ohlc_map, trade_date, prediction=prediction)
            if sig:
                signals.append(sig)
        return signals

    @abstractmethod
    async def _check(
        self,
        lh: LongHeadResult,
        sector_size: int,
        ohlc_map: dict[str, dict],
        trade_date: str,
        prediction=None,
    ) -> PatternSignal | None:
        """返回触发信号，或 None。

        prediction: YiziPrediction 或 None（仅当 needs_predictor=True 时传入）
        """
