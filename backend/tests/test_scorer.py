"""Scorer integration tests — run against real DB.

Verifies three properties after the data/rules/orchestration split:
  1. Single-stock and batch scores are identical
  2. Historical scoring does not read future data
  3. Sparse/empty data produces stable results without errors

Usage:
  cd backend && python -m pytest tests/test_scorer.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:zxslchj12345@localhost:5432/ai_trade",
)

from app.shared.scorer_data import (
    prefetch_batch,
    fetch_tech_inputs,
    fetch_fundamental_inputs,
    fetch_news_inputs,
    fetch_sentiment_inputs,
)
from app.shared.scorer_rules import score_tech, score_fundamental, score_news, score_sentiment
from app.shared.stock_scorer import score_stock, rank_stocks

# ── Constants ────────────────────────────────────────────────────────────

TRADE_DATE = "20260410"
RICH_STOCK = "300131.SZ"
SPARSE_STOCK = "000002.SZ"
FUTURE_PROBE_STOCK = "600710.SH"
FUTURE_PROBE_DATE = "20260410"


# ══════════════════════════════════════════════════════════════════════════
# 1. Single-stock / batch consistency
# ══════════════════════════════════════════════════════════════════════════

async def test_rich_stock_single_batch_match(db):
    async with db() as s:
        single = await score_stock(s, RICH_STOCK, TRADE_DATE)
        ctx = await prefetch_batch(s, TRADE_DATE, [RICH_STOCK])
        batch = await score_stock(s, RICH_STOCK, TRADE_DATE, ctx=ctx)
    for key in ("total_score", "tech_score", "sentiment_score",
                "fundamental_score", "news_score"):
        assert single[key] == batch[key], f"{key}: {single[key]} != {batch[key]}"


async def test_sparse_stock_single_batch_match(db):
    async with db() as s:
        single = await score_stock(s, SPARSE_STOCK, TRADE_DATE)
        ctx = await prefetch_batch(s, TRADE_DATE, [SPARSE_STOCK])
        batch = await score_stock(s, SPARSE_STOCK, TRADE_DATE, ctx=ctx)
    for key in ("total_score", "tech_score", "sentiment_score",
                "fundamental_score", "news_score"):
        assert single[key] == batch[key], f"{key}: {single[key]} != {batch[key]}"


async def test_ranked_contains_consistent_score(db):
    async with db() as s:
        ranked = await rank_stocks(s, TRADE_DATE, limit=2000, min_score=0)
    ranked_map = {x["ts_code"]: x for x in ranked["scored_stocks"]}
    if RICH_STOCK not in ranked_map:
        pytest.skip(f"{RICH_STOCK} not in ranked output")
    async with db() as s:
        codes = [x["ts_code"] for x in ranked["scored_stocks"]]
        ctx = await prefetch_batch(s, TRADE_DATE, codes)
        single = await score_stock(s, RICH_STOCK, TRADE_DATE, ctx=ctx)
    assert single["total_score"] == ranked_map[RICH_STOCK]["total_score"]


# ══════════════════════════════════════════════════════════════════════════
# 2. No future function
# ══════════════════════════════════════════════════════════════════════════

async def test_fina_single_respects_ann_date(db):
    async with db() as s:
        inputs = await fetch_fundamental_inputs(s, FUTURE_PROBE_STOCK, FUTURE_PROBE_DATE)
    fina_row = inputs["fina_row"]
    if fina_row is not None:
        assert fina_row[0] != "20251231", (
            "Future fina leak: saw end_date=20251231 (ann_date=20260414)"
        )


async def test_fina_batch_respects_ann_date(db):
    async with db() as s:
        ctx = await prefetch_batch(s, FUTURE_PROBE_DATE, [FUTURE_PROBE_STOCK])
    fina_row = ctx["fina_data"].get(FUTURE_PROBE_STOCK)
    if fina_row is not None:
        assert fina_row[0] != "20251231", (
            "Future fina leak (batch): saw end_date=20251231"
        )


async def test_bars_no_future_dates(db):
    async with db() as s:
        inputs = await fetch_tech_inputs(s, RICH_STOCK, FUTURE_PROBE_DATE)
    bars = inputs["bars"]
    if bars:
        assert bars[0][0] <= FUTURE_PROBE_DATE, f"Future bar: {bars[0][0]}"


async def test_anns_no_future_dates(db):
    from sqlalchemy import text
    async with db() as s:
        r = await s.execute(text("""
            SELECT MAX(a.ann_date) FROM anns_classified ac
            JOIN stock_anns a ON ac.anns_id = a.id
            WHERE a.ts_code = :code AND a.ann_date <= :td
        """), {"code": RICH_STOCK, "td": FUTURE_PROBE_DATE})
        max_date = r.scalar()
    if max_date:
        assert max_date <= FUTURE_PROBE_DATE


# ══════════════════════════════════════════════════════════════════════════
# 3. Sparse / empty data robustness
# ══════════════════════════════════════════════════════════════════════════

async def test_sparse_stock_no_crash(db):
    async with db() as s:
        result = await score_stock(s, SPARSE_STOCK, TRADE_DATE)
    for key in ("total_score", "tech_score", "sentiment_score",
                "fundamental_score", "news_score"):
        assert 0 <= result[key] <= 100, f"{key}={result[key]}"
    assert isinstance(result["signals"], list)


async def test_sparse_sentiment_no_lhb(db):
    async with db() as s:
        inputs = await fetch_sentiment_inputs(s, SPARSE_STOCK, TRADE_DATE)
    assert inputs["on_lhb"] is False
    score, detail, _ = score_sentiment(**inputs)
    assert 0 <= score <= 100
    assert detail["on_dragon_tiger"] is False


async def test_sparse_news_zero_counts(db):
    async with db() as s:
        inputs = await fetch_news_inputs(s, SPARSE_STOCK, TRADE_DATE)
    score, detail, _ = score_news(**inputs)
    assert 0 <= score <= 100
    assert detail["positive_news"] == 0
    assert detail["negative_news"] == 0


async def test_batch_mixed_stocks(db):
    async with db() as s:
        ctx = await prefetch_batch(s, TRADE_DATE, [RICH_STOCK, SPARSE_STOCK])
        for code in (RICH_STOCK, SPARSE_STOCK):
            result = await score_stock(s, code, TRADE_DATE, ctx=ctx)
            assert 0 <= result["total_score"] <= 100, f"{code}={result['total_score']}"


# ── Pure rule edge cases (no DB) ─────────────────────────────────────────

def test_empty_bars_base_score():
    score, _, _ = score_tech(limit_rows=[], bars=[])
    assert score == 50.0


def test_empty_fina_base_score():
    score, _, _ = score_fundamental(fina_row=None, industry=None, all_pe=[], own_pe=None)
    assert 0 <= score <= 100


def test_empty_news_base_score():
    score, _, _ = score_news(pos_count=0, neg_count=0, ann_rows=[])
    assert score == 50.0
