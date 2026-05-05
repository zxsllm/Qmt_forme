"""12 模式策略池 信号生成 + 简化回测。

用法：
    python backend/scripts/test_pattern_backtest.py 20260428 20260429 20260430
    python backend/scripts/test_pattern_backtest.py --pattern 1,3,10 20260428 20260429 20260430

回测口径（简化）：
    - 买入价 = T 日 daily.close
    - 卖出价 = T+1 日 daily.open
    - 100 股 / 笔，含手续费
    - 不模拟封单/撮合，只看价差 → 给出胜率 + 盈亏比的初步参考
"""
import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from app.research.data.cb_resolver import (
    fetch_cb_close_open, fetch_min_close_at,
)
from app.research.strategies.base_pattern import PatternSignal, PatternTrade
from app.research.strategies.pattern_01_long1_natural import Pattern01
from app.research.strategies.pattern_03_yizi_relay import Pattern03
from app.research.strategies.pattern_04_yizi_break import Pattern04
from app.research.strategies.pattern_05_yizi_down_bounce import Pattern05
from app.research.strategies.pattern_06_double_break import Pattern06
from app.research.strategies.pattern_07_down_open_buy import Pattern07
from app.research.strategies.pattern_08_panic_bounce import Pattern08
from app.research.strategies.pattern_10_new_theme_day1 import Pattern10
from app.research.strategies.pattern_11_divergence_pullback import Pattern11
from app.research.strategies.pattern_12_ambush_volume import Pattern12
from sqlalchemy import text


# 模式 9 不实现（依赖新闻系统 + 做空向操作，超出当前回测能力范围）
PATTERNS = {
    "1": Pattern01(),  # 龙头隔夜模式（合并原 1/2）
    "3": Pattern03(), "4": Pattern04(),
    "5": Pattern05(), "6": Pattern06(), "7": Pattern07(),
    "8": Pattern08(),
    "10": Pattern10(), "11": Pattern11(), "12": Pattern12(),
}


def calc_fee(price: float, qty: int, side: str, ts_code: str, kind: str = "stock") -> float:
    """A 股：佣金万2.5（最低5）/ 印花税0.05%（仅卖）/ 沪市过户0.001%。
    可转债：佣金万2.5（最低5）/ 无印花税 / 无过户费。"""
    amount = price * qty
    commission = max(amount * 0.00025, 5.0)
    if kind == "cb":
        return round(commission, 2)
    stamp = amount * 0.0005 if side == "SELL" else 0
    transfer = amount * 0.00001 if ts_code.endswith(".SH") else 0
    return round(commission + stamp + transfer, 2)


async def next_trade_date(td: str) -> str | None:
    async with async_session() as s:
        r = await s.execute(text(
            "SELECT cal_date FROM trade_cal "
            "WHERE cal_date > :d AND is_open=1 "
            "ORDER BY cal_date LIMIT 1"
        ), {"d": td})
        row = r.fetchone()
        return row[0] if row else None


async def fetch_stock_close_open(td: str, t1: str, code: str) -> tuple[float | None, float | None]:
    async with async_session() as s:
        r1 = await s.execute(text(
            "SELECT close FROM stock_daily WHERE trade_date=:d AND ts_code=:c"
        ), {"d": td, "c": code})
        r2 = await s.execute(text(
            "SELECT open FROM stock_daily WHERE trade_date=:d AND ts_code=:c"
        ), {"d": t1, "c": code})
        a = r1.fetchone()
        b = r2.fetchone()
        return (a[0] if a else None, b[0] if b else None)


async def fetch_stock_open(td: str, code: str) -> float | None:
    async with async_session() as s:
        r = await s.execute(text(
            "SELECT open FROM stock_daily WHERE trade_date=:d AND ts_code=:c"
        ), {"d": td, "c": code})
        row = r.fetchone()
        return row[0] if row else None


ANCHOR_TIME_MAP = {
    "today_close": "145500",   # 散户能下单的最后实际可控时刻
    "today_open": "093000",
    "next_open": "093000",
}


