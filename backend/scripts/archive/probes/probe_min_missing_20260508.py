"""一次性诊断：5/8 回测中 missing price 的 5 个标的，分钟K 在哪些时刻缺失。

跑完即归档（已放在 archive/probes/）。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.database import async_session
from sqlalchemy import text

# 5/8 missing price 涉及的标的
TARGETS = [
    ("stock_min_kline", "603459.SH", "红板科技 (PCB 龙1)"),
    ("cb_min_kline",    "111001.SH", "山东玻纤转债 (PCB 跟风)"),
    ("stock_min_kline", "603399.SH", "永杉锂业 (电池 龙1)"),
    ("stock_min_kline", "002031.SZ", "巨轮智能 (机器人/汽车 龙1)"),
    ("stock_min_kline", "000700.SZ", "模塑科技 (汽车 影子龙)"),
]

async def main():
    async with async_session() as s:
        for table, code, label in TARGETS:
            print(f"\n=== {label}  [{code}] in {table} ===")
            cnt = (await s.execute(text(
                f"SELECT COUNT(*) FROM {table} "
                f"WHERE trade_time >= '2026-05-08'::timestamp "
                f"AND trade_time < '2026-05-09'::timestamp AND ts_code=:c"
            ), {"c": code})).scalar()
            first_last = (await s.execute(text(
                f"SELECT MIN(trade_time), MAX(trade_time) FROM {table} "
                f"WHERE trade_time >= '2026-05-08'::timestamp "
                f"AND trade_time < '2026-05-09'::timestamp AND ts_code=:c"
            ), {"c": code})).fetchone()
            cnt_overall = (await s.execute(text(
                f"SELECT MIN(trade_time), MAX(trade_time), COUNT(*) FROM {table} "
                f"WHERE ts_code=:c"
            ), {"c": code})).fetchone()
            print(f"  5/8 分钟K 行数: {cnt}")
            if cnt:
                print(f"  5/8 时间区间: {first_last[0]} ~ {first_last[1]}")
            print(f"  全表覆盖: {cnt_overall[0]} ~ {cnt_overall[1]}  共 {cnt_overall[2]} 条")

asyncio.run(main())
