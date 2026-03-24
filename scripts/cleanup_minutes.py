"""
Cleanup old minute-bar partitions older than N months.

Drops PostgreSQL partition tables named stock_min_kline_YYYY_MM that are
older than the configured retention period (default 6 months).

Usage:
    python scripts/cleanup_minutes.py              # execute cleanup
    python scripts/cleanup_minutes.py --dry-run    # preview only
"""

import os
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(env_path)

RETENTION_MONTHS = 6
PARTITION_RE = re.compile(r"^stock_min_kline_(\d{4})_(\d{2})$")


def main():
    db_url = os.getenv("DATABASE_URL", "").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    import psycopg2

    dry_run = "--dry-run" in sys.argv
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name LIKE 'stock_min_kline_%'"
    )
    partitions = [r[0] for r in cur.fetchall()]

    cutoff = datetime.now() - timedelta(days=RETENTION_MONTHS * 30)
    cutoff_ym = (cutoff.year, cutoff.month)

    dropped = []
    kept = []

    for name in sorted(partitions):
        m = PARTITION_RE.match(name)
        if not m:
            continue
        year, month = int(m.group(1)), int(m.group(2))
        if (year, month) < cutoff_ym:
            if dry_run:
                print(f"  [DRY-RUN] would drop: {name}")
            else:
                cur.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
                print(f"  [DROPPED] {name}")
            dropped.append(name)
        else:
            kept.append(name)

    cur.close()
    conn.close()

    print(f"\nSummary: dropped={len(dropped)}, kept={len(kept)}, cutoff={cutoff_ym}")
    if dry_run:
        print("(dry-run mode, nothing was actually dropped)")
    for d in dropped:
        print(f"  - {d}")


if __name__ == "__main__":
    main()
