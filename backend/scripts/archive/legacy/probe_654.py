"""把 4-30 在 stock_min_kline 出现过的 ts_code 与 watch_codes 各组成画像比对。"""
from __future__ import annotations
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from app.core.config import settings


def main():
    sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg")
    eng = create_engine(sync_url, echo=False)

    with eng.connect() as conn:
        codes_in_min = {r[0] for r in conn.execute(text(
            "SELECT DISTINCT ts_code FROM stock_min_kline "
            "WHERE freq='1min' AND trade_time::date='2026-04-30'"
        )).fetchall()}
        print(f"[A] 4-30 在 stock_min_kline 出现过的 ts_code 数：{len(codes_in_min)}")

        # —— watch_codes 由 scheduler.collect_watch_codes() 收集自三处 —— #

        # 1) 当前持仓（4-30 之前/当天还在持仓的 ts_code）
        try:
            positions = {r[0] for r in conn.execute(text(
                "SELECT DISTINCT ts_code FROM positions"
            )).fetchall()}
            print(f"[B1] positions 表 ts_code 数：{len(positions)}")
        except Exception as e:
            positions = set()
            print(f"[B1] positions: ERROR {e}")

        # 2) 活跃挂单（任何状态非 FILLED/CANCELED 的）
        try:
            orders = {r[0] for r in conn.execute(text(
                "SELECT DISTINCT ts_code FROM orders WHERE order_date='20260430'"
            )).fetchall()}
            print(f"[B2] orders 表（4-30 当天）ts_code 数：{len(orders)}")
        except Exception as e:
            orders = set()
            print(f"[B2] orders: ERROR {e}")

        # 3) 默认兜底
        DEFAULT_FALLBACK = {"000001.SZ"}

        # 4) daily_plan.watch_stocks_json (前端关注列表)
        try:
            row = conn.execute(text(
                "SELECT watch_stocks_json FROM daily_plan "
                "WHERE trade_date='20260430'"
            )).fetchone()
            watch_plan = set()
            if row and row[0]:
                items = row[0] if isinstance(row[0], list) else json.loads(row[0])
                for it in items:
                    code = it.get("ts_code") if isinstance(it, dict) else it
                    if code:
                        watch_plan.add(code)
            print(f"[B3] daily_plan(4-30) watchlist ts_code 数：{len(watch_plan)}")
        except Exception as e:
            watch_plan = set()
            print(f"[B3] daily_plan: ERROR {e}")

        # 5) monitor_largecap_alerts 4-30 涉及的票（盘中加进 watch 的常见途径）
        try:
            alerts = {r[0] for r in conn.execute(text(
                "SELECT DISTINCT ts_code FROM monitor_largecap_alerts "
                "WHERE event_date='2026-04-30'"
            )).fetchall()}
            print(f"[B4] monitor_largecap_alerts(4-30) ts_code 数：{len(alerts)}")
        except Exception as e:
            alerts = set()
            print(f"[B4] alerts: ERROR {e}")

        # 推断的 watch_codes 全集
        watch_union = positions | orders | DEFAULT_FALLBACK | watch_plan | alerts
        print(f"\n[C] 推断 watch 全集（positions ∪ orders ∪ default ∪ plan ∪ alerts）= {len(watch_union)}")

        # —— 对比 —— #
        inter = codes_in_min & watch_union
        only_min = codes_in_min - watch_union
        only_watch = watch_union - codes_in_min

        print(f"\n[D] 交集（既在 4-30 分钟线里、又在 watch 全集里）= {len(inter)}")
        print(f"[E] 只在 4-30 分钟线、不在 watch 全集里的 ts_code = {len(only_min)}")
        if only_min:
            sample = sorted(only_min)[:30]
            print(f"    样本（前 30）：{sample}")
        print(f"[F] 在 watch 全集、但 4-30 分钟线里没有的 ts_code = {len(only_watch)}")
        if only_watch:
            sample = sorted(only_watch)[:30]
            print(f"    样本（前 30）：{sample}")

        # —— 进一步：4-30 这 654 个的写入时间分布 —— #
        rows = conn.execute(text(
            "SELECT MIN(trade_time)::time AS tmin, MAX(trade_time)::time AS tmax, "
            "       COUNT(*) AS n_rows "
            "FROM stock_min_kline "
            "WHERE freq='1min' AND trade_time::date='2026-04-30'"
        )).fetchone()
        print(f"\n[G] 4-30 在表里的时间窗：tmin={rows[0]}  tmax={rows[1]}  rows={rows[2]}")

        # —— 4-30 每只票各有几行（看是否多数刚好 241，还是参差）—— #
        bucket_rows = conn.execute(text(
            "WITH per_code AS ("
            "  SELECT ts_code, COUNT(*) AS n FROM stock_min_kline "
            "  WHERE freq='1min' AND trade_time::date='2026-04-30' "
            "  GROUP BY ts_code"
            ") "
            "SELECT n, COUNT(*) AS k FROM per_code GROUP BY n ORDER BY n DESC"
        )).fetchall()
        print(f"\n[H] 4-30 每只票分钟数分布（n=每只多少行，k=有多少只这样的票）:")
        for n, k in bucket_rows[:15]:
            print(f"    n={n:>4}  k={k}")

    eng.dispose()


if __name__ == "__main__":
    main()
