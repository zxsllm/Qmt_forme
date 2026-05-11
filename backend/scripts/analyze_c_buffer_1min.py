"""分析 C VWAP 止损加 1 分钟缓冲的效果。

逻辑：
  - 重跑 pattern_01 拿所有 sell_reason=='C_vwap' 的信号
  - 对每笔，拉 underlying 在 sell_minute / +1min / +2min 的 close 和 vwap
  - 模拟 1min 缓冲：
    - 若 +1min underlying close >= +1min vwap → 「缓冲救回」，不止损（持到 14:55 看效果）
    - 若 +1min underlying close < +1min vwap → 「缓冲失败」，在 +1min 卖（CB 价更新）
  - 对照原 C 立止损 vs 1min 缓冲后 PnL

用法：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe \\
        backend/scripts/analyze_c_buffer_1min.py 20260429 20260430 20260506 20260507
"""
import argparse
import asyncio
import io
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.database import async_session  # noqa: E402
from app.research.data.cb_resolver import fetch_min_close_at  # noqa: E402
from app.research.signals.long_head_detector import (  # noqa: E402
    compute_vwap_until, fetch_minute_quotes,
)
from app.research.strategies.base_pattern import PatternSignal  # noqa: E402
from app.research.strategies.pattern_01_long1_natural import Pattern01  # noqa: E402
from sqlalchemy import text  # noqa: E402

from test_pattern_backtest import execute_signal, next_trade_date  # noqa: E402


def add_minutes_dt(dt: datetime, mins: int) -> datetime:
    return dt + timedelta(minutes=mins)


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


async def analyze_buffer(sig: PatternSignal, trade) -> dict | None:
    cb_code = sig.pick_code
    sell_t_str = sig.sell_anchor_time
    if not sell_t_str or not trade.sell_price:
        return None
    sell_dt = datetime.strptime(sig.trade_date, "%Y%m%d").replace(
        hour=int(sell_t_str[:2]), minute=int(sell_t_str[2:4])
    )
    plus1_dt = add_minutes_dt(sell_dt, 1)
    plus2_dt = add_minutes_dt(sell_dt, 2)

    async with async_session() as s:
        # 拉 underlying 全天分钟数据（用于算 vwap）
        u_quotes = await fetch_minute_quotes(s, sig.trade_date, [sig.underlying_code])
        # underlying 在 sell / +1 / +2 的 close
        q0 = u_quotes.get((sig.underlying_code, sell_dt))
        q1 = u_quotes.get((sig.underlying_code, plus1_dt))
        q2 = u_quotes.get((sig.underlying_code, plus2_dt))
        # underlying 在 sell / +1 / +2 的 累计 VWAP
        vwap0 = compute_vwap_until(u_quotes, sig.underlying_code, sell_dt)
        vwap1 = compute_vwap_until(u_quotes, sig.underlying_code, plus1_dt)
        vwap2 = compute_vwap_until(u_quotes, sig.underlying_code, plus2_dt)

        # CB 在 sell / +1 / +2 / 14:55 / 次日 09:30 的 close
        cb_sell = trade.sell_price
        cb_plus1 = await fetch_min_close_at(
            s, cb_code, sig.trade_date, plus1_dt.strftime("%H%M%S"),
            table="cb_min_kline",
        )
        cb_today_close = await fetch_min_close_at(
            s, cb_code, sig.trade_date, "145500", table="cb_min_kline",
        )
        t1 = await next_trade_date(sig.trade_date)
        cb_next_open = (await fetch_min_close_at(
            s, cb_code, t1, "093000", table="cb_min_kline",
        )) if t1 else None

        cb_name = await fetch_cb_name(s, cb_code)
        u_name = await fetch_stock_name(s, sig.underlying_code) if sig.underlying_code else "—"

    # 缓冲判定
    if q1 is None or vwap1 is None:
        buffer_status = "no_data"
        buffer_save = False
    elif q1.close >= vwap1:
        buffer_status = "rebound"  # +1min 回到 vwap 上方 → 缓冲救回
        buffer_save = True
    else:
        buffer_status = "still_below"  # +1min 仍跌破 → 缓冲失败
        buffer_save = False

    return {
        "sig": sig,
        "trade": trade,
        "cb_name": cb_name,
        "underlying_name": u_name,
        "u_close_0": q0.close if q0 else None,
        "u_close_1": q1.close if q1 else None,
        "u_close_2": q2.close if q2 else None,
        "u_vwap_0": vwap0,
        "u_vwap_1": vwap1,
        "u_vwap_2": vwap2,
        "cb_sell": cb_sell,
        "cb_plus1": cb_plus1,
        "cb_today_close": cb_today_close,
        "cb_next_open": cb_next_open,
        "buffer_status": buffer_status,
        "buffer_save": buffer_save,
    }


