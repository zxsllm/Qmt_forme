"""探针 v2：直接调 stk_mins 给可转债 ts_code，看 tushare 后端是否兼容。

pro_bar(asset='CB') SDK 没实现分钟，但底层 stk_mins 是泛接口，
直接传 ts_code='113052.SH' 这种可转债代码可能也能返回数据。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.research.data.tushare_service import TushareService

svc = TushareService()


def show(label: str, df) -> None:
    if df is None or df.empty:
        print(f"  [{label}] EMPTY")
        return
    print(f"  [{label}] rows={len(df)} cols={list(df.columns)}")
    print(f"     range=[{df['trade_time'].min()} → {df['trade_time'].max()}]")
    print(f"     sample row: {df.iloc[0].to_dict()}")


# 用一只主流可转债：兴业转债 113052.SH (规模最大)
candidates = [
    ("113052.SH", "兴业转债 (沪市规模王)"),
    ("128136.SZ", "深市规模较大转债"),
    ("123178.SZ", "深市创业板转债"),
]

for code, name in candidates:
    print(f"\n== {code} {name} ==")
    t0 = time.time()
    try:
        df = svc.stk_mins(
            ts_code=code, freq="1min",
            start_date="2026-04-30 09:00:00", end_date="2026-04-30 16:00:00",
        )
        print(f"  耗时 {time.time()-t0:.2f}s")
        show("1day", df)
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")
