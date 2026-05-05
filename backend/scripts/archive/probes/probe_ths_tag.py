"""验证 limit_list_ths.tag 字段能否替代 concept_detail 做主线归类。

目标：看 4/30 涨停股的 ths.tag 是否覆盖韭研主线（国产芯片 / 算力 / 机器人 / 电池产业链）。
"""
import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from sqlalchemy import text


JIUYAN_4_30 = {
    "国产芯片*9": ["002081.SZ", "002989.SZ", "600246.SH", "000066.SZ", "000628.SZ", "002158.SZ", "688256.SH", "002685.SZ", "603687.SH"],
    "电池产业链*7": ["603399.SH", "002192.SZ", "002805.SZ", "002785.SZ", "002240.SZ", "000628.SZ", "000833.SZ"],
    "机器人*6": ["600400.SH", "603178.SH", "300885.SH", "688400.SH", "002870.SZ", "603897.SH"],
    "算力*5": ["603095.SH", "002990.SZ", "688521.SH", "605376.SH", "002929.SZ"],
    "商业航天*5": ["603131.SH", "002149.SZ", "603698.SH", "605222.SH", "001268.SZ"],
}


async def main():
    async with async_session() as s:
        # 1) 4/30 整体覆盖率
        r = await s.execute(text(
            "SELECT COUNT(*), COUNT(tag), COUNT(DISTINCT tag) "
            "FROM limit_list_ths WHERE trade_date='20260430' AND limit_type='U'"
        ))
        total, with_tag, distinct = r.fetchone()
        print(f"4/30 涨停 (THS 口径): {total} 只 | 有 tag: {with_tag} | distinct tags: {distinct}")

        # 2) tag 频次
        r = await s.execute(text(
            "SELECT tag, COUNT(*) FROM limit_list_ths "
            "WHERE trade_date='20260430' AND limit_type='U' AND tag IS NOT NULL "
            "GROUP BY tag ORDER BY COUNT(*) DESC LIMIT 25"
        ))
        print("\n--- 4/30 ths.tag top 25 ---")
        for tag, cnt in r.fetchall():
            print(f"  {cnt:3d}  {tag}")

        # 3) 验证韭研主线票的 tag 命中
        print("\n\n=== 韭研主线票的 ths.tag 命中情况 ===")
        for sector, codes in JIUYAN_4_30.items():
            print(f"\n{sector}")
            for code in codes:
                r = await s.execute(text(
                    "SELECT name, tag FROM limit_list_ths "
                    "WHERE trade_date='20260430' AND limit_type='U' AND ts_code=:c"
                ), {"c": code})
                row = r.fetchone()
                if row:
                    print(f"  {code} {row[0]:10s}  tag={row[1]}")
                else:
                    print(f"  {code} <未在 limit_list_ths 中>")

        # 4) 看下 tag 怎么分隔（"+" 或 " " 或 ","）
        r = await s.execute(text(
            "SELECT tag FROM limit_list_ths "
            "WHERE trade_date='20260430' AND limit_type='U' AND tag IS NOT NULL "
            "ORDER BY tag LIMIT 10"
        ))
        print("\n--- 样本 tag 原始值 ---")
        for row in r.fetchall():
            print(f"  '{row[0]}'")


if __name__ == "__main__":
    asyncio.run(main())
