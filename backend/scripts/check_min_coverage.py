"""扫 stock_min_kline 在每个交易日的覆盖率，找缺失/不完整。"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from app.core.config import settings


def main():
    sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg")
    eng = create_engine(sync_url, echo=False)

    with eng.connect() as conn:
        # 拿全部 4-30 之前 (含) 且 is_open=1 的交易日
        cal_dates = conn.execute(text(
            "SELECT cal_date FROM trade_cal "
            "WHERE is_open=1 AND cal_date <= '20260430' "
            "  AND cal_date >= '20250922' "
            "ORDER BY cal_date"
        )).fetchall()
        cal_dates = [r[0] for r in cal_dates]
        print(f"trade days in [20250922, 20260430]: {len(cal_dates)}")

        # 在场 L 股数（用作每日基准）
        l_count = conn.execute(text(
            "SELECT COUNT(*) FROM stock_basic WHERE list_status='L'"
        )).scalar()
        print(f"current listed L stocks: {l_count}")

        # 单次聚合：每个 trade_date 的 行数 / 不同 ts_code 数
        rows = conn.execute(text(
            "SELECT trade_time::date AS d, "
            "       COUNT(*) AS n_rows, "
            "       COUNT(DISTINCT ts_code) AS n_codes, "
            "       MIN(trade_time)::time AS tmin, "
            "       MAX(trade_time)::time AS tmax "
            "FROM stock_min_kline "
            "WHERE freq='1min' "
            "  AND trade_time >= '2025-09-22' "
            "  AND trade_time <  '2026-05-01' "
            "GROUP BY d ORDER BY d"
        )).fetchall()
        by_date = {r[0].strftime("%Y%m%d"): (r[1], r[2], r[3], r[4]) for r in rows}

        print("\n=== anomaly report ===")
        # 1. 列出在 trade_cal 里但 0 行的天
        empties = []
        partials = []
        weird_codes = []
        weird_time = []
        ALL = []
        for td in cal_dates:
            stat = by_date.get(td)
            if stat is None:
                empties.append(td)
                ALL.append((td, 0, 0, None, None))
                continue
            n_rows, n_codes, tmin, tmax = stat
            ALL.append((td, n_rows, n_codes, tmin, tmax))
            # 标准一天每股 241 bars，全市场约 5500 只 → 1.32M 行附近
            if n_codes < l_count * 0.95:
                partials.append((td, n_rows, n_codes))
            if n_rows < 1_000_000:
                weird_codes.append((td, n_rows, n_codes))
            # 时间窗合理性：min<=09:30, max>=15:00
            if tmin and tmin.strftime("%H:%M") > "09:30":
                weird_time.append((td, "tmin", tmin))
            if tmax and tmax.strftime("%H:%M") < "15:00":
                weird_time.append((td, "tmax", tmax))

        if empties:
            print(f"\n[A] {len(empties)} trade days with 0 rows (entirely missing):")
            for td in empties:
                print(f"   {td}")
        else:
            print("\n[A] no fully-empty trade days")

        if partials:
            print(f"\n[B] {len(partials)} trade days with code coverage < 95% of listed:")
            for td, n_rows, n_codes in partials:
                print(f"   {td}  rows={n_rows:>10}  codes={n_codes}/{l_count}  ({n_codes/l_count*100:.1f}%)")
        else:
            print("\n[B] all trade days have ≥95% code coverage")

        if weird_codes:
            print(f"\n[C] {len(weird_codes)} trade days with rows < 1.0M (suspiciously low):")
            for td, n_rows, n_codes in weird_codes:
                print(f"   {td}  rows={n_rows:>10}  codes={n_codes}")
        else:
            print("\n[C] all trade days have ≥1.0M rows")

        if weird_time:
            print(f"\n[D] {len(weird_time)} trade days with abnormal time bounds:")
            for td, kind, t in weird_time:
                print(f"   {td}  {kind}={t}")
        else:
            print("\n[D] all trade days span the normal 09:30–15:00 window")

        # 总览（每个交易日）
        print("\n=== per-day summary ===")
        for td, n_rows, n_codes, tmin, tmax in ALL:
            tag = ""
            if n_rows == 0:
                tag = " ← MISSING"
            elif n_codes < l_count * 0.95:
                tag = " ← partial"
            elif n_rows < 1_000_000:
                tag = " ← low rows"
            print(f"  {td}  rows={n_rows:>10}  codes={n_codes:>5}  tmin={tmin}  tmax={tmax}{tag}")

    eng.dispose()


if __name__ == "__main__":
    main()
