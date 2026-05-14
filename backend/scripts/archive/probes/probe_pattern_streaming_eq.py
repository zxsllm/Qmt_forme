"""Pattern1/2 batch (find_signals) vs streaming (on_bar) 等价性验证 — 阶段 1 出口门槛。

跑法：
    cd backend
    ../.venv/Scripts/python.exe scripts/archive/probes/probe_pattern_streaming_eq.py [td=20260513] [pattern=both|1|2]

验证：
    Path A — 通过 strategy.find_signals(session, td) 拿到 PatternSignal 列表
    Path B — 手动构造 streaming：warm_up → on_init → 按分钟从 DB 取该分钟 watched
             bars → strategy.on_bar(td, bars) → 收集 strategy._pattern_signals
    门槛（严格）：数量一致 + (ts_code, pick_role, sell_anchor, sell_anchor_time,
                              buy_anchor_time) 五元组逐笔一致

注意：
    Path A 内部也走 on_bar 主循环（基类 find_signals 是 thin wrapper），所以
    本质上是验证"一次性预拉全天 bars 后 minute-by-minute dispatch" 与"按分钟从
    DB 拉 watched bars 后 dispatch"两种喂数方式的等价性 — 一致才能保证模拟盘
    streaming 与回测对得上。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# 让 scripts/ 能 import backend 的 app.*
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sqlalchemy import text  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.research.signals.long_head_detector import iter_trading_minutes  # noqa: E402
from app.research.strategies.pattern_01_long1_natural import Pattern01  # noqa: E402
from app.research.strategies.pattern_02_long1_yizi import Pattern02  # noqa: E402
from app.shared.interfaces.models import BacktestConfig, BacktestContext, BarData  # noqa: E402


COMPARE_FIELDS = ("pick_code", "pick_role", "sell_anchor", "sell_anchor_time", "buy_anchor_time")


def _signal_key(ps) -> tuple:
    return tuple(getattr(ps, f) or "" for f in COMPARE_FIELDS)


async def _fetch_bars_for_minute(
    session, trade_date: str, minute_dt: datetime,
    stock_codes: list[str], cb_codes: list[str],
) -> dict[str, BarData]:
    """从 DB 取该分钟的所有 watched bars（stock + cb）。"""
    bars: dict[str, BarData] = {}
    if stock_codes:
        rows = (await session.execute(text(
            "SELECT m.ts_code, m.trade_time, m.open, m.high, m.low, m.close, "
            "       m.vol, m.amount, d.pre_close "
            "FROM stock_min_kline m "
            "LEFT JOIN stock_daily d ON d.trade_date=:td AND d.ts_code=m.ts_code "
            "WHERE m.ts_code = ANY(:codes) "
            "  AND m.trade_time = :mt AND m.freq='1min'"
        ), {"td": trade_date, "codes": stock_codes, "mt": minute_dt})).fetchall()
        for ts_code, tt, o, h, l, c, v, amt, pre in rows:
            if c is None:
                continue
            bars[ts_code] = BarData(
                ts_code=ts_code, timestamp=tt.replace(second=0, microsecond=0),
                open=float(o) if o is not None else float(c),
                high=float(h) if h is not None else float(c),
                low=float(l) if l is not None else float(c),
                close=float(c),
                vol=float(v) if v is not None else 0.0,
                amount=float(amt) if amt is not None else 0.0,
                pre_close=float(pre) if pre is not None else None,
                freq="1min",
            )
    if cb_codes:
        rows = (await session.execute(text(
            "SELECT m.ts_code, m.trade_time, m.open, m.high, m.low, m.close, "
            "       m.vol, m.amount, cd.pre_close "
            "FROM cb_min_kline m "
            "LEFT JOIN cb_daily cd ON cd.trade_date=:td AND cd.ts_code=m.ts_code "
            "WHERE m.ts_code = ANY(:codes) "
            "  AND m.trade_time = :mt AND m.freq='1min'"
        ), {"td": trade_date, "codes": cb_codes, "mt": minute_dt})).fetchall()
        for ts_code, tt, o, h, l, c, v, amt, pre in rows:
            if c is None:
                continue
            bars[ts_code] = BarData(
                ts_code=ts_code, timestamp=tt.replace(second=0, microsecond=0),
                open=float(o) if o is not None else float(c),
                high=float(h) if h is not None else float(c),
                low=float(l) if l is not None else float(c),
                close=float(c),
                vol=float(v) if v is not None else 0.0,
                amount=float(amt) if amt is not None else 0.0,
                pre_close=float(pre) if pre is not None else None,
                freq="1min",
            )
    return bars


async def run_one(td: str, strategy_cls, label: str) -> bool:
    print(f"\n{'='*72}\n  {label} @ {td}\n{'='*72}")

    # Path A: 通过 find_signals
    async with async_session() as s:
        sa = strategy_cls()
        sigs_a = await sa.find_signals(s, td)
    print(f"[A] find_signals: {len(sigs_a)} signals")

    # Path B: 手动 streaming
    async with async_session() as s:
        sb = strategy_cls()
        await sb.warm_up(s, td)
        if not sb.sectors:
            print(f"[B] no sectors — skip")
            return len(sigs_a) == 0

        stock_codes = list({c for cs in sb.sectors.values() for c in cs})
        cb_codes = list(set(sb.cb_resolver_cache.values()))

        config = BacktestConfig(
            strategy_name=sb.name or sb.pattern_id, start_date=td, end_date=td,
        )
        ctx = BacktestContext(
            config=config, trade_dates=[td], universe_codes=stock_codes,
        )
        sb.on_init(ctx)

        for minute_dt in iter_trading_minutes(td):
            bars = await _fetch_bars_for_minute(s, td, minute_dt, stock_codes, cb_codes)
            sb.on_bar(td, bars)
        # streaming 收尾兜底（与 find_signals 一致）
        sb.on_stop()
        sigs_b = list(sb._pattern_signals)
    print(f"[B] streaming on_bar: {len(sigs_b)} signals")

    # 比较：先看总数
    if len(sigs_a) != len(sigs_b):
        print(f"!! 数量不一致: A={len(sigs_a)} B={len(sigs_b)}")
        keys_a = [_signal_key(p) for p in sigs_a]
        keys_b = [_signal_key(p) for p in sigs_b]
        set_a = set(keys_a)
        set_b = set(keys_b)
        only_a = set_a - set_b
        only_b = set_b - set_a
        if only_a:
            print(f"  仅 A 有 ({len(only_a)} 条):")
            for k in list(only_a)[:10]:
                print(f"    {k}")
        if only_b:
            print(f"  仅 B 有 ({len(only_b)} 条):")
            for k in list(only_b)[:10]:
                print(f"    {k}")
        return False

    # 数量一致 → 比较有序的 key 列表
    keys_a = [_signal_key(p) for p in sigs_a]
    keys_b = [_signal_key(p) for p in sigs_b]
    mismatches = []
    for i, (ka, kb) in enumerate(zip(keys_a, keys_b)):
        if ka != kb:
            mismatches.append((i, ka, kb))
    if mismatches:
        print(f"!! {len(mismatches)} mismatches (order/fields differ, top 5):")
        for i, ka, kb in mismatches[:5]:
            print(f"  [{i}] A={ka}")
            print(f"      B={kb}")
        if sorted(keys_a) == sorted(keys_b):
            print(f"  set-equivalent (order differs only) -> PASS")
            return True
        return False

    print(f"[PASS] {label} strict equivalence: {len(sigs_a)} signals match")
    return True


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--td", default="20260513")
    p.add_argument("--pattern", default="both", choices=["1", "2", "both"])
    args = p.parse_args()

    targets = []
    if args.pattern in ("1", "both"):
        targets.append((Pattern01, "Pattern01"))
    if args.pattern in ("2", "both"):
        targets.append((Pattern02, "Pattern02"))

    results = []
    for cls, label in targets:
        ok = await run_one(args.td, cls, label)
        results.append((label, ok))

    print(f"\n{'='*72}\n  Summary\n{'='*72}")
    for label, ok in results:
        print(f"  {label}: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if all(ok for _, ok in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
