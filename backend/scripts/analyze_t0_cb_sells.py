"""分析 T+0 立卖（L_CB B 分支）卖出决定是否正确。

用法：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe \\
        backend/scripts/analyze_t0_cb_sells.py 20260429 20260430 20260506 20260507

逻辑：
  - 重跑 pattern_01.find_signals 拿当日所有信号
  - 过滤 B 分支：pick_kind='cb' + sell_anchor='intraday_at' + (sell_min - buy_min) <= 5
  - 同股去重 (trade_date, pick_code) — 与回测一致
  - 对每笔拉:
    - 卖出后 +5min / +15min / +30min 内的最高价 + 最低价
    - 当日剩余时段最高价 / 最低价
    - 当日 14:55 收盘价
    - 次日 09:30 开盘价
    - 次日 14:55 收盘价
    - 次日全日最高价
  - 算"如果不卖"的几种假设收益
  - 输出 markdown 数据表到 reports/t0_cb_sell_analysis.md
"""
import argparse
import asyncio
import io
import sys
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.database import async_session  # noqa: E402
from app.research.data.cb_resolver import fetch_min_close_at  # noqa: E402
from app.research.strategies.base_pattern import PatternSignal  # noqa: E402
from app.research.strategies.pattern_01_long1_natural import Pattern01  # noqa: E402
from sqlalchemy import text  # noqa: E402

from test_pattern_backtest import execute_signal, next_trade_date  # noqa: E402


def is_t0_b_branch(sig: PatternSignal) -> bool:
    if sig.pick_kind != "cb":
        return False
    if sig.sell_anchor != "intraday_at":
        return False
    if not sig.sell_anchor_time or not sig.buy_anchor_time:
        return False
    buy_min = int(sig.buy_anchor_time[:2]) * 60 + int(sig.buy_anchor_time[2:4])
    sell_min = int(sig.sell_anchor_time[:2]) * 60 + int(sig.sell_anchor_time[2:4])
    return (sell_min - buy_min) <= 5


def add_minutes(hhmmss: str, mins: int) -> str:
    h, m = int(hhmmss[:2]), int(hhmmss[2:4])
    total = h * 60 + m + mins
    return f"{total // 60:02d}{total % 60:02d}00"


async def fetch_cb_minute_range(s, td: str, code: str, start_hhmmss: str, end_hhmmss: str):
    """拉指定时段的分钟价（含 high/low/close）。"""
    if not code or not td:
        return []
    start_dt = datetime.strptime(td, "%Y%m%d").replace(
        hour=int(start_hhmmss[:2]), minute=int(start_hhmmss[2:4])
    )
    end_dt = datetime.strptime(td, "%Y%m%d").replace(
        hour=int(end_hhmmss[:2]), minute=int(end_hhmmss[2:4])
    )
    rows = (await s.execute(text(
        "SELECT trade_time, high, low, close FROM cb_min_kline "
        "WHERE ts_code=:c AND freq='1min' "
        "AND trade_time >= :st AND trade_time <= :et "
        "ORDER BY trade_time"
    ), {"c": code, "st": start_dt, "et": end_dt})).fetchall()
    return rows


async def fetch_cb_name(s, code: str) -> str:
    r = (await s.execute(text(
        "SELECT bond_short_name FROM cb_basic WHERE ts_code=:c"
    ), {"c": code})).fetchone()
    return (r[0] or code) if r else code


async def fetch_stock_name(s, code: str) -> str:
    r = (await s.execute(text(
        "SELECT name FROM stock_basic WHERE ts_code=:c"
    ), {"c": code})).fetchone()
    return ((r[0] or code).replace(" ", "")) if r else code


