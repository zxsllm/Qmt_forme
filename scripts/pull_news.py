"""
Pull latest market news from Tushare major_news API.

Usage:
    python scripts/pull_news.py              # pull latest news
    python scripts/pull_news.py --limit 200  # pull up to 200 items
"""

import logging
import os
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import psycopg2
from psycopg2.extras import execute_values
from app.research.data.tushare_service import TushareService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")

INSERT_COLS = ["datetime", "content", "channels", "source"]


def _normalize_news_df(df):
    """Rename Tushare news columns to our schema."""
    col_rename = {}
    if "pub_time" in df.columns and "datetime" not in df.columns:
        col_rename["pub_time"] = "datetime"
    if "title" in df.columns and "content" not in df.columns:
        col_rename["title"] = "content"
    if "src" in df.columns and "source" not in df.columns:
        col_rename["src"] = "source"
    return df.rename(columns=col_rename)


def _to_native(v):
    """Convert pandas value to Python native type for psycopg2."""
    if v is None or (isinstance(v, float) and str(v) == "nan"):
        return None
    return str(v)


def insert_news_batch(cur, df) -> int:
    """Batch-insert a normalized news DataFrame. Returns inserted count."""
    available = [c for c in INSERT_COLS if c in df.columns]
    if not available or df.empty:
        return 0

    rows = [
        tuple(_to_native(row.get(c)) for c in available)
        for _, row in df.iterrows()
    ]
    col_str = ",".join(available)
    execute_values(cur, f"INSERT INTO stock_news ({col_str}) VALUES %s", rows)
    return len(rows)


NEWS_SOURCES = [
    "sina", "cls", "eastmoney", "wallstreetcn", "10jqka",
    "yuncaijing", "fenghuang", "jinrongjie", "yicai",
]
_source_index = 0


def fetch_latest_news(ts_svc: TushareService, db_url: str, limit: int = 50,
                      src: str | None = None) -> int:
    """Fetch new news from Tushare and insert into DB. Returns inserted count.

    If src is None, rotates through NEWS_SOURCES automatically.
    This function is also called by scheduler._pull_news_sync for DRY reuse.
    """
    global _source_index

    if src is None:
        src = NEWS_SOURCES[_source_index % len(NEWS_SOURCES)]
        _source_index += 1

    with psycopg2.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(datetime) FROM stock_news")
            last_dt = cur.fetchone()[0] or ""

            df = ts_svc.news(src=src, limit=limit)
            if df.empty:
                return 0

            df = _normalize_news_df(df)
            df["source"] = src
            if "datetime" not in df.columns:
                logger.warning("Unexpected columns from news(src=%s): %s", src, list(df.columns))
                return 0

            if last_dt:
                df = df[df["datetime"] > last_dt]
            if df.empty:
                return 0

            df = df.drop_duplicates(subset=["datetime", "content"], keep="first")
            if df.empty:
                return 0

            cur.execute(
                "SELECT datetime, LEFT(content, 100) FROM stock_news "
                "WHERE datetime >= %s",
                (df["datetime"].min(),),
            )
            existing = {(r[0], r[1]) for r in cur.fetchall()}
            mask = df.apply(
                lambda r: (str(r.get("datetime", "")), str(r.get("content", ""))[:100]) not in existing,
                axis=1,
            )
            df = df[mask]
            if df.empty:
                return 0

            count = insert_news_batch(cur, df)
            conn.commit()
            logger.info("news(%s): inserted %d items", src, count)
            return count


def pull_news(ts_svc: TushareService, conn, limit: int):
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(datetime) FROM stock_news")
        last_dt = cur.fetchone()[0] or ""

    logger.info("  Last news datetime in DB: %s", last_dt or "(empty)")
    logger.info("  Pulling up to %d news items...", limit)

    df = ts_svc.news(src="sina", limit=limit)
    if df.empty:
        df = ts_svc.news(limit=limit)
    if df.empty:
        logger.warning("  [WARN] No news returned from API")
        return

    df = _normalize_news_df(df)
    df["source"] = "sina"
    if "datetime" not in df.columns:
        logger.warning("  [WARN] Unexpected columns: %s", list(df.columns))
        return

    if last_dt:
        df = df[df["datetime"] > last_dt]

    if df.empty:
        logger.info("  [OK] No new news items")
        return

    with conn.cursor() as cur:
        count = insert_news_batch(cur, df)
        conn.commit()
    logger.info("  [OK] Inserted %d news items", count)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    ts_svc = TushareService()
    with psycopg2.connect(DB_URL) as conn:
        pull_news(ts_svc, conn, args.limit)
    logger.info("Done.")


if __name__ == "__main__":
    main()
