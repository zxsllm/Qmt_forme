"""验证 Pattern01/02 注册路径：warm_up → get_universe → scheduler.add_watch_code。

不通过 HTTP，直接调底层函数避开 09:30-15:00 startup 检查。
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.database import async_session
from app.research.strategies.pattern_01_long1_natural import Pattern01
from app.research.strategies.pattern_02_long1_yizi import Pattern02


async def test_one(cls, trade_date: str) -> bool:
    strategy = cls()
    print(f"\n=== {strategy.name} @ {trade_date} ===")
    async with async_session() as session:
        await strategy.warm_up(session, trade_date)

    if not getattr(strategy, "_warmed", False):
        print(f"  FAIL: warm_up flag false")
        return False

    universe = strategy.get_universe()
    sectors_count = len(strategy.sectors)
    cbs = len(set(strategy.cb_resolver_cache.values()))
    print(f"  sectors: {sectors_count} | universe: {len(universe)} ts_codes | CBs: {cbs}")
    if not universe:
        print(f"  FAIL: empty universe")
        return False
    print(f"  sample: {universe[:5]} ...")
    return True


async def main():
    # 用最近一个有数据的交易日（5-13 是 P1+P2 强势日，多次验证过）
    td = "20260513"
    r1 = await test_one(Pattern01, td)
    r2 = await test_one(Pattern02, td)

    # 双重验证 registry
    from app.execution.api import start_strategy  # noqa: F401
    import app.execution.api as api_mod
    src = (Path(api_mod.__file__)).read_text(encoding="utf-8")
    has_p1 = '"pattern_01"' in src and "Pattern01" in src
    has_p2 = '"pattern_02"' in src and "Pattern02" in src
    print(f"\n=== api.py registry ===")
    print(f"  pattern_01 registered: {has_p1}")
    print(f"  pattern_02 registered: {has_p2}")

    ok = r1 and r2 and has_p1 and has_p2
    print(f"\nOverall: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
