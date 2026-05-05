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
    for r in rows:
        ts_code, name, ft, lt_, consec, lt_times, ot, ths_tag, lamt, fmv, amt = r
        board_count = max(
            _parse_board_count(ths_tag, fallback=0),
            int(consec),
            int(lt_times),
        )
        stocks.append(LimitUpStock(
            ts_code=ts_code, name=(name or "").replace(" ", ""),
            first_time=_parse_time(ft), last_time=_parse_time(lt_),
            limit_times=board_count, consec_days=int(consec),
            open_times=int(ot), tag=ths_tag,
            limit_amount=lamt, float_mv=fmv, amount=amt,
        ))

    if not stocks:
        return LongHeadResult(sector=sector_name, notes=["no limit-up in this sector"])

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
