"""
Pull financial data: fina_indicator, income, forecast, fina_mainbz, disclosure_date.

These APIs return max 100 rows per call (fina_indicator/fina_mainbz) and require
per-stock iteration. We pull the latest period for all active stocks.

Usage:
    python scripts/pull_fina.py                    # pull latest period
    python scripts/pull_fina.py --period 20251231  # specific period
"""

import argparse
import logging
import os
import sys
import time
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


def pull_fina_indicator(svc, conn, period: str | None):
    cols = [
        "ts_code", "ann_date", "end_date", "eps", "dt_eps", "profit_dedt",
        "roe", "roe_waa", "roe_dt", "roa", "netprofit_margin", "grossprofit_margin",
        "debt_to_assets", "ocfps", "bps", "current_ratio", "quick_ratio",
        "netprofit_yoy", "dt_netprofit_yoy", "tr_yoy", "or_yoy",
    ]
    kwargs = {}
    if period:
        kwargs["period"] = period
    else:
        kwargs["period"] = _latest_quarter()

    logger.info("Pulling fina_indicator for period=%s ...", kwargs.get("period"))
    total = 0
    for exchange in ["SSE", "SZSE", "BSE"]:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ts_code FROM stock_basic WHERE list_status='L' AND exchange=%s",
                    (exchange,),
                )
                codes = [r[0] for r in cur.fetchall()]

            for i in range(0, len(codes), 50):
                batch_codes = codes[i:i+50]
                for code in batch_codes:
                    try:
                        df = svc.fina_indicator(ts_code=code, **kwargs)
                        if df.empty:
                            continue
                        rows = _df_to_tuples(df, cols)
                        with conn.cursor() as cur:
                            col_str = ",".join(cols)
                            execute_values(
                                cur,
                                f"INSERT INTO fina_indicator ({col_str}) VALUES %s "
                                "ON CONFLICT (ts_code, end_date) DO NOTHING",
                                rows,
                            )
                        total += len(rows)
                    except Exception as e:
                        logger.warning("fina_indicator %s failed: %s", code, e)
                conn.commit()
                logger.info("  fina_indicator: %d/%d stocks", min(i+50, len(codes)), len(codes))
        except Exception as e:
            logger.warning("fina_indicator exchange=%s failed: %s", exchange, e)

    logger.info("[OK] fina_indicator: %d rows inserted", total)


def pull_forecast(svc, conn, period: str | None):
    cols = [
        "ts_code", "ann_date", "end_date", "type", "p_change_min", "p_change_max",
        "net_profit_min", "net_profit_max", "last_parent_net", "summary", "change_reason",
    ]
    kwargs = {}
    if period:
        kwargs["period"] = period
    else:
        kwargs["period"] = _latest_quarter()

    logger.info("Pulling forecast for period=%s ...", kwargs.get("period"))
    try:
        df = svc.forecast(**kwargs)
        if df.empty:
            logger.info("  forecast: no data")
            return
        rows = _df_to_tuples(df, cols)
        with conn.cursor() as cur:
            col_str = ",".join(cols)
            execute_values(
                cur,
                f"INSERT INTO forecast ({col_str}) VALUES %s "
                "ON CONFLICT (ts_code, ann_date, end_date) DO NOTHING",
                rows,
            )
        conn.commit()
        logger.info("[OK] forecast: %d rows", len(rows))
    except Exception as e:
        logger.warning("forecast failed: %s", e)