async def analyze_one(sig: PatternSignal, trade) -> dict | None:
    """对一笔 B 分支信号做后续走势分析。"""
    cb_code = sig.pick_code
    sell_t = sig.sell_anchor_time
    sell_price = trade.sell_price
    if not sell_price:
        return None

    async with async_session() as s:
        plus5 = await fetch_cb_minute_range(s, sig.trade_date, cb_code, sell_t, add_minutes(sell_t, 5))
        plus15 = await fetch_cb_minute_range(s, sig.trade_date, cb_code, sell_t, add_minutes(sell_t, 15))
        plus30 = await fetch_cb_minute_range(s, sig.trade_date, cb_code, sell_t, add_minutes(sell_t, 30))
        rest = await fetch_cb_minute_range(s, sig.trade_date, cb_code, sell_t, "150000")
        close_t = await fetch_min_close_at(s, cb_code, sig.trade_date, "145500", table="cb_min_kline")
        t1 = await next_trade_date(sig.trade_date)
        next_open = await fetch_min_close_at(s, cb_code, t1, "093000", table="cb_min_kline") if t1 else None
        next_close = await fetch_min_close_at(s, cb_code, t1, "145500", table="cb_min_kline") if t1 else None
        next_rest = await fetch_cb_minute_range(s, t1, cb_code, "093000", "150000") if t1 else []
        cb_name = await fetch_cb_name(s, cb_code)
        underlying_name = await fetch_stock_name(s, sig.underlying_code) if sig.underlying_code else "—"

    def max_of(rows):
        return max((r[1] for r in rows if r[1]), default=None)
    def min_of(rows):
        return min((r[2] for r in rows if r[2]), default=None)

    return {
        "sig": sig,
        "trade": trade,
        "cb_name": cb_name,
        "underlying_name": underlying_name,
        "sell_price": sell_price,
        "buy_price": trade.buy_price,
        "next_date": t1,
        "p5_max": max_of(plus5),
        "p5_min": min_of(plus5),
        "p15_max": max_of(plus15),
        "p15_min": min_of(plus15),
        "p30_max": max_of(plus30),
        "p30_min": min_of(plus30),
        "rest_max": max_of(rest),
        "rest_min": min_of(rest),
        "today_close": close_t,
        "next_open": next_open,
        "next_close": next_close,
        "next_max": max_of(next_rest),
        "next_min": min_of(next_rest),
    }


def pct(target, base) -> str:
    if target is None or base is None or base == 0:
        return "—"
    return f"{(target - base) / base * 100:+.2f}%"


