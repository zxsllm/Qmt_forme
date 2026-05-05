"""测试龙头识别：用板块必读 daily 已确认的主线 + 成员，验证 long_head_detector。

用法：
    python backend/scripts/test_long_head.py 20260428 20260429 20260430
    python backend/scripts/test_long_head.py 20260430
    python backend/scripts/test_long_head.py            # 默认跑 4/28、4/29、4/30
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from app.research.signals.long_head_detector import detect_long_head, format_result
from sqlalchemy import text


async def run_one_day(td: str):
    print(f"\n{'='*70}\n>>> {td} 龙1 识别\n{'='*70}")
    async with async_session() as s:
        r = await s.execute(text(
            "SELECT sector_name, array_agg(ts_code ORDER BY board_count DESC) "
            "FROM daily_sector_review "
            "WHERE trade_date=:d AND source='bankuai' "
            "AND raw_meta->>'scope'='daily' "
            "AND sector_name NOT IN ('一季报预增','反弹','公告','其他') "
            "AND ts_code IS NOT NULL "
            "GROUP BY sector_name "
            "ORDER BY MIN(sector_rank)"
        ), {"d": td})
        rows = r.fetchall()

        if not rows:
            print(f"[skip] {td} 无板块必读 daily 数据")
            return

        for sec, codes in rows:
            res = await detect_long_head(s, td, codes, sector_name=sec)
            print(format_result(res))
            print()


async def main():
    if len(sys.argv) >= 2:
        dates = sys.argv[1:]
    else:
        dates = ["20260428", "20260429", "20260430"]
    for td in dates:
        await run_one_day(td)


if __name__ == "__main__":
    asyncio.run(main())