async def execute_signal(sig: PatternSignal) -> PatternTrade:
    """统一撮合：所有锚点都走分钟线（精确到分钟）。"""
    is_cb = sig.pick_kind == "cb"
    table = "cb_min_kline" if is_cb else "stock_min_kline"
    buy_price: float | None = None
    sell_price: float | None = None
    next_date = sig.trade_date

    async with async_session() as s:
        # ---- 买入价（分钟线）----
        if sig.buy_anchor in ("today_close", "today_open"):
            hhmmss = ANCHOR_TIME_MAP[sig.buy_anchor]
            buy_price = await fetch_min_close_at(s, sig.pick_code, sig.trade_date,
                                                  hhmmss, table=table)
        elif sig.buy_anchor == "intraday_at" and sig.buy_anchor_time:
            buy_price = await fetch_min_close_at(s, sig.pick_code, sig.trade_date,
                                                  sig.buy_anchor_time, table=table)
        else:
            return PatternTrade(signal=sig, next_date="", buy_price=None, sell_price=None,
                                skip_reason=f"unknown buy_anchor={sig.buy_anchor}")

        # ---- 卖出价（分钟线）----
        if sig.sell_anchor == "next_open":
            t1 = await next_trade_date(sig.trade_date)
            if not t1:
                return PatternTrade(signal=sig, next_date="", buy_price=buy_price,
                                    sell_price=None, skip_reason="no T+1")
            next_date = t1
            sell_price = await fetch_min_close_at(s, sig.pick_code, t1, "093000", table=table)
        elif sig.sell_anchor == "today_close":
            sell_price = await fetch_min_close_at(s, sig.pick_code, sig.trade_date,
                                                   "145500", table=table)
        elif sig.sell_anchor == "intraday_at" and sig.sell_anchor_time:
            sell_price = await fetch_min_close_at(s, sig.pick_code, sig.trade_date,
                                                   sig.sell_anchor_time, table=table)
        else:
            return PatternTrade(signal=sig, next_date="", buy_price=buy_price, sell_price=None,
                                skip_reason=f"unknown sell_anchor={sig.sell_anchor}")

    if buy_price is None or sell_price is None or buy_price <= 0 or sell_price <= 0:
        return PatternTrade(signal=sig, next_date=next_date, buy_price=buy_price,
                            sell_price=sell_price,
                            skip_reason=f"missing price (kind={sig.pick_kind})")

    qty = 100 if not is_cb else 10  # CB 1 手 = 10 张
    bf = calc_fee(buy_price, qty, "BUY", sig.pick_code, kind=sig.pick_kind)
    sf = calc_fee(sell_price, qty, "SELL", sig.pick_code, kind=sig.pick_kind)
    fee = bf + sf
    pnl = (sell_price - buy_price) * qty - fee
    ret_pct = (sell_price - buy_price) / buy_price * 100
    return PatternTrade(
        signal=sig, next_date=next_date, buy_price=round(buy_price, 2),
        sell_price=round(sell_price, 2), qty=qty, fee=fee,
        pnl=round(pnl, 2), ret_pct=round(ret_pct, 2),
    )


ROLE_LABEL = {
    "long1": "龙1",
    "long2": "龙2",
    "long3": "龙3",
    "shadow": "影子龙",
    "follower": "跟风",
    "long1_cb": "龙1债",
    "long2_cb": "龙2债",
    "shadow_cb": "影子龙债",
    "follower_cb": "跟风债",
}


def role_label(role: str) -> str:
    return ROLE_LABEL.get(role, role)


def _hhmm_of(anchor: str, anchor_time: str | None) -> str:
    if anchor == "today_close":
        return "14:55"
    if anchor in ("today_open", "next_open"):
        return "09:30"
    if anchor == "intraday_at" and anchor_time:
        return f"{anchor_time[:2]}:{anchor_time[2:4]}"
    return "?"


def fmt_trade(t: PatternTrade) -> str:
    s = t.signal
    kind_tag = "CB" if s.pick_kind == "cb" else "股"
    role = role_label(s.pick_role)
    if t.skip_reason:
        return (f"  [SKIP] {s.trade_date} {s.sector:<10} {role:<8} "
                f"[{kind_tag}]{s.pick_code} {s.pick_name} | {t.skip_reason}")
    sign = "+" if t.pnl > 0 else ""
    buy_t = _hhmm_of(s.buy_anchor, s.buy_anchor_time)
    sell_t = _hhmm_of(s.sell_anchor, s.sell_anchor_time)
    sell_date = t.next_date if s.sell_anchor == "next_open" else s.trade_date
    return (f"  {s.sector:<10} {role:<8} [{kind_tag}]{s.pick_code} {s.pick_name:<10} "
            f"| 龙1 {s.long1_name}({s.long1_tag}) "
            f"| 买 {s.trade_date} {buy_t}={t.buy_price} → 卖 {sell_date} {sell_t}={t.sell_price} "
            f"| {sign}{t.ret_pct}%")


