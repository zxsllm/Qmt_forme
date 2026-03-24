"""
Incremental data sync: pull new data since last available date.

Updates: stock_basic, trade_cal, stock_daily, daily_basic, index_daily.
Does NOT handle minute data (use pull_minutes.py --resume for that).

Usage:
    python scripts/sync_incremental.py              # sync all tables
    python scripts/sync_incremental.py --dry-run    # show what would be synced
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
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

sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg")
engine = create_engine(sync_url, echo=False)
svc = TushareService()

TODAY = datetime.now().strftime("%Y%m%d")

CORE_INDICES = [
    "000001.SH", "399001.SZ", "399006.SZ",
    "000300.SH", "000905.SH", "000688.SH", "899050.BJ",
]


def get_last_date(table: str, date_col: str = "trade_date") -> str:
    with engine.connect() as conn:
        row = conn.execute(text(f"SELECT max({date_col}) FROM {table}")).scalar()
        return row or settings.DATA_START_DATE


def get_trading_days(start: str, end: str) -> list[str]:
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT cal_date FROM trade_cal "
                "WHERE is_open = 1 AND cal_date >= :s AND cal_date <= :e "
                "ORDER BY cal_date"
            ),
            {"s": start, "e": end},
        )
        return [row[0] for row in result]


def sync_stock_basic():
    logger.info("=== Syncing stock_basic ===")
    try:
        df = svc.stock_basic(list_status="L")
        df_d = svc.stock_basic(list_status="D")
        import pandas as pd
        df_all = pd.concat([df, df_d], ignore_index=True)
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE stock_basic"))
            df_all.to_sql("stock_basic", conn, if_exists="append", index=False)
        logger.info("  stock_basic: %d rows", len(df_all))
    except Exception as e:
        logger.error("sync_stock_basic failed: %s", e)


def sync_trade_cal():
    logger.info("=== Syncing trade_cal ===")
    try:
        last = get_last_date("trade_cal", "cal_date")
        future_end = (datetime.now() + timedelta(days=90)).strftime("%Y%m%d")
        df = svc.trade_cal(start_date=last, end_date=future_end)
        if df.empty:
            logger.info("  No new calendar data")
            return
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM trade_cal WHERE cal_date >= :s"), {"s": last})
            df.to_sql("trade_cal", conn, if_exists="append", index=False)
        logger.info("  trade_cal: +%d rows (from %s to %s)", len(df), last, future_end)
    except Exception as e:
        logger.error("sync_trade_cal failed: %s", e)


def sync_daily(dry_run: bool = False):
    last = get_last_date("stock_daily")
    next_day = str(int(last) + 1)
    days = get_trading_days(next_day, TODAY)
    logger.info("=== Syncing stock_daily: %d new days (after %s) ===", len(days), last)
    if not days:
        return
    if dry_run:
        logger.info("  [DRY RUN] Would pull %d days: %s ... %s", len(days), days[0], days[-1])
        return

    total, failed = 0, []
    for i, td in enumerate(days):
        try:
            df = svc.daily(trade_date=td)
            if df.empty:
                continue
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM stock_daily WHERE trade_date = :td"), {"td": td})
                df.to_sql("stock_daily", conn, if_exists="append", index=False)
            total += len(df)
            if (i + 1) % 10 == 0 or i == 0:
                logger.info("  [%d/%d] %s: %d rows (cum: %d)", i + 1, len(days), td, len(df), total)
        except Exception as e:
            logger.warning("sync_daily failed for %s: %s", td, e)
            failed.append(td)

    logger.info("  stock_daily: +%d rows", total)
    if failed:
        logger.warning("  Failed dates (%d): %s", len(failed), failed)


def sync_daily_basic(dry_run: bool = False):
    last = get_last_date("daily_basic")
    next_day = str(int(last) + 1)
    days = get_trading_days(next_day, TODAY)
    logger.info("=== Syncing daily_basic: %d new days (after %s) ===", len(days), last)
    if not days:
        return
    if dry_run:
        logger.info("  [DRY RUN] Would pull %d days", len(days))
        return

    total, failed = 0, []
    for i, td in enumerate(days):
        try:
            df = svc.daily_basic(ts_code="", trade_date=td)
            if df.empty:
                continue
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM daily_basic WHERE trade_date = :td"), {"td": td})
                df.to_sql("daily_basic", conn, if_exists="append", index=False)
            total += len(df)
            if (i + 1) % 10 == 0 or i == 0:
                logger.info("  [%d/%d] %s: %d rows (cum: %d)", i + 1, len(days), td, len(df), total)
        except Exception as e:
            logger.warning("sync_daily_basic failed for %s: %s", td, e)
            failed.append(td)

    logger.info("  daily_basic: +%d rows", total)
    if failed:
        logger.warning("  Failed dates (%d): %s", len(failed), failed)


def sync_index_daily(dry_run: bool = False):
    last = get_last_date("index_daily")
    next_day = str(int(last) + 1)
    logger.info("=== Syncing index_daily (after %s) ===", last)

    if dry_run:
        logger.info("  [DRY RUN] Would pull %d indices from %s to %s", len(CORE_INDICES), next_day, TODAY)
        return

    total, failed = 0, []
    for idx_code in CORE_INDICES:
        try:
            df = svc.index_daily(ts_code=idx_code, start_date=next_day, end_date=TODAY)
            if df.empty:
                continue
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM index_daily WHERE ts_code = :c AND trade_date >= :s"),
                    {"c": idx_code, "s": next_day},
                )
                df.to_sql("index_daily", conn, if_exists="append", index=False)
            total += len(df)
        except Exception as e:
            logger.warning("sync_index_daily failed for %s: %s", idx_code, e)
            failed.append(idx_code)

    logger.info("  index_daily: +%d rows", total)
    if failed:
        logger.warning("  Failed indices (%d): %s", len(failed), failed)


def verify():
    logger.info("=== Current data status ===")
    with engine.connect() as conn:
        for table, col in [
            ("stock_daily", "trade_date"),
            ("daily_basic", "trade_date"),
            ("index_daily", "trade_date"),
        ]:
            row = conn.execute(
                text(f"SELECT count(*), max({col}) FROM {table}")
            ).fetchone()
            logger.info("  %s: %s rows, latest: %s", table, row[0], row[1])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show what would be synced")
    args = parser.parse_args()

    logger.info("Incremental sync started (today: %s)", TODAY)

    sync_stock_basic()
    sync_trade_cal()
    sync_daily(dry_run=args.dry_run)
    sync_daily_basic(dry_run=args.dry_run)
    sync_index_daily(dry_run=args.dry_run)

    verify()
    logger.info("Sync done!")


if __name__ == "__main__":
    main()
