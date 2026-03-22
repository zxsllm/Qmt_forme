"""
Phase 1 MVP: Pull 6 months of daily data into PostgreSQL.

Usage:
    cd backend && python -m scripts.init_data        (from Qmt_forme/)
    or: python scripts/init_data.py                  (from Qmt_forme/)

Pulls:
    1. stock_basic  -- all listed stocks
    2. trade_cal    -- SSE calendar for date range
    3. daily        -- daily bars per trade_date, ~120 requests
"""

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

sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg")
engine = create_engine(sync_url, echo=False)
svc = TushareService()


def pull_stock_basic():
    logger.info("=== Pulling stock_basic ===")
    df = svc.stock_basic(list_status="L")
    logger.info("Listed stocks (L): %d", len(df))

    df_d = svc.stock_basic(list_status="D")
    logger.info("Delisted stocks (D): %d", len(df_d))

    df_p = svc.stock_basic(list_status="P")
    logger.info("Paused stocks (P): %d", len(df_p))

    import pandas as pd

    df_all = pd.concat([df, df_d, df_p], ignore_index=True)
    df_all = df_all.drop_duplicates(subset=["ts_code"], keep="first")
    logger.info("Total unique stocks: %d", len(df_all))

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE stock_basic"))
        df_all.to_sql("stock_basic", conn, if_exists="append", index=False)

    logger.info("stock_basic done: %d rows written", len(df_all))
    return len(df_all)


def pull_trade_cal():
    logger.info("=== Pulling trade_cal ===")
    df = svc.trade_cal(
        exchange="SSE",
        start_date=settings.DATA_START_DATE,
        end_date=settings.DATA_END_DATE,
    )
    logger.info("Calendar rows: %d", len(df))

    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM trade_cal WHERE cal_date >= :s AND cal_date <= :e"
            ),
            {"s": settings.DATA_START_DATE, "e": settings.DATA_END_DATE},
        )
        df.to_sql("trade_cal", conn, if_exists="append", index=False)

    open_days = len(df[df["is_open"] == 1])
    logger.info("trade_cal done: %d rows, %d trading days", len(df), open_days)
    return open_days


def pull_daily(trading_days: list[str]):
    logger.info("=== Pulling daily (by trade_date) ===")
    total_rows = 0
    errors = []

    for i, td in enumerate(trading_days):
        try:
            df = svc.daily(trade_date=td)
            if df.empty:
                logger.warning("  [%d/%d] %s: empty", i + 1, len(trading_days), td)
                continue

            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM stock_daily WHERE trade_date = :td"),
                    {"td": td},
                )
                df.to_sql("stock_daily", conn, if_exists="append", index=False)

            total_rows += len(df)
            if (i + 1) % 10 == 0 or i == 0:
                logger.info(
                    "  [%d/%d] %s: %d rows (cumulative: %d)",
                    i + 1,
                    len(trading_days),
                    td,
                    len(df),
                    total_rows,
                )
        except Exception as e:
            logger.error("  [%d/%d] %s: FAILED %s", i + 1, len(trading_days), td, e)
            errors.append(td)

    logger.info(
        "daily done: %d total rows, %d errors %s",
        total_rows,
        len(errors),
        errors if errors else "",
    )
    return total_rows


def get_trading_days() -> list[str]:
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT cal_date FROM trade_cal "
                "WHERE is_open = 1 AND cal_date >= :s AND cal_date <= :e "
                "ORDER BY cal_date"
            ),
            {"s": settings.DATA_START_DATE, "e": settings.DATA_END_DATE},
        )
        return [row[0] for row in result]


def verify():
    logger.info("=== Verification ===")
    with engine.connect() as conn:
        for table in ["stock_basic", "trade_cal", "stock_daily"]:
            row = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()
            logger.info("  %s: %d rows", table, row)


def main():
    logger.info("Starting data pull: %s ~ %s", settings.DATA_START_DATE, settings.DATA_END_DATE)

    pull_stock_basic()
    pull_trade_cal()

    trading_days = get_trading_days()
    logger.info("Trading days to pull: %d", len(trading_days))

    pull_daily(trading_days)
    verify()

    logger.info("All done!")


if __name__ == "__main__":
    main()
