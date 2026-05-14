"""P0.4 — 端到端联调 + DB 持久化 + 重启鲁棒性。

1. 清空 sim_*
2. 跑 Pattern01 @ 2026-05-13 完整一天（保留 _persist 真实写入 DB）
3. 校验 sim_orders 含 sell_anchor / pick_role / lot_id 等字段
4. 校验 sim_positions 多 lot 写入（lot_id 作 PK）
5. 新建 TradingEngine → await restore_from_db()
6. 模拟 T+1 09:30 → auto_close_check 应派 SELL

注：这是首次让 _persist 真实写 DB，所以早期可能暴露字段映射 bug。
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sqlalchemy import text

from app.core.database import async_session
from app.execution.engine import TradingEngine
from app.research.signals.long_head_detector import iter_trading_minutes
from app.research.strategies.pattern_01_long1_natural import Pattern01
from app.shared.interfaces.models import BacktestConfig, BacktestContext, BarData
from app.shared.interfaces.types import OrderSide, OrderStatus

# 复用 replay 工具的辅助函数
from replay_pattern_live import (
    _bars_to_snapshot,
    _fetch_full_day_bars,
    _fetch_price_limits,
    _resolve_next_trade_date,
)


async def clear_sim_tables():
    async with async_session() as s:
        for tbl in ("sim_trades", "sim_orders", "sim_positions", "sim_account"):
            await s.execute(text(f"delete from {tbl}"))
        await s.commit()


async def count_rows(tbl: str) -> int:
    async with async_session() as s:
        r = await s.execute(text(f"select count(*) from {tbl}"))
        return r.scalar() or 0


async def sample_rows(tbl: str, cols: list[str], limit: int = 3) -> list[dict]:
    sel = ", ".join(cols)
    async with async_session() as s:
        r = await s.execute(text(f"select {sel} from {tbl} limit {limit}"))
        return [dict(zip(cols, row)) for row in r.all()]


async def run_one_day(td: str) -> tuple[TradingEngine, dict]:
    """复用 replay 主循环逻辑，但保留 _persist 真实写入 DB。"""
    eng = TradingEngine(initial_capital=1_000_000)
    eng.set_risk_limits(max_daily_buys=80)
    from app.execution import matcher as _m
    _m.calc_slippage = lambda *a, **k: 0.01

    eng.begin_day()
    await asyncio.sleep(0.3)

    async with async_session() as s:
        limits = await _fetch_price_limits(s, td)
    eng.set_price_limits(limits)

    strategy = Pattern01()
    async with async_session() as s:
        await strategy.warm_up(s, td)

    universe_codes = list({c for cs in strategy.sectors.values() for c in cs})
    cb_codes = list(set(strategy.cb_resolver_cache.values()))

    ctx = BacktestContext(
        config=BacktestConfig(strategy_name=strategy.name, start_date=td, end_date=td),
        trade_dates=[td], universe_codes=universe_codes,
    )
    strategy.on_init(ctx)

    async with async_session() as s:
        td_bars = await _fetch_full_day_bars(s, td, universe_codes, cb_codes)

    traded_today = set()
    for minute_dt in iter_trading_minutes(td):
        bars = td_bars.get(minute_dt, {})
        if bars:
            try:
                eng.on_bar(bars)
            except Exception as e:
                print(f"  [warn] engine.on_bar @ {minute_dt}: {e}")

        signals = strategy.on_bar(td, bars)
        for sig in signals:
            if sig.side == OrderSide.BUY:
                key = ((td, sig.ts_code, "rebuy")
                       if sig.pick_role == "follower_cb_rebuy"
                       else (td, sig.ts_code))
                if key in traded_today:
                    continue
                traded_today.add(key)
            sig.timestamp = minute_dt
            try:
                eng.submit_signal(sig)
            except Exception as e:
                print(f"  [warn] submit_signal {sig.ts_code}: {e}")

        snapshot = _bars_to_snapshot(bars)
        try:
            eng.auto_close_check(minute_dt, snapshot)
        except Exception as e:
            print(f"  [warn] auto_close_check @ {minute_dt}: {e}")

    # 等所有 _persist 异步任务落库
    await asyncio.sleep(1.5)

    summary = {
        "buys_filled": sum(1 for o in eng.get_orders()
                           if o.status == OrderStatus.FILLED and o.side == OrderSide.BUY),
        "sells_filled": sum(1 for o in eng.get_orders()
                            if o.status == OrderStatus.FILLED and o.side == OrderSide.SELL),
        "total_orders": len(eng.get_orders()),
        "active_lots": sum(len(lots) for lots in eng.position_book._lots.values()),
    }
    return eng, summary


async def test_persist_and_restart(td: str = "20260513"):
    print("=" * 72)
    print(f"  P0.4 — End-to-end persist + restart @ {td}")
    print("=" * 72)

    print("\n[1] clear sim_*")
    await clear_sim_tables()
    for t in ("sim_orders", "sim_positions", "sim_account"):
        assert await count_rows(t) == 0, f"{t} not empty after clear"
    print("    OK: all sim_* tables empty")

    print(f"\n[2] run Pattern01 @ {td} with real DB persist")
    eng, summ = await run_one_day(td)
    print(f"    in-memory: BUY {summ['buys_filled']} filled, "
          f"SELL {summ['sells_filled']} filled, "
          f"total {summ['total_orders']} orders, "
          f"{summ['active_lots']} active lots")

    print("\n[3] verify DB rows")
    n_orders = await count_rows("sim_orders")
    n_positions = await count_rows("sim_positions")
    print(f"    sim_orders: {n_orders} rows")
    print(f"    sim_positions: {n_positions} rows (active lots after day end)")
    assert n_orders > 0, "sim_orders empty — persistence broken"

    print("\n[4] inspect sim_orders sample (sell_anchor / pick_role / lot_id)")
    rows = await sample_rows(
        "sim_orders",
        ["ts_code", "side", "status", "filled_qty", "filled_price",
         "sell_anchor", "pick_role", "pick_kind", "lot_id"],
        limit=5,
    )
    for r in rows:
        print(f"    {r['ts_code']:12s} {r['side']:4s} {r['status']:8s} "
              f"qty={r['filled_qty']:5d} px={r['filled_price'] or 0:.3f} "
              f"sell_anchor={r['sell_anchor']:12s} pick_role={r['pick_role']:18s} "
              f"pick_kind={r['pick_kind']:5s} lot={r['lot_id'][:8] if r['lot_id'] else '----'}")

    print("\n[5] inspect sim_positions sample (lot_id PK + sell_anchor_date)")
    rows = await sample_rows(
        "sim_positions",
        ["lot_id", "ts_code", "qty", "available_qty", "sell_anchor",
         "sell_anchor_date", "pick_role", "settlement_rule"],
        limit=5,
    )
    for r in rows:
        print(f"    lot={r['lot_id'][:8]} {r['ts_code']:12s} qty={r['qty']:5d} "
              f"avail={r['available_qty']:5d} "
              f"sell_anchor={r['sell_anchor']:12s} date={r['sell_anchor_date']:10s} "
              f"role={r['pick_role']:18s} settle={r['settlement_rule']}")

    next_open_lots_db = 0
    async with async_session() as s:
        r = await s.execute(text(
            "select count(*) from sim_positions where sell_anchor='next_open'"
        ))
        next_open_lots_db = r.scalar() or 0
    print(f"\n    next_open lots in DB: {next_open_lots_db}")
    if next_open_lots_db == 0:
        print("    [warn] no next_open lots — restart test will skip")

    print("\n[6] simulate restart: new TradingEngine.restore_from_db()")
    eng2 = TradingEngine(initial_capital=1_000_000)
    eng2.set_risk_limits(max_daily_buys=80)
    info = await eng2.restore_from_db()
    print(f"    restore_from_db result: {info}")
    eng2.begin_day()
    await asyncio.sleep(0.3)

    restored_lots = sum(len(lots) for lots in eng2.position_book._lots.values())
    restored_next_open = sum(
        1 for lots in eng2.position_book._lots.values()
        for lot in lots if lot.sell_anchor == "next_open"
    )
    print(f"    in-memory after restore: {restored_lots} lots "
          f"({restored_next_open} next_open)")

    print("\n[7] simulate T+1 09:30 tick → auto_close_check")
    # 用恢复后的 lot.sell_anchor_date 反推 now_dt（避免 wall-clock vs replay 日期错位）
    sell_anchor_dates = sorted({
        lot.sell_anchor_date for lots in eng2.position_book._lots.values()
        for lot in lots if lot.sell_anchor == "next_open"
    })
    if not sell_anchor_dates:
        print("    [skip] no next_open lots restored")
        return
    target_date = sell_anchor_dates[0]
    next_dt = datetime.strptime(target_date, "%Y-%m-%d").replace(hour=9, minute=30, second=1)
    print(f"    earliest sell_anchor_date in restored lots: {target_date}")
    print(f"    now_dt = {next_dt}")

    due = eng2.position_book.iter_lots_due_for_close(next_dt)
    print(f"    iter_lots_due_for_close: {len(due)} lots")

    snap = {
        code: {"close": lot.market_price}
        for code, lots in eng2.position_book._lots.items()
        for lot in lots
    }
    sells = eng2.auto_close_check(next_dt, snap)
    print(f"    auto_close_check submitted: {len(sells)} SELL orders")

    ok = (n_orders > 0
          and restored_lots >= max(0, summ["active_lots"])
          and (next_open_lots_db == 0 or len(sells) > 0))

    print("\n" + "=" * 72)
    print(f"  Overall: {'PASS' if ok else 'FAIL'}")
    print("=" * 72)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(test_persist_and_restart())