def evaluate(r: dict) -> tuple[str, str]:
    """评判卖出是否正确。
    比较"卖价"和后续假设持有的几个时点价：
    - 当日 14:55 / 次日 09:30 / 当日剩余最高 / 当日剩余最低 / 次日最高
    判定：
    - ✅ 卖对了: 当日剩余最低跌 ≥1% 或 当日收盘跌 ≥1%（验证及时止损避免更大亏损）
    - ❌ 踏空: 当日收盘高 ≥0.5% 或 次日开盘高 ≥1%（说明应该继续持有）
    - ⚪ 中性: 横盘震荡（卖了也没显著区别）
    """
    sell = r["sell_price"]
    if not sell:
        return ("?", "no sell")
    today_hold = (r["today_close"] - sell) / sell * 100 if r["today_close"] else None
    next_open_hold = (r["next_open"] - sell) / sell * 100 if r["next_open"] else None
    rest_max_pct = (r["rest_max"] - sell) / sell * 100 if r["rest_max"] else None
    rest_min_pct = (r["rest_min"] - sell) / sell * 100 if r["rest_min"] else None
    next_max_pct = (r["next_max"] - sell) / sell * 100 if r["next_max"] else None

    # 踏空判定（强信号优先）
    if (today_hold is not None and today_hold >= 0.5) or \
       (next_open_hold is not None and next_open_hold >= 1.0):
        notes = []
        if today_hold and today_hold >= 0.5:
            notes.append(f"当日收盘高 {today_hold:+.2f}%")
        if next_open_hold and next_open_hold >= 1.0:
            notes.append(f"次日开盘高 {next_open_hold:+.2f}%")
        if rest_max_pct and rest_max_pct >= 1.0:
            notes.append(f"剩余最高 {rest_max_pct:+.2f}%")
        return ("❌ 踏空", " / ".join(notes))

    # 卖对判定
    if (rest_min_pct is not None and rest_min_pct <= -1.0) or \
       (today_hold is not None and today_hold <= -1.0):
        notes = []
        if rest_min_pct and rest_min_pct <= -1.0:
            notes.append(f"剩余最低跌 {rest_min_pct:+.2f}%")
        if today_hold and today_hold <= -1.0:
            notes.append(f"当日收盘跌 {today_hold:+.2f}%")
        if next_open_hold and next_open_hold <= -1.0:
            notes.append(f"次日开盘跌 {next_open_hold:+.2f}%")
        return ("✅ 卖对了", " / ".join(notes))

    # 中性
    notes = []
    if today_hold is not None:
        notes.append(f"当日收盘 {today_hold:+.2f}%")
    if next_open_hold is not None:
        notes.append(f"次日开 {next_open_hold:+.2f}%")
    return ("⚪ 中性", " / ".join(notes))


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("dates", nargs="+")
    args = p.parse_args()

    pattern = Pattern01()
    all_results = []

    for td in args.dates:
        async with async_session() as s:
            sigs = await pattern.find_signals(s, td)
        b_sigs = [sig for sig in sigs if is_t0_b_branch(sig)]
        # 同股去重
        seen: set[tuple[str, str]] = set()
        b_sigs_dedup = []
        for sig in b_sigs:
            key = (sig.trade_date, sig.pick_code)
            if key in seen:
                continue
            seen.add(key)
            b_sigs_dedup.append(sig)
        print(f"\n=== {td}: 信号 {len(sigs)} / B 分支 {len(b_sigs)} / 去重 {len(b_sigs_dedup)} ===")
        for sig in b_sigs_dedup:
            trade = await execute_signal(sig)
            if trade.skip_reason:
                print(f"  SKIP {sig.pick_code}: {trade.skip_reason}")
                continue
            r = await analyze_one(sig, trade)
            if r:
                all_results.append(r)
                print(f"  [{sig.pick_code} {r['cb_name']}] underlying={r['underlying_name']} "
                      f"卖 {sig.sell_anchor_time[:4]} ¥{trade.sell_price} | "
                      f"剩余max {r['rest_max']} | 收盘 {r['today_close']} | 次日开 {r['next_open']}")

    # ---- 输出 markdown ----
    out = []
    out.append("# T+0 债立卖（L_CB B 分支）卖出对错分析\n\n")
    out.append(f"分析范围: {' / '.join(args.dates)}（4 个交易日）\n")
    out.append(f"总笔数: {len(all_results)}\n\n")
    out.append("## 判定逻辑\n\n")
    out.append("对每笔 B 分支立卖，对照「假设不卖」的几个时点价：\n")
    out.append("- 卖后 +5/+15/+30 分钟最高价（机会成本短期）\n")
    out.append("- 当日剩余时段最高 / 最低（机会 vs 避损）\n")
    out.append("- 当日 14:55 收盘价（如果改 D 分支 fallback）\n")
    out.append("- 次日 09:30 开盘价（如果改 A 分支隔夜）\n")
    out.append("- 次日 14:55 收盘价 / 次日全日最高（隔夜博弈实际效果）\n\n")
    out.append("**判定规则:**\n")
    out.append("- ✅ **卖对了**: 当日剩余最低跌 ≥1% 或 当日收盘跌 ≥1%（验证及时止损避免更大亏损）\n")
    out.append("- ❌ **踏空**: 当日收盘高 ≥0.5% 或 次日开盘高 ≥1%（说明应该继续持有）\n")
    out.append("- ⚪ **中性**: 横盘震荡，卖与不卖差别不大\n\n")

    out.append("## 数据明细\n\n")
    out.append("| # | 日期 | 主线 | 债代码 | 债名 | 正股 | 买价 | 卖价 |"
               " +5min最高 | +15min最高 | +30min最高 | 剩余最高 | 剩余最低 |"
               " 当日14:55 | 次日09:30 | 次日14:55 | 次日最高 | 评判 | 备注 |\n")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")

    win_correct = 0
    miss_correct = 0
    neutral = 0

    for i, r in enumerate(all_results, 1):
        sig = r["sig"]
        verdict, note = evaluate(r)
        if "踏空" in verdict:
            miss_correct += 1
        elif "卖对" in verdict:
            win_correct += 1
        else:
            neutral += 1

        def fmt(v):
            return f"{v:.3f}" if v else "—"

        sell = r["sell_price"]
        out.append(
            f"| {i} | {sig.trade_date} | {sig.sector} | {sig.pick_code} | {r['cb_name']} | "
            f"{sig.underlying_code or '—'} {r['underlying_name']} | "
            f"{fmt(r['buy_price'])} | {fmt(sell)} | "
            f"{fmt(r['p5_max'])} {pct(r['p5_max'], sell)} | "
            f"{fmt(r['p15_max'])} {pct(r['p15_max'], sell)} | "
            f"{fmt(r['p30_max'])} {pct(r['p30_max'], sell)} | "
            f"{fmt(r['rest_max'])} {pct(r['rest_max'], sell)} | "
            f"{fmt(r['rest_min'])} {pct(r['rest_min'], sell)} | "
            f"{fmt(r['today_close'])} {pct(r['today_close'], sell)} | "
            f"{fmt(r['next_open'])} {pct(r['next_open'], sell)} | "
            f"{fmt(r['next_close'])} {pct(r['next_close'], sell)} | "
            f"{fmt(r['next_max'])} {pct(r['next_max'], sell)} | "
            f"{verdict} | {note} |\n"
        )

    out.append(f"\n## 总览\n\n")
    out.append(f"- ✅ 卖对了: **{win_correct} 笔** ({win_correct/max(len(all_results),1)*100:.0f}%)\n")
    out.append(f"- ❌ 踏空: **{miss_correct} 笔** ({miss_correct/max(len(all_results),1)*100:.0f}%)\n")
    out.append(f"- ⚪ 中性: **{neutral} 笔** ({neutral/max(len(all_results),1)*100:.0f}%)\n")

    # ---- 假设收益对照 ----
    out.append("\n## 假设收益对照（vs 真实 B 分支立卖）\n\n")
    out.append("如果改成不同卖出策略，5 天合计收益如何变化（以每笔 10 张 CB 计算）：\n\n")
    out.append("| 策略 | 总笔数 | 总收益（不含手续费） | 平均每笔 | vs 真实立卖 |\n")
    out.append("|---|---|---|---|---|\n")

    qty = 10  # CB 1 手 = 10 张
    real_pnl = sum((r["sell_price"] - r["buy_price"]) * qty for r in all_results)
    today_close_pnl = sum((r["today_close"] - r["buy_price"]) * qty for r in all_results if r["today_close"])
    next_open_pnl = sum((r["next_open"] - r["buy_price"]) * qty for r in all_results if r["next_open"])
    next_close_pnl = sum((r["next_close"] - r["buy_price"]) * qty for r in all_results if r["next_close"])
    rest_max_pnl = sum((r["rest_max"] - r["buy_price"]) * qty for r in all_results if r["rest_max"])
    next_max_pnl = sum((r["next_max"] - r["buy_price"]) * qty for r in all_results if r["next_max"])

    n = len(all_results)
    n_close = sum(1 for r in all_results if r["today_close"])
    n_no = sum(1 for r in all_results if r["next_open"])
    n_nc = sum(1 for r in all_results if r["next_close"])
    n_rm = sum(1 for r in all_results if r["rest_max"])
    n_nm = sum(1 for r in all_results if r["next_max"])

    out.append(f"| **真实 B 分支立卖（基线）** | {n} | ¥{real_pnl:+,.2f} | ¥{real_pnl/max(n,1):+.2f} | — |\n")
    out.append(f"| 改 D 分支（当日 14:55 fallback） | {n_close} | ¥{today_close_pnl:+,.2f} | ¥{today_close_pnl/max(n_close,1):+.2f} | {today_close_pnl - real_pnl:+,.2f} |\n")
    out.append(f"| 改 A 分支（次日 09:30 隔夜） | {n_no} | ¥{next_open_pnl:+,.2f} | ¥{next_open_pnl/max(n_no,1):+.2f} | {next_open_pnl - real_pnl:+,.2f} |\n")
    out.append(f"| 持仓到次日 14:55 收盘 | {n_nc} | ¥{next_close_pnl:+,.2f} | ¥{next_close_pnl/max(n_nc,1):+.2f} | {next_close_pnl - real_pnl:+,.2f} |\n")
    out.append(f"| 当日剩余最高（理论极致） | {n_rm} | ¥{rest_max_pnl:+,.2f} | ¥{rest_max_pnl/max(n_rm,1):+.2f} | {rest_max_pnl - real_pnl:+,.2f} |\n")
    out.append(f"| 次日最高（理论极致） | {n_nm} | ¥{next_max_pnl:+,.2f} | ¥{next_max_pnl/max(n_nm,1):+.2f} | {next_max_pnl - real_pnl:+,.2f} |\n")

    out_path = Path(__file__).resolve().parents[2] / "reports" / "t0_cb_sell_analysis.md"
    out_path.write_text("".join(out), encoding="utf-8")
    print(f"\n=== 总览 ===")
    print(f"  ✅ 卖对了: {win_correct} | ❌ 踏空: {miss_correct} | ⚪ 中性: {neutral}")
    print(f"  真实 B 分支 PnL ¥{real_pnl:+.2f}")
    print(f"  改 D fallback PnL ¥{today_close_pnl:+.2f} ({today_close_pnl-real_pnl:+.2f})")
    print(f"  改 A 隔夜 PnL ¥{next_open_pnl:+.2f} ({next_open_pnl-real_pnl:+.2f})")
    print(f"\n→ {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
