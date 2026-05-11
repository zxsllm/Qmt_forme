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
    sell_reason: str = ""               # 真实卖出分支（"A_overnight" | "B_window_timeout" | "C_vwap" | "D_today_close" | "A_then_recheck_fallback"）


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
    session: AsyncSession,
    trade_date: str,
    lookback_days: int = 5,
) -> dict[str, list[str]]:
    """T 日盘前可知的板块成员名单 = 最近 N 个交易日（≤T-1）三源标签的并集。

    源：bankuai（板块必读，主源） + jiuyan（韭研公社） + llm_v2（LLM 主线判定）。
    板块必读为优先主源，韭研次之，LLM v2 作补充覆盖人工漏标。
    过滤：剔除"一季报预增/反弹/公告/其他"这类基本面属性 / 无主线归类。
    归一：板块名通过 theme_taxonomy.ALIAS_TO_CANONICAL 把同义词收敛到 canonical
         细分主线（"光模块"="光通信模块"、"PCB"="PCB板"="印制电路板"），
         小细分独立保留（光模块/光模块零件/光纤是 3 个不同主线），
         未匹配 alias 的 sector_name 保留原始名（不再压成大筐）。

    N 日滚动并集 = 老主线 T 日仍然抓得到（昨日已识别），新主线 T 日漏掉
    （要等 T+1 进入名单），代价用户接受。

    Raises:
        ValueError: trade_date 非交易日（避免静默退化到错误的 lookback 窗口）
    """
    from app.research.signals.theme_taxonomy import ALIAS_TO_CANONICAL

    is_open = (await session.execute(text(
        "SELECT is_open FROM trade_cal WHERE cal_date=:td"
    ), {"td": trade_date})).scalar()
    if is_open != 1:
        raise ValueError(
            f"load_sectors: trade_date={trade_date} 不是交易日（is_open={is_open}），"
            "拒绝静默退化到 lookback 数据"
        )

    cal_rows = (await session.execute(text(
        "SELECT cal_date FROM trade_cal "
        "WHERE cal_date < :td AND is_open=1 "
        "ORDER BY cal_date DESC LIMIT :n"
    ), {"td": trade_date, "n": lookback_days})).fetchall()
    if not cal_rows:
        return {}
    dates = [r[0] for r in cal_rows]

    rows = (await session.execute(text(
        "SELECT sector_name, ts_code "
        "FROM daily_sector_review "
        "WHERE trade_date = ANY(:dates) "
        "AND source IN ('bankuai','jiuyan','llm_v2') "
        "AND ts_code IS NOT NULL AND ts_code <> '' "
        "AND sector_name NOT IN ('一季报预增','反弹','公告','其他')"
    ), {"dates": dates})).fetchall()

    # 多源 / 多日 / 同义词合并到 canonical 细分主线，按 (sector, ts_code) 去重
    merged: dict[str, set[str]] = {}
    for sec_name, ts_code in rows:
        canonical = ALIAS_TO_CANONICAL.get(sec_name, sec_name)
        merged.setdefault(canonical, set()).add(ts_code)
    return {sec: sorted(codes) for sec, codes in merged.items()}


# ---------------------------------------------------------------------------
# 基类
# ---------------------------------------------------------------------------

class BasePattern(ABC):
    """模式策略基类 — 子类必须自己实现 find_signals。

    基类只提供：
    - 类属性（pattern_id / description / 等）
    - 可复用辅助函数（load_sectors / detect_long_head / fetch_daily_ohlc / is_natural_limit / is_yizi 等）
    都在本模块内 import 即用。
    """
    pattern_id: str = ""
    description: str = ""
    sector_min_size: int = 1
    needs_predictor: bool = False

    @abstractmethod
    async def find_signals(
        self, session: AsyncSession, trade_date: str
    ) -> list[PatternSignal]:
        """返回 T 日触发的信号列表。"""
