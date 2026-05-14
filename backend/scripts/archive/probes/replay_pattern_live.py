"""阶段 3.1 — 回放历史 1min bar 驱动 Pattern 走完整 OMS 链路。

设计：
    历史 stock_min_kline + cb_min_kline → "假装"成 rt_k tick → 喂给 strategy.on_bar
    + trading_engine.on_bar + trading_engine.auto_close_check。直接调（不走 Redis
    pub/sub）以保证可重现。

每分钟执行顺序（与现实 live 系统时序对齐）：
    1. engine.on_bar(T 的 bars)         — 撮合 T-1 minute 提交的开仓单 → 在 T.open 成交
    2. strategy.on_bar(T, T 的 bars)    — 策略扫描，产出 Signal
    3. submit_signal 提交 → orders 入 OMS
    4. engine.auto_close_check(T, snapshot) — 触发到期 lot 的 SELL Signal
       注：intraday_at / today_close 在第 4 步发出后，下一分钟的第 1 步成交

T+1 处理：begin_day → 跑前几分钟，让 next_open SELL 触发并匹配。

输出：filled Order 列表（按 ts_code 配对 BUY/SELL → 计算 PnL），用于与
gen_backtest_report 输出的 PatternTrade 对账。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sqlalchemy import text  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.execution.engine import TradingEngine  # noqa: E402
from app.research.signals.long_head_detector import iter_trading_minutes  # noqa: E402
from app.research.strategies.pattern_01_long1_natural import Pattern01  # noqa: E402
from app.research.strategies.pattern_02_long1_yizi import Pattern02  # noqa: E402
from app.shared.interfaces.models import (  # noqa: E402
    BacktestConfig, BacktestContext, BarData, Order,
)
from app.shared.interfaces.types import OrderSide, OrderStatus  # noqa: E402

PATTERNS = {"1": Pattern01, "2": Pattern02}


async def _fetch_full_day_bars(
    session, td: str, stock_codes: list[str], cb_codes: list[str],
) -> dict[datetime, dict[str, BarData]]:
    """按分钟分组 (minute_dt → {ts_code → BarData})。"""
    by_minute: dict[datetime, dict[str, BarData]] = {}
    open_dt = datetime.strptime(td, "%Y%m%d").replace(hour=9, minute=30)
    close_dt = datetime.strptime(td, "%Y%m%d").replace(hour=15, minute=0)

    for table, codes in [("stock_min_kline", stock_codes), ("cb_min_kline", cb_codes)]:
        if not codes:
            continue
        # CB 的 pre_close 来自 cb_daily；stock 来自 stock_daily
        daily_table = "cb_daily" if table == "cb_min_kline" else "stock_daily"
        rows = (await session.execute(text(
            f"SELECT m.ts_code, m.trade_time, m.open, m.high, m.low, m.close, "
            f"       m.vol, m.amount, d.pre_close "
            f"FROM {table} m "
            f"LEFT JOIN {daily_table} d ON d.trade_date=:td AND d.ts_code=m.ts_code "
            f"WHERE m.ts_code = ANY(:codes) "
            f"  AND m.trade_time >= :open_dt AND m.trade_time <= :close_dt "
            f"  AND m.freq='1min'"
        ), {"td": td, "codes": codes, "open_dt": open_dt, "close_dt": close_dt})).fetchall()
        for ts_code, tt, o, h, l, c, v, amt, pre in rows:
            if c is None:
                continue
            mt = tt.replace(second=0, microsecond=0)
            bar = BarData(
                ts_code=ts_code, timestamp=mt,
                open=float(o) if o is not None else float(c),
                high=float(h) if h is not None else float(c),
                low=float(l) if l is not None else float(c),
                close=float(c),
                vol=float(v) if v is not None else 0.0,
                amount=float(amt) if amt is not None else 0.0,
                pre_close=float(pre) if pre is not None else None,
                freq="1min",
            )
            by_minute.setdefault(mt, {})[ts_code] = bar
    return by_minute


async def _fetch_price_limits(session, td: str) -> dict[str, tuple[float, float]]:
    rows = (await session.execute(text(
        "SELECT ts_code, up_limit, down_limit FROM stock_limit WHERE trade_date=:td"
    ), {"td": td})).fetchall()
    return {r[0]: (float(r[1]), float(r[2])) for r in rows
            if r[1] is not None and r[2] is not None}


async def _resolve_next_trade_date(session, td: str) -> str | None:
    r = await session.execute(text(
        "SELECT cal_date FROM trade_cal "
        "WHERE cal_date > :d AND is_open=1 "
        "ORDER BY cal_date LIMIT 1"
    ), {"d": td})
    row = r.fetchone()
    return row[0] if row else None


def _bars_to_snapshot(bars: dict[str, BarData]) -> dict[str, dict]:
    """BarData dict → rt_k-style snapshot dict（engine.auto_close_check 需要）。"""
    return {
        code: {
            "close": bar.close, "open": bar.open,
            "high": bar.high, "low": bar.low,
            "vol": bar.vol, "amount": bar.amount,
            "pre_close": bar.pre_close,
        }
        for code, bar in bars.items()
    }


async def replay_one(td: str, pattern_cls) -> dict:
    """单日单 Pattern 全链路回放。返回 {orders, trades, summary}。"""
    eng = TradingEngine(initial_capital=1_000_000)
    # 阶段 3 probe — DB 持久化未迁移（sim_orders 缺新列），临时禁用 _persist
    eng._persist = lambda *a, **k: None  # type: ignore[assignment]
    eng.set_risk_limits(max_daily_buys=80)
    # 与 backtest gen_backtest_report.execute_signal 对齐：禁用 volume-impact 滑点
    # （CB 1min 成交量稀，impact slippage 会塞进 5-10% 的额外价差），只保留 1 tick base
    # 必须 patch matcher 模块的 calc_slippage 引用（matcher 在 import 时已绑定）
    from app.execution import matcher as _m
    _m.calc_slippage = lambda *a, **k: 0.01  # 1 tick base only
    eng.begin_day()
    # 等异步 trade_cal 缓存
    await asyncio.sleep(0.3)

    # Load price limits
    async with async_session() as s:
        limits = await _fetch_price_limits(s, td)
    eng.set_price_limits(limits)

    # warm_up strategy
    strategy = pattern_cls()
    async with async_session() as s:
        await strategy.warm_up(s, td)
    if not strategy.sectors:
        return {"orders": [], "summary": {"total": 0, "note": "no sectors"}}

    universe_codes = list({c for cs in strategy.sectors.values() for c in cs})
    cb_codes = list(set(strategy.cb_resolver_cache.values()))
    all_codes = universe_codes + cb_codes

    ctx = BacktestContext(
        config=BacktestConfig(
            strategy_name=strategy.name, start_date=td, end_date=td,
        ),
        trade_dates=[td], universe_codes=universe_codes,
    )
    strategy.on_init(ctx)

    # Fetch T-day full bars + next_td first 5min bars
    async with async_session() as s:
        td_bars = await _fetch_full_day_bars(s, td, universe_codes, cb_codes)
        next_td = await _resolve_next_trade_date(s, td)
        if next_td:
            tn_bars = await _fetch_full_day_bars(s, next_td, universe_codes, cb_codes)
            # 也 set 下次日的涨停（用于 next_open 卖出时的 matcher 检查）
            tn_limits = await _fetch_price_limits(s, next_td)
        else:
            tn_bars, tn_limits = {}, {}

    print(f"  T={td} bars: {sum(len(b) for b in td_bars.values())} | "
          f"T+1={next_td} bars: {sum(len(b) for b in tn_bars.values())}")

    # 与 gen_backtest_report.py 同步的"每日单标的去重"集合
    #   - 一次性进场（long1/shadow/follower_cb 等）：key = (td, pick_code)
    #   - 买回：key = (td, pick_code, "rebuy")
    # OMS 自身 dedup 窗口只有 5min；跨窗口的多 sector 同 ts_code/role 信号会创建第二
    # 个 lot 但其 SELL 被 dedup 拦住 → "孤儿 lot"。对账时按回测口径预 dedup 屏蔽。
    traded_today: set[tuple] = set()

    # 主循环：T 日所有交易分钟
    for minute_dt in iter_trading_minutes(td):
        bars = td_bars.get(minute_dt, {})

        # 1. 先撮合（T-1 提交的 BUY 在 T.open 成交）
        if bars:
            try:
                eng.on_bar(bars)
            except Exception as e:
                print(f"  [warn] engine.on_bar @ {minute_dt}: {e}")

        # 2. 策略扫描
        signals = strategy.on_bar(td, bars)

        # 3. 提交 signals — 把 timestamp 改成 minute_dt（不是 wall-clock now），
        # 否则 order.created_at = 真实时间，entry_date 错位 → sell_anchor_date 错位 →
        # auto_close 永远不触发
        for sig in signals:
            # 与 gen_backtest_report.py 一致的去重 — 仅对 BUY 生效（每个标的当日最多
            # 1 笔进场 + 1 笔买回）；SELL 不去重（state machine 必须能为每个 BUY 配
            # 对一个 SELL，否则 lot 卡死）。
            if sig.side == OrderSide.BUY:
                if sig.pick_role == "follower_cb_rebuy":
                    key = (td, sig.ts_code, "rebuy")
                else:
                    key = (td, sig.ts_code)
                if key in traded_today:
                    continue
                traded_today.add(key)

            sig.timestamp = minute_dt
            try:
                eng.submit_signal(sig)
            except Exception as e:
                print(f"  [warn] submit_signal {sig.ts_code}: {e}")

        # 4. auto_close（intraday_at / today_close 触发）
        snapshot = _bars_to_snapshot(bars)
        try:
            eng.auto_close_check(minute_dt, snapshot)
        except Exception as e:
            print(f"  [warn] auto_close_check @ {minute_dt}: {e}")

    # T+1：跑 next_open SELL
    if next_td and tn_bars:
        eng.begin_day()
        await asyncio.sleep(0.1)
        eng.set_price_limits(tn_limits)
        # 跑 09:30 ~ 09:34 五分钟足够 next_open SELL 匹配
        next_open_dt = datetime.strptime(next_td, "%Y%m%d").replace(hour=9, minute=30)
        for delta in range(5):
            minute_dt = next_open_dt + timedelta(minutes=delta)
            bars = tn_bars.get(minute_dt, {})
            if bars:
                try:
                    eng.on_bar(bars)  # 匹配上一分钟提交的 SELL
                except Exception as e:
                    print(f"  [warn] T+1 engine.on_bar: {e}")
            snapshot = _bars_to_snapshot(bars)
            try:
                eng.auto_close_check(minute_dt, snapshot)
            except Exception as e:
                print(f"  [warn] T+1 auto_close_check: {e}")
        # 再跑一次 09:35 让 auto_close 派的 SELL 最终成交
        last_mt = next_open_dt + timedelta(minutes=5)
        last_bars = tn_bars.get(last_mt, {})
        if last_bars:
            eng.on_bar(last_bars)

    orders = eng.get_orders()
    trades = _pair_buy_sell(orders)
    summary = _summarize(trades, orders)
    return {"orders": orders, "trades": trades, "summary": summary, "strategy": strategy}


def _pair_buy_sell(orders: list[Order]) -> list[dict]:
    """配对 BUY/SELL（按 ts_code FIFO — 与 position_book 的 FIFO 卖 lot 行为一致）。

    OMS auto_close 用 lot_id 精确配对；strategy state machine SELL 用 lot_id=""，
    走 FIFO。本函数统一按 ts_code FIFO 配对（最早 BUY 配最早 SELL）。

    返回 [{"ts_code", "buy_price", "sell_price", "qty", "fee", "pnl", "ret_pct",
           "buy_anchor_time", "sell_anchor_time", "sell_reason", "pick_role"}]
    """
    filled = [o for o in orders if o.status == OrderStatus.FILLED and o.filled_qty > 0]
    by_code: dict[str, dict] = {}
    for o in filled:
        d = by_code.setdefault(o.ts_code, {"buys": [], "sells": []})
        if o.side == OrderSide.BUY:
            d["buys"].append(o)
        else:
            d["sells"].append(o)

    trades: list[dict] = []
    for ts_code, d in by_code.items():
        buys = sorted(d["buys"], key=lambda o: o.created_at)
        sells = sorted(d["sells"], key=lambda o: o.created_at)
        # FIFO 配对：最早 BUY ↔ 最早 SELL（同 qty 全量配，简化）
        for buy, sell in zip(buys, sells):
            qty = min(buy.filled_qty, sell.filled_qty)
            pnl = (sell.filled_price - buy.filled_price) * qty - buy.fee - sell.fee
            ret_pct = ((sell.filled_price - buy.filled_price) / buy.filled_price * 100
                       if buy.filled_price else 0)
            trades.append({
                "ts_code": ts_code,
                "buy_price": round(buy.filled_price, 3),
                "sell_price": round(sell.filled_price, 3),
                "qty": qty,
                "fee": round(buy.fee + sell.fee, 2),
                "pnl": round(pnl, 2),
                "ret_pct": round(ret_pct, 2),
                "buy_anchor_time": buy.buy_anchor_time,
                "sell_anchor_time": sell.sell_anchor_time,
                "sell_reason": sell.sell_reason,
                "pick_role": buy.pick_role,
            })
    return trades


def _summarize(trades: list[dict], orders: list[Order]) -> dict:
    total = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    pnl = sum(t["pnl"] for t in trades)
    cost = sum(t["buy_price"] * t["qty"] for t in trades)
    fees = sum(t["fee"] for t in trades)
    n_orders_total = len(orders)
    n_orders_filled = sum(1 for o in orders if o.status in (OrderStatus.FILLED, OrderStatus.PARTIAL_FILLED))
    return {
        "trades": total, "wins": len(wins), "losses": len(losses),
        "win_rate": (len(wins) / total * 100) if total else 0.0,
        "pnl": round(pnl, 2), "cost": round(cost, 2), "fees": round(fees, 2),
        "orders_total": n_orders_total, "orders_filled": n_orders_filled,
    }


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--td", default="20260513")
    p.add_argument("--pattern", default="1", choices=["1", "2"])
    args = p.parse_args()

    cls = PATTERNS[args.pattern]
    print(f"\n=== Replay Pattern{args.pattern} @ {args.td} ===")
    res = await replay_one(args.td, cls)
    s = res["summary"]
    print(f"\n  filled trades:  {s['trades']}")
    print(f"  wins / losses:  {s['wins']} / {s['losses']}  (win rate {s['win_rate']:.1f}%)")
    print(f"  total PnL:      {s['pnl']:+.2f}")
    print(f"  total cost:     {s['cost']:.2f}")
    print(f"  total fees:     {s['fees']:.2f}")
    print(f"  orders:         filled {s['orders_filled']} / total {s['orders_total']}")

    print(f"\n  trade detail (first 10):")
    for t in res["trades"][:10]:
        print(f"    {t['ts_code']:12s} {t['pick_role']:18s} "
              f"buy={t['buy_price']:.3f} sell={t['sell_price']:.3f} qty={t['qty']:5d} "
              f"pnl={t['pnl']:+8.2f} ret={t['ret_pct']:+.2f}% "
              f"reason={t['sell_reason']}")

    # 按 side 统计
    buys = [o for o in res["orders"] if o.side == OrderSide.BUY]
    sells = [o for o in res["orders"] if o.side == OrderSide.SELL]
    buys_filled = [o for o in buys if o.status == OrderStatus.FILLED]
    sells_filled = [o for o in sells if o.status == OrderStatus.FILLED]
    print(f"\n  by side: BUY {len(buys)} (filled {len(buys_filled)}) | "
          f"SELL {len(sells)} (filled {len(sells_filled)})")
    print(f"  SELL not-filled status breakdown:")
    from collections import Counter
    not_filled = Counter(o.status.value for o in sells if o.status != OrderStatus.FILLED)
    for st, n in not_filled.items():
        print(f"    {st}: {n}")
    print(f"  SELL unfilled detail:")
    for o in sells:
        if o.status == OrderStatus.FILLED:
            continue
        print(f"    SELL {o.ts_code:12s} qty={o.qty} created={o.created_at.strftime('%Y-%m-%d %H:%M:%S')} "
              f"lot={o.lot_id[:8] if o.lot_id else '----'} reason={o.sell_reason} "
              f"sell_anchor_time={o.sell_anchor_time} role={o.pick_role}")


if __name__ == "__main__":
    asyncio.run(main())
