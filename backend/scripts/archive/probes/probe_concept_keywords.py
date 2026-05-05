"""验证 Tushare concept_detail 是否覆盖当日热点主线（芯片、算力、机器人、电池）。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from sqlalchemy import text


async def main():
    async with async_session() as s:
        for kw in ["芯片", "算力", "机器人", "电池", "AI", "半导体", "国产", "光伏", "锂"]:
            r = await s.execute(text(
                "SELECT concept_name, COUNT(DISTINCT ts_code) AS n "
                "FROM concept_detail WHERE concept_name LIKE :kw "
                "GROUP BY concept_name ORDER BY n DESC LIMIT 5"
            ), {"kw": f"%{kw}%"})
            rows = r.fetchall()
            print(f"\n=== 含 '{kw}' 的概念 ===")
            for row in rows:
                print(f"  {row[0]:30s}  覆盖 {row[1]} 只")


if __name__ == "__main__":
    asyncio.run(main())
