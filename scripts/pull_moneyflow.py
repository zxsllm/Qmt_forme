"""
Pull daily money flow (moneyflow_dc) for the latest trade date(s).

Usage:
    python scripts/pull_moneyflow.py                # pull latest trade date
    python scripts/pull_moneyflow.py --days 5       # pull last 5 trade days
"""

import logging
import os
import sys
import argparse
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import psycopg2
from app.research.data.tushare_service import TushareService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")


def get_recent_trade_dates(cur, n: int) -> list[str]:
    cur.execute(
        "SELECT DISTINCT trade_date FROM stock_daily "
        "ORDER BY trade_date DESC LIMIT %s", (n,)
    )
    return [r[0] for r in cur.fetchall()]


def pull_moneyflow(ts_svc: TushareService, conn, trade_dates: list[str]):
    cur = conn.cursor()
    failed = []
    for td in trade_dates:
        try:
            cur.execute("SELECT count(*) FROM moneyflow_dc WHERE trade_date = %s", (td,))
            if cur.fetchone()[0] > 0:
                logger.info("  [SKIP] %s already has data", td)
                continue

            logger.info("  Pulling moneyflow_dc for %s...", td)
            df = ts_svc.moneyflow_dc(trade_date=td)
            if df.empty:
                logger.warning("  [WARN] No data for %s", td)
                continue

            cols = [
                "ts_code", "trade_date", "buy_sm_amount", "sell_sm_amount",
                "buy_md_amount", "sell_md_amount", "buy_lg_amount", "sell_lg_amount",
                "buy_elg_amount", "sell_elg_amount", "net_mf_amount",
            ]
            available = [c for c in cols if c in df.columns]
            df = df[available].dropna(subset=["ts_code", "trade_date"])

            buf = StringIO()
            df.to_csv(buf, index=False, header=False, sep="\t", na_rep="\\N")
            buf.seek(0)
            cur.copy_from(buf, "moneyflow_dc", columns=available, sep="\t", null="\\N")
            conn.commit()
            logger.info("  [OK] %s: %d rows", td, len(df))
        except Exception as e:
            conn.rollback()
            logger.warning("moneyflow_dc failed for %s: %s", td, e)
            failed.append(td)

    cur.close()
    if failed:
        logger.warning("  Failed dates (%d): %s", len(failed), failed)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=1)
    args = parser.parse_args()

    ts_svc = TushareService()
    with psycopg2.connect(DB_URL) as conn:
        cur = conn.cursor()
        dates = get_recent_trade_dates(cur, args.days)
        cur.close()

        if not dates:
            logger.info("No trade dates found")
            return

        logger.info("Pulling moneyflow_dc for %d date(s): %s", len(dates), dates)
        pull_moneyflow(ts_svc, conn, dates)

    logger.info("Done.")


if __name__ == "__main__":
    main()
