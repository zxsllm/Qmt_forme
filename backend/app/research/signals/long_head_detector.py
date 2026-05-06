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


async def find_entry_trigger(
    session: AsyncSession,
    trade_date: str,
    self_code: str,
    sector_codes: list[str],
    first_time: str,
    self_pct: float = 9.0,
    sector_pct: float = 6.0,
    sector_min: int = 3,
    lookback_minutes: int = 5,
) -> tuple[str, float | None]:
    """从 first_time 往前 lookback_minutes 内找入场触发时刻（封板前夕、能买到）。

    判定（双条件，事中可见）：
        1. 该股自身涨幅 ≥ self_pct%（默认 9%）— 即将封板
        2. 同板块 ≥ sector_min 只票涨幅 ≥ sector_pct%（默认 ≥3 只 ≥6%）— 共识形成

    用户原话："板块龙头到 +9% 的同时，同板块跟风也到 +6%，这时候也许就是一个买点"

    返回 (trigger_hhmmss, trigger_close)：
        - 找到 → 触发时刻 + 那一分钟 close（通常 +9~+10%，未到涨停）
        - 找不到 → fallback first_time + 那一分钟 close（涨停价，靠撮合层 skip 兜底）
    """
    target = _hhmmss_to_dt(trade_date, first_time)
    if not target:
        return first_time, None

    # 扫描窗口下界：max(first_time - 5min, 09:30:00)
    open_dt = datetime.strptime(trade_date, "%Y%m%d").replace(hour=9, minute=30)
    start = max(target - timedelta(minutes=lookback_minutes), open_dt)
    if start >= target:
        # first_time = 09:30:00 这种边界 → 没有可用的前序窗口
        rows = []
    else:
        rows = (await session.execute(text(
            "SELECT m.trade_time, m.close, d.pre_close "
            "FROM stock_min_kline m "
            "LEFT JOIN stock_daily d ON d.trade_date=:td AND d.ts_code=:c "
            "WHERE m.ts_code=:c AND m.trade_time >= :start AND m.trade_time < :end "
            "  AND m.freq='1min' ORDER BY m.trade_time"
        ), {"td": trade_date, "c": self_code, "start": start, "end": target})).fetchall()

    self_threshold = 1 + self_pct / 100
    for trade_time, close, pre_close in rows:
        if not pre_close or pre_close <= 0 or close is None:
            continue
        if float(close) < float(pre_close) * self_threshold:
            continue
        # 自身 ≥ self_pct% 达标 → 检查那一分钟板块共识
        hhmmss = trade_time.strftime("%H%M%S")
        n, _, _ = await count_near_limit_at_minute(
            session, trade_date, sector_codes, hhmmss, sector_pct
        )
        if n >= sector_min:
            return hhmmss, float(close)

    # 没找到合适触发 → fallback first_time（first_time 那分钟自身已涨停 + 共识达标）
    # first_time 可能含秒（如 093136）但分钟线表按整分钟存（093100），截断到分钟匹配
    target_minute = target.replace(second=0)
    fallback_close = (await session.execute(text(
        "SELECT close FROM stock_min_kline "
        "WHERE ts_code=:c AND trade_time=:t AND freq='1min'"
    ), {"c": self_code, "t": target_minute})).scalar()
    return first_time, (float(fallback_close) if fallback_close is not None else None)


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
    try:
        ft_time = time(int(at_hhmmss[:2]), int(at_hhmmss[2:4]), int(at_hhmmss[4:6]))
    except (ValueError, TypeError):
        return 0, 0

    row = (await session.execute(text(
        "SELECT "
        "  COUNT(*) AS limit_count, "
        "  SUM(CASE WHEN COALESCE(open_times, 0) > 0 THEN 1 ELSE 0 END) AS broken_count "
        "FROM limit_stats "
        "WHERE trade_date = :td "
        "  AND ts_code = ANY(:codes) "
        "  AND \"limit\" = 'U' "
        "  AND first_time IS NOT NULL "
        "  AND first_time <= :ft"
    ), {"td": trade_date, "codes": sector_codes, "ft": ft_time})).fetchone()
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
