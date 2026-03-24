"""
Pull latest company announcements from Tushare anns_d API.

Usage:
    python scripts/pull_anns.py                # pull today's announcements
    python scripts/pull_anns.py --days 3       # pull last 3 days
"""

import logging
import os
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import psycopg2
from psycopg2.extras import execute_values
from app.research.data.tushare_service import TushareService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")


def _to_native(v):
    if v is None or (isinstance(v, float) and str(v) == "nan"):
        return None
    return str(v)


def pull_anns(ts_svc: TushareService, conn, days: int):
    today = datetime.now()
    dates = [(today - timedelta(days=i)).strftime("%Y%m%d") for i in range(days)]

    total_inserted = 0
    for ann_date in dates:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM stock_anns WHERE ann_date = %s", (ann_date,)
            )
            existing = cur.fetchone()[0]
        if existing > 0:
            logger.info("  [SKIP] %s already has %d announcements", ann_date, existing)
            continue

        logger.info("  Pulling announcements for %s...", ann_date)
        try:
            df = ts_svc.anns(ann_date=ann_date)
        except Exception as e:
            logger.warning("  [ERROR] Failed to pull %s: %s", ann_date, e)
            continue

        if df.empty:
            logger.info("  [WARN] No announcements for %s", ann_date)
            continue

        required = ["ts_code", "ann_date", "title"]
        if not all(c in df.columns for c in required):
            logger.warning("  [WARN] Missing required columns. Got: %s", list(df.columns))
            continue

        insert_cols = ["ts_code", "ann_date", "title", "url"]
        available = [c for c in insert_cols if c in df.columns]

        rows = [
            tuple(_to_native(row.get(c)) for c in available)
            for _, row in df.iterrows()
        ]

        with conn.cursor() as cur:
            col_str = ",".join(available)
            execute_values(cur, f"INSERT INTO stock_anns ({col_str}) VALUES %s", rows)
            conn.commit()

        logger.info("  [OK] %s: %d announcements", ann_date, len(rows))
        total_inserted += len(rows)

    logger.info("  Total inserted: %d", total_inserted)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=1)
    args = parser.parse_args()

    ts_svc = TushareService()
    with psycopg2.connect(DB_URL) as conn:
        pull_anns(ts_svc, conn, args.days)
    logger.info("Done.")


if __name__ == "__main__":
    main()