def fmt_pct(target, base):
    if target is None or base is None or base == 0:
        return "—"
    return f"{(target - base) / base * 100:+.2f}%"


def fmt(v, digits=3):
    return f"{v:.{digits}f}" if v is not None else "—"


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("dates", nargs="+")
    args = p.parse_args()

    pattern = Pattern01()
    all_results = []

    for td in args.dates:
        async with async_session() as s:
            sigs = await pattern.find_signals(s, td)
        c_sigs = [sig for sig in sigs if getattr(sig, "sell_reason", "") == "C_vwap"]
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
                continue
            r = await analyze_buffer(sig, trade)
            if r:
                all_results.append(r)
                print(f"  [{sig.pick_code} {r['cb_name']}] underlying={r['underlying_name']} "
                      f"卖 {sig.sell_anchor_time[:4]}: u_close={r['u_close_0']} vwap={r['u_vwap_0']} "
                      f"| +1min: close={r['u_close_1']} vwap={r['u_vwap_1']} → {r['buffer_status']}")

    out = []
    out.append("# C VWAP 止损「+1 分钟缓冲」效果分析\n\n")
    out.append(f"分析范围: {' / '.join(args.dates)}\n")
    out.append(f"总笔数: {len(all_results)}\n\n")
    out.append("## 缓冲规则\n\n")
    out.append("- 原 C 触发: underlying close < VWAP → 立刻卖\n")
    out.append("- 加 1min 缓冲: underlying close < VWAP 时不立刻卖，等 1 分钟\n")
    out.append("  - +1min underlying close ≥ VWAP → 「rebound 缓冲救回」，不止损（继续走状态机）\n")
    out.append("  - +1min underlying close < VWAP → 「still_below 缓冲失败」，在 +1min 时刻卖\n\n")

    save_count = sum(1 for r in all_results if r["buffer_save"])
    fail_count = sum(1 for r in all_results if not r["buffer_save"] and r["buffer_status"] != "no_data")
    out.append(f"## 缓冲分类\n\n")
    out.append(f"- 🟢 缓冲救回 (rebound): **{save_count} 笔** — +1min 回到均线上方\n")
    out.append(f"- 🔴 缓冲失败 (still_below): **{fail_count} 笔** — +1min 仍跌破\n\n")

    out.append("## 数据明细\n\n")
    out.append("| # | 日期 | 主线 | 债代码 | 债名 | 正股 | 卖时刻 |"
               " u_close@0 | u_vwap@0 | u_close@+1 | u_vwap@+1 | 缓冲结果 |"
               " CB卖价 | CB+1价 | CB14:55 | CB次日09:30 |\n")
    out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    for i, r in enumerate(all_results, 1):
        sig = r["sig"]
        sell_t = sig.sell_anchor_time
        sell_hhmm = f"{sell_t[:2]}:{sell_t[2:4]}" if sell_t else "—"
        status_label = {
            "rebound": "🟢 救回",
            "still_below": "🔴 失败",
            "no_data": "⚪ 缺数据",
        }.get(r["buffer_status"], "?")
        out.append(
            f"| {i} | {sig.trade_date} | {sig.sector} | {sig.pick_code} | {r['cb_name']} | "
            f"{sig.underlying_code} {r['underlying_name']} | {sell_hhmm} | "
            f"{fmt(r['u_close_0'], 2)} | {fmt(r['u_vwap_0'], 3)} | "
            f"{fmt(r['u_close_1'], 2)} | {fmt(r['u_vwap_1'], 3)} | {status_label} | "
            f"{fmt(r['cb_sell'], 2)} | {fmt(r['cb_plus1'], 2)} | "
            f"{fmt(r['cb_today_close'], 2)} | {fmt(r['cb_next_open'], 2)} |\n"
        )

    # 假设收益对照（每笔 10 张 CB）
    qty = 10
    real_pnl = sum((r["cb_sell"] - r["trade"].buy_price) * qty for r in all_results)

    # "1min 缓冲" 策略：
    #   - rebound: 不止损，假设持到 14:55（保守 D fallback）
    #   - still_below: 在 +1min 卖 (cb_plus1)，如果 cb_plus1 缺则用原 cb_sell
    buffer_pnl = 0
    rebound_pnl = 0
    still_pnl = 0
    n_buf_used = 0
    for r in all_results:
        bp = r["trade"].buy_price
        if r["buffer_save"]:
            sell = r["cb_today_close"] if r["cb_today_close"] else r["cb_sell"]
            d = (sell - bp) * qty
            rebound_pnl += d
        else:
            sell = r["cb_plus1"] if r["cb_plus1"] else r["cb_sell"]
            d = (sell - bp) * qty
            still_pnl += d
        buffer_pnl += d
        n_buf_used += 1

    # "1min 缓冲 + A 隔夜（rebound 走 A）" 备选：
    altA_pnl = 0
    for r in all_results:
        bp = r["trade"].buy_price
        if r["buffer_save"]:
            sell = r["cb_next_open"] if r["cb_next_open"] else r["cb_sell"]
        else:
            sell = r["cb_plus1"] if r["cb_plus1"] else r["cb_sell"]
        altA_pnl += (sell - bp) * qty

    out.append(f"\n## 假设收益对照（不含手续费 / 每笔 10 张）\n\n")
    out.append("| 策略 | 总 PnL | 平均每笔 | vs 原 C 立卖 |\n")
    out.append("|---|---|---|---|\n")
    out.append(f"| **原 C 立卖（基线）** | ¥{real_pnl:+,.2f} | ¥{real_pnl/max(len(all_results),1):+.2f} | — |\n")
    out.append(f"| 1min 缓冲（rebound 持到 14:55 / fail 在 +1min 卖） | ¥{buffer_pnl:+,.2f} | ¥{buffer_pnl/max(len(all_results),1):+.2f} | {buffer_pnl - real_pnl:+,.2f} |\n")
    out.append(f"| 1min 缓冲（rebound 持到次日 09:30 / fail 在 +1min 卖） | ¥{altA_pnl:+,.2f} | ¥{altA_pnl/max(len(all_results),1):+.2f} | {altA_pnl - real_pnl:+,.2f} |\n")
    out.append(f"\n（rebound 救回 {save_count} 笔贡献 ¥{rebound_pnl:+,.2f}, "
               f"still_below {fail_count} 笔贡献 ¥{still_pnl:+,.2f}）\n")

    out_path = Path(__file__).resolve().parents[2] / "reports" / "c_buffer_1min_analysis.md"
    out_path.write_text("".join(out), encoding="utf-8")
    print(f"\n=== 总览 ===")
    print(f"  🟢 缓冲救回: {save_count} | 🔴 缓冲失败: {fail_count}")
    print(f"  原 C 立卖 PnL ¥{real_pnl:+.2f}")
    print(f"  1min 缓冲 (D fallback) PnL ¥{buffer_pnl:+.2f} ({buffer_pnl-real_pnl:+.2f})")
    print(f"  1min 缓冲 (A 隔夜) PnL ¥{altA_pnl:+.2f} ({altA_pnl-real_pnl:+.2f})")
    print(f"\n→ {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
