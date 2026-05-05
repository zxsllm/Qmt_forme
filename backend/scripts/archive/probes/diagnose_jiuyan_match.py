"""诊断：4/30 韭研图里"国产芯片*9"的 9 只股票，在 concept_detail 里都挂什么概念。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from sqlalchemy import text


# 韭研 4/30 全天复盘的几个主线 + 票
JIUYAN_4_30 = {
    "国产芯片*9": [
        "002081.SZ", "002989.SZ", "600246.SH", "000066.SZ", "000628.SZ",
        "002158.SZ", "688256.SH", "002685.SZ", "603687.SH",
    ],
    "电池产业链*7": [
        "603399.SH", "002192.SZ", "002805.SZ", "002785.SZ", "002240.SZ",
        "000628.SZ", "000833.SZ",  # 注意 7 只
    ],
    "机器人*6": [
        "600400.SH", "603178.SH", "300885.SH", "688400.SH", "002870.SZ", "603897.SH",
    ],
    "算力*5": [
        "603095.SH", "002990.SZ", "688521.SH", "605376.SH", "002929.SZ",
    ],
}


async def main():
    async with async_session() as s:
        for jiuyan_sector, codes in JIUYAN_4_30.items():
            print(f"\n=== {jiuyan_sector} ===")
            for code in codes:
                r = await s.execute(text(
                    "SELECT concept_name FROM concept_detail "
                    "WHERE ts_code=:c ORDER BY concept_name"
                ), {"c": code})
                concepts = [row[0] for row in r.fetchall()]
                # 取个名字
                r2 = await s.execute(text(
                    "SELECT name FROM stock_basic WHERE ts_code=:c"
                ), {"c": code})
                name = r2.scalar() or "?"
                print(f"  {code} {name}: {len(concepts)} 个概念")
                # 打印关键词命中的
                hits = [c for c in concepts if any(k in c for k in ["芯", "AI", "半导体", "电池", "机器", "锂", "算力", "数据", "服务器"])]
                if hits:
                    print(f"     命中关键词: {hits[:8]}")
                else:
                    print(f"     全部概念: {concepts[:8]}")


if __name__ == "__main__":
    asyncio.run(main())
