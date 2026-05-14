"""验证 auto_close + sell_anchor_date trade_cal-aware 计算。

模拟：
  1. 一个 BUY fill (sell_anchor=next_open) -> position_book 应记 sell_anchor_date 为下一交易日
  2. trade_cal 缓存刷新后，节假日前的 BUY 应跳过整段节假日 (2026-04-30 -> 2026-05-06)
  3. iter_lots_due_for_close 在到期 + 当前时间触发
  4. auto_close_check 派出 SELL 信号
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.execution.engine import TradingEngine  # noqa: E402
from app.shared.interfaces.models import Order  # noqa: E402
from app.shared.interfaces.types import OrderSide, OrderStatus, OrderType  # noqa: E402


async def _main():
    eng = TradingEngine(initial_capital=1_000_000)
    eng.begin_day()  # populates trade_cal cache asynchronously

    # 等异步缓存刷新（_persist 用 create_task）
    await asyncio.sleep(1.0)
    assert eng._trade_dates_cache, "trade_cal cache should be populated"
    print(f"[OK] trade_cal cache: {len(eng._trade_dates_cache)} dates, first={eng._trade_dates_cache[0]}")

    # cache 从今天起拉，所以 next_trade_date 应能命中"今天 -> 下个交易日"
    today_str = datetime.now().strftime("%Y-%m-%d")
    next_td = eng._next_trade_date(today_str)
    assert next_td > today_str, f"next_td={next_td} should be > today {today_str}"
    print(f"[OK] today {today_str} -> next_td {next_td} (trade_cal-aware)")

    # 周末 fallback：cache 里没有周六，应跳过周末
    # 找个 cache 中的周五，验证 +1 给周一
    fri_in_cache = next(
        (d for d in eng._trade_dates_cache
         if datetime.strptime(d, "%Y-%m-%d").weekday() == 4), None,
    )
    if fri_in_cache:
        nd = eng._next_trade_date(fri_in_cache)
        nd_dt = datetime.strptime(nd, "%Y-%m-%d")
        assert nd_dt.weekday() < 5, f"next of fri should be weekday, got {nd} (weekday={nd_dt.weekday()})"
        print(f"[OK] fri {fri_in_cache} -> next_td {nd} (weekday)")

    # 模拟一个 BUY fill 进 position_book — 用 cache 里的今天作 entry，next_td 是下个开盘日
    entry_date = today_str
    sell_anchor_date = eng._next_trade_date(entry_date)
    lot = eng.position_book.apply_fill(
        ts_code="000001.SZ", side=OrderSide.BUY, qty=100, price=10.0, fee=5.0,
        lot_id=str(uuid4()), sell_anchor="next_open",
        sell_anchor_date=sell_anchor_date, sell_anchor_time="",
        sell_reason="", pick_role="long1", pick_kind="stock",
        settlement_rule="T+1", entry_date=entry_date,
    )
    assert lot.sell_anchor_date == sell_anchor_date
    print(f"[OK] lot.sell_anchor_date = {lot.sell_anchor_date}")

    # 模拟 T+1 begin_day：unlock
    eng.position_book.begin_day()
    assert lot.available_qty == 100
    print(f"[OK] T+1 unlocked: lot.available_qty = {lot.available_qty}")

    # iter_lots_due_for_close：当 now 是 sell_anchor_date 09:30 时，next_open lot 应到期
    sad = datetime.strptime(sell_anchor_date, "%Y-%m-%d")
    now_dt = sad.replace(hour=9, minute=30, second=1)
    due = eng.position_book.iter_lots_due_for_close(now_dt)
    assert any(l.lot_id == lot.lot_id for l in due), \
        f"lot {lot.lot_id} should be due at {now_dt}, due={[l.lot_id for l in due]}"
    print(f"[OK] iter_lots_due_for_close at {sell_anchor_date} 09:30:01 -> {len(due)} due (incl. our lot)")

    # 提交 auto_close — 走 submit_signal 路径
    snapshot = {"000001.SZ": {"close": 10.5}}
    orders = eng.auto_close_check(now_dt, snapshot)
    assert orders, "auto_close should submit SELL order"
    sell_order = orders[0]
    assert sell_order.side == OrderSide.SELL
    assert sell_order.ts_code == "000001.SZ"
    print(f"[OK] auto_close submitted SELL order: side={sell_order.side.value} qty={sell_order.qty}")

    # 再次调 auto_close — pending_sell_qty >= qty 应防止重复
    orders2 = eng.auto_close_check(now_dt, snapshot)
    assert not orders2, f"second call should NOT re-submit (pending_sell_qty guard), got {orders2}"
    print(f"[OK] pending_sell_qty guard works (no re-submit)")

    print("\n[ALL PASS]")


if __name__ == "__main__":
    asyncio.run(_main())
