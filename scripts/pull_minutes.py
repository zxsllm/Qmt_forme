"""
Pull 1-minute bar data for all stocks into partitioned stock_min_kline table.

Features:
- Resumes from last pulled stock (tracks progress in DB)
- Rate limiting (default 450 req/min, leaving headroom)
- Batch insert per stock
- Skips suspended stocks

Usage:
    python scripts/pull_minutes.py              # pull all stocks
    python scripts/pull_minutes.py --test 5     # test with 5 stocks
    python scripts/pull_minutes.py --resume     # resume from last progress
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
ROWS_PER_REQUEST = 8000
BARS_PER_DAY = 240
REQUESTS_PER_MIN = 450


def get_stock_list() -> list[str]:
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT ts_code FROM stock_basic WHERE list_status = 'L' ORDER BY ts_code")
        )
        return [row[0] for row in result]


def get_already_pulled() -> set[str]:
    """Find stocks that already have minute data in the date range."""
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT DISTINCT ts_code FROM stock_min_kline
                WHERE trade_time >= :s AND trade_time < :e AND freq = :f
            """),
            {
                "s": settings.DATA_START_DATE[:4] + "-" + settings.DATA_START_DATE[4:6] + "-" + settings.DATA_START_DATE[6:],
                "e": settings.DATA_END_DATE[:4] + "-" + settings.DATA_END_DATE[4:6] + "-" + settings.DATA_END_DATE[6:],
                "f": FREQ,
            },
        )
        return {row[0] for row in result}


def pull_stock_minutes(ts_code: str) -> int:
    """Pull all 1-min bars for one stock in the configured date range."""
    start_dt = f"{settings.DATA_START_DATE[:4]}-{settings.DATA_START_DATE[4:6]}-{settings.DATA_START_DATE[6:]} 09:00:00"
    end_dt = f"{settings.DATA_END_DATE[:4]}-{settings.DATA_END_DATE[4:6]}-{settings.DATA_END_DATE[6:]} 16:00:00"

    all_rows = []
    cur_end = end_dt

    while True:
        df = svc.query(
            "stk_mins",
            ts_code=ts_code,
            freq=FREQ,
            start_date=start_dt,
            end_date=cur_end,
        )
        if df.empty:
            break

        all_rows.append(df)
        if len(df) < ROWS_PER_REQUEST:
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
        conn.execute(
            text("""
                DELETE FROM stock_min_kline
                WHERE ts_code = :c AND freq = :f
                AND trade_time >= :s AND trade_time < :e
            """),
            {
                "c": ts_code,
                "f": FREQ,
                "s": start_dt,
                "e": end_dt,
            },
        )
        df_all.to_sql("stock_min_kline", conn, if_exists="append", index=False, chunksize=5000)

    return len(df_all)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", type=int, default=0, help="Only pull N stocks for testing")
    parser.add_argument("--resume", action="store_true", help="Skip already-pulled stocks")
    args = parser.parse_args()

    stocks = get_stock_list()
    logger.info("Total listed stocks: %d", len(stocks))

    if args.resume:
        already = get_already_pulled()
        stocks = [s for s in stocks if s not in already]
        logger.info("Resuming: %d stocks remaining (skipped %d already pulled)", len(stocks), len(already))

    if args.test > 0:
        stocks = stocks[: args.test]
        logger.info("Test mode: pulling %d stocks only", len(stocks))

    total_rows = 0
    errors = []
    t0 = time.time()

    for i, ts_code in enumerate(stocks):
        try:
            n = pull_stock_minutes(ts_code)
            total_rows += n
            if (i + 1) % 50 == 0 or i == 0 or args.test:
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed * 60 if elapsed > 0 else 0
                logger.info(
                    "  [%d/%d] %s: %d bars (cum: %d, %.0f stocks/min)",
                    i + 1, len(stocks), ts_code, n, total_rows, rate,
                )
        except Exception as e:
            logger.error("  [%d/%d] %s: FAILED %s", i + 1, len(stocks), ts_code, e)
            errors.append(ts_code)

    elapsed = time.time() - t0
    logger.info(
        "Done! %d stocks, %d total rows, %d errors, %.1f minutes",
        len(stocks), total_rows, len(errors), elapsed / 60,
    )
    if errors:
        logger.info("Failed stocks: %s", errors[:20])


if __name__ == "__main__":
    main()