_TAG_BOARD_RE = re.compile(r"(\d+)天(\d+)板")


def _parse_board(tag: str | None, lt_times: int) -> int:
    if not tag:
        return lt_times
    if tag == "首板":
        return 1
    m = _TAG_BOARD_RE.match(tag)
    return int(m.group(2)) if m else lt_times


async def fetch_sector_followers(
    sector: str, trade_date: str, exclude_codes: set[str],
    long1_first_time: str | None = None,
) -> dict:
    """拉同板块当日涨停股明细。

    返回 dict 含:
        followers: list[dict]   — 跟风列表（去 exclude_codes，按 first_time 排）
        max_board: int          — 板块最高板数
        max_stock: (name, tag)  — 板块最高板对应的票
        at_long1_count: int     — 龙1 封板时刻 (first_time <= long1_ft) 已经封板的跟风数
    """
    if not sector or sector.startswith("("):
        return {"followers": [], "max_board": 0, "max_stock": None, "at_long1_count": 0}
    async with async_session() as s:
        rows = (await s.execute(text(
            "SELECT ls.ts_code, ls.name, ls.first_time, ls.open_times, "
            "       lt.tag, COALESCE(ls.limit_times, 1) as lt_times "
            "FROM limit_stats ls "
            "JOIN daily_sector_review dsr ON dsr.ts_code=ls.ts_code "
            "     AND dsr.trade_date=ls.trade_date "
            "LEFT JOIN limit_list_ths lt ON lt.trade_date=ls.trade_date "
            "     AND lt.ts_code=ls.ts_code AND lt.limit_type='涨停池' "
            "WHERE ls.trade_date=:d AND dsr.sector_name=:s "
            "  AND dsr.source='bankuai' AND dsr.raw_meta->>'scope'='daily' "
            "  AND ls.\"limit\"='U' "
            "ORDER BY ls.first_time"
        ), {"d": trade_date, "s": sector})).fetchall()

    max_board, max_stock = 0, None
    out: list[dict] = []
    at_long1_count = 0
    for r in rows:
        board = _parse_board(r[4], int(r[5]))
        name = (r[1] or "").replace(" ", "")
        tag = r[4] or f"{int(r[5])}板"
        if board > max_board:
            max_board = board
            max_stock = (name, tag)
        if r[0] in exclude_codes:
            continue
        raw = r[2]
        if raw is None:
            ft = "999999"
        elif hasattr(raw, "strftime"):
            ft = raw.strftime("%H%M%S")
        else:
            ss = str(raw).replace(":", "").strip()
            ft = ss.zfill(6) if len(ss) <= 6 else ss[:6]
        if long1_first_time and ft <= long1_first_time:
            at_long1_count += 1
        out.append({
            "code": r[0], "name": name, "first_time": ft,
            "open_times": int(r[3] or 0), "tag": tag, "board": board,
        })
    return {
        "followers": out, "max_board": max_board, "max_stock": max_stock,
        "at_long1_count": at_long1_count,
    }


