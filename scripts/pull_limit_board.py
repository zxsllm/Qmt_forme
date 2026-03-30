"""
Pull limit-up/down board data: limit_list_ths, limit_list_d (stats),
limit_step, top_list (dragon-tiger), hm_detail, limit_cpt_list, dc_hot.

All APIs accept trade_date as parameter. We pull the latest trading day.

Usage:
    python scripts/pull_limit_board.py                       # latest day
    python scripts/pull_limit_board.py --date 20260320       # specific date
    python scripts/pull_limit_board.py --start 20260301 --end 20260320  # range
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
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


def _get_trade_dates(conn, start: str, end: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT cal_date FROM trade_cal WHERE is_open='1' AND cal_date BETWEEN %s AND %s ORDER BY cal_date",
            (start, end),
        )
        return [r[0] for r in cur.fetchall()]


def pull_for_date(svc: TushareService, conn, trade_date: str):
    """Pull all board data for one trading day."""
    failed = []

    # 1. limit_list_ths
    try:
        cols = ["trade_date", "ts_code", "name", "pct_chg", "limit_type",
                "first_lu_time", "last_lu_time", "open_num", "limit_amount",
                "turnover_rate", "tag", "status"]
        df = svc.limit_list_ths(trade_date=trade_date)
        if not df.empty:
            rows = _df_to_tuples(df, cols)
            with conn.cursor() as cur:
                execute_values(cur,
                    f"INSERT INTO limit_list_ths ({','.join(cols)}) VALUES %s "
                    "ON CONFLICT (trade_date, ts_code, limit_type) DO NOTHING", rows)
            conn.commit()
            logger.info("  limit_list_ths %s: %d rows", trade_date, len(rows))
    except Exception as e:
        conn.rollback()
        failed.append(("limit_list_ths", e))

    # 2. limit_list_d → limit_stats
    for lt in ["U", "D", "Z"]:
        try:
            cols = ["trade_date", "ts_code", "name", "industry", "close", "pct_chg",
                    "amount", "limit_amount", "float_mv", "first_time", "last_time",
                    "open_times", "limit_times", "limit"]
            df = svc.limit_list_d(trade_date=trade_date, limit_type=lt)
            if not df.empty:
                rows = _df_to_tuples(df, cols)
                quoted_cols = [f'"{c}"' if c == "limit" else c for c in cols]
                with conn.cursor() as cur:
                    execute_values(cur,
                        f"INSERT INTO limit_stats ({','.join(quoted_cols)}) VALUES %s "
                        'ON CONFLICT (trade_date, ts_code, "limit") DO NOTHING', rows)
                conn.commit()
                logger.info("  limit_stats %s type=%s: %d rows", trade_date, lt, len(rows))
        except Exception as e:
            conn.rollback()
            failed.append((f"limit_stats_{lt}", e))

    # 3. limit_step
    try:
        cols = ["ts_code", "name", "trade_date", "nums"]
        df = svc.limit_step(trade_date=trade_date)
        if not df.empty:
            rows = _df_to_tuples(df, cols)
            with conn.cursor() as cur:
                execute_values(cur,
                    f"INSERT INTO limit_step ({','.join(cols)}) VALUES %s "
                    "ON CONFLICT (trade_date, ts_code) DO NOTHING", rows)
            conn.commit()
            logger.info("  limit_step %s: %d rows", trade_date, len(rows))
    except Exception as e:
        conn.rollback()
        failed.append(("limit_step", e))

    # 4. top_list (dragon-tiger)
    try:
        cols = ["trade_date", "ts_code", "name", "close", "pct_change",
                "turnover_rate", "amount", "l_sell", "l_buy", "l_amount",
                "net_amount", "net_rate", "reason"]
        df = svc.top_list(trade_date=trade_date)
        if not df.empty:
            rows = _df_to_tuples(df, cols)
            with conn.cursor() as cur:
                execute_values(cur,
                    f"INSERT INTO top_list ({','.join(cols)}) VALUES %s "
                    "ON CONFLICT (trade_date, ts_code) DO NOTHING", rows)
            conn.commit()
            logger.info("  top_list %s: %d rows", trade_date, len(rows))
    except Exception as e:
        conn.rollback()
        failed.append(("top_list", e))

    # 5. hm_detail (hot money)
    try:
        cols = ["trade_date", "ts_code", "ts_name", "buy_amount",
                "sell_amount", "net_amount", "hm_name", "tag"]
        df = svc.hm_detail(trade_date=trade_date)
        if not df.empty:
            rows = _df_to_tuples(df, cols)
            with conn.cursor() as cur:
                execute_values(cur,
                    f"INSERT INTO hm_detail ({','.join(cols)}) VALUES %s "
                    "ON CONFLICT (trade_date, ts_code, hm_name) DO NOTHING", rows)
            conn.commit()
            logger.info("  hm_detail %s: %d rows", trade_date, len(rows))
    except Exception as e:
        conn.rollback()
        failed.append(("hm_detail", e))

    # 6. limit_cpt_list (strongest sector)
    try:
        cols = ["ts_code", "name", "trade_date", "days", "up_stat",
                "cons_nums", "up_nums", "pct_chg", "rank"]
        df = svc.limit_cpt_list(trade_date=trade_date)
        if not df.empty:
            rows = _df_to_tuples(df, cols)
            with conn.cursor() as cur:
                execute_values(cur,
                    f"INSERT INTO limit_cpt_list ({','.join(cols)}) VALUES %s "
                    "ON CONFLICT (trade_date, ts_code) DO NOTHING", rows)
            conn.commit()
            logger.info("  limit_cpt_list %s: %d rows", trade_date, len(rows))
    except Exception as e:
        conn.rollback()
        failed.append(("limit_cpt_list", e))

    # 7. dc_hot (Eastmoney hot list)
    try:
        cols = ["trade_date", "data_type", "ts_code", "ts_name",
                "rank", "pct_change", "current_price"]
        df = svc.dc_hot(trade_date=trade_date)
        if not df.empty:
            rows = _df_to_tuples(df, cols)
            with conn.cursor() as cur:
                execute_values(cur,
                    f"INSERT INTO dc_hot ({','.join(cols)}) VALUES %s "
                    "ON CONFLICT (trade_date, ts_code, data_type) DO NOTHING", rows)
            conn.commit()
            logger.info("  dc_hot %s: %d rows", trade_date, len(rows))
    except Exception as e:
        conn.rollback()
        failed.append(("dc_hot", e))

    if failed:
        for name, err in failed:
            logger.warning("  [WARN] %s %s: %s", name, trade_date, err)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="Single date YYYYMMDD")
    parser.add_argument("--start", default=None, help="Start date YYYYMMDD")
    parser.add_argument("--end", default=None, help="End date YYYYMMDD")
    args = parser.parse_args()

    svc = TushareService()
    with psycopg2.connect(DB_URL) as conn:
        if args.start and args.end:
            dates = _get_trade_dates(conn, args.start, args.end)
            logger.info("Pulling board data for %d dates: %s ~ %s", len(dates), args.start, args.end)
            for d in dates:
                pull_for_date(svc, conn, d)
        else:
            trade_date = args.date
            if not trade_date:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT cal_date FROM trade_cal WHERE is_open='1' AND cal_date <= %s ORDER BY cal_date DESC LIMIT 1",
                        (datetime.now().strftime("%Y%m%d"),),
                    )
                    row = cur.fetchone()
                    trade_date = row[0] if row else datetime.now().strftime("%Y%m%d")
            logger.info("Pulling board data for %s", trade_date)
            pull_for_date(svc, conn, trade_date)

    logger.info("Done.")


if __name__ == "__main__":
    main()
