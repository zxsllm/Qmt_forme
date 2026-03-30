"""Analyze market-wide overnight gap distribution.

Checks if (next_open / today_close - 1) is systematically negative,
which would make any long-only overnight gap strategy unviable.
"""
import asyncio
import sys
sys.path.insert(0, "backend")

import numpy as np
import pandas as pd


async def main():
    from app.shared.data.data_loader import DataLoader
    loader = DataLoader()

    start, end = "20251001", "20260327"
    cal = await loader.trade_calendar("20251001", end)
    trade_dates = [d for d in cal if start <= d <= end]

    print(f"Loading daily data {start}~{end} ...")
    daily = await loader._query(
        "SELECT ts_code, trade_date, open, close, vol, amount "
        "FROM stock_daily WHERE trade_date >= :s AND trade_date <= :e "
        "AND vol > 0",
        {"s": start, "e": end},
    )
    daily = daily.sort_values(["ts_code", "trade_date"])

    # Compute overnight gap: next_open / today_close - 1
    daily["next_open"] = daily.groupby("ts_code")["open"].shift(-1)
    daily["next_date"] = daily.groupby("ts_code")["trade_date"].shift(-1)
    daily = daily.dropna(subset=["next_open"])

    # Filter: only liquid stocks (amount in 千元, 50000 = 5000万 daily turnover)
    daily = daily[daily["amount"] > 50000]

    daily["gap_pct"] = (daily["next_open"] / daily["close"] - 1) * 100

    print(f"\n{'='*60}")
    print(f"  Market-wide Overnight Gap Analysis ({start}~{end})")
    print(f"{'='*60}")
    print(f"  Total observations: {len(daily):,}")
    print(f"  Unique stocks:      {daily['ts_code'].nunique():,}")
    print(f"  Trading days:       {len(trade_dates)}")
    print()
    print(f"  Mean overnight gap:   {daily['gap_pct'].mean():+.4f}%")
    print(f"  Median overnight gap: {daily['gap_pct'].median():+.4f}%")
    print(f"  Std overnight gap:    {daily['gap_pct'].std():.4f}%")
    print(f"  % positive gaps:      {(daily['gap_pct'] > 0).mean()*100:.1f}%")
    print(f"  % negative gaps:      {(daily['gap_pct'] < 0).mean()*100:.1f}%")
    print()

    # By month
    daily["month"] = daily["trade_date"].str[:6]
    monthly = daily.groupby("month")["gap_pct"].agg(["mean", "median", "count"])
    print("  Monthly average overnight gap:")
    for m, row in monthly.iterrows():
        print(f"    {m}: mean={row['mean']:+.4f}%  median={row['median']:+.4f}%  n={int(row['count']):,}")

    # Quintile analysis: what if we could perfectly sort stocks?
    print(f"\n  Quintile analysis (by actual gap):")
    daily["q"] = pd.qcut(daily["gap_pct"], 5, labels=["Q1(worst)", "Q2", "Q3", "Q4", "Q5(best)"])
    for q, g in daily.groupby("q", observed=True):
        print(f"    {q}: mean={g['gap_pct'].mean():+.4f}%  range=[{g['gap_pct'].min():+.2f}%, {g['gap_pct'].max():+.2f}%]")

    # Conditional: overnight gap for stocks that went UP on the day (close > open)
    up_day = daily[daily["close"] > daily["open"]]
    dn_day = daily[daily["close"] < daily["open"]]
    print(f"\n  Conditional overnight gap:")
    print(f"    Up-day stocks (close>open):  n={len(up_day):,}  mean_gap={up_day['gap_pct'].mean():+.4f}%  pos_rate={((up_day['gap_pct']>0).mean()*100):.1f}%")
    print(f"    Down-day stocks (close<open): n={len(dn_day):,}  mean_gap={dn_day['gap_pct'].mean():+.4f}%  pos_rate={((dn_day['gap_pct']>0).mean()*100):.1f}%")

    # Tail analysis: last-hour return vs overnight gap
    # Using close price vs some approximation of 14:00 price (we'll use the daily change direction)
    big_up = daily[daily["close"] / daily["open"] - 1 > 0.02]
    big_dn = daily[daily["close"] / daily["open"] - 1 < -0.02]
    print(f"    Big up (>2%):  n={len(big_up):,}  mean_gap={big_up['gap_pct'].mean():+.4f}%  pos_rate={((big_up['gap_pct']>0).mean()*100):.1f}%")
    print(f"    Big dn (<-2%): n={len(big_dn):,}  mean_gap={big_dn['gap_pct'].mean():+.4f}%  pos_rate={((big_dn['gap_pct']>0).mean()*100):.1f}%")


if __name__ == "__main__":
    asyncio.run(main())
