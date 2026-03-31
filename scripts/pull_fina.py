"""
Pull financial data: fina_indicator, income, forecast, fina_mainbz, disclosure_date.

Pulls recent 4 quarters to maximize coverage. Skips stocks that already have data.

Usage:
    python scripts/pull_fina.py                    # full pull (skip stocks with data)
    python scripts/pull_fina.py --force             # force re-pull all stocks
    python scripts/pull_fina.py --daily             # lightweight daily mode
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


def _get_all_codes(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT ts_code FROM stock_basic WHERE list_status='L' ORDER BY ts_code")
        return [r[0] for r in cur.fetchall()]


def _get_existing_codes(conn, table: str) -> set[str]:
    recent_quarters = _recent_4_quarters()
    if not recent_quarters:
        return set()
    placeholders = ",".join(["%s"] * len(recent_quarters))
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT ts_code FROM {table} WHERE end_date IN ({placeholders})",
            recent_quarters,
        )
        return {r[0] for r in cur.fetchall()}


def pull_fina_indicator(svc, conn, codes: list[str]):
    """Pull fina_indicator for given stock codes. No period filter = get all available."""
    cols = [
        "ts_code", "ann_date", "end_date", "eps", "dt_eps", "profit_dedt",
        "roe", "roe_waa", "roe_dt", "roa", "netprofit_margin", "grossprofit_margin",
        "debt_to_assets", "ocfps", "bps", "current_ratio", "quick_ratio",
        "netprofit_yoy", "dt_netprofit_yoy", "tr_yoy", "or_yoy",
    ]
    recent = _recent_4_quarters()
    total = 0
    logger.info("Pulling fina_indicator for %d stocks (recent periods: %s)...", len(codes), recent)

    for i, code in enumerate(codes):
        try:
            df = svc.fina_indicator(ts_code=code, start_date=recent[-1] if recent else None)
            if df.empty:
                continue
            rows = _df_to_tuples(df, cols)
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    f"INSERT INTO fina_indicator ({','.join(cols)}) VALUES %s "
                    "ON CONFLICT (ts_code, end_date) DO NOTHING",
                    rows,
                )
            total += len(rows)
        except Exception as e:
            if "每分钟" in str(e) or "exceed" in str(e).lower():
                logger.warning("Rate limit hit at %d/%d, sleeping 60s...", i, len(codes))
                time.sleep(60)
            else:
                logger.debug("fina_indicator %s: %s", code, e)

        if (i + 1) % 500 == 0:
            conn.commit()
            logger.info("  fina_indicator: %d/%d stocks done, %d rows", i + 1, len(codes), total)

    conn.commit()
    logger.info("[OK] fina_indicator: %d rows from %d stocks", total, len(codes))


def pull_income(svc, conn, codes: list[str]):
    """Pull income for given stock codes."""
    cols = [
        "ts_code", "ann_date", "f_ann_date", "end_date", "report_type",
        "total_revenue", "revenue", "oper_cost", "sell_exp", "admin_exp",
        "fin_exp", "rd_exp", "operate_profit", "total_profit", "income_tax",
        "n_income", "n_income_attr_p", "basic_eps",
    ]
    recent = _recent_4_quarters()
    total = 0
    logger.info("Pulling income for %d stocks...", len(codes))

    for i, code in enumerate(codes):
        try:
            df = svc.income(ts_code=code, start_date=recent[-1] if recent else None)
            if df.empty:
                continue
            rows = _df_to_tuples(df, cols)
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    f"INSERT INTO income ({','.join(cols)}) VALUES %s "
                    "ON CONFLICT (ts_code, end_date, report_type) DO NOTHING",
                    rows,
                )
            total += len(rows)
        except Exception as e:
            if "每分钟" in str(e) or "exceed" in str(e).lower():
                logger.warning("Rate limit hit at %d/%d, sleeping 60s...", i, len(codes))
                time.sleep(60)
            else:
                logger.debug("income %s: %s", code, e)

        if (i + 1) % 500 == 0:
            conn.commit()
            logger.info("  income: %d/%d stocks done, %d rows", i + 1, len(codes), total)

    conn.commit()
    logger.info("[OK] income: %d rows from %d stocks", total, len(codes))


def pull_forecast(svc, conn):
    """Forecast requires ann_date or ts_code; iterate recent ann_dates."""
    from datetime import date, timedelta
    cols = [
        "ts_code", "ann_date", "end_date", "type", "p_change_min", "p_change_max",
        "net_profit_min", "net_profit_max", "last_parent_net", "summary", "change_reason",
    ]
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(ann_date) FROM forecast")
        row = cur.fetchone()
        last = row[0] if row and row[0] else "20250101"

    start = date(int(last[:4]), int(last[4:6]), int(last[6:8])) + timedelta(days=1)
    end = date.today()
    total = 0
    logger.info("Pulling forecast ann_date %s → %s ...", start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))

    d = start
    while d <= end:
        ds = d.strftime("%Y%m%d")
        try:
            df = svc.forecast(ann_date=ds)
            if not df.empty:
                rows = _df_to_tuples(df, cols)
                with conn.cursor() as cur:
                    execute_values(
                        cur,
                        f"INSERT INTO forecast ({','.join(cols)}) VALUES %s "
                        "ON CONFLICT (ts_code, ann_date, end_date) DO NOTHING",
                        rows,
                    )
                conn.commit()
                total += len(rows)
        except Exception as e:
            if "每分钟" in str(e) or "exceed" in str(e).lower():
                logger.warning("Rate limited, sleeping 60s...")
                time.sleep(60)
                continue
            else:
                logger.debug("forecast %s: %s", ds, e)
        d += timedelta(days=1)

    logger.info("[OK] forecast: %d rows", total)


def pull_fina_mainbz(svc, conn, codes: list[str]):
    """Pull main business composition for given stock codes."""
    cols = ["ts_code", "end_date", "bz_item", "bz_sales", "bz_profit", "bz_cost", "curr_type"]
    total = 0
    logger.info("Pulling fina_mainbz for %d stocks...", len(codes))

    for i, code in enumerate(codes):
        try:
            df = svc.fina_mainbz(ts_code=code, type="P")
            if df.empty:
                continue
            rows = _df_to_tuples(df, cols)
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    f"INSERT INTO fina_mainbz ({','.join(cols)}) VALUES %s "
                    "ON CONFLICT (ts_code, end_date, bz_item) DO NOTHING",
                    rows,
                )
            total += len(rows)
        except Exception as e:
            if "每分钟" in str(e) or "exceed" in str(e).lower():
                logger.warning("Rate limit hit at %d/%d, sleeping 60s...", i, len(codes))
                time.sleep(60)
            else:
                logger.debug("fina_mainbz %s: %s", code, e)

        if (i + 1) % 500 == 0:
            conn.commit()
            logger.info("  fina_mainbz: %d/%d stocks done, %d rows", i + 1, len(codes), total)

    conn.commit()
    logger.info("[OK] fina_mainbz: %d rows from %d stocks", total, len(codes))


def pull_disclosure_date(svc, conn, periods: list[str]):
    """Disclosure date supports batch by period."""
    cols = ["ts_code", "ann_date", "end_date", "pre_date", "actual_date", "modify_date"]
    total = 0
    for period in periods:
        logger.info("Pulling disclosure_date end_date=%s ...", period)
        try:
            df = svc.disclosure_date(end_date=period)
            if df.empty:
                continue
            rows = _df_to_tuples(df, cols)
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    f"INSERT INTO disclosure_date ({','.join(cols)}) VALUES %s "
                    "ON CONFLICT (ts_code, end_date) DO UPDATE SET "
                    "pre_date=EXCLUDED.pre_date, actual_date=EXCLUDED.actual_date, modify_date=EXCLUDED.modify_date",
                    rows,
                )
            conn.commit()
            total += len(rows)
            logger.info("  disclosure_date %s: %d rows", period, len(rows))
        except Exception as e:
            conn.rollback()
            logger.warning("disclosure_date %s failed: %s", period, e)

    logger.info("[OK] disclosure_date: %d rows total", total)


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


def _recent_4_quarters() -> list[str]:
    """Return the most recent 4 quarter-end dates that could have data."""
    from datetime import date
    today = date.today()
    y = today.year
    all_q = [
        f"{y-1}1231", f"{y-1}0930", f"{y-1}0630", f"{y-1}0331",
        f"{y-2}1231", f"{y-2}0930",
    ]
    return all_q[:4]


def _has_fina_data(conn, period: str, min_rows: int = 2000) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM fina_indicator WHERE end_date = %s", (period,))
        return cur.fetchone()[0] >= min_rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily", action="store_true",
                        help="Daily mode: only forecast+disclosure; skip heavy per-stock pulls if data exists")
    parser.add_argument("--force", action="store_true",
                        help="Force pull all stocks even if they have existing data")
    args = parser.parse_args()

    periods = _recent_4_quarters()
    logger.info("Target periods: %s", periods)
    svc = TushareService()

    with psycopg2.connect(DB_URL) as conn:
        pull_forecast(svc, conn)
        pull_disclosure_date(svc, conn, periods)

        if args.daily:
            latest = _latest_quarter()
            if _has_fina_data(conn, latest):
                logger.info("Daily mode: fina data sufficient for %s, skipping.", latest)
            else:
                logger.info("Daily mode: new period %s detected, pulling...", latest)
                all_codes = _get_all_codes(conn)
                pull_fina_indicator(svc, conn, all_codes)
                pull_income(svc, conn, all_codes)
        else:
            all_codes = _get_all_codes(conn)

            if args.force:
                fina_codes = all_codes
                income_codes = all_codes
                mainbz_codes = all_codes
            else:
                existing_fina = _get_existing_codes(conn, "fina_indicator")
                fina_codes = [c for c in all_codes if c not in existing_fina]
                logger.info("fina_indicator: %d existing, %d to pull", len(existing_fina), len(fina_codes))

                existing_income = _get_existing_codes(conn, "income")
                income_codes = [c for c in all_codes if c not in existing_income]
                logger.info("income: %d existing, %d to pull", len(existing_income), len(income_codes))

                existing_mainbz = _get_existing_codes(conn, "fina_mainbz")
                mainbz_codes = [c for c in all_codes if c not in existing_mainbz]
                logger.info("fina_mainbz: %d existing, %d to pull", len(existing_mainbz), len(mainbz_codes))

            pull_fina_indicator(svc, conn, fina_codes)
            pull_income(svc, conn, income_codes)
            pull_fina_mainbz(svc, conn, mainbz_codes)

    logger.info("Done.")


if __name__ == "__main__":
    main()
