"""Pull stk_limit (daily up/down limit prices) and suspend_d data.

Usage:
    python scripts/pull_stk_limit.py
    python scripts/pull_stk_limit.py --dry-run
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import create_engine, text
from app.core.config import settings
from app.research.data.tushare_service import TushareService

DB_URL = settings.DATABASE_URL.replace("+asyncpg", "+psycopg")
engine = create_engine(DB_URL, echo=False)
ts_svc = TushareService()


def get_trade_dates() -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT cal_date FROM trade_cal WHERE is_open = 1 ORDER BY cal_date")
        ).fetchall()
    return [r[0] for r in rows]


def pull_stk_limit(trade_dates: list[str], dry_run: bool = False):
    with engine.connect() as conn:
        existing = set()
        rows = conn.execute(text("SELECT DISTINCT trade_date FROM stock_limit")).fetchall()
        existing = {r[0] for r in rows}

    todo = [d for d in trade_dates if d not in existing]
    print(f"stk_limit: {len(todo)} dates to pull ({len(existing)} already done)")

    if dry_run:
        print("  [DRY RUN] skipping")
        return

    total_rows = 0
    for i, td in enumerate(todo):
        df = ts_svc.stk_limit(trade_date=td)
        if df.empty:
            print(f"  [{i+1}/{len(todo)}] {td}: 0 rows (skip)")
            continue

        df = df[["trade_date", "ts_code", "pre_close", "up_limit", "down_limit"]]
        df.to_sql("stock_limit", engine, if_exists="append", index=False, method="multi")
        total_rows += len(df)
        if (i + 1) % 10 == 0 or i == len(todo) - 1:
            print(f"  [{i+1}/{len(todo)}] {td}: +{len(df)} rows (total: {total_rows})")

    print(f"stk_limit done: {total_rows} rows inserted")


def pull_suspend_d(trade_dates: list[str], dry_run: bool = False):
    with engine.connect() as conn:
        existing = set()
        rows = conn.execute(text("SELECT DISTINCT trade_date FROM suspend_d")).fetchall()
        existing = {r[0] for r in rows}

    todo = [d for d in trade_dates if d not in existing]
    print(f"suspend_d: {len(todo)} dates to pull ({len(existing)} already done)")

    if dry_run:
        print("  [DRY RUN] skipping")
        return

    total_rows = 0
    for i, td in enumerate(todo):
        df = ts_svc.suspend_d(suspend_type="S", trade_date=td)
        if df.empty:
            continue

        df = df[["ts_code", "trade_date", "suspend_type", "suspend_timing"]]
        df.to_sql("suspend_d", engine, if_exists="append", index=False, method="multi")
        total_rows += len(df)
        if (i + 1) % 10 == 0 or i == len(todo) - 1:
            print(f"  [{i+1}/{len(todo)}] {td}: +{len(df)} rows (total: {total_rows})")

    print(f"suspend_d done: {total_rows} rows inserted")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dates = get_trade_dates()
    print(f"Found {len(dates)} trade dates in DB")

    pull_stk_limit(dates, dry_run=args.dry_run)
    pull_suspend_d(dates, dry_run=args.dry_run)
