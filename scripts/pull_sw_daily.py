"""
Pull Shenwan industry index daily bars from Tushare sw_daily API.

Usage:
    python scripts/pull_sw_daily.py              # incremental sync
    python scripts/pull_sw_daily.py --days 30    # pull last 30 days
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


def pull_sw_daily(days: int):
    today = datetime.now()
    start = (today - timedelta(days=days)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    trade_dates = get_trade_dates_in_range(start, end)
    if not trade_dates:
        logger.info("No trade dates in range %s ~ %s", start, end)
        return

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT DISTINCT trade_date FROM sw_daily")
        ).fetchall()
        existing = {r[0] for r in rows}

    todo = [d for d in trade_dates if d not in existing]
    logger.info("sw_daily: %d dates to pull (%d already done)", len(todo), len(existing))

    total, failed = 0, []
    for i, td in enumerate(todo):
        try:
            df = ts_svc.sw_daily(trade_date=td)
            if df.empty:
                continue
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM sw_daily WHERE trade_date = :td"), {"td": td})
                df.to_sql("sw_daily", conn, if_exists="append", index=False)
            total += len(df)
            if (i + 1) % 5 == 0 or i == len(todo) - 1:
                logger.info("  [%d/%d] %s: +%d rows (total: %d)", i + 1, len(todo), td, len(df), total)
        except Exception as e:
            logger.warning("sw_daily failed for %s: %s", td, e)
            failed.append(td)

    logger.info("sw_daily done: %d rows inserted", total)
    if failed:
        logger.warning("  Failed dates (%d): %s", len(failed), failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    pull_sw_daily(args.days)
