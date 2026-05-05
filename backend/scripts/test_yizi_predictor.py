"""龙1 次日一字预测器验证：跑 4/28~4/30 所有板块，输出每个龙1 的评分分解。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from app.research.signals.long_head_detector import detect_long_head
from app.research.signals.long1_yizi_predictor import predict_long1_yizi, format_prediction
from app.research.strategies.base_pattern import load_sectors


async def run_one(td: str):
    print(f"\n{'='*80}\n>>> {td} 龙1 次日一字预测\n{'='*80}")
    async with async_session() as s:
        sectors = await load_sectors(s, td, "bankuai")
        for sec_name, codes in sectors.items():
            lh = await detect_long_head(s, td, codes, sector_name=sec_name)
            if not lh.long1:
                continue
            pred = await predict_long1_yizi(s, td, codes, lh)
            if not pred:
                continue
            print(format_prediction(pred))
            for k, v in pred.breakdown.items():
                print(f"      {k}: {v}")
            print()


async def main():
    dates = sys.argv[1:] if len(sys.argv) >= 2 else ["20260428", "20260429", "20260430"]
    for td in dates:
        await run_one(td)


if __name__ == "__main__":
    asyncio.run(main())
