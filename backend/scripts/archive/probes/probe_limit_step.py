import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from sqlalchemy import text


async def main():
    async with async_session() as s:
        r = await s.execute(text("SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM limit_step"))
        print("limit_step:", r.fetchone())

        codes = ['002081.SZ', '600246.SH', '000066.SZ', '688256.SH', '603095.SH']
        r = await s.execute(text(
            "SELECT ts_code, name, nums FROM limit_step "
            "WHERE trade_date='20260430' AND ts_code = ANY(:codes)"
        ), {"codes": codes})
        print("\nlimit_step 4/30:")
        for row in r.fetchall():
            print(" ", row)

        # 也看看更全的几个有趣股
        r = await s.execute(text(
            "SELECT ts_code, name, nums FROM limit_step WHERE trade_date='20260430' "
            "ORDER BY nums DESC LIMIT 10"
        ))
        print("\n4/30 最高板:")
        for row in r.fetchall():
            print(" ", row)


if __name__ == "__main__":
    asyncio.run(main())
