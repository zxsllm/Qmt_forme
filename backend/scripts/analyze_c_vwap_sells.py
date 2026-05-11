"""分析 C VWAP 止损卖出后后续走势 — 用真实 sell_reason 字段筛 C 分支。

用法：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe \\
        backend/scripts/analyze_c_vwap_sells.py 20260429 20260430 20260506 20260507

输出: reports/c_vwap_sell_analysis.md
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


def add_minutes(hhmmss: str, mins: int) -> str:
    h, m = int(hhmmss[:2]), int(hhmmss[2:4])
    total = h * 60 + m + mins
    return f"{total // 60:02d}{total % 60:02d}00"


async def fetch_cb_minute_range(s, td: str, code: str, st: str, et: str):
    if not code or not td:
        return []
    sd = datetime.strptime(td, "%Y%m%d").replace(hour=int(st[:2]), minute=int(st[2:4]))
    ed = datetime.strptime(td, "%Y%m%d").replace(hour=int(et[:2]), minute=int(et[2:4]))
    rows = (await s.execute(text(
        "SELECT trade_time, high, low, close FROM cb_min_kline "
        "WHERE ts_code=:c AND freq='1min' AND trade_time >= :st AND trade_time <= :et "
        "ORDER BY trade_time"
    ), {"c": code, "st": sd, "et": ed})).fetchall()
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
    cb_code = sig.pick_code
    sell_t = sig.sell_anchor_time
    sell_price = trade.sell_price
    if not sell_price or not sell_t:
        return None

    async with async_session() as s:
        rest = await fetch_cb_minute_range(s, sig.trade_date, cb_code, sell_t, "150000")
        close_t = await fetch_min_close_at(s, cb_code, sig.trade_date, "145500", table="cb_min_kline")
        t1 = await next_trade_date(sig.trade_date)
        next_open = await fetch_min_close_at(s, cb_code, t1, "093000", table="cb_min_kline") if t1 else None
        next_close = await fetch_min_close_at(s, cb_code, t1, "145500", table="cb_min_kline") if t1 else None
        next_rest = await fetch_cb_minute_range(s, t1, cb_code, "093000", "150000") if t1 else []
        cb_name = await fetch_cb_name(s, cb_code)
        underlying_name = await fetch_stock_name(s, sig.underlying_code) if sig.underlying_code else "—"

    def max_of(rs):
        return max((r[1] for r in rs if r[1]), default=None)
    def min_of(rs):
        return min((r[2] for r in rs if r[2]), default=None)

    return {
        "sig": sig,
        "trade": trade,
        "cb_name": cb_name,
        "underlying_name": underlying_name,
        "sell_price": sell_price,
        "buy_price": trade.buy_price,
        "next_date": t1,
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


def evaluate_c(r: dict) -> tuple[str, str]:
    """C VWAP 止损的判定：是否避免了大跌 vs 是否踏空了反弹。"""
    sell = r["sell_price"]
    if not sell:
        return ("?", "no sell")
    today_hold = (r["today_close"] - sell) / sell * 100 if r["today_close"] else None
    next_open_hold = (r["next_open"] - sell) / sell * 100 if r["next_open"] else None
    rest_max_pct = (r["rest_max"] - sell) / sell * 100 if r["rest_max"] else None
    rest_min_pct = (r["rest_min"] - sell) / sell * 100 if r["rest_min"] else None

    if (today_hold is not None and today_hold >= 1.0) or \
       (next_open_hold is not None and next_open_hold >= 1.5):
        notes = []
        if today_hold and today_hold >= 1.0:
            notes.append(f"当日收盘 {today_hold:+.2f}%")
        if next_open_hold and next_open_hold >= 1.5:
            notes.append(f"次日开 {next_open_hold:+.2f}%")
        if rest_max_pct:
            notes.append(f"剩余最高 {rest_max_pct:+.2f}%")
        return ("❌ C 误杀（踏空）", " / ".join(notes))

    if (rest_min_pct is not None and rest_min_pct <= -2.0) or \
       (today_hold is not None and today_hold <= -2.0):
        notes = []
        if rest_min_pct and rest_min_pct <= -2.0:
            notes.append(f"剩余最低 {rest_min_pct:+.2f}%")
        if today_hold and today_hold <= -2.0:
            notes.append(f"当日收盘 {today_hold:+.2f}%")
        return ("✅ C 救对（避损）", " / ".join(notes))

    return ("⚪ C 中性", f"当日收 {today_hold:+.2f}% / 次日开 {next_open_hold:+.2f}%" if today_hold else "—")


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("dates", nargs="+")
    args = p.parse_args()

    pattern = Pattern01()
    all_results = []

    for td in args.dates:
        async with async_session() as s:
            sigs = await pattern.find_signals(s, td)
        # 只看 C VWAP 止损（用真实的 sell_reason 字段，而不是时间差启发式）
        c_sigs = [sig for sig in sigs if getattr(sig, "sell_reason", "") == "C_vwap"]
        # 同股去重
        seen = set()
        c_dedup = []
        for sig in c_sigs:
            key = (sig.trade_date, sig.pick_code)
            if key in seen:
                continue
            seen.add(key)
            c_dedup.append(sig)
        print(f"\n=== {td}: 信号 {len(sigs)} / C 分支 {len(c_sigs)} / 去重 {len(c_dedup)} ===")
        for sig in c_dedup:
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

    out = []
    out.append("# C VWAP 止损卖出对错分析（基于真实 sell_reason 字段）\n\n")
    out.append(f"分析范围: {' / '.join(args.dates)}\n")
    out.append(f"总笔数: {len(all_results)}\n\n")
    out.append("## 判定逻辑\n\n")
    out.append("C 止损本意：underlying 跌破当日 VWAP → 假设走弱 → 提前避损。\n")
    out.append("但 CB 跟风债买入早（事中L1时刻），underlying 可能暂时回调后再涨。\n\n")
    out.append("**判定规则:**\n")
    out.append("- ✅ **C 救对（避损）**: 卖后剩余最低 ≤ -2% 或当日收 ≤ -2%（不卖会更亏）\n")
    out.append("- ❌ **C 误杀（踏空）**: 当日收 ≥ +1% 或次日开 ≥ +1.5%（不卖会赚）\n")
    out.append("- ⚪ **C 中性**: 横盘震荡，卖与不卖差别不大\n\n")

    out.append("## 数据明细\n\n")
    out.append("| # | 日期 | 主线 | 债代码 | 债名 | 正股 | 卖时刻 | 买价 | 卖价 |"
               " 剩余最高 | 剩余最低 | 当日14:55 | 次日09:30 | 次日14:55 | 次日最高 | 评判 | 备注 |\n")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")

    save_correct = 0
    miss_correct = 0
    neutral = 0

    for i, r in enumerate(all_results, 1):
        sig = r["sig"]
        verdict, note = evaluate_c(r)
        if "误杀" in verdict:
            miss_correct += 1
        elif "救对" in verdict:
            save_correct += 1
        else:
            neutral += 1

        def fmt(v):
            return f"{v:.3f}" if v else "—"

        sell = r["sell_price"]
        sell_t = sig.sell_anchor_time
        sell_hhmm = f"{sell_t[:2]}:{sell_t[2:4]}" if sell_t else "—"

        out.append(
            f"| {i} | {sig.trade_date} | {sig.sector} | {sig.pick_code} | {r['cb_name']} | "
            f"{sig.underlying_code or '—'} {r['underlying_name']} | {sell_hhmm} | "
            f"{fmt(r['buy_price'])} | {fmt(sell)} | "
            f"{fmt(r['rest_max'])} {pct(r['rest_max'], sell)} | "
            f"{fmt(r['rest_min'])} {pct(r['rest_min'], sell)} | "
            f"{fmt(r['today_close'])} {pct(r['today_close'], sell)} | "
            f"{fmt(r['next_open'])} {pct(r['next_open'], sell)} | "
            f"{fmt(r['next_close'])} {pct(r['next_close'], sell)} | "
            f"{fmt(r['next_max'])} {pct(r['next_max'], sell)} | "
            f"{verdict} | {note} |\n"
        )

    n = len(all_results)
    out.append(f"\n## 总览\n\n")
    out.append(f"- ✅ C 救对（避损）: **{save_correct} 笔** ({save_correct/max(n,1)*100:.0f}%)\n")
    out.append(f"- ❌ C 误杀（踏空）: **{miss_correct} 笔** ({miss_correct/max(n,1)*100:.0f}%)\n")
    out.append(f"- ⚪ C 中性: **{neutral} 笔** ({neutral/max(n,1)*100:.0f}%)\n")

    # 假设收益对照
    qty = 10
    real_pnl = sum((r["sell_price"] - r["buy_price"]) * qty for r in all_results)
    today_close_pnl = sum((r["today_close"] - r["buy_price"]) * qty for r in all_results if r["today_close"])
    next_open_pnl = sum((r["next_open"] - r["buy_price"]) * qty for r in all_results if r["next_open"])
    next_close_pnl = sum((r["next_close"] - r["buy_price"]) * qty for r in all_results if r["next_close"])
    rest_max_pnl = sum((r["rest_max"] - r["buy_price"]) * qty for r in all_results if r["rest_max"])
    next_max_pnl = sum((r["next_max"] - r["buy_price"]) * qty for r in all_results if r["next_max"])

    n_close = sum(1 for r in all_results if r["today_close"])
    n_no = sum(1 for r in all_results if r["next_open"])
    n_nc = sum(1 for r in all_results if r["next_close"])
    n_rm = sum(1 for r in all_results if r["rest_max"])
    n_nm = sum(1 for r in all_results if r["next_max"])

    out.append("\n## 假设收益对照（vs 真实 C VWAP 止损）\n\n")
    out.append("如果改成不同卖出策略，后续收益（不含手续费 / 每笔 10 张 CB）:\n\n")
    out.append("| 策略 | 笔数 | 总 PnL | 平均每笔 | vs 真实 C 卖 |\n")
    out.append("|---|---|---|---|---|\n")
    out.append(f"| **真实 C VWAP 止损（基线）** | {n} | ¥{real_pnl:+,.2f} | ¥{real_pnl/max(n,1):+.2f} | — |\n")
    out.append(f"| 持到当日 14:55（D fallback） | {n_close} | ¥{today_close_pnl:+,.2f} | ¥{today_close_pnl/max(n_close,1):+.2f} | {today_close_pnl - real_pnl:+,.2f} |\n")
    out.append(f"| 持到次日 09:30（A 隔夜） | {n_no} | ¥{next_open_pnl:+,.2f} | ¥{next_open_pnl/max(n_no,1):+.2f} | {next_open_pnl - real_pnl:+,.2f} |\n")
    out.append(f"| 持到次日 14:55 | {n_nc} | ¥{next_close_pnl:+,.2f} | ¥{next_close_pnl/max(n_nc,1):+.2f} | {next_close_pnl - real_pnl:+,.2f} |\n")
    out.append(f"| 当日剩余最高（理论极致） | {n_rm} | ¥{rest_max_pnl:+,.2f} | ¥{rest_max_pnl/max(n_rm,1):+.2f} | {rest_max_pnl - real_pnl:+,.2f} |\n")
    out.append(f"| 次日最高（理论极致） | {n_nm} | ¥{next_max_pnl:+,.2f} | ¥{next_max_pnl/max(n_nm,1):+.2f} | {next_max_pnl - real_pnl:+,.2f} |\n")

    out_path = Path(__file__).resolve().parents[2] / "reports" / "c_vwap_sell_analysis.md"
    out_path.write_text("".join(out), encoding="utf-8")
    print(f"\n=== 总览 ===")
    print(f"  ✅ 救对: {save_correct} | ❌ 误杀: {miss_correct} | ⚪ 中性: {neutral}")
    print(f"  真实 C PnL ¥{real_pnl:+.2f}")
    print(f"  改 D fallback PnL ¥{today_close_pnl:+.2f} ({today_close_pnl-real_pnl:+.2f})")
    print(f"  改 A 隔夜 PnL ¥{next_open_pnl:+.2f} ({next_open_pnl-real_pnl:+.2f})")
    print(f"\n→ {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
