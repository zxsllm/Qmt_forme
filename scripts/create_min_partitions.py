"""
Create partitioned stock_min_kline table with monthly partitions.
This uses raw SQL because Alembic doesn't handle PostgreSQL partitioning well.

Usage: python scripts/create_min_partitions.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import create_engine, text

from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg")
engine = create_engine(sync_url, echo=False)

PARTITIONS = [
    ("2025_09", "2025-09-01", "2025-10-01"),
    ("2025_10", "2025-10-01", "2025-11-01"),
    ("2025_11", "2025-11-01", "2025-12-01"),
    ("2025_12", "2025-12-01", "2026-01-01"),
    ("2026_01", "2026-01-01", "2026-02-01"),
    ("2026_02", "2026-02-01", "2026-03-01"),
    ("2026_03", "2026-03-01", "2026-04-01"),
    ("2026_04", "2026-04-01", "2026-05-01"),
    ("2026_05", "2026-05-01", "2026-06-01"),
]


def create_table():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS stock_min_kline (
                ts_code     VARCHAR(16) NOT NULL,
                trade_time  TIMESTAMP   NOT NULL,
                freq        VARCHAR(8)  NOT NULL DEFAULT '1min',
                open        DOUBLE PRECISION,
                close       DOUBLE PRECISION,
                high        DOUBLE PRECISION,
                low         DOUBLE PRECISION,
                vol         DOUBLE PRECISION,
                amount      DOUBLE PRECISION,
                PRIMARY KEY (ts_code, trade_time, freq)
            ) PARTITION BY RANGE (trade_time)
        """))
        logger.info("Parent table stock_min_kline created (or already exists)")

        for suffix, start, end in PARTITIONS:
            part_name = f"stock_min_kline_{suffix}"
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {part_name}
                PARTITION OF stock_min_kline
                FOR VALUES FROM ('{start}') TO ('{end}')
            """))
            logger.info("  Partition %s: [%s, %s)", part_name, start, end)

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_min_kline_ts_code
            ON stock_min_kline (ts_code, trade_time)
        """))
        logger.info("Index created")


def verify():
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT relname, pg_size_pretty(pg_relation_size(oid))
            FROM pg_class
            WHERE relname LIKE 'stock_min_kline%'
            ORDER BY relname
        """))
        for row in result:
            logger.info("  %s: %s", row[0], row[1])


if __name__ == "__main__":
    create_table()
    verify()
    logger.info("Done!")
