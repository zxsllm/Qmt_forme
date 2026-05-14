"""每日对账：OMS 实盘 (DB sim_orders) vs 回测 (find_signals→execute_signal)。

输出到 `reports/oms_reconcile/YYYYMMDD/`：
  - pattern_01.json — 机器读：matched/mismatch/PnL 详情
  - pattern_01.txt  — 人看：成对交易清单 + 价差 + PnL diff
  - pattern_02.json
  - pattern_02.txt
  - summary.md      — 当日总结：本期实盘 vs 回测一致性

注意：对账门槛沿用 compare_replay_vs_backtest 的 v2 阈值
  - 买/卖价差 ≤ 1.0%
  - PnL 偏差 ≤ 10% 相对 或 ≤ 500 CNY 绝对
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from app.core.database import async_session

logger = logging.getLogger(__name__)


async def _fetch_db_orders(strategy_name: str, td: str) -> list[dict]:
    """从 sim_orders 拉当日实盘 FILLED orders，按 ts_code FIFO 配对 BUY/SELL → trades 列表。"""
    start_dt = datetime.strptime(td, "%Y%m%d")
    end_dt = start_dt.replace(hour=23, minute=59, second=59)

    async with async_session() as s:
        r = await s.execute(text(
            "SELECT ts_code, side, filled_qty, filled_price, fee, "
            "       sell_anchor, sell_anchor_time, sell_reason, pick_role, "
            "       buy_anchor_time, lot_id, created_at "
            "FROM sim_orders "
            "WHERE strategy_name = :sn "
            "  AND status = 'FILLED' "
            "  AND created_at >= :start AND created_at <= :end "
            "ORDER BY created_at"
        ), {"sn": strategy_name, "start": start_dt, "end": end_dt})
        rows = r.all()

    # FIFO 配对 BUY ↔ SELL by ts_code
    by_code: dict[str, dict] = {}
    for row in rows:
        d = by_code.setdefault(row[0], {"buys": [], "sells": []})
        rec = {
            "ts_code": row[0], "side": row[1],
            "qty": row[2], "price": float(row[3] or 0),
            "fee": float(row[4] or 0),
            "sell_anchor": row[5], "sell_anchor_time": row[6],
            "sell_reason": row[7], "pick_role": row[8],
            "buy_anchor_time": row[9], "lot_id": row[10],
            "created_at": row[11],
        }
        if rec["side"] == "BUY":
            d["buys"].append(rec)
        else:
            d["sells"].append(rec)

    trades: list[dict] = []
    for ts_code, d in by_code.items():
        for b, sell in zip(d["buys"], d["sells"]):
            qty = min(b["qty"], sell["qty"])
            pnl = (sell["price"] - b["price"]) * qty - b["fee"] - sell["fee"]
            trades.append({
                "ts_code": ts_code,
                "buy_price": round(b["price"], 3),
                "sell_price": round(sell["price"], 3),
                "qty": qty,
                "fee": round(b["fee"] + sell["fee"], 2),
                "pnl": round(pnl, 2),
                "buy_anchor_time": b["buy_anchor_time"],
                "sell_anchor": sell["sell_anchor"],
                "sell_anchor_time": sell["sell_anchor_time"],
                "sell_reason": sell["sell_reason"],
                "pick_role": b["pick_role"] or sell["pick_role"],
            })
    return trades


async def _fetch_backtest_trades(strategy_name: str, td: str) -> list[dict]:
    """复用 test_pattern_backtest.execute_signal 跑回测。"""
    from app.research.strategies.pattern_01_long1_natural import Pattern01
    from app.research.strategies.pattern_02_long1_yizi import Pattern02

    registry = {"pattern_01": Pattern01, "pattern_02": Pattern02}
    cls = registry.get(strategy_name)
    if not cls:
        return []

    strategy = cls()
    async with async_session() as session:
        sigs = await strategy.find_signals(session, td)

    # 与 gen_backtest_report 一致的 traded_today 去重
    import sys
    backend_scripts = Path(__file__).resolve().parents[2] / "scripts"
    if str(backend_scripts) not in sys.path:
        sys.path.insert(0, str(backend_scripts))
    from test_pattern_backtest import execute_signal  # type: ignore

    traded_today: set[tuple] = set()
    trades: list[dict] = []
    for sig in sigs:
        if sig.pick_role == "follower_cb_rebuy":
            key = (sig.trade_date, sig.pick_code, "rebuy")
        else:
            key = (sig.trade_date, sig.pick_code)
        if key in traded_today:
            continue
        try:
            trade = await execute_signal(sig)
        except Exception:
            logger.exception("execute_signal failed for %s", sig.pick_code)
            continue
        if trade.skip_reason:
            continue
        traded_today.add(key)
        trades.append({
            "ts_code": sig.pick_code,
            "pick_role": sig.pick_role,
            "buy_price": trade.buy_price,
            "sell_price": trade.sell_price,
            "qty": trade.qty,
            "fee": trade.fee,
            "pnl": trade.pnl,
            "sell_anchor": sig.sell_anchor,
        })
    return trades


def _pair_by_code_role(a: list[dict], b: list[dict]) -> list[tuple[dict | None, dict | None]]:
    """按 (ts_code, pick_role) 双向配对。"""
    a_by, b_by = {}, {}
    for t in a:
        a_by.setdefault((t["ts_code"], t.get("pick_role", "")), []).append(t)
    for t in b:
        b_by.setdefault((t["ts_code"], t.get("pick_role", "")), []).append(t)

    out = []
    for key in sorted(set(a_by) | set(b_by)):
        al, bl = a_by.get(key, []), b_by.get(key, [])
        for i in range(max(len(al), len(bl))):
            out.append((al[i] if i < len(al) else None,
                        bl[i] if i < len(bl) else None))
    return out


def _pct_diff(x: float | None, y: float | None) -> float:
    if x is None or y is None or x == 0:
        return float("inf")
    return abs((y - x) / x) * 100


async def _compare_one(strategy_name: str, td: str) -> dict:
    db = await _fetch_db_orders(strategy_name, td)
    bt = await _fetch_backtest_trades(strategy_name, td)

    pairs = _pair_by_code_role(bt, db)
    matched = sum(1 for a, b in pairs if a and b)
    only_bt = sum(1 for a, b in pairs if a and not b)
    only_rp = sum(1 for a, b in pairs if b and not a)

    buy_diffs, sell_diffs = [], []
    bt_pnl_matched = rp_pnl_matched = 0.0
    rp_pnl_extra = 0.0
    for a, b in pairs:
        if a and b:
            buy_diffs.append(_pct_diff(a["buy_price"], b["buy_price"]))
            sell_diffs.append(_pct_diff(a["sell_price"], b["sell_price"]))
            bt_pnl_matched += a["pnl"]
            rp_pnl_matched += b["pnl"]
        elif b:
            rp_pnl_extra += b["pnl"]

    PRICE_MAX, PNL_REL_MAX, PNL_ABS_MAX = 1.0, 10.0, 500.0
    max_buy = max(buy_diffs) if buy_diffs else 0
    max_sell = max(sell_diffs) if sell_diffs else 0
    pnl_abs = abs(rp_pnl_matched - bt_pnl_matched)
    pnl_rel = pnl_abs / abs(bt_pnl_matched) * 100 if abs(bt_pnl_matched) > 1 else 0

    pass_price = max_buy < PRICE_MAX and max_sell < PRICE_MAX
    pass_pnl = pnl_rel <= PNL_REL_MAX or pnl_abs <= PNL_ABS_MAX

    return {
        "strategy_name": strategy_name,
        "trade_date": td,
        "counts": {
            "backtest": len(bt), "live": len(db),
            "matched": matched, "only_backtest": only_bt, "only_live": only_rp,
        },
        "price_diff": {
            "buy_max_pct": round(max_buy, 3),
            "sell_max_pct": round(max_sell, 3),
            "threshold": PRICE_MAX,
            "pass": pass_price,
        },
        "pnl": {
            "backtest_total": round(bt_pnl_matched, 2),
            "live_matched": round(rp_pnl_matched, 2),
            "live_extra_only_rp": round(rp_pnl_extra, 2),
            "diff_pct": round(pnl_rel, 2),
            "diff_abs": round(pnl_abs, 2),
            "pass": pass_pnl,
        },
        "overall_pass": pass_price and pass_pnl,
        "trades_backtest": bt,
        "trades_live": db,
        "pairs": [(a, b) for a, b in pairs],
    }


def _render_txt(report: dict) -> str:
    lines = []
    n = report["strategy_name"]
    c = report["counts"]
    p = report["price_diff"]
    pnl = report["pnl"]
    ok = "PASS" if report["overall_pass"] else "FAIL"
    lines.append(f"========== {n} @ {report['trade_date']} | {ok} ==========")
    lines.append(f"")
    lines.append(f"Counts: backtest={c['backtest']} live={c['live']} "
                 f"matched={c['matched']} only-bt={c['only_backtest']} only-rp={c['only_live']}")
    lines.append(f"Price diff: buy max={p['buy_max_pct']:.3f}% sell max={p['sell_max_pct']:.3f}% "
                 f"(threshold <{p['threshold']:.1f}%) {'PASS' if p['pass'] else 'FAIL'}")
    lines.append(f"PnL: bt={pnl['backtest_total']:+.2f} live={pnl['live_matched']:+.2f} "
                 f"diff_rel={pnl['diff_pct']:.2f}% diff_abs={pnl['diff_abs']:.2f} "
                 f"{'PASS' if pnl['pass'] else 'FAIL'}")
    if pnl["live_extra_only_rp"]:
        lines.append(f"     only-live (extra fills): {pnl['live_extra_only_rp']:+.2f} (info only)")
    lines.append("")

    if c["only_backtest"] or c["only_live"]:
        lines.append("Mismatches:")
        for a, b in report["pairs"]:
            if a and b:
                continue
            if a:
                lines.append(f"  [only-bt] {a['ts_code']:12s} {a.get('pick_role',''):18s} "
                             f"buy={a['buy_price']} sell={a['sell_price']} pnl={a['pnl']:+.2f}")
            else:
                lines.append(f"  [only-rp] {b['ts_code']:12s} {b.get('pick_role',''):18s} "
                             f"buy={b['buy_price']} sell={b['sell_price']} pnl={b['pnl']:+.2f}")
        lines.append("")

    matched_pairs = [(a, b) for a, b in report["pairs"] if a and b]
    if matched_pairs:
        lines.append("Top 10 paired trades by |pnl diff|:")
        rows = sorted(matched_pairs, key=lambda ab: -abs(ab[0]['pnl'] - ab[1]['pnl']))[:10]
        for a, b in rows:
            lines.append(f"  {a['ts_code']:12s} {a.get('pick_role',''):18s} | "
                         f"bt buy={a['buy_price']} sell={a['sell_price']} pnl={a['pnl']:+.2f} | "
                         f"rp buy={b['buy_price']} sell={b['sell_price']} pnl={b['pnl']:+.2f}")
        lines.append("")
    return "\n".join(lines)


async def generate_daily_reconcile(td: str, out_dir: Path) -> dict:
    """主入口：生成 P1+P2 对账报告到 out_dir。"""
    results: dict[str, dict] = {}
    for strategy in ("pattern_01", "pattern_02"):
        try:
            report = await _compare_one(strategy, td)
        except Exception:
            logger.exception("reconcile %s @ %s failed", strategy, td)
            continue
        results[strategy] = report

        # JSON 落库（pairs 字段 tuple → list，datetime → str）
        def _serialize(o):
            if isinstance(o, datetime):
                return o.isoformat()
            raise TypeError(f"not serializable: {type(o)}")

        with open(out_dir / f"{strategy}.json", "w", encoding="utf-8") as f:
            payload = {**report,
                       "pairs": [{"backtest": a, "live": b} for a, b in report["pairs"]]}
            json.dump(payload, f, ensure_ascii=False, indent=2, default=_serialize)

        # TXT 人看版
        with open(out_dir / f"{strategy}.txt", "w", encoding="utf-8") as f:
            f.write(_render_txt(report))

    # summary.md
    with open(out_dir / "summary.md", "w", encoding="utf-8") as f:
        f.write(f"# OMS Reconcile {td}\n\n")
        for strategy, r in results.items():
            ok = "PASS" if r["overall_pass"] else "FAIL"
            c = r["counts"]
            pnl = r["pnl"]
            f.write(f"## {strategy} — {ok}\n\n")
            f.write(f"- backtest trades: {c['backtest']} | live trades: {c['live']}\n")
            f.write(f"- matched: {c['matched']} / only-bt: {c['only_backtest']} / only-live: {c['only_live']}\n")
            f.write(f"- PnL bt: {pnl['backtest_total']:+.2f} | live: {pnl['live_matched']:+.2f} "
                    f"(diff {pnl['diff_pct']:.2f}% / {pnl['diff_abs']:+.2f})\n\n")

    return results
