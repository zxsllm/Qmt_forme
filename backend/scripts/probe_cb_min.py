"""探针：验证 ts.pro_bar(asset='CB', freq='1min') 在可转债上是否可用。

目的：
1. 确认积分/权限是否足够拉到分钟数据
2. 摸清返回字段、单次行数上限、最早可拉日期
3. 摸清单次调用耗时，估算全量 + 增量同步成本

无副作用：只 print，不写 DB。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tushare as ts
from app.core.config import settings

ts.set_token(settings.TUSHARE_TOKEN)


def show(label: str, df) -> None:
    if df is None or df.empty:
        print(f"  [{label}] EMPTY")
        return
    print(f"  [{label}] rows={len(df)} cols={list(df.columns)}")
    print(f"     min_t={df.iloc[-1].get('trade_time') or df.iloc[-1].get('trade_date')}")
    print(f"     max_t={df.iloc[0].get('trade_time') or df.iloc[0].get('trade_date')}")
    print(f"     sample_first_row={df.iloc[0].to_dict()}")


def main() -> None:
    # 任选一只活跃可转债：通过 cb_basic 拿一个
    pro = ts.pro_api()
    cb = pro.cb_basic(fields="ts_code,bond_short_name,list_date,delist_date,remain_size")
    print(f"== cb_basic 返回 {len(cb)} 行, 列={list(cb.columns)} ==")
    if "delist_date" in cb.columns:
        cb = cb[cb["delist_date"].isna() | (cb["delist_date"] == "")]
    print(f"== 活跃可转债 (排除已退市): {len(cb)} 只 ==")
    if cb.empty:
        print("没有活跃可转债，退出")
        return

    if "remain_size" in cb.columns:
        sample = cb.sort_values("remain_size", ascending=False).iloc[0]
    else:
        sample = cb.iloc[0]
    ts_code = sample["ts_code"]
    print(f"探针标的: {ts_code} {sample['bond_short_name']} 余额={sample['remain_size']}\n")

    # 1) 短窗口 (今天) - 验证基本可用
    print("== [1] 1min, 最近1天 ==")
    t0 = time.time()
    try:
        df = ts.pro_bar(
            ts_code=ts_code, asset="CB", freq="1min",
            start_date="2026-04-30 09:00:00", end_date="2026-04-30 16:00:00",
        )
        print(f"  耗时 {time.time()-t0:.2f}s")
        show("1day", df)
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")

    # 2) 5天窗口 - 看分页是否触发
    print("\n== [2] 1min, 最近5个交易日 ==")
    t0 = time.time()
    try:
        df = ts.pro_bar(
            ts_code=ts_code, asset="CB", freq="1min",
            start_date="2026-04-24 09:00:00", end_date="2026-04-30 16:00:00",
        )
        print(f"  耗时 {time.time()-t0:.2f}s")
        show("5day", df)
        if df is not None and not df.empty:
            dates = df["trade_time"].astype(str).str[:10].value_counts().sort_index()
            for d, n in dates.items():
                print(f"     {d}: {n} bars")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")

    # 3) 远期 - 看历史可拉到多远
    print("\n== [3] 1min, 半年前 (2025-11-01) 可达性 ==")
    try:
        df = ts.pro_bar(
            ts_code=ts_code, asset="CB", freq="1min",
            start_date="2025-11-03 09:00:00", end_date="2025-11-03 16:00:00",
        )
        show("2025-11-03", df)
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")

    # 4) 5min - 替代频率（如果 1min 不通可降级）
    print("\n== [4] 5min, 最近1天 ==")
    try:
        df = ts.pro_bar(
            ts_code=ts_code, asset="CB", freq="5min",
            start_date="2026-04-30 09:00:00", end_date="2026-04-30 16:00:00",
        )
        show("5min", df)
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
