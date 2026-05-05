"""一次性诊断：查 stock_min_kline 中 2026-04-30 的写入实况。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from app.core.config import settings


def main():
    sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg")
    print(f"DSN: {sync_url}")
    eng = create_engine(sync_url, echo=False)

    with eng.connect() as conn:
        # 1. 当前 DB 名 / 库标识
        r = conn.execute(text("SELECT current_database(), current_schema(), version()")).fetchone()
        print(f"db={r[0]}  schema={r[1]}  pg={r[2][:60]}")

        # 2. 父表与所有分区
        print("\n=== partitions of stock_min_kline ===")
        rows = conn.execute(text(
            "SELECT inhrelid::regclass::text AS partition,"
            "       pg_get_expr(c.relpartbound, c.oid) AS bound,"
            "       (SELECT reltuples::bigint FROM pg_class WHERE oid=inhrelid) AS approx_rows "
            "FROM pg_inherits i "
            "JOIN pg_class c ON c.oid=i.inhrelid "
            "WHERE inhparent='stock_min_kline'::regclass "
            "ORDER BY partition"
        )).fetchall()
        for p, bound, approx in rows:
            print(f"  {p:40} {bound}   approx_rows={approx}")

        # 3. 每个交易日的精确行数（最近 6 天）
        print("\n=== row counts by date (last 6 trading days, 1min freq) ===")
        rows = conn.execute(text(
            "SELECT trade_time::date AS d, COUNT(*) AS n,"
            "       MIN(trade_time) AS tmin, MAX(trade_time) AS tmax "
            "FROM stock_min_kline "
            "WHERE freq='1min' "
            "  AND trade_time >= '2026-04-23' "
            "  AND trade_time < '2026-05-03' "
            "GROUP BY d ORDER BY d"
        )).fetchall()
        for d, n, tmin, tmax in rows:
            print(f"  {d}  rows={n:>10}  min={tmin}  max={tmax}")
        if not rows:
            print("  (no rows in last 10 days at all)")

        # 4. 直接看 2026_04 分区子表的总行数
        print("\n=== direct row count: stock_min_kline_2026_04 ===")
        try:
            r = conn.execute(text(
                "SELECT COUNT(*), MIN(trade_time), MAX(trade_time) "
                "FROM stock_min_kline_2026_04"
            )).fetchone()
            print(f"  count={r[0]}  min={r[1]}  max={r[2]}")
        except Exception as e:
            print(f"  ERROR: {e}")

        # 5. 直接看 2026_05 分区子表（万一时区漂到 5 月）
        print("\n=== direct row count: stock_min_kline_2026_05 ===")
        try:
            r = conn.execute(text(
                "SELECT COUNT(*), MIN(trade_time), MAX(trade_time) "
                "FROM stock_min_kline_2026_05"
            )).fetchone()
            print(f"  count={r[0]}  min={r[1]}  max={r[2]}")
        except Exception as e:
            print(f"  ERROR: {e}")

        # 6. trade_cal 中 4-29 / 4-30 是否标记为开市
        print("\n=== trade_cal 04-25 ~ 05-02 ===")
        rows = conn.execute(text(
            "SELECT cal_date, is_open, pretrade_date FROM trade_cal "
            "WHERE cal_date BETWEEN '20260425' AND '20260502' "
            "ORDER BY cal_date"
        )).fetchall()
        for cd, op, prev in rows:
            print(f"  {cd}  is_open={op}  pretrade={prev}")

        # 7. monitor_largecap_alerts 4-30 事件统计
        print("\n=== monitor_largecap_alerts on 2026-04-30 ===")
        try:
            r = conn.execute(text(
                "SELECT COUNT(*),"
                "       COUNT(*) FILTER (WHERE ret_5m IS NULL),"
                "       COUNT(*) FILTER (WHERE ret_eod IS NULL) "
                "FROM monitor_largecap_alerts "
                "WHERE event_date='2026-04-30'"
            )).fetchone()
            print(f"  total={r[0]}  null_ret5m={r[1]}  null_eod={r[2]}")
        except Exception as e:
            print(f"  ERROR: {e}")

        # 8. 抽 3 个常见票，看它们 4-29 / 4-30 在 DB 里到底有几条
        print("\n=== sanity: per-stock row count on 04-29 vs 04-30 ===")
        for code in ("000001.SZ", "600519.SH", "300750.SZ"):
            r = conn.execute(text(
                "SELECT "
                "  COUNT(*) FILTER (WHERE trade_time::date='2026-04-29') AS d29,"
                "  COUNT(*) FILTER (WHERE trade_time::date='2026-04-30') AS d30,"
                "  MAX(trade_time) FILTER (WHERE trade_time::date='2026-04-30') AS max30 "
                "FROM stock_min_kline WHERE ts_code=:c AND freq='1min'"
            ), {"c": code}).fetchone()
            print(f"  {code}  d29={r[0]:>4}  d30={r[1]:>4}  max30={r[2]}")

    eng.dispose()


if __name__ == "__main__":
    main()
