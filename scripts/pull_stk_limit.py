"""Pull stk_limit (daily up/down limit prices) and suspend_d data.

Usage:
    python scripts/pull_stk_limit.py
    python scripts/pull_stk_limit.py --dry-run
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import create_engine, text
from app.core.config import settings
from app.research.data.tushare_service import TushareService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

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
        rows = conn.execute(text("SELECT DISTINCT trade_date FROM stock_limit")).fetchall()
        existing = {r[0] for r in rows}

    todo = [d for d in trade_dates if d not in existing]
    logger.info("stk_limit: %d dates to pull (%d already done)", len(todo), len(existing))

    if dry_run:
        logger.info("  [DRY RUN] skipping")
        return

    total_rows, failed = 0, []
    for i, td in enumerate(todo):
        try:
            df = ts_svc.stk_limit(trade_date=td)
            if df.empty:
                continue

            df = df[["trade_date", "ts_code", "pre_close", "up_limit", "down_limit"]]
            df.to_sql("stock_limit", engine, if_exists="append", index=False, method="multi")
            total_rows += len(df)
            if (i + 1) % 10 == 0 or i == len(todo) - 1:
                logger.info("  [%d/%d] %s: +%d rows (total: %d)", i + 1, len(todo), td, len(df), total_rows)
        except Exception as e:
            logger.warning("stk_limit failed for %s: %s", td, e)
            failed.append(td)

    logger.info("stk_limit done: %d rows inserted", total_rows)
    if failed:
        logger.warning("  Failed dates (%d): %s", len(failed), failed)


def pull_suspend_d(trade_dates: list[str], dry_run: bool = False):
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT DISTINCT trade_date FROM suspend_d")).fetchall()
        existing = {r[0] for r in rows}

    todo = [d for d in trade_dates if d not in existing]
    logger.info("suspend_d: %d dates to pull (%d already done)", len(todo), len(existing))

    if dry_run:
        logger.info("  [DRY RUN] skipping")
        return

    total_rows, failed = 0, []
    for i, td in enumerate(todo):
        try:
            df = ts_svc.suspend_d(suspend_type="S", trade_date=td)
            if df.empty:
                continue

            df = df[["ts_code", "trade_date", "suspend_type", "suspend_timing"]]
            df.to_sql("suspend_d", engine, if_exists="append", index=False, method="multi")
            total_rows += len(df)
            if (i + 1) % 10 == 0 or i == len(todo) - 1:
                logger.info("  [%d/%d] %s: +%d rows (total: %d)", i + 1, len(todo), td, len(df), total_rows)
        except Exception as e:
            logger.warning("suspend_d failed for %s: %s", td, e)
            failed.append(td)

    logger.info("suspend_d done: %d rows inserted", total_rows)
    if failed:
        logger.warning("  Failed dates (%d): %s", len(failed), failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dates = get_trade_dates()
    logger.info("Found %d trade dates in DB", len(dates))

    pull_stk_limit(dates, dry_run=args.dry_run)
    pull_suspend_d(dates, dry_run=args.dry_run)
