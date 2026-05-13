"""12 模式策略池 信号生成 + 简化回测。

用法：
    python backend/scripts/test_pattern_backtest.py 20260428 20260429 20260430
    python backend/scripts/test_pattern_backtest.py --pattern 1,3,10 20260428 20260429 20260430

回测口径：
    - 买卖价：分钟线（按 buy_anchor / sell_anchor 取真实分钟 close）
    - 仓位：单笔目标 ¥10,000（向下取整到不超过 10k 的整手；最少 1 手）
            * 正股 1 手 = 100 股；qty = max(1, floor(10000 / (price × 100))) × 100
            * 转债 1 手 = 10 张；qty = max(1, floor(10000 / (price × 10))) × 10
    - 含手续费（佣金万 2.5 最低 5、印花税 0.05% 仅卖、沪市过户 0.001%）
    - 涨停封单：买入价 ≥ 涨停价（含 0.005 容差）→ SKIP
"""
import argparse
import asyncio
import math
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
from sqlalchemy import text


PATTERNS = {
    "1": Pattern01(),  # 龙头隔夜模式（合并原 1/2，事中共识 ≥3 只 ≥6%）
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


async def fetch_stock_up_limit(s, td: str, code: str) -> float | None:
    """T 日真实涨停价（含主板10/创业科创20/北交所30/ST 5%），来自 stock_limit 表。"""
    r = await s.execute(text(
        "SELECT up_limit FROM stock_limit WHERE trade_date=:d AND ts_code=:c"
    ), {"d": td, "c": code})
    row = r.fetchone()
    return row[0] if row else None


# 散户挂涨停板 99% 排不进，buy_price ≥ up_limit - 0.005（容差 0.5 分）视为已封板 → skip
LIMIT_UP_FILL_TOLERANCE = 0.005

# 单笔目标仓位（向下取整到不超过此金额的整手；若 1 手已超也仍买 1 手）
# 通过 env var STRATEGY_PRESET 切换（moderate=10k / strict=5k / loose=15k）
from app.research.strategies.pattern_01_params import ACTIVE as _P_BT
TARGET_NOTIONAL = _P_BT["TARGET_NOTIONAL"]


def calc_qty(price: float, is_cb: bool) -> int:
    """单笔目标 ¥10k：正股 1 手 = 100 股，转债 1 手 = 10 张；最少 1 手。"""
    lot_size = 10 if is_cb else 100
    one_lot_value = price * lot_size
    if one_lot_value <= 0:
        return lot_size
    n_lots = max(1, math.floor(TARGET_NOTIONAL / one_lot_value))
    return n_lots * lot_size


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

    # "假装触发"信号（L2 偏离度过高放弃买入）：不撮合，直接 SKIP，理由原样传出
    if sig.buy_anchor == "skip":
        return PatternTrade(
            signal=sig, next_date="", buy_price=None, sell_price=None,
            skip_reason=sig.reason or "skip(price_too_high)",
        )

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

        # ---- 涨停封单判定（仅正股，CB 流动性好不卡）----
        if not is_cb and buy_price is not None and buy_price > 0:
            up_limit = await fetch_stock_up_limit(s, sig.trade_date, sig.pick_code)
            if up_limit and buy_price >= up_limit - LIMIT_UP_FILL_TOLERANCE:
                return PatternTrade(
                    signal=sig, next_date="", buy_price=buy_price, sell_price=None,
                    skip_reason=f"unfillable_limit: buy={buy_price:.2f} ≥ "
                                f"涨停价{up_limit:.2f}（含 0.005 容差）"
                )

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

    qty = calc_qty(buy_price, is_cb)  # 单笔目标 ¥10,000 向下取整
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
    "follower_cb_rebuy": "跟风债-买回",
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

    sector 是归一后的细分主线名（如"光模块"/"PCB"/"算力租赁"），SQL 用
    ALIAS_TO_CANONICAL 反向展开 — 找出所有归一到这个 canonical 的 raw alias，
    一并匹配 daily_sector_review.sector_name。

    返回 dict 含:
        followers: list[dict]   — 跟风列表（去 exclude_codes，按 first_time 排）
        max_board: int          — 板块最高板数
        max_stock: (name, tag)  — 板块最高板对应的票
        at_long1_count: int     — 龙1 封板时刻 (first_time <= long1_ft) 已经封板的跟风数
    """
    from app.research.signals.theme_taxonomy import ALIAS_TO_CANONICAL
    if not sector or sector.startswith("("):
        return {"followers": [], "max_board": 0, "max_stock": None, "at_long1_count": 0}
    # 反向查：找所有归一到 sector 这个 canonical 细分的 raw alias
    aliases = [alias for alias, canonical in ALIAS_TO_CANONICAL.items() if canonical == sector]
    sub_names = list({sector, *aliases})
    async with async_session() as s:
        rows = (await s.execute(text(
            "SELECT DISTINCT ls.ts_code, ls.name, ls.first_time, ls.open_times, "
            "       lt.tag, COALESCE(ls.limit_times, 1) as lt_times "
            "FROM limit_stats ls "
            "JOIN daily_sector_review dsr ON dsr.ts_code=ls.ts_code "
            "     AND dsr.trade_date=ls.trade_date "
            "LEFT JOIN limit_list_ths lt ON lt.trade_date=ls.trade_date "
            "     AND lt.ts_code=ls.ts_code AND lt.limit_type='涨停池' "
            "WHERE ls.trade_date=:d AND dsr.sector_name = ANY(:names) "
            "  AND dsr.source IN ('bankuai','jiuyan') "
            "  AND ls.\"limit\"='U' "
            "ORDER BY ls.first_time"
        ), {"d": trade_date, "names": sub_names})).fetchall()

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
            # 同一标的当日只下一笔单（与实盘 OMS 一致）。去重 key 按 pick_role 分两类：
            #   - 一次性进场（long1 / shadow / follower_cb）：key = (trade_date, pick_code)
            #     不论被多少个板块同时识别为 L1/L2/跟风，只买一次（避免 5/11 富春染织转债
            #     同分钟被"纺织"+"机器人"两个板块各发一次债，造成同票买两次的 bug）
            #   - 买回（follower_cb_rebuy）：key = (trade_date, pick_code, buy_anchor_time)
            #     保留时刻区分，让早盘 C 止损后下午板块重燃的买回能独立成交
            traded_today: set[tuple] = set()
            for i, sig in enumerate(sigs, 1):
                if sig.pick_role == "follower_cb_rebuy":
                    key = (sig.trade_date, sig.pick_code, sig.buy_anchor_time)
                else:
                    key = (sig.trade_date, sig.pick_code)
                if key in traded_today:
                    skip_trade = PatternTrade(
                        signal=sig, next_date="", buy_price=None, sell_price=None,
                        skip_reason=f"already_traded（同日 {sig.pick_code} 已被前序 sector 信号买入，本信号 sector={sig.sector} 跳过）",
                    )
                    all_trades.append(skip_trade)
                    print(fmt_trade_block(skip_trade))
                    continue
                trade = await execute_signal(sig)
                all_trades.append(trade)
                if trade.skip_reason:
                    print(fmt_trade_block(trade))
                    continue
                # 成功执行后才登记，避免 unfillable_limit / missing price 占用槽位
                traded_today.add(key)
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
