import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from sqlalchemy import text


async def main():
    codes = ['002081.SZ', '600246.SH', '000066.SZ', '688256.SH', '002989.SZ', '603095.SH']
    async with async_session() as s:
        r = await s.execute(text(
            "SELECT ts_code, name, first_time, last_time, limit_times, open_times, "
            "limit_amount, float_mv, amount FROM limit_stats "
            "WHERE trade_date='20260430' AND ts_code = ANY(:codes)"
        ), {"codes": codes})
        for row in r.fetchall():
            print(row)


if __name__ == "__main__":
    asyncio.run(main())
