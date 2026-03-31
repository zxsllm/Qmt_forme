"""
Pull convertible bond data: cb_basic, cb_daily, cb_call.

Usage:
    python scripts/pull_cb.py                  # full pull (basic + call) + incremental daily
    python scripts/pull_cb.py --daily-only     # only incremental cb_daily for latest date
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import psycopg2
from psycopg2.extras import execute_values

from app.research.data.tushare_service import TushareService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")


def _to_native(v):
    if v is None or (isinstance(v, float) and str(v) == "nan"):
        return None
    return v


def _df_to_tuples(df, cols):
    return [tuple(_to_native(row.get(c)) for c in cols) for _, row in df.iterrows()]


def pull_cb_basic(svc: TushareService, conn):
    """Pull all convertible bond basic info (full refresh)."""
    cols = [
        "ts_code", "bond_short_name", "stk_code", "stk_short_name", "maturity",
        "maturity_date", "list_date", "delist_date", "exchange",
        "conv_start_date", "conv_end_date", "conv_price", "first_conv_price",
        "issue_size", "remain_size", "call_clause", "put_clause", "reset_clause",
        "conv_clause", "par", "issue_price",
    ]
    try:
        df = svc.cb_basic()
        if df.empty:
            logger.warning("cb_basic returned empty")
            return
        rows = _df_to_tuples(df, cols)
        update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "ts_code")
        with conn.cursor() as cur:
            execute_values(cur,
                f"INSERT INTO cb_basic ({','.join(cols)}) VALUES %s "
                f"ON CONFLICT (ts_code) DO UPDATE SET {update_set}", rows)
        conn.commit()
        logger.info("cb_basic: %d rows upserted", len(rows))
    except Exception as e:
        conn.rollback()
        logger.error("cb_basic failed: %s", e)


def pull_cb_call(svc: TushareService, conn):
    """Pull all convertible bond call/redemption events (full refresh)."""
    cols = [
        "ts_code", "call_type", "is_call", "ann_date", "call_date",
        "call_price", "call_price_tax", "call_vol", "call_amount",
        "payment_date", "call_reg_date",
    ]
    try:
        df = svc.cb_call()
        if df.empty:
            logger.warning("cb_call returned empty")
            return
        rows = _df_to_tuples(df, cols)
        with conn.cursor() as cur:
            cur.execute("TRUNCATE cb_call")
            execute_values(cur,
                f"INSERT INTO cb_call ({','.join(cols)}) VALUES %s", rows)
        conn.commit()
        logger.info("cb_call: %d rows (full refresh)", len(rows))
    except Exception as e:
        conn.rollback()
        logger.error("cb_call failed: %s", e)


def pull_cb_daily(svc: TushareService, conn):
    """Pull incremental cb_daily for the latest trade date."""
    cols = [
        "ts_code", "trade_date", "pre_close", "open", "high", "low", "close",
        "change", "pct_chg", "vol", "amount", "bond_value", "bond_over_rate",
        "cb_value", "cb_over_rate",
    ]
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(trade_date) FROM cb_daily")
        latest = cur.fetchone()[0]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT cal_date FROM trade_cal WHERE is_open='1' AND cal_date <= %s "
            "ORDER BY cal_date DESC LIMIT 1",
            (datetime.now().strftime("%Y%m%d"),),
        )
        row = cur.fetchone()
        today_td = row[0] if row else datetime.now().strftime("%Y%m%d")

    start = latest if latest else "20250101"
    if start >= today_td:
        logger.info("cb_daily up-to-date: %s", start)
        return

    with conn.cursor() as cur:
        cur.execute(
            "SELECT cal_date FROM trade_cal WHERE is_open='1' AND cal_date > %s AND cal_date <= %s ORDER BY cal_date",
            (start, today_td),
        )
        dates = [r[0] for r in cur.fetchall()]

    logger.info("cb_daily: pulling %d dates (%s ~ %s)", len(dates), dates[0] if dates else "?", dates[-1] if dates else "?")
    total = 0
    for td in dates:
        try:
            time.sleep(1.3)
            df = svc.cb_daily(trade_date=td)
            if df.empty:
                continue
            rows = _df_to_tuples(df, cols)
            with conn.cursor() as cur:
                execute_values(cur,
                    f"INSERT INTO cb_daily ({','.join(cols)}) VALUES %s "
                    "ON CONFLICT (ts_code, trade_date) DO NOTHING", rows)
            conn.commit()
            total += len(rows)
            logger.info("  cb_daily %s: %d rows", td, len(rows))
        except Exception as e:
            conn.rollback()
            logger.warning("  cb_daily %s failed: %s", td, e)

    logger.info("cb_daily total: %d rows across %d dates", total, len(dates))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-only", action="store_true", help="Only pull incremental cb_daily")
    args = parser.parse_args()

    svc = TushareService()
    with psycopg2.connect(DB_URL) as conn:
        if not args.daily_only:
            pull_cb_basic(svc, conn)
            time.sleep(1.5)
            pull_cb_call(svc, conn)
            time.sleep(1.5)
        pull_cb_daily(svc, conn)

    logger.info("Done.")


if __name__ == "__main__":
    main()
