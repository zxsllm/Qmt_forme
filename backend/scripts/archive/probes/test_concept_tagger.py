"""手工跑算法 B 在 4/30 这一天的输出，对照韭研复盘图。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from app.research.signals.concept_tagger import compute_main_line, format_main_line_report


async def main():
    async with async_session() as s:
        sectors = await compute_main_line(s, "20260430", top_n=15, min_count=2)
    print(format_main_line_report(sectors))
    print()
    print(f"总主线数：{len(sectors)}")


if __name__ == "__main__":
    asyncio.run(main())
