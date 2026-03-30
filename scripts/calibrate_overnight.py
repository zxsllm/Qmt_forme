"""Threshold calibration for OvernightGap V2."""

from __future__ import annotations

import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.research.strategies.overnight_gap import run_backtest

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)-5s %(name)s - %(message)s",
)
logging.getLogger("app.research.strategies.overnight_gap").setLevel(logging.INFO)


async def main():
    train_start, train_end = "20251001", "20260110"
    val_start, val_end = "20260112", "20260327"

    thresholds = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]

    print("=" * 80)
    print("  OvernightGap V2 阈值校准 (V8-style factors)")
    print(f"  训练集: {train_start} ~ {train_end}")
    print(f"  验证集: {val_start} ~ {val_end}")
    print("=" * 80)

    print(f"\n{'阈值':>6} {'交易':>5} {'胜率':>6} {'总收益%':>8} {'年化%':>8} "
          f"{'夏普':>7} {'回撤%':>7} {'盈亏比':>6}")
    print("-" * 62)

    results = []
    for thr in thresholds:
        s = await run_backtest(
            start_date=train_start, end_date=train_end,
            initial_capital=100_000, max_buy=3, lot_size=100,
            buy_threshold=thr,
        )
        results.append((thr, s))
        print(f"  {thr:.2f}  {s.total_trades:>5d}  {s.win_rate:>5.1f}%  "
              f"{s.total_return:>+7.2f}%  {s.annual_return:>+7.2f}%  "
              f"{s.sharpe_ratio:>+6.2f}  {s.max_drawdown:>6.2f}%  {s.profit_factor:>5.2f}")

    best_thr, best_s = max(results, key=lambda x: x[1].sharpe_ratio)
    print(f"\n  >>> 训练集最优阈值: {best_thr:.2f} (夏普={best_s.sharpe_ratio:.4f})")

    print(f"\n{'='*60}")
    print(f"  验证集 ({val_start} ~ {val_end})")
    print(f"{'='*60}\n")

    nearby = sorted(set([max(0.50, best_thr - 0.05), best_thr, min(0.95, best_thr + 0.05)]))
    print(f"  {'阈值':>6} {'交易':>5} {'胜率':>6} {'总收益%':>8} {'夏普':>7} {'回撤%':>7}")
    for t in nearby:
        v = await run_backtest(
            start_date=val_start, end_date=val_end,
            initial_capital=100_000, max_buy=3, lot_size=100,
            buy_threshold=t,
        )
        print(f"  {t:.2f}  {v.total_trades:>5d}  {v.win_rate:>5.1f}%  "
              f"{v.total_return:>+7.2f}%  {v.sharpe_ratio:>+6.2f}  {v.max_drawdown:>6.2f}%")

    print()


if __name__ == "__main__":
    asyncio.run(main())