def fmt_trade_block(t: PatternTrade, sec_info: dict | None = None) -> str:
    """结构化多行输出。"""
    s = t.signal
    kind_tag = "CB" if s.pick_kind == "cb" else "股"
    role = role_label(s.pick_role)
    if t.skip_reason:
        return (f"  [SKIP] {s.trade_date} {s.sector} {role} "
                f"[{kind_tag}]{s.pick_code} {s.pick_name} | {t.skip_reason}")
    sign = "+" if t.pnl > 0 else ""
    buy_t = _hhmm_of(s.buy_anchor, s.buy_anchor_time)
    sell_t = _hhmm_of(s.sell_anchor, s.sell_anchor_time)
    sell_date = t.next_date if s.sell_anchor == "next_open" else s.trade_date

    lines = []
    lines.append(f"  ── {s.trade_date} {s.sector} | {role} ──")
    lines.append(f"     标的: [{kind_tag}] {s.pick_code} {s.pick_name} ({s.pick_tag})")
    lines.append(f"     龙1: {s.long1_name}({s.long1_tag}) 首封{s.long1_first_time[:2]}:"
                 f"{s.long1_first_time[2:4]} 当日炸{s.long1_open_times}次")
    lines.append(f"     买入: {s.trade_date} {buy_t} = ¥{t.buy_price}")
    lines.append(f"     卖出: {sell_date} {sell_t} = ¥{t.sell_price}")
    lines.append(f"     收益: {sign}{t.ret_pct}% (PnL {sign}{t.pnl})")
    if sec_info:
        max_stock = sec_info.get("max_stock")
        max_board = sec_info.get("max_board", 0)
        if max_stock:
            lines.append(f"     板块最高: {max_stock[0]} ({max_stock[1]})")
        else:
            lines.append(f"     板块最高: {max_board}板")
        at_long1 = sec_info.get("at_long1_count", 0)
        fs = sec_info.get("followers", [])
        lines.append(f"     封板时刻已封跟风: {at_long1}只 / 全天跟风: {len(fs)}只")
        if fs:
            for f in fs:
                ft = f"{f['first_time'][:2]}:{f['first_time'][2:4]}"
                ob = f" 炸{f['open_times']}" if f["open_times"] > 0 else ""
                lines.append(f"       · {f['name']:<8} ({f['tag']}, {ft}{ob})")
    return "\n".join(lines)


def stats_block(label: str, trades: list[PatternTrade]) -> str:
    valid = [t for t in trades if not t.skip_reason]
    if not valid:
        return f"  {label}: 无有效成交（信号 {len(trades)} 笔，全 SKIP）"
    wins = [t for t in valid if t.pnl > 0]
    losses = [t for t in valid if t.pnl <= 0]
    win_rate = len(wins) / len(valid) * 100
    avg_win = sum(t.pnl for t in wins) / max(len(wins), 1)
    avg_loss = abs(sum(t.pnl for t in losses) / max(len(losses), 1))
    pl_ratio = avg_win / max(avg_loss, 0.01)
    avg_ret = sum(t.ret_pct for t in valid) / len(valid)
    total_pnl = sum(t.pnl for t in valid)
    return (f"  {label}: {len(valid)}笔  胜 {len(wins)} 负 {len(losses)}  "
            f"胜率 {win_rate:.1f}%  均收益 {avg_ret:+.2f}%  "
            f"盈亏比 {pl_ratio:.2f}  PnL {total_pnl:+.2f}")


async def run_pattern(pattern, label: str, dates: list[str]) -> list[PatternTrade]:
    print(f"\n{'='*82}\n>>> {label}\n     {pattern.description}\n{'='*82}")

    all_trades: list[PatternTrade] = []
    async with async_session() as s:
        for td in dates:
            sigs = await pattern.find_signals(s, td)
            if not sigs:
                print(f"  {td}: 无触发")
                continue
            print(f"\n  --- {td}：触发 {len(sigs)} 个信号 ---")
            for i, sig in enumerate(sigs, 1):
                trade = await execute_signal(sig)
                all_trades.append(trade)
                if trade.skip_reason:
                    print(fmt_trade_block(trade))
                    continue
                sec_info = await fetch_sector_followers(
                    sig.sector, sig.trade_date,
                    exclude_codes={sig.long1_code, sig.pick_code},
                    long1_first_time=sig.long1_first_time,
                )
                print(f"\n  [{i}] " + fmt_trade_block(trade, sec_info).lstrip())

    print()
    print(stats_block("结果", all_trades))
    return all_trades


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("dates", nargs="+", help="trade dates YYYYMMDD ...")
    p.add_argument("--pattern", default="all",
                   help="逗号分隔的模式编号（如 1,3,10）；默认 all")
    args = p.parse_args()

    if args.pattern == "all":
        keys = list(PATTERNS.keys())
    else:
        keys = [k.strip() for k in args.pattern.split(",")]

    summary: list[tuple[str, list[PatternTrade]]] = []
    for k in keys:
        if k not in PATTERNS:
            print(f"[skip] 未知模式 {k}")
            continue
        pat = PATTERNS[k]
        label = f"模式 {k}"
        trades = await run_pattern(pat, label, args.dates)
        summary.append((label, trades))

    print(f"\n{'='*82}\n>>> 总表（按模式对比）\n{'='*82}")
    for label, trades in summary:
        print(stats_block(label, trades))


if __name__ == "__main__":
    asyncio.run(main())