def pull_income(svc, conn, period: str | None):
    cols = [
        "ts_code", "ann_date", "f_ann_date", "end_date", "report_type",
        "total_revenue", "revenue", "oper_cost", "sell_exp", "admin_exp",
        "fin_exp", "rd_exp", "operate_profit", "total_profit", "income_tax",
        "n_income", "n_income_attr_p", "basic_eps",
    ]
    kwargs = {}
    if period:
        kwargs["period"] = period
    else:
        kwargs["period"] = _latest_quarter()

    logger.info("Pulling income for period=%s ...", kwargs.get("period"))
    total = 0
    for exchange in ["SSE", "SZSE", "BSE"]:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ts_code FROM stock_basic WHERE list_status='L' AND exchange=%s",
                    (exchange,),
                )
                codes = [r[0] for r in cur.fetchall()]

            for i in range(0, len(codes), 50):
                batch_codes = codes[i:i+50]
                for code in batch_codes:
                    try:
                        df = svc.income(ts_code=code, **kwargs)
                        if df.empty:
                            continue
                        rows = _df_to_tuples(df, cols)
                        with conn.cursor() as cur:
                            col_str = ",".join(cols)
                            execute_values(
                                cur,
                                f"INSERT INTO income ({col_str}) VALUES %s "
                                "ON CONFLICT (ts_code, end_date, report_type) DO NOTHING",
                                rows,
                            )
                        total += len(rows)
                    except Exception as e:
                        logger.warning("income %s failed: %s", code, e)
                conn.commit()
                logger.info("  income: %d/%d stocks", min(i+50, len(codes)), len(codes))
        except Exception as e:
            logger.warning("income exchange=%s failed: %s", exchange, e)

    logger.info("[OK] income: %d rows inserted", total)


def pull_disclosure_date(svc, conn, end_date: str | None):
    cols = ["ts_code", "ann_date", "end_date", "pre_date", "actual_date", "modify_date"]
    kwargs = {}
    if end_date:
        kwargs["end_date"] = end_date
    else:
        kwargs["end_date"] = _latest_quarter()

    logger.info("Pulling disclosure_date for end_date=%s ...", kwargs.get("end_date"))
    try:
        df = svc.disclosure_date(**kwargs)
        if df.empty:
            logger.info("  disclosure_date: no data")
            return
        rows = _df_to_tuples(df, cols)
        with conn.cursor() as cur:
            col_str = ",".join(cols)
            execute_values(
                cur,
                f"INSERT INTO disclosure_date ({col_str}) VALUES %s "
                "ON CONFLICT (ts_code, end_date) DO UPDATE SET "
                "pre_date=EXCLUDED.pre_date, actual_date=EXCLUDED.actual_date, modify_date=EXCLUDED.modify_date",
                rows,
            )
        conn.commit()
        logger.info("[OK] disclosure_date: %d rows", len(rows))
    except Exception as e:
        logger.warning("disclosure_date failed: %s", e)


def _latest_quarter():
    from datetime import date
    today = date.today()
    m, y = today.month, today.year
    if m <= 3:
        return f"{y-1}1231"
    elif m <= 6:
        return f"{y}0331"
    elif m <= 9:
        return f"{y}0630"
    else:
        return f"{y}0930"


def _has_fina_data(conn, period: str, min_rows: int = 500) -> bool:
    """Check if we already have significant fina_indicator data for this period."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM fina_indicator WHERE end_date = %s",
            (period,),
        )
        count = cur.fetchone()[0]
    return count >= min_rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", default=None, help="Report period YYYYMMDD (e.g. 20251231)")
    parser.add_argument("--daily", action="store_true",
                        help="Daily mode: only forecast+disclosure_date; skip heavy fina_indicator/income if data exists")
    args = parser.parse_args()

    period = args.period or _latest_quarter()
    svc = TushareService()
    with psycopg2.connect(DB_URL) as conn:
        pull_forecast(svc, conn, args.period)
        pull_disclosure_date(svc, conn, args.period)

        if args.daily:
            if _has_fina_data(conn, period):
                logger.info("Daily mode: fina_indicator/income already has data for %s, skipping.", period)
            else:
                logger.info("Daily mode: new period %s detected, pulling fina_indicator/income...", period)
                pull_fina_indicator(svc, conn, args.period)
                pull_income(svc, conn, args.period)
        else:
            pull_fina_indicator(svc, conn, args.period)
            pull_income(svc, conn, args.period)

    logger.info("Done.")


if __name__ == "__main__":
    main()
