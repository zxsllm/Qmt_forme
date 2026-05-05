"""一次性探针：看清 limit_stats / concept_detail 的当前可用数据范围。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from sqlalchemy import text


async def main():
    async with async_session() as s:
        r = await s.execute(
            text("SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM limit_stats WHERE \"limit\"=:l"),
            {"l": "U"},
        )
        print("limit_stats U:", r.fetchone())

        r = await s.execute(text("SELECT COUNT(*), COUNT(DISTINCT concept_code) FROM concept_detail"))
        print("concept_detail (rows, distinct concepts):", r.fetchone())

        r = await s.execute(text("SELECT COUNT(DISTINCT ts_code) FROM concept_detail"))
        print("concept_detail (distinct stocks):", r.fetchone())

        r = await s.execute(text(
            "SELECT trade_date, \"limit\", COUNT(*) FROM limit_stats "
            "WHERE trade_date BETWEEN '20260420' AND '20260430' "
            "GROUP BY trade_date, \"limit\" ORDER BY trade_date DESC, \"limit\""
        ))
        print("\nrecent limit_stats:")
        for row in r.fetchall():
            print(" ", row)

        # 抽一个最近交易日，看 join concept_detail 后多少股票有概念
        r = await s.execute(text(
            "SELECT MAX(trade_date) FROM limit_stats WHERE \"limit\"='U'"
        ))
        latest = r.scalar()
        print(f"\nlatest U-limit date: {latest}")

        if latest:
            r = await s.execute(text(
                "SELECT COUNT(DISTINCT ls.ts_code), "
                "       COUNT(DISTINCT cd.ts_code) "
                "FROM limit_stats ls "
                "LEFT JOIN concept_detail cd ON cd.ts_code = ls.ts_code "
                "WHERE ls.trade_date=:d AND ls.\"limit\"='U'"
            ), {"d": latest})
            row = r.fetchone()
            print(f"  涨停股票总数: {row[0]} | 有概念归属的: {row[1]}")

            r = await s.execute(text(
                "SELECT cd.concept_name, COUNT(DISTINCT ls.ts_code) AS cnt "
                "FROM limit_stats ls "
                "JOIN concept_detail cd ON cd.ts_code = ls.ts_code "
                "WHERE ls.trade_date=:d AND ls.\"limit\"='U' "
                "GROUP BY cd.concept_name "
                "ORDER BY cnt DESC LIMIT 15"
            ), {"d": latest})
            print(f"  top 15 概念出现频次：")
            for row in r.fetchall():
                print(f"    {row[0]:30s}  {row[1]}")


if __name__ == "__main__":
    asyncio.run(main())
