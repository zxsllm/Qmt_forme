"""探测：Tushare stk_mins 在不同 start_date 格式下，对 4-29/4-30 的实际返回。"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.research.data.tushare_service import TushareService

svc = TushareService()
ts_code = "000001.SZ"


def show(label, **kw):
    df = svc.stk_mins(ts_code=ts_code, freq="1min", **kw)
    if df is None or df.empty:
        print(f"  {label}: EMPTY")
        return
    df = df.sort_values("trade_time")
    dates = df["trade_time"].astype(str).str[:10].value_counts().sort_index()
    print(f"  {label}: rows={len(df)}  min={df['trade_time'].iloc[0]}  max={df['trade_time'].iloc[-1]}")
    for d, n in dates.items():
        print(f"      {d}: {n}")


print(f"== probe: ts_code={ts_code} ==")

print("\n[A] dashed format, range covers 4-29 + 4-30")
show("start='2026-04-29 09:00:00' end='2026-04-30 16:00:00'",
     start_date="2026-04-29 09:00:00", end_date="2026-04-30 16:00:00")

print("\n[B] dashless (current bug?) format, same range")
show("start='20260429 09:00:00' end='20260430 16:00:00'",
     start_date="20260429 09:00:00", end_date="20260430 16:00:00")

print("\n[C] dashed, only 4-30")
show("start='2026-04-30 09:00:00' end='2026-04-30 16:00:00'",
     start_date="2026-04-30 09:00:00", end_date="2026-04-30 16:00:00")

print("\n[D] dashless, only 4-30")
show("start='20260430 09:00:00' end='20260430 16:00:00'",
     start_date="20260430 09:00:00", end_date="20260430 16:00:00")
