"""
Pull concept (theme/sector) data: concept_list + concept_detail.

concept_list changes infrequently; concept_detail maps stocks to concepts.
Safe to run weekly or on demand.

Usage:
    python scripts/pull_concept.py
"""

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


def pull_concept_list(svc: TushareService, conn) -> list[str]:
    """Pull all concept names, return list of concept codes."""
    logger.info("Pulling concept list...")
    df = svc.concept()
    if df.empty:
        logger.warning("concept API returned empty")
        return []

    cols = ["code", "name", "src"]
    rows = _df_to_tuples(df, cols)
    with conn.cursor() as cur:
        execute_values(
            cur,
            f"INSERT INTO concept_list ({','.join(cols)}) VALUES %s "
            "ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name, src=EXCLUDED.src",
            rows,
        )
    conn.commit()
    logger.info("concept_list: %d concepts synced", len(rows))
    return df["code"].tolist()


def pull_concept_detail(svc: TushareService, conn, concept_codes: list[str]):
    """Pull stock-concept mappings for each concept code."""
    total = 0
    failed = []

    for i, code in enumerate(concept_codes):
        try:
            df = svc.concept_detail(id=code)
            if df.empty:
                continue

            df = df.rename(columns={"id": "concept_code"})
            cols = ["concept_code", "ts_code", "concept_name", "name"]
            rows = _df_to_tuples(df, cols)
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    f"INSERT INTO concept_detail ({','.join(cols)}) VALUES %s "
                    "ON CONFLICT (concept_code, ts_code) DO UPDATE SET "
                    "concept_name=EXCLUDED.concept_name, name=EXCLUDED.name",
                    rows,
                )
            conn.commit()
            total += len(rows)

            if (i + 1) % 50 == 0:
                logger.info("  progress: %d/%d concepts, %d mappings", i + 1, len(concept_codes), total)

        except Exception as e:
            conn.rollback()
            failed.append((code, e))
            if "每分钟" in str(e) or "exceed" in str(e).lower():
                logger.warning("Rate limited at concept %s, sleeping 60s...", code)
                time.sleep(60)

    logger.info("concept_detail: %d mappings synced across %d concepts", total, len(concept_codes))
    if failed:
        logger.warning("%d concepts failed:", len(failed))
        for code, err in failed[:10]:
            logger.warning("  %s: %s", code, err)


def main():
    svc = TushareService()
    with psycopg2.connect(DB_URL) as conn:
        codes = pull_concept_list(svc, conn)
        if codes:
            pull_concept_detail(svc, conn, codes)
        else:
            logger.warning("No concept codes to pull detail for")

    logger.info("Done.")


if __name__ == "__main__":
    main()
