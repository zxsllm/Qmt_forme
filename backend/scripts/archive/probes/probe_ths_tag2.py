import asyncio
import sys
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
        # limit_type 取值分布
        r = await s.execute(text(
            "SELECT limit_type, COUNT(*) FROM limit_list_ths "
            "WHERE trade_date='20260430' GROUP BY limit_type"
        ))
        print("4/30 limit_type 分布:")
        for row in r.fetchall():
            print(" ", row)

        # 样本
        r = await s.execute(text(
            "SELECT ts_code, name, limit_type, tag, status, first_lu_time "
            "FROM limit_list_ths WHERE trade_date='20260430' LIMIT 8"
        ))
        print("\n--- 样本 ---")
        for row in r.fetchall():
            print(" ", row)

        # tag 频次
        r = await s.execute(text(
            "SELECT tag, COUNT(*) FROM limit_list_ths "
            "WHERE trade_date='20260430' AND tag IS NOT NULL "
            "GROUP BY tag ORDER BY COUNT(*) DESC LIMIT 25"
        ))
        print("\n--- 4/30 tag top 25 ---")
        for row in r.fetchall():
            print(f"  {row[1]:3d}  {row[0]}")

        # 韭研主线票的 tag 命中
        print("\n\n=== 韭研主线票的 ths.tag ===")
        for sector, codes in JIUYAN_4_30.items():
            print(f"\n{sector}")
            for code in codes:
                r = await s.execute(text(
                    "SELECT name, limit_type, tag FROM limit_list_ths "
                    "WHERE trade_date='20260430' AND ts_code=:c"
                ), {"c": code})
                row = r.fetchone()
                if row:
                    print(f"  {code} {row[0]:10s} type={row[1]} tag={row[2]}")
                else:
                    print(f"  {code} <未在 limit_list_ths 中>")


if __name__ == "__main__":
    asyncio.run(main())
