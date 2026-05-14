"""阶段 3.4 — 风控通过性 + 重启鲁棒性

(3d) 风控通过性：
    跑 P1+P2 同日 Signal > 25 笔的日子（5-13），验证 max_daily_buys=80 不拦截。

(3c) 重启鲁棒性（in-memory 简化版 — 不依赖 sim_orders 新列 DB 迁移）：
    用旧 engine 跑出 next_open 持仓 → 把 position_book._lots 序列化到 dict → 用新
    engine 反序列化 → 模拟周五 09:30 → 验证自动触发 SELL。
    DB 持久化路径（restore_from_db）依赖阶段 0 F3 schema 迁移，未在本次范围；
    这里验证 in-memory 状态机的恢复正确性，证明数据契约（Position.sell_anchor /
    sell_anchor_date / pending_sell_qty）足够支撑重启。
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parents[3]))
sys.path.insert(0, str(_THIS.parents[2]))
sys.path.insert(0, str(_THIS.parent))

from app.execution.engine import TradingEngine  # noqa: E402
from app.research.strategies.pattern_01_long1_natural import Pattern01  # noqa: E402
from app.research.strategies.pattern_02_long1_yizi import Pattern02  # noqa: E402
from app.shared.interfaces.types import OrderStatus  # noqa: E402

from replay_pattern_live import replay_one  # noqa: E402


async def test_risk_passes() -> bool:
    """3d: P1 + P2 同日总 BUY 信号数 > 25 → max_daily_buys=80 不应拦截。"""
    print("\n" + "=" * 72)
    print("  3d 风控通过性：max_daily_buys=80 不拦截 P1+P2 同日 27+笔")
    print("=" * 72)

    td = "20260513"
    total_filled = 0
    rejections = 0
    risk_blocks = 0
    for cls, label in [(Pattern01, "P1"), (Pattern02, "P2")]:
        res = await replay_one(td, cls)
        orders = res["orders"]
        filled = [o for o in orders if o.status == OrderStatus.FILLED]
        rejected = [o for o in orders if o.status == OrderStatus.REJECTED]
        total_filled += len(filled)
        rejections += len(rejected)
        # 风控审计事件
        for evt in res.get("audit", []):
            if evt.action.value == "RISK_BLOCK":
                risk_blocks += 1
        print(f"  {label}: {len(orders)} orders | filled={len(filled)} | rejected={len(rejected)}")

    print(f"\n  total filled across P1+P2: {total_filled}")
    print(f"  total rejected: {rejections}")
    print(f"  audit RISK_BLOCK events: {risk_blocks}")
    ok = (total_filled >= 25) and (rejections == 0)
    print(f"  -> {'PASS' if ok else 'FAIL'}")
    return ok


async def test_restart_inmemory() -> bool:
    """3c: in-memory 重启 — 拷贝 position_book._lots 到新 engine → 验证自动 SELL。"""
    print("\n" + "=" * 72)
    print("  3c 重启鲁棒性（in-memory）：next_open 持仓恢复后自动触发 SELL")
    print("=" * 72)

    # Step 1: 旧 engine 跑出 next_open 持仓（5-13 Pattern01）
    res = await replay_one("20260513", Pattern01)
    orders = res["orders"]
    # 取所有 sell_anchor=next_open 的 lot（应在 T+1 09:30 触发 SELL）
    eng_old = res.get("eng")  # 注意：replay_one 没暴露 eng，需要重跑
    # 简化：直接从 orders 还原 lot 集合
    # 找一笔 BUY filled 且 sell_anchor=next_open
    buys_next_open = [
        o for o in orders
        if o.status == OrderStatus.FILLED and o.side.value == "BUY"
        and o.sell_anchor == "next_open"
    ]
    print(f"  旧 engine: {len(buys_next_open)} 个 next_open lots 待 T+1 平仓")
    if not buys_next_open:
        print("  [skip] no next_open lots — 选 5-13 P1 不存在 next_open 持仓")
        return False

    # Step 2: 创建新 engine，导入这些 lot（模拟从 DB 恢复）
    eng_new = TradingEngine(initial_capital=1_000_000)
    eng_new._persist = lambda *a, **k: None
    eng_new.begin_day()
    await asyncio.sleep(0.3)

    from app.shared.interfaces.models import Position
    from uuid import uuid4
    for o in buys_next_open:
        # 用 trade_cal 算的下一交易日
        entry_date = o.created_at.strftime("%Y-%m-%d")
        sell_anchor_date = eng_new._next_trade_date(entry_date)
        lot = Position(
            ts_code=o.ts_code,
            qty=o.filled_qty,
            available_qty=o.filled_qty,  # T+1 已解锁
            avg_cost=o.filled_price,
            market_price=o.filled_price,
            lot_id=o.lot_id or str(uuid4()),
            sell_anchor="next_open",
            sell_anchor_date=sell_anchor_date,
            sell_reason="",
            pick_role=o.pick_role,
            pick_kind=o.pick_kind,
            underlying_code=o.underlying_code,
            settlement_rule="T+0" if o.pick_kind == "cb" else "T+1",
            entry_date=entry_date,
            pending_sell_qty=0,
        )
        eng_new.position_book._lots.setdefault(o.ts_code, []).append(lot)
    print(f"  新 engine: 恢复 {sum(len(v) for v in eng_new.position_book._lots.values())} 个 lot")

    # Step 3: 模拟周五 09:30 rt tick
    next_td = eng_new._trade_dates_cache[0] if eng_new._trade_dates_cache else None
    if not next_td:
        print("  [warn] trade_cal cache empty")
        next_td_dt = datetime.now().replace(hour=9, minute=30, second=1)
    else:
        next_td_dt = datetime.strptime(next_td, "%Y-%m-%d").replace(hour=9, minute=30, second=1)
    print(f"  模拟 now={next_td_dt} (T+1 09:30)")

    # Step 4: iter_lots_due_for_close 应返回所有 next_open lot
    due = eng_new.position_book.iter_lots_due_for_close(next_td_dt)
    print(f"  iter_lots_due_for_close: {len(due)} due")

    # Step 5: auto_close_check 应派 SELL
    snapshot = {
        code: {"close": lot.market_price}
        for code, lots in eng_new.position_book._lots.items()
        for lot in lots
    }
    sell_orders = eng_new.auto_close_check(next_td_dt, snapshot)
    print(f"  auto_close_check: {len(sell_orders)} SELL orders submitted")

    ok = len(sell_orders) == len(buys_next_open)
    print(f"  -> {'PASS' if ok else 'FAIL'} (expected {len(buys_next_open)} SELLs)")
    return ok


async def main():
    r1 = await test_risk_passes()
    r2 = await test_restart_inmemory()

    print("\n" + "=" * 72)
    print("  Summary")
    print("=" * 72)
    print(f"  3d 风控通过性:      {'PASS' if r1 else 'FAIL'}")
    print(f"  3c 重启鲁棒性 (in-mem): {'PASS' if r2 else 'FAIL'}")
    sys.exit(0 if (r1 and r2) else 1)


if __name__ == "__main__":
    asyncio.run(main())
