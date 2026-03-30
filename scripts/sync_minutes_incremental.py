"""Incremental sync of 1-minute bar data.

Only pulls the MISSING recent days for each stock, instead of re-pulling
the entire 6-month history. Designed to run daily after market close.

Usage:
    python scripts/sync_minutes_incremental.py                   # sync all to latest
    python scripts/sync_minutes_incremental.py --test 5          # test with 5 stocks
    python scripts/sync_minutes_incremental.py --from 20260321   # explicit start date
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

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

FREQ = "1min"


def get_stock_list() -> list[str]:
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT ts_code FROM stock_basic WHERE list_status = 'L' ORDER BY ts_code")
        )
        return [row[0] for row in result]


def get_latest_per_stock() -> dict[str, str]:
    """Get the latest trade_time date string for each stock in DB."""
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT ts_code, MAX(trade_time)::date as latest "
            "FROM stock_min_kline WHERE freq = :f "
            "GROUP BY ts_code"
        ), {"f": FREQ})
        return {row[0]: row[1].strftime("%Y-%m-%d") for row in result}


def get_latest_trade_date() -> str:
    """Get the most recent trading day from trade_cal."""
    today = datetime.now().strftime("%Y%m%d")
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT cal_date FROM trade_cal "
            "WHERE is_open = 1 AND cal_date <= :td "
            "ORDER BY cal_date DESC LIMIT 1"
        ), {"td": today})
        row = result.fetchone()
        return row[0] if row else today


def pull_range(ts_code: str, start_date: str, end_date: str) -> int:
    """Pull 1-min bars for one stock in a specific date range."""
    start_dt = f"{start_date} 09:00:00"
    end_dt = f"{end_date} 16:00:00"

    all_rows = []
    cur_end = end_dt

    while True:
        df = svc.stk_mins(
            ts_code=ts_code, freq=FREQ,
            start_date=start_dt, end_date=cur_end,
        )
        if df.empty:
            break
        all_rows.append(df)
        if len(df) < 8000:
            break
        earliest = df["trade_time"].min()
        cur_end = earliest
        time.sleep(0.05)

    if not all_rows:
        return 0

    df_all = pd.concat(all_rows, ignore_index=True)
    df_all = df_all.drop_duplicates(subset=["ts_code", "trade_time"], keep="first")
    df_all["freq"] = FREQ
    df_all["trade_time"] = pd.to_datetime(df_all["trade_time"])

    with engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM stock_min_kline "
            "WHERE ts_code = :c AND freq = :f "
            "AND trade_time >= :s AND trade_time <= :e"
        ), {"c": ts_code, "f": FREQ, "s": start_dt, "e": end_dt})
        df_all.to_sql("stock_min_kline", conn, if_exists="append", index=False, chunksize=5000)

    return len(df_all)


def main():
    parser = argparse.ArgumentParser(description="Incremental minute data sync")
    parser.add_argument("--test", type=int, default=0, help="Test with N stocks")
    parser.add_argument("--from", dest="from_date", default="", help="Force start date YYYYMMDD")
    args = parser.parse_args()

    stocks = get_stock_list()
    logger.info("Total listed stocks: %d", len(stocks))

    target_date = get_latest_trade_date()
    target_fmt = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:]}"
    logger.info("Target: sync all minute data up to %s", target_date)

    if args.from_date:
        force_start = args.from_date
        force_start_fmt = f"{force_start[:4]}-{force_start[4:6]}-{force_start[6:]}"
        logger.info("Forced start date: %s", force_start)
        latest_map = {}
    else:
        logger.info("Scanning existing minute data coverage...")
        latest_map = get_latest_per_stock()
        logger.info("Found coverage info for %d stocks", len(latest_map))

    if args.test > 0:
        stocks = stocks[:args.test]
        logger.info("Test mode: %d stocks", len(stocks))

    total_rows = 0
    skipped = 0
    errors = []
    t0 = time.time()

    for i, ts_code in enumerate(stocks):
        try:
            if args.from_date:
                sync_start = force_start_fmt
            else:
                existing_latest = latest_map.get(ts_code)
                if existing_latest and existing_latest >= target_fmt:
                    skipped += 1
                    continue
                if existing_latest:
                    sync_start = existing_latest
                else:
                    sync_start = f"{settings.DATA_START_DATE[:4]}-{settings.DATA_START_DATE[4:6]}-{settings.DATA_START_DATE[6:]}"

            n = pull_range(ts_code, sync_start.replace("-", ""), target_date)
            total_rows += n

            done = i + 1
            if done % 100 == 0 or done == 1 or args.test:
                elapsed = time.time() - t0
                rate = done / elapsed * 60 if elapsed > 0 else 0
                logger.info(
                    "  [%d/%d] %s: +%d bars (cum: %d, %.0f stocks/min, skipped: %d)",
                    done, len(stocks), ts_code, n, total_rows, rate, skipped,
                )
        except Exception as e:
            logger.error("  [%d/%d] %s: FAILED %s", i + 1, len(stocks), ts_code, e)
            errors.append(ts_code)

    elapsed = time.time() - t0
    logger.info(
        "Done! %d stocks processed, %d skipped (already fresh), "
        "%d total new rows, %d errors, %.1f minutes",
        len(stocks) - skipped, skipped, total_rows, len(errors), elapsed / 60,
    )
    if errors:
        logger.info("Failed stocks (first 20): %s", errors[:20])


if __name__ == "__main__":
    main()
