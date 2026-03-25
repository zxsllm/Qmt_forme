"""
Pull international index daily bars from Tushare index_global API.

Covers 12 major global indices. Up to 4000 rows per call.

Usage:
    python scripts/pull_index_global.py              # incremental (last 30 days)
    python scripts/pull_index_global.py --days 180   # pull last 180 days
"""

import logging
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

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

INDEX_CODES = [
    "DJI", "SPX", "IXIC", "FTSE", "GDAXI", "N225",
    "HSI", "HKTECH", "XIN9", "KS11", "TWII", "SENSEX",
]


def pull_index_global(days: int):
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    end = datetime.now().strftime("%Y%m%d")

    import pandas as pd

    total, failed = 0, []
    for code in INDEX_CODES:
        try:
            df = ts_svc.index_global(ts_code=code, start_date=start, end_date=end)
            if df.empty:
                logger.info("  %s: no data", code)
                continue
            float_cols = ["open", "close", "high", "low", "pre_close", "change", "pct_chg", "vol", "amount"]
            for col in float_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM index_global WHERE ts_code = :c AND trade_date >= :s AND trade_date <= :e"),
                    {"c": code, "s": start, "e": end},
                )
                df.to_sql("index_global", conn, if_exists="append", index=False)
            total += len(df)
            logger.info("  %s: %d rows", code, len(df))
        except Exception as e:
            logger.warning("  %s failed: %s", code, e)
            failed.append(code)

    logger.info("index_global done: %d rows inserted", total)
    if failed:
        logger.warning("  Failed codes: %s", failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    pull_index_global(args.days)
