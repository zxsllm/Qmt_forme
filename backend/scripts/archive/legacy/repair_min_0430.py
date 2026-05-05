"""一次性：补 4-30 那些当天有日 K 但分钟线没拉到的票。

判定缺失：
  当天有 stock_daily 行（说明真的交易了）
  且 stock_min_kline (freq=1min) 当天 0 行
  且 list_status='L'

对每只票拉一次 stk_mins(start='2026-04-30 09:30', end='2026-04-30 15:00')，
返回非空才 INSERT；返回空时显式记录到日志，二次重试一次再判定 give-up。
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

# 必须在 import TushareService 之前清掉代理变量
def bypass_proxy_for_tushare() -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                 "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(name, None)
    hosts = ["api.tushare.pro", "api.waditu.com", "127.0.0.1", "localhost"]
    for name in ("NO_PROXY", "no_proxy"):
        cur = [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]
        merged = cur + [h for h in hosts if h not in cur]
        os.environ[name] = ",".join(merged)

bypass_proxy_for_tushare()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.research.data.tushare_service import TushareService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

TARGET_DATE = "20260430"
TARGET_DATE_DASH = "2026-04-30"
START_DT = f"{TARGET_DATE_DASH} 09:30:00"
END_DT = f"{TARGET_DATE_DASH} 15:00:00"
FREQ = "1min"


def main():
    sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg")
    engine = create_engine(sync_url, echo=False)
    svc = TushareService()

    # 1. 计算缺失集合：日 K 有 + 分钟线缺 + 仍 L
    with engine.connect() as conn:
        rows = conn.execute(text(
            "WITH d_codes AS ("
            "  SELECT DISTINCT ts_code FROM stock_daily WHERE trade_date=:td"
            "), m_codes AS ("
            "  SELECT DISTINCT ts_code FROM stock_min_kline "
            "  WHERE freq='1min' AND trade_time::date=:td_dash"
            ") "
            "SELECT d.ts_code FROM d_codes d "
            "JOIN stock_basic sb ON sb.ts_code=d.ts_code AND sb.list_status='L' "
            "LEFT JOIN m_codes m ON m.ts_code=d.ts_code "
            "WHERE m.ts_code IS NULL "
            "ORDER BY d.ts_code"
        ), {"td": TARGET_DATE, "td_dash": TARGET_DATE_DASH}).fetchall()
    targets = [r[0] for r in rows]
    logger.info("repair targets: %d codes (had daily K, missing 1min)", len(targets))
    if not targets:
        logger.info("nothing to repair")
        return

    ok = 0
    still_empty = 0
    failed = []
    t0 = time.time()

    for i, code in enumerate(targets, 1):
        try:
            df = svc.stk_mins(ts_code=code, freq=FREQ,
                              start_date=START_DT, end_date=END_DT)
            if df is None or df.empty:
                # 二次重试一次（避免单次抽风）
                time.sleep(0.4)
                df = svc.stk_mins(ts_code=code, freq=FREQ,
                                  start_date=START_DT, end_date=END_DT)
            if df is None or df.empty:
                still_empty += 1
                logger.warning("[%d/%d] %s: still empty after retry", i, len(targets), code)
                continue

            df = df.drop_duplicates(subset=["ts_code", "trade_time"], keep="first")
            df["freq"] = FREQ
            df["trade_time"] = pd.to_datetime(df["trade_time"])

            with engine.begin() as wconn:
                wconn.execute(text(
                    "DELETE FROM stock_min_kline "
                    "WHERE ts_code=:c AND freq=:f "
                    "  AND trade_time >= :s AND trade_time <= :e"
                ), {"c": code, "f": FREQ, "s": START_DT, "e": END_DT})
                df.to_sql("stock_min_kline", wconn,
                          if_exists="append", index=False, chunksize=5000)
            ok += 1

            if i % 50 == 0 or i == 1:
                elapsed = time.time() - t0
                rate = i / elapsed * 60 if elapsed > 0 else 0
                logger.info("[%d/%d] %s: +%d bars (ok=%d empty=%d, %.0f/min)",
                            i, len(targets), code, len(df), ok, still_empty, rate)
        except Exception as e:
            failed.append(code)
            logger.error("[%d/%d] %s: FAILED %s", i, len(targets), code, e)

    elapsed = time.time() - t0
    logger.info(
        "repair done: targets=%d  ok=%d  still_empty=%d  failed=%d  elapsed=%.1fmin",
        len(targets), ok, still_empty, len(failed), elapsed / 60,
    )
    if failed:
        logger.info("failed (first 30): %s", failed[:30])


if __name__ == "__main__":
    main()
