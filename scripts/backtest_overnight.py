"""Run the OvernightGap V2 strategy backtest from CLI.

Usage:
    python -m scripts.backtest_overnight --mode fixed --entry 1450
    python -m scripts.backtest_overnight --mode signal --threshold 0.45
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.research.strategies.overnight_gap import run_backtest, BacktestSummary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s - %(message)s",
)


def print_summary(s: BacktestSummary, mode: str) -> None:
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  尾盘隔夜策略 V2 [{mode}] 回测报告")
    print(f"{sep}\n")
    print(f"  回测区间:   {s.start_date} ~ {s.end_date}")
    print(f"  交易天数:   {s.trading_days}")
    print(f"  总交易笔数: {s.total_trades}")
    print(f"  盈利笔数:   {s.winning_trades}   亏损笔数: {s.losing_trades}")
    print(f"  胜率:       {s.win_rate:.1f}%")
    print()
    print(f"  总盈亏:     {s.total_pnl:>+,.2f} 元")
    print(f"  总收益率:   {s.total_return:>+.2f}%")
    print(f"  年化收益率: {s.annual_return:>+.2f}%")
    print(f"  最大回撤:   {s.max_drawdown:.2f}%")
    print(f"  夏普比率:   {s.sharpe_ratio:.4f}")
    print(f"  盈亏比:     {s.profit_factor:.2f}")
    print()
    print(f"  日均盈亏:   {s.avg_daily_pnl:>+,.2f} 元")
    print(f"  平均盈利:   {s.avg_win:>+,.2f} 元 / 笔")
    print(f"  平均亏损:   {s.avg_loss:>+,.2f} 元 / 笔")
    print(f"\n{sep}")

    if s.trade_log:
        print(f"\n  最近 20 笔交易明细:")
        print(f"  {'买入日':>10} {'卖出日':>10} {'代码':>10} {'名称':>8} "
              f"{'买时':>6} {'得分':>6} {'买价':>8} {'卖价':>8} "
              f"{'盈亏':>10} {'收益率':>7}")
        print(f"  {'-'*10} {'-'*10} {'-'*10} {'-'*8} "
              f"{'-'*6} {'-'*6} {'-'*8} {'-'*8} {'-'*10} {'-'*7}")
        for r in s.trade_log[-20:]:
            name_short = r.name[:4] if len(r.name) > 4 else r.name
            hm = f"{r.buy_minute // 100}:{r.buy_minute % 100:02d}"
            print(f"  {r.trade_date:>10} {r.next_date:>10} {r.ts_code:>10} "
                  f"{name_short:>8} {hm:>6} {r.buy_score:>6.3f} "
                  f"{r.buy_price:>8.2f} {r.sell_price:>8.2f} "
                  f"{r.pnl:>+10.2f} {r.ret:>+6.2f}%")

    if s.daily_pnl_list:
        pos = sum(1 for p in s.daily_pnl_list if p > 0)
        zero = sum(1 for p in s.daily_pnl_list if p == 0)
        neg = sum(1 for p in s.daily_pnl_list if p < 0)
        print(f"\n  日盈亏分布: 盈利 {pos} 天, 持平 {zero} 天, 亏损 {neg} 天")
        if pos + neg > 0:
            print(f"  日胜率:     {pos/(pos+neg)*100:.1f}%")

    if s.trade_log:
        from collections import Counter
        md = Counter(r.buy_minute for r in s.trade_log)
        top = md.most_common(5)
        print(f"  买入时间分布: {', '.join(f'{m//100}:{m%100:02d}({c})' for m,c in top)}")
    print()


async def main():
    parser = argparse.ArgumentParser(description="OvernightGap V2 backtest")
    parser.add_argument("--start", default="20251001")
    parser.add_argument("--end", default="20260327")
    parser.add_argument("--capital", type=float, default=100_000)
    parser.add_argument("--max-buy", type=int, default=3)
    parser.add_argument("--lot", type=int, default=100)
    parser.add_argument("--mode", choices=["fixed", "signal"], default="signal")
    parser.add_argument("--entry", type=int, default=1450, help="Entry HHMM for fixed mode")
    parser.add_argument("--threshold", type=float, default=0.45, help="Score threshold for signal mode")
    args = parser.parse_args()

    summary = await run_backtest(
        start_date=args.start, end_date=args.end,
        initial_capital=args.capital, max_buy=args.max_buy,
        lot_size=args.lot, mode=args.mode,
        entry_minute=args.entry, buy_threshold=args.threshold,
    )
    print_summary(summary, args.mode)


if __name__ == "__main__":
    asyncio.run(main())
