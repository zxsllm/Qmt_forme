"""龙1 / 影子龙 / 跟风识别 v5 — 当日口径，炸板也算上板。

排序键（当日口径）：
    1. 首封时间正序（最早封最强 — 不管炸不炸都算上板了）
    2. 当日炸板次数升序（同时间封板时不炸优先 — tie-breaker）
    3. 累计板数倒序（同 first_time 同 open_times 时板高优先）

龙1 判定：
    - 板块内 first_time 最早的就是当日龙1
    - 炸过板的也算（先封板了，回封说明资金护盘）

影子龙判定（v5 修正 — 老师课件原意）：
    - **影子龙 = 板块第二只封板的票（即 long2）**，不再硬卡 15min
    - 老师"15分钟"原文（docs/100_AI课件.md:113 + 视频 870/1060 行）
      指的是"散户低进影子龙的上车窗口"，不是"判定窗口"
    - 是否在 15min 上车窗口内 → result.shadow_within_15min（事中实操参考）
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"(\d+)天(\d+)板")
_SHADOW_WINDOW_MINUTES = 15


def _parse_board_count(tag: str | None, fallback: int) -> int:
    """从 limit_list_ths.tag 解析累计板数。"""
    if not tag:
        return fallback
    if tag == "首板":
        return 1
    m = _TAG_RE.match(tag)
    if m:
        return int(m.group(2))
    return fallback


def _parse_time(t) -> str:
    """统一为 HHMMSS 6 位字符串，兼容 datetime.time / 字符串 / None。"""
    if t is None or t == "":
        return "999999"
    if hasattr(t, "strftime"):
        return t.strftime("%H%M%S")
    s = str(t).replace(":", "").strip()
    return s.zfill(6) if len(s) <= 6 else s[:6]


def _add_minutes(hhmmss: str, minutes: int) -> str:
    h, m, s = int(hhmmss[:2]), int(hhmmss[2:4]), int(hhmmss[4:6])
    total = h * 3600 + m * 60 + s + minutes * 60
    h2, m2, s2 = total // 3600, (total % 3600) // 60, total % 60
    return f"{h2:02d}{m2:02d}{s2:02d}"


def _is_yizi_open(s: "LimitUpStock") -> bool:
    """一字开盘简化判定：09:30 ± 1 分钟内首封 + 没炸板。
    严格 OHLC 全等判定在 base_pattern.is_yizi 里，detector 里轻量判定。"""
    return s.first_time <= "093100" and s.open_times == 0


@dataclass
class LimitUpStock:
    ts_code: str
    name: str
    first_time: str  # "HHMMSS"
    last_time: str
    limit_times: int  # 累计板数（"X天Y板"的 Y）
    consec_days: int
    open_times: int
    tag: str | None
    limit_amount: float | None
    float_mv: float | None
    amount: float | None


@dataclass
class LongHeadResult:
    sector: str
    long1: LimitUpStock | None = None
    long1_group: list[LimitUpStock] = field(default_factory=list)  # 多龙1（一字群组）
    long2: LimitUpStock | None = None
    shadow: LimitUpStock | None = None  # = long2（最强跟风），不再卡 15min
    shadow_within_15min: bool = False    # 事中实操参考：影子龙是否在上车窗口内
    followers: list[LimitUpStock] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


async def detect_long_head(
    session: AsyncSession,
    trade_date: str,
    sector_stocks: list[str],
    sector_name: str = "",
) -> LongHeadResult:
    if not sector_stocks:
        return LongHeadResult(sector=sector_name, notes=["empty sector"])

    rows = (await session.execute(text(
        "SELECT ls.ts_code, ls.name, ls.first_time, ls.last_time, "
        "       COALESCE(lst.nums, 1) AS consec, "
        "       COALESCE(ls.limit_times, 1) AS lt, "
        "       COALESCE(ls.open_times, 0) AS ot, "
        "       lt.tag AS ths_tag, "
        "       ls.limit_amount, ls.float_mv, ls.amount "
        "FROM limit_stats ls "
        "LEFT JOIN limit_step lst ON lst.trade_date=ls.trade_date AND lst.ts_code=ls.ts_code "
        "LEFT JOIN limit_list_ths lt ON lt.trade_date=ls.trade_date AND lt.ts_code=ls.ts_code "
        "       AND lt.limit_type='涨停池' "
        "WHERE ls.trade_date=:d AND ls.\"limit\"='U' AND ls.ts_code = ANY(:codes)"
    ), {"d": trade_date, "codes": sector_stocks})).fetchall()

    stocks: list[LimitUpStock] = []
    skipped_null_ft = 0
    for r in rows:
        ts_code, name, ft, lt_, consec, lt_times, ot, ths_tag, lamt, fmv, amt = r
        # first_time 为 NULL 的票直接跳过（数据问题，不当龙1，避免后续静默丢信号）
        if ft is None or ft == "":
            skipped_null_ft += 1
            continue
        # 板数优先取 ths_tag 解析（"X天Y板"的 Y），缺失时退回 lt_times。
        # 不和 consec 取 max — consec 可能是连板天数（X），与板数(Y) 口径不一致。
        board_count = _parse_board_count(ths_tag, fallback=int(lt_times))
        stocks.append(LimitUpStock(
            ts_code=ts_code, name=(name or "").replace(" ", ""),
            first_time=_parse_time(ft), last_time=_parse_time(lt_),
            limit_times=board_count, consec_days=int(consec),
            open_times=int(ot), tag=ths_tag,
            limit_amount=lamt, float_mv=fmv, amount=amt,
        ))

    if not stocks:
        notes = ["no limit-up in this sector"]
        if skipped_null_ft:
            notes.append(f"skipped {skipped_null_ft} stocks with NULL first_time")
        return LongHeadResult(sector=sector_name, notes=notes)

    # v4 当日口径：纯按 first_time 排（炸板了也算上板）
    stocks.sort(key=lambda s: (s.first_time, s.open_times, -s.limit_times))

    result = LongHeadResult(sector=sector_name)
    result.long1 = stocks[0]
    result.long1_group = [stocks[0]]  # 退化（多只一字识别要 OHLC，调用方做）

    long1_codes = {s.ts_code for s in result.long1_group}

    # 龙2：当日第二只封板（不在龙1群组内），按当日排序键的第一只
    non_long1 = [s for s in stocks if s.ts_code not in long1_codes]
    if non_long1:
        result.long2 = non_long1[0]

    # 影子龙 = long2（最强跟风=板块第二只封板，老师课件原意）
    # shadow_within_15min: 是否在 15min 上车窗口内（事中实操标记）
    if result.long2:
        result.shadow = result.long2
        long1_ft = result.long1.first_time
        window_end = _add_minutes(long1_ft, _SHADOW_WINDOW_MINUTES)
        result.shadow_within_15min = (
            result.long2.first_time > long1_ft
            and result.long2.first_time <= window_end
        )

    # 跟风：去掉龙1群组 + 龙2
    exclude = set(long1_codes)
    if result.long2:
        exclude.add(result.long2.ts_code)
    result.followers = [s for s in stocks if s.ts_code not in exclude]

    return result


def _hhmmss_to_dt(td: str, hhmmss: str) -> datetime | None:
    if not td or not hhmmss:
        return None
    s = hhmmss.zfill(6)[:6]
    try:
        return datetime.strptime(td + s, "%Y%m%d%H%M%S")
    except ValueError:
        return None


async def detect_emerging_sectors(
    session: AsyncSession,
    trade_date: str,
    known_codes: set[str],
    cutoff_hhmmss: str = "113000",
    min_count: int = 3,
) -> dict[str, tuple[list[str], str]]:
    """T 日盘中萌芽主线探测（按 stock_basic.industry 分组，严格事中可见）。

    判定逻辑：
        - T 日 first_time <= cutoff（默认 11:30 = 早盘结束）的涨停股
        - 剔除已在 known_codes（T-1 lookback 三源并集）的票
        - 按 stock_basic.industry 分组
        - 同一行业 >= min_count（默认 3）只 → 视为萌芽主线候选

    用 industry（中信行业）回避 concept_detail 覆盖不全的问题（用户原话"游
    资新题材或壳概念漏光"）。industry 粗糙但确定可用，足以把"杂鱼涨停股"
    与"行业内同步爆发"区分开。

    返回 {industry: (ts_codes, identification_hhmmss)}：
        - ts_codes 按 first_time 升序
        - identification_hhmmss = 第 min_count 只票的 first_time（即该行业满足
          ≥3 只条件的最早时刻），上层用作 L_CB 最早买点（事中可执行）
    """
    if not cutoff_hhmmss or len(cutoff_hhmmss) < 6:
        return {}
    cutoff_str = cutoff_hhmmss.zfill(6)

    rows = (await session.execute(text(
        "SELECT ls.ts_code, sb.industry, LPAD(ls.first_time, 6, '0') AS ft "
        "FROM limit_stats ls "
        "LEFT JOIN stock_basic sb ON sb.ts_code = ls.ts_code "
        "WHERE ls.trade_date=:td AND ls.\"limit\"='U' "
        "  AND ls.first_time IS NOT NULL "
        "  AND LPAD(ls.first_time, 6, '0') <= :cutoff "
        "ORDER BY LPAD(ls.first_time, 6, '0')"
    ), {"td": trade_date, "cutoff": cutoff_str})).fetchall()

    by_industry: dict[str, list[tuple[str, str]]] = {}
    for ts_code, industry, ft in rows:
        if not industry or ts_code in known_codes:
            continue
        by_industry.setdefault(industry, []).append((ts_code, ft))

    out: dict[str, tuple[list[str], str]] = {}
    for industry, items in by_industry.items():
        if len(items) < min_count:
            continue
        codes = [c for c, _ in items]
        # 第 min_count 只票封板的时刻 = 该行业达成共识的最早时刻
        identification_time = items[min_count - 1][1]
        out[industry] = (codes, identification_time)
    return out


async def count_sector_limit_state(
    session: AsyncSession,
    trade_date: str,
    sector_codes: list[str],
    at_hhmmss: str,
) -> tuple[int, int]:
    """截至 at_hhmmss 那一刻，板块内（已封板的票数, 已炸板的票数）。

    用于 L_CB 升级隔夜判定：
        - limit_count >= 3（板块涨停数共识）
        - broken_count <= 1（板块没大面积炸板）
        → 持有 L_CB 到 T+1 09:30；否则 T+0 立即卖

    判定口径（事中可见简化）：
        - 已封板数 = limit_stats 中 first_time <= at_hhmmss 的票数
        - 已炸板数 = first_time <= at_hhmmss AND open_times > 0 的票数
          （open_times 是当日累计字段，存在轻微未来函数风险——后续撮合层用
           分钟线精化）
    """
    if not sector_codes or not at_hhmmss or len(at_hhmmss) < 6:
        return 0, 0
    # limit_stats.first_time 是 character varying，可能存为 "92500"（缺前导 0），
    # 字符串字典序会错 ("92500" > "094500")，先 LPAD 到 6 位再比较
    ft_str = at_hhmmss.zfill(6)

    row = (await session.execute(text(
        "SELECT "
        "  COUNT(*) AS limit_count, "
        "  SUM(CASE WHEN COALESCE(open_times, 0) > 0 THEN 1 ELSE 0 END) AS broken_count "
        "FROM limit_stats "
        "WHERE trade_date = :td "
        "  AND ts_code = ANY(:codes) "
        "  AND \"limit\" = 'U' "
        "  AND first_time IS NOT NULL "
        "  AND LPAD(first_time, 6, '0') <= :ft"
    ), {"td": trade_date, "codes": sector_codes, "ft": ft_str})).fetchone()
    if not row:
        return 0, 0
    return int(row[0] or 0), int(row[1] or 0)


async def count_near_limit_at_minute(
    session: AsyncSession,
    trade_date: str,
    sector_codes: list[str],
    at_hhmmss: str,
    threshold_pct: float = 9.0,
) -> tuple[int, list[tuple[str, float]], float]:
    """事中共识代理：T 日 at_hhmmss 那一分钟，板块成员中涨幅 ≥ threshold_pct% 的票数。

    实现（严格匹配，杜绝未来函数）：
    - 取 trade_time ∈ [target, target + 1min]（容忍那一分钟缺数据时取下一分钟，但绝不
      回填后续行情，避免"看到 14:30 的拉升当 10:00 共识"）
    - join stock_daily.pre_close 算涨幅 = (close - pre_close) / pre_close * 100

    返回 (count, [(ts_code, pct), ...], coverage)。
        coverage = 实际查到分钟线的票数 / 板块成员数（0~1）
        coverage < 0.3 时 logger.warning 警告（数据不全 vs 真没共识 区分）
    """
    if not sector_codes or not at_hhmmss:
        return 0, [], 0.0
    target = _hhmmss_to_dt(trade_date, at_hhmmss)
    if not target:
        return 0, [], 0.0
    target_plus_1min = target.replace(second=0) + timedelta(minutes=1)

    rows = (await session.execute(text(
        "SELECT m.ts_code, m.close, d.pre_close FROM ("
        "  SELECT DISTINCT ON (ts_code) ts_code, close "
        "  FROM stock_min_kline "
        "  WHERE ts_code = ANY(:codes) "
        "    AND trade_time >= :target AND trade_time <= :upper "
        "    AND freq = '1min' "
        "  ORDER BY ts_code, trade_time"
        ") m "
        "LEFT JOIN stock_daily d ON d.trade_date=:td AND d.ts_code=m.ts_code"
    ), {"codes": sector_codes, "target": target, "upper": target_plus_1min,
        "td": trade_date})).fetchall()

    matched = 0
    detail: list[tuple[str, float]] = []
    for ts_code, close, pre_close in rows:
        if not pre_close or pre_close <= 0 or close is None:
            continue
        matched += 1
        pct = (float(close) - float(pre_close)) / float(pre_close) * 100.0
        if pct >= threshold_pct:
            detail.append((ts_code, pct))
    detail.sort(key=lambda x: -x[1])

    coverage = matched / len(sector_codes) if sector_codes else 0.0
    if coverage < 0.3:
        logger.warning(
            "count_near_limit coverage low: %s @ %s — matched %d/%d (%.1f%%) "
            "consensus result may be unreliable",
            trade_date, at_hhmmss, matched, len(sector_codes), coverage * 100,
        )
    return len(detail), detail, coverage


def _fmt_tag(s: LimitUpStock) -> str:
    if s.tag and s.tag != "首板":
        return s.tag
    return f"{s.limit_times}板"


def format_result(r: LongHeadResult) -> str:
    lines = [f"=== 板块「{r.sector}」龙头识别 ==="]
    if r.long1_group and len(r.long1_group) > 1:
        lines.append(f"  龙1群组（{len(r.long1_group)} 只一字）:")
        for s in r.long1_group:
            star = "★" if s is r.long1 else " "
            lines.append(f"    {star} {s.ts_code} {s.name} | {_fmt_tag(s)} "
                         f"| first={s.first_time[:4]} | 开板{s.open_times}次")
    elif r.long1:
        s = r.long1
        lines.append(f"  龙1: {s.ts_code} {s.name} | {_fmt_tag(s)} | first={s.first_time[:4]} "
                     f"| 开板{s.open_times}次 | 流通{(s.float_mv or 0)/1e8:.1f}亿")
    if r.shadow:
        s = r.shadow
        lines.append(f"  影子龙: {s.ts_code} {s.name} | {_fmt_tag(s)} | first={s.first_time[:4]} "
                     f"(龙1后 {_SHADOW_WINDOW_MINUTES}min 内首封)")
    if r.long2 and (not r.shadow or r.long2.ts_code != r.shadow.ts_code):
        s = r.long2
        lines.append(f"  龙2: {s.ts_code} {s.name} | {_fmt_tag(s)} | first={s.first_time[:4]}")
    for s in r.followers[:5]:
        lines.append(f"  跟风: {s.ts_code} {s.name} | {_fmt_tag(s)} | first={s.first_time[:4]}")
    if len(r.followers) > 5:
        lines.append(f"  ... 还有 {len(r.followers) - 5} 只跟风")
    for note in r.notes:
        lines.append(f"  ℹ {note}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# 严格事中扫描工具函数（v6 模拟盘对齐）
#
# 用途：模拟盘里 rt_k 每秒推 1min K 线到内存；回测时一次预拉所有需要的分钟
# 数据到内存替代流式推送。两套数据源、同一套事中扫描算法（不偷看未来）。
# ═══════════════════════════════════════════════════════════════════════════


# 一根分钟线的精简快照
@dataclass
class MinuteQuote:
    close: float
    pre_close: float
    pct: float          # 涨幅 %
    is_limit: bool      # close >= pre × 1.099 即视为已封板


# (ts_code, minute_dt) -> MinuteQuote
QuoteMap = dict[tuple[str, datetime], MinuteQuote]


def iter_trading_minutes(trade_date: str) -> list[datetime]:
    """生成 T 日 A 股交易分钟时间戳序列。

    上午 09:30 ~ 11:30 共 121 根（含 11:30 收盘那根）
    下午 13:00 ~ 15:00 共 121 根
    去重后返回 datetime 列表。

    回测时按这个序列驱动主循环；模拟盘里 rt_k 推送的时间戳会落在这个集合内。
    """
    base = datetime.strptime(trade_date, "%Y%m%d")
    minutes: list[datetime] = []
    # 上午
    cur = base.replace(hour=9, minute=30)
    end_am = base.replace(hour=11, minute=30)
    while cur <= end_am:
        minutes.append(cur)
        cur += timedelta(minutes=1)
    # 下午
    cur = base.replace(hour=13, minute=0)
    end_pm = base.replace(hour=15, minute=0)
    while cur <= end_pm:
        minutes.append(cur)
        cur += timedelta(minutes=1)
    return minutes


async def fetch_minute_quotes(
    session: AsyncSession,
    trade_date: str,
    ts_codes: list[str],
) -> QuoteMap:
    """一次性预拉一批票全天 1min 行情 + pre_close → 事中扫描查询用。

    回测专用，模拟盘不需要（rt_k 流式推送）。
    扫描结束后调用方应 quote_map.clear() 释放内存。
    """
    if not ts_codes:
        return {}
    rows = (await session.execute(text(
        "SELECT m.ts_code, m.trade_time, m.close, d.pre_close "
        "FROM stock_min_kline m "
        "LEFT JOIN stock_daily d ON d.trade_date=:td AND d.ts_code=m.ts_code "
        "WHERE m.ts_code = ANY(:codes) "
        "  AND m.trade_time >= :open_dt AND m.trade_time <= :close_dt "
        "  AND m.freq='1min'"
    ), {
        "td": trade_date,
        "codes": ts_codes,
        "open_dt": datetime.strptime(trade_date, "%Y%m%d").replace(hour=9, minute=30),
        "close_dt": datetime.strptime(trade_date, "%Y%m%d").replace(hour=15, minute=0),
    })).fetchall()

    out: QuoteMap = {}
    for ts_code, trade_time, close, pre_close in rows:
        if close is None or pre_close is None or pre_close <= 0:
            continue
        # 截断到分钟（DB 可能存秒数）
        minute_dt = trade_time.replace(second=0, microsecond=0)
        c = float(close)
        p = float(pre_close)
        pct = (c - p) / p * 100.0
        is_limit = c >= p * 1.099   # A 股主板 +10%（容差 0.1%）
        out[(ts_code, minute_dt)] = MinuteQuote(
            close=c, pre_close=p, pct=pct, is_limit=is_limit,
        )
    return out


def count_codes_above_pct_intraday(
    quotes: QuoteMap, codes: list[str], minute_dt: datetime, pct_threshold: float,
) -> int:
    """事中：那一分钟板块内涨幅 ≥ pct_threshold% 的票数（替代 count_near_limit_at_minute）。

    严格按 minute_dt 那一分钟的 close 算，不偷看后续。
    """
    n = 0
    for code in codes:
        q = quotes.get((code, minute_dt))
        if q and q.pct >= pct_threshold:
            n += 1
    return n


def count_sector_limit_state_intraday(
    quotes: QuoteMap, codes: list[str], minute_dt: datetime,
) -> tuple[int, int]:
    """事中：截至 minute_dt 板块内（已封过板的票数, 已炸过板的票数）。

    判定（用分钟线，严格事中无未来函数）:
        - 已封过板 = 在 [09:30, minute_dt] 任意一分钟 close ≥ pre × 1.099
        - 已炸过板 = 已封过板 且 minute_dt 当下 close < pre × 1.099

    替代 count_sector_limit_state（旧版用 limit_stats.open_times，是当日累计字段
    带 mild 未来风险）。
    """
    ever_limit = 0
    broken = 0
    for code in codes:
        # 扫该票在 [09:30, minute_dt] 的所有分钟，看是否曾封板
        had_limit = False
        for (c, mt), q in quotes.items():
            if c != code or mt > minute_dt:
                continue
            if q.is_limit:
                had_limit = True
                break
        if not had_limit:
            continue
        ever_limit += 1
        # 当下是否已炸（close < 涨停价）
        cur = quotes.get((code, minute_dt))
        if cur and not cur.is_limit:
            broken += 1
    return ever_limit, broken


def compute_vwap_until(
    quotes: QuoteMap, ts_code: str, minute_dt: datetime,
) -> float | None:
    """事中：截至 minute_dt 那一分钟（含），该票的简单分时均价（AVG close）。

    简化版：用 close 累计平均代替成交量加权（vol 字段未拉，需要的话再加）。
    A 股盘中"分时均线"实际是 VWAP，但 close 累计平均在涨停盘是足够近似的指标。
    """
    closes: list[float] = []
    for (c, mt), q in quotes.items():
        if c != ts_code or mt > minute_dt:
            continue
        closes.append(q.close)
    if not closes:
        return None
    return sum(closes) / len(closes)


async def fetch_industries(
    session: AsyncSession, ts_codes: list[str],
) -> dict[str, str]:
    """批量取股票 → 中信行业映射（萌芽主线分组用）。"""
    if not ts_codes:
        return {}
    rows = (await session.execute(text(
        "SELECT ts_code, industry FROM stock_basic WHERE ts_code = ANY(:codes)"
    ), {"codes": ts_codes})).fetchall()
    return {r[0]: r[1] for r in rows if r[1]}


async def fetch_first_limit_times(
    session: AsyncSession, trade_date: str,
) -> dict[str, datetime]:
    """T 日全市场 first_time（事中可见的"封板时刻"）。

    返回 {ts_code: first_time_datetime}（截到分钟）。
    萌芽主线扫描用：每分钟检查"该分钟新增封板的票"。
    """
    rows = (await session.execute(text(
        "SELECT ts_code, first_time FROM limit_stats "
        "WHERE trade_date=:td AND \"limit\"='U' AND first_time IS NOT NULL"
    ), {"td": trade_date})).fetchall()
    base = datetime.strptime(trade_date, "%Y%m%d")
    out: dict[str, datetime] = {}
    for ts_code, ft in rows:
        if not ft:
            continue
        s = ft.zfill(6)
        try:
            h, m = int(s[:2]), int(s[2:4])
            out[ts_code] = base.replace(hour=h, minute=m, second=0, microsecond=0)
        except (ValueError, TypeError):
            continue
    return out
