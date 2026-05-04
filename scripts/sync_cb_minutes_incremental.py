"""Incremental sync of 1-minute bar data for **convertible bonds**.

Mirror of sync_minutes_incremental.py, but:
  * 标的列表来自 cb_basic（剔除已退市）
  * 写入 cb_min_kline 分区表
  * 数据源仍是 svc.stk_mins —— Tushare 的 stk_mins 后端是泛接口，
    传入可转债 ts_code 同样能返回 1min K 线。

Usage:
    python scripts/sync_cb_minutes_incremental.py                   # sync all to latest
    python scripts/sync_cb_minutes_incremental.py --test 5          # test with 5 bonds
    python scripts/sync_cb_minutes_incremental.py --from 20260321   # explicit start date
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

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


def bypass_proxy_for_tushare() -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(name, None)
    hosts = ["api.tushare.pro", "api.waditu.com", "127.0.0.1", "localhost"]
    for name in ("NO_PROXY", "no_proxy"):
        current = [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]
        merged = current + [host for host in hosts if host not in current]
        os.environ[name] = ",".join(merged)


bypass_proxy_for_tushare()

sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg")
engine = create_engine(sync_url, echo=False)
svc = TushareService()

FREQ = "1min"
TABLE = "cb_min_kline"


def get_cb_list(target_date: str) -> list[str]:
    """Active, exchange-traded convertible bonds at target_date.

    过滤逻辑：
    - 必须有 list_date（剔除 list_date IS NULL 的定向/私募债，它们没有二级市场分钟行情）
    - list_date <= 目标日（已上市）
    - delist_date 为空或晚于目标日（未退市）
    """
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT ts_code FROM cb_basic "
            "WHERE list_date IS NOT NULL AND list_date <> '' "
            "  AND list_date <= :td "
            "  AND (delist_date IS NULL OR delist_date = '' OR delist_date > :td) "
            "ORDER BY ts_code"
        ), {"td": target_date})
        return [row[0] for row in result]


def get_latest_per_code() -> dict[str, str]:
    with engine.connect() as conn:
        result = conn.execute(text(
            f"SELECT ts_code, MAX(trade_time)::date as latest "
            f"FROM {TABLE} WHERE freq = :f "
            f"GROUP BY ts_code"
        ), {"f": FREQ})
        return {row[0]: row[1].strftime("%Y-%m-%d") for row in result}


def get_latest_trade_date() -> str:
    today = datetime.now().strftime("%Y%m%d")
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT cal_date FROM trade_cal "
            "WHERE is_open = 1 AND cal_date <= :td "
            "ORDER BY cal_date DESC LIMIT 1"
        ), {"td": today})
        row = result.fetchone()
        return row[0] if row else today


def pull_range(ts_code: str, start_date: str, end_date: str) -> int:
    start_dt = f"{start_date} 09:00:00"
    end_dt = f"{end_date} 16:00:00"

    all_rows = []
    cur_end = end_dt

    while True:
        df = svc.stk_mins(
            ts_code=ts_code, freq=FREQ,
            start_date=start_dt, end_date=cur_end,
        )
        if df is None or df.empty:
            if not all_rows:
                time.sleep(0.4)
                df = svc.stk_mins(
                    ts_code=ts_code, freq=FREQ,
                    start_date=start_dt, end_date=cur_end,
                )
                if df is None or df.empty:
                    break
                all_rows.append(df)
                if len(df) < 8000:
                    break
                cur_end = df["trade_time"].min()
                time.sleep(0.05)
                continue
            break
        all_rows.append(df)
        if len(df) < 8000:
            break
        cur_end = df["trade_time"].min()
        time.sleep(0.05)

    if not all_rows:
        return 0

    df_all = pd.concat(all_rows, ignore_index=True)
    df_all = df_all.drop_duplicates(subset=["ts_code", "trade_time"], keep="first")
    df_all["freq"] = FREQ
    df_all["trade_time"] = pd.to_datetime(df_all["trade_time"])

    with engine.begin() as conn:
        conn.execute(text(
            f"DELETE FROM {TABLE} "
            f"WHERE ts_code = :c AND freq = :f "
            f"AND trade_time >= :s AND trade_time <= :e"
        ), {"c": ts_code, "f": FREQ, "s": start_dt, "e": end_dt})
        df_all.to_sql(TABLE, conn, if_exists="append", index=False, chunksize=5000)

    return len(df_all)


def main():
    parser = argparse.ArgumentParser(description="Incremental CB-minute data sync")
    parser.add_argument("--test", type=int, default=0, help="Test with N bonds")
    parser.add_argument("--from", dest="from_date", default="", help="Force start date YYYYMMDD")
    args = parser.parse_args()

    target_date = get_latest_trade_date()
    target_fmt = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:]}"
    bonds = get_cb_list(target_date)
    logger.info("Active convertible bonds at %s: %d", target_date, len(bonds))
    logger.info("Target: sync all CB minute data up to %s", target_date)

    if args.from_date:
        force_start = args.from_date
        force_start_fmt = f"{force_start[:4]}-{force_start[4:6]}-{force_start[6:]}"
        logger.info("Forced start date: %s", force_start)
        latest_map: dict[str, str] = {}
    else:
        logger.info("Scanning existing CB minute coverage...")
        latest_map = get_latest_per_code()
        logger.info("Found coverage info for %d bonds", len(latest_map))

    if args.test > 0:
        bonds = bonds[: args.test]
        logger.info("Test mode: %d bonds", len(bonds))

    total_rows = 0
    skipped = 0
    errors: list[str] = []
    t0 = time.time()

    for i, ts_code in enumerate(bonds):
        try:
            if args.from_date:
                sync_start = force_start_fmt
            else:
                existing_latest = latest_map.get(ts_code)
                if existing_latest and existing_latest >= target_fmt:
                    skipped += 1
                    continue
                if existing_latest:
                    sync_start = existing_latest
                else:
                    sync_start = f"{settings.DATA_START_DATE[:4]}-{settings.DATA_START_DATE[4:6]}-{settings.DATA_START_DATE[6:]}"

            n = pull_range(ts_code, sync_start.replace("-", ""), target_date)
            total_rows += n

            done = i + 1
            if done % 50 == 0 or done == 1 or args.test:
                elapsed = time.time() - t0
                rate = done / elapsed * 60 if elapsed > 0 else 0
                logger.info(
                    "  [%d/%d] %s: +%d bars (cum: %d, %.0f bonds/min, skipped: %d)",
                    done, len(bonds), ts_code, n, total_rows, rate, skipped,
                )
        except Exception as e:
            logger.error("  [%d/%d] %s: FAILED %s", i + 1, len(bonds), ts_code, e)
            errors.append(ts_code)

    elapsed = time.time() - t0
    logger.info(
        "Done! %d bonds processed, %d skipped (already fresh), "
        "%d total new rows, %d errors, %.1f minutes",
        len(bonds) - skipped, skipped, total_rows, len(errors), elapsed / 60,
    )
    if errors:
        logger.info("Failed bonds (first 20): %s", errors[:20])

    # ── Sanity check：仿股票分钟脚本，覆盖率 < 90% 退出非零 ──
    # CB 阈值用 90%（比股票 95% 略松），原因：可转债活跃度差异更大，
    # 一些小余额、长期不活跃的债 Tushare 可能完全无成交→无返回。
    target_dash = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:]}"
    with engine.connect() as conn:
        n_codes = conn.execute(text(
            f"SELECT COUNT(DISTINCT ts_code) FROM {TABLE} "
            f"WHERE freq=:f AND trade_time::date=:d"
        ), {"f": FREQ, "d": target_dash}).scalar() or 0

    if args.test == 0 and not args.from_date:
        l_count = len(bonds)
        coverage = n_codes / l_count if l_count else 0
        logger.info(
            "Sanity check: target=%s  ts_codes_in_db=%d / %d  coverage=%.1f%%",
            target_date, n_codes, l_count, coverage * 100,
        )
        if coverage < 0.90:
            logger.error(
                "SANITY FAIL: target_date=%s coverage %.1f%% < 90%%, "
                "likely Tushare didn't return today's CB data yet — exiting non-zero.",
                target_date, coverage * 100,
            )
            sys.exit(2)
    else:
        logger.info(
            "Sanity check (info-only, test/--from mode): target=%s  ts_codes_in_db=%d",
            target_date, n_codes,
        )


if __name__ == "__main__":
    main()
