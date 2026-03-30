"""
Classify existing stock_news and stock_anns entries using rule-based engine.

Usage:
    python scripts/classify_news.py              # classify all unclassified
    python scripts/classify_news.py --all        # re-classify everything
    python scripts/classify_news.py --limit 500  # process up to 500 items
"""

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import psycopg2
from psycopg2.extras import execute_values

from app.shared.news_classifier import NewsClassifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
BATCH_SIZE = 500


def load_classifier(cur) -> NewsClassifier:
    """Load reference data from DB and build classifier."""
    clf = NewsClassifier()

    cur.execute("SELECT ts_code, name FROM stock_basic WHERE name IS NOT NULL")
    stock_rows = cur.fetchall()

    cur.execute("SELECT DISTINCT industry_name FROM index_classify WHERE industry_name IS NOT NULL")
    industry_rows = cur.fetchall()
    industry_names = [r[0] for r in industry_rows]

    clf.load_reference_data(stock_rows, industry_names)
    logger.info("Loaded %d stock names, %d industry names", len(stock_rows), len(industry_names))
    return clf


def classify_news_batch(cur, clf: NewsClassifier, reclassify: bool, limit: int | None):
    """Classify stock_news entries."""
    if reclassify:
        sql = "SELECT id, content, datetime FROM stock_news ORDER BY id"
    else:
        sql = (
            "SELECT n.id, n.content, n.datetime FROM stock_news n "
            "LEFT JOIN news_classified nc ON n.id = nc.news_id "
            "WHERE nc.news_id IS NULL ORDER BY n.id"
        )
    if limit:
        sql += f" LIMIT {limit}"

    cur.execute(sql)
    rows = cur.fetchall()
    total = len(rows)
    if total == 0:
        logger.info("No unclassified news found")
        return 0

    logger.info("Classifying %d news items...", total)
    classified = 0
    batch: list[tuple] = []

    for row_id, content, dt_str in rows:
        content = content or ""
        dt_str = dt_str or ""
        result = clf.classify_news(row_id, content, dt_str)
        d = result.to_db_dict(row_id)
        batch.append((
            d["news_id"], d["news_scope"], d["time_slot"],
            d["sentiment"], d["related_codes"],
            d["related_industries"], d["keywords"],
        ))

        if len(batch) >= BATCH_SIZE:
            _upsert_news_batch(cur, batch)
            classified += len(batch)
            logger.info("  progress: %d / %d", classified, total)
            batch = []

    if batch:
        _upsert_news_batch(cur, batch)
        classified += len(batch)

    return classified


def _upsert_news_batch(cur, batch: list[tuple]):
    execute_values(
        cur,
        """INSERT INTO news_classified
           (news_id, news_scope, time_slot, sentiment, related_codes, related_industries, keywords)
           VALUES %s
           ON CONFLICT (news_id) DO UPDATE SET
             news_scope = EXCLUDED.news_scope,
             time_slot = EXCLUDED.time_slot,
             sentiment = EXCLUDED.sentiment,
             related_codes = EXCLUDED.related_codes,
             related_industries = EXCLUDED.related_industries,
             keywords = EXCLUDED.keywords,
             classified_at = NOW()""",
        batch,
    )


def classify_anns_batch(cur, clf: NewsClassifier, reclassify: bool, limit: int | None):
    """Classify stock_anns entries."""
    if reclassify:
        sql = "SELECT id, title FROM stock_anns ORDER BY id"
    else:
        sql = (
            "SELECT a.id, a.title FROM stock_anns a "
            "LEFT JOIN anns_classified ac ON a.id = ac.anns_id "
            "WHERE ac.anns_id IS NULL ORDER BY a.id"
        )
    if limit:
        sql += f" LIMIT {limit}"

    cur.execute(sql)
    rows = cur.fetchall()
    total = len(rows)
    if total == 0:
        logger.info("No unclassified announcements found")
        return 0

    logger.info("Classifying %d announcements...", total)
    classified = 0
    batch: list[tuple] = []

    for row_id, title in rows:
        title = title or ""
        result = clf.classify_anns(row_id, title)
        d = result.to_db_dict(row_id)
        batch.append((d["anns_id"], d["ann_type"], d["sentiment"], d["keywords"]))

        if len(batch) >= BATCH_SIZE:
            _upsert_anns_batch(cur, batch)
            classified += len(batch)
            logger.info("  progress: %d / %d", classified, total)
            batch = []

    if batch:
        _upsert_anns_batch(cur, batch)
        classified += len(batch)

    return classified


def _upsert_anns_batch(cur, batch: list[tuple]):
    execute_values(
        cur,
        """INSERT INTO anns_classified (anns_id, ann_type, sentiment, keywords)
           VALUES %s
           ON CONFLICT (anns_id) DO UPDATE SET
             ann_type = EXCLUDED.ann_type,
             sentiment = EXCLUDED.sentiment,
             keywords = EXCLUDED.keywords,
             classified_at = NOW()""",
        batch,
    )


def main():
    parser = argparse.ArgumentParser(description="Classify news and announcements")
    parser.add_argument("--all", action="store_true", help="Re-classify all (not just unclassified)")
    parser.add_argument("--limit", type=int, default=None, help="Max items to process")
    parser.add_argument("--news-only", action="store_true")
    parser.add_argument("--anns-only", action="store_true")
    args = parser.parse_args()

    with psycopg2.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            clf = load_classifier(cur)

            if not args.anns_only:
                n_news = classify_news_batch(cur, clf, args.all, args.limit)
                conn.commit()
                logger.info("[OK] Classified %d news items", n_news)

            if not args.news_only:
                n_anns = classify_anns_batch(cur, clf, args.all, args.limit)
                conn.commit()
                logger.info("[OK] Classified %d announcements", n_anns)

    logger.info("Done.")


if __name__ == "__main__":
    main()
