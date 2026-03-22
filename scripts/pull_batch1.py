"""
Phase 1-后续 Batch 1: Pull daily_basic, index_basic, index_daily, index_classify.

Usage: python scripts/pull_batch1.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import create_engine, text

from app.core.config import settings
from app.research.data.tushare_service import TushareService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg")
engine = create_engine(sync_url, echo=False)
svc = TushareService()

CORE_INDICES = [
    "000001.SH",  # 上证指数
    "399001.SZ",  # 深证成指
    "399006.SZ",  # 创业板指
    "000300.SH",  # 沪深300
    "000905.SH",  # 中证500
    "000688.SH",  # 科创50
    "899050.BJ",  # 北证50
]


def get_trading_days() -> list[str]:
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT cal_date FROM trade_cal "
                "WHERE is_open = 1 AND cal_date >= :s AND cal_date <= :e "
                "ORDER BY cal_date"
            ),
            {"s": settings.DATA_START_DATE, "e": settings.DATA_END_DATE},
        )
        return [row[0] for row in result]


def pull_daily_basic(trading_days: list[str]):
    logger.info("=== Pulling daily_basic (%d days) ===", len(trading_days))
    total = 0
    errors = []

    for i, td in enumerate(trading_days):
        try:
            df = svc.daily_basic(ts_code="", trade_date=td)
            if df.empty:
                continue
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM daily_basic WHERE trade_date = :td"),
                    {"td": td},
                )
                df.to_sql("daily_basic", conn, if_exists="append", index=False)
            total += len(df)
            if (i + 1) % 20 == 0 or i == 0:
                logger.info("  [%d/%d] %s: %d (cum: %d)", i + 1, len(trading_days), td, len(df), total)
        except Exception as e:
            logger.error("  [%d/%d] %s: FAILED %s", i + 1, len(trading_days), td, e)
            errors.append(td)

    logger.info("daily_basic done: %d rows, %d errors", total, len(errors))
    return total


def pull_index_basic():
    logger.info("=== Pulling index_basic ===")
    import pandas as pd

    frames = []
    for market in ["SSE", "SZSE", "CSI", "SW"]:
        df = svc.index_basic(market=market)
        if not df.empty:
            logger.info("  index_basic market=%s: %d", market, len(df))
            frames.append(df)

    if not frames:
        logger.warning("No index_basic data")
        return 0

    df_all = pd.concat(frames, ignore_index=True)
    cols = ["ts_code", "name", "fullname", "market", "publisher", "index_type",
            "category", "base_date", "base_point", "list_date"]
    for c in cols:
        if c not in df_all.columns:
            df_all[c] = None
    df_all = df_all[cols].drop_duplicates(subset=["ts_code"], keep="first")

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE index_basic"))
        df_all.to_sql("index_basic", conn, if_exists="append", index=False)

    logger.info("index_basic done: %d rows", len(df_all))
    return len(df_all)


def pull_index_daily():
    logger.info("=== Pulling index_daily (core indices) ===")
    total = 0

    for idx_code in CORE_INDICES:
        try:
            df = svc.index_daily(
                ts_code=idx_code,
                start_date=settings.DATA_START_DATE,
                end_date=settings.DATA_END_DATE,
            )
            if df.empty:
                logger.warning("  %s: empty", idx_code)
                continue
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM index_daily WHERE ts_code = :c AND trade_date >= :s AND trade_date <= :e"),
                    {"c": idx_code, "s": settings.DATA_START_DATE, "e": settings.DATA_END_DATE},
                )
                df.to_sql("index_daily", conn, if_exists="append", index=False)
            total += len(df)
            logger.info("  %s: %d rows", idx_code, len(df))
        except Exception as e:
            logger.error("  %s: FAILED %s", idx_code, e)

    logger.info("index_daily done: %d rows", total)
    return total


def pull_index_classify():
    logger.info("=== Pulling index_classify (SW2021) ===")
    import pandas as pd

    frames = []
    for level in ["L1", "L2", "L3"]:
        df = svc.index_classify(level=level, src="SW2021")
        if not df.empty:
            logger.info("  SW2021 %s: %d", level, len(df))
            frames.append(df)

    if not frames:
        logger.warning("No index_classify data")
        return 0

    df_all = pd.concat(frames, ignore_index=True)
    df_all = df_all.drop_duplicates(subset=["index_code"], keep="first")

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE index_classify"))
        df_all.to_sql("index_classify", conn, if_exists="append", index=False)

    logger.info("index_classify done: %d rows", len(df_all))
    return len(df_all)


def verify():
    logger.info("=== Verification ===")
    with engine.connect() as conn:
        for table in ["daily_basic", "index_basic", "index_daily", "index_classify"]:
            row = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()
            logger.info("  %s: %d rows", table, row)


def main():
    logger.info("Starting Batch 1 pull")

    pull_index_basic()
    pull_index_classify()
    pull_index_daily()

    trading_days = get_trading_days()
    logger.info("Trading days for daily_basic: %d", len(trading_days))
    pull_daily_basic(trading_days)

    verify()
    logger.info("Batch 1 done!")


if __name__ == "__main__":
    main()
