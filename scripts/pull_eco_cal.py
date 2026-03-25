"""
Pull global economic calendar from Tushare eco_cal API.

Returns up to 100 rows per call. Pulls upcoming 14 days + past 7 days,
using UPSERT to keep values updated as events publish.

Usage:
    python scripts/pull_eco_cal.py                    # default ±14 days
    python scripts/pull_eco_cal.py --days-back 30     # past 30 days + 14 days forward
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


def pull_eco_cal(days_back: int = 7, days_forward: int = 14):
    today = datetime.now()
    start = (today - timedelta(days=days_back)).strftime("%Y%m%d")
    end = (today + timedelta(days=days_forward)).strftime("%Y%m%d")

    logger.info("eco_cal: pulling %s ~ %s", start, end)

    all_rows = []
    current = datetime.strptime(start, "%Y%m%d")
    end_dt = datetime.strptime(end, "%Y%m%d")

    while current <= end_dt:
        date_str = current.strftime("%Y%m%d")
        try:
            df = ts_svc.eco_cal(date=date_str)
            if not df.empty:
                all_rows.append(df)
        except Exception as e:
            logger.warning("eco_cal failed for %s: %s", date_str, e)
        current += timedelta(days=1)

    if not all_rows:
        logger.info("eco_cal: no data returned")
        return

    import pandas as pd
    combined = pd.concat(all_rows, ignore_index=True)
    combined = combined.drop_duplicates(subset=["date", "time", "event"], keep="last")
    combined = combined.where(combined.notna(), None)

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM eco_cal WHERE date >= :s AND date <= :e"),
            {"s": start, "e": end},
        )
        combined.to_sql("eco_cal", conn, if_exists="append", index=False)

    logger.info("eco_cal done: %d rows inserted (%s ~ %s)", len(combined), start, end)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days-back", type=int, default=7)
    parser.add_argument("--days-forward", type=int, default=14)
    args = parser.parse_args()
    pull_eco_cal(args.days_back, args.days_forward)
