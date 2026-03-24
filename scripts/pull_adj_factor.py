"""
Pull adjustment factors from Tushare adj_factor API.

Usage:
    python scripts/pull_adj_factor.py              # incremental sync
    python scripts/pull_adj_factor.py --days 30    # pull last 30 days
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


def get_trade_dates_in_range(start: str, end: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT cal_date FROM trade_cal "
                "WHERE is_open = 1 AND cal_date >= :s AND cal_date <= :e "
                "ORDER BY cal_date"
            ),
            {"s": start, "e": end},
        ).fetchall()
    return [r[0] for r in rows]


def pull_adj_factor(days: int):
    today = datetime.now()
    start = (today - timedelta(days=days)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    trade_dates = get_trade_dates_in_range(start, end)
    if not trade_dates:
        logger.info("No trade dates in range %s ~ %s", start, end)
        return

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT DISTINCT trade_date FROM adj_factor")
        ).fetchall()
        existing = {r[0] for r in rows}

    todo = [d for d in trade_dates if d not in existing]
    logger.info("adj_factor: %d dates to pull (%d already done)", len(todo), len(existing))

    total, failed = 0, []
    for i, td in enumerate(todo):
        try:
            df = ts_svc.adj_factor(trade_date=td)
            if df.empty:
                continue
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM adj_factor WHERE trade_date = :td"), {"td": td})
                df.to_sql("adj_factor", conn, if_exists="append", index=False)
            total += len(df)
            if (i + 1) % 10 == 0 or i == len(todo) - 1:
                logger.info("  [%d/%d] %s: +%d rows (total: %d)", i + 1, len(todo), td, len(df), total)
        except Exception as e:
            logger.warning("adj_factor failed for %s: %s", td, e)
            failed.append(td)

    logger.info("adj_factor done: %d rows inserted", total)
    if failed:
        logger.warning("  Failed dates (%d): %s", len(failed), failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    pull_adj_factor(args.days)
