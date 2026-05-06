"""龙头隔阵模式核心边界单测。

跑法：
    cd backend && python -m pytest tests/test_pattern_long_head.py -v

覆盖三个工程评审点出的边界：
  1. 分钟线全空时，count_near_limit_at_minute 返回 coverage=0（不再静默 0）
  2. ohlc=None 时 is_natural_limit 用 first_time 退化判定
  3. 周末/非交易日传入 load_sectors 时直接 raise ValueError（不再静默退化）
"""

import os
import sys
from dataclasses import dataclass

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:zxslchj12345@localhost:5432/ai_trade",
)

from app.research.signals.long_head_detector import (
    LimitUpStock,
    count_near_limit_at_minute,
)
from app.research.strategies.base_pattern import is_natural_limit, load_sectors


# ══════════════════════════════════════════════════════════════════════════
# 1. 分钟线全空 → coverage=0（不静默丢信号）
# ══════════════════════════════════════════════════════════════════════════

async def test_count_near_limit_no_min_data(db):
    """传一组绝不可能在 stock_min_kline 出现的假代码，应得 (0, [], 0.0)。"""
    fake_codes = ["TEST00.SZ", "TEST01.SZ", "TEST02.SZ"]
    async with db() as s:
        n, detail, coverage = await count_near_limit_at_minute(
            s, "20260429", fake_codes, "100000", threshold_pct=6.0,
        )
    assert n == 0
    assert detail == []
    assert coverage == 0.0  # 关键：coverage 必须为 0 才能让上游识别"数据缺失"


async def test_count_near_limit_empty_codes(db):
    """空 codes 列表也应稳健返回。"""
    async with db() as s:
        n, detail, coverage = await count_near_limit_at_minute(
            s, "20260429", [], "100000", threshold_pct=6.0,
        )
    assert (n, detail, coverage) == (0, [], 0.0)


# ══════════════════════════════════════════════════════════════════════════
# 2. ohlc=None 时 first_time 退化判定
# ══════════════════════════════════════════════════════════════════════════

def _mk_stock(first_time: str) -> LimitUpStock:
    return LimitUpStock(
        ts_code="000001.SZ", name="test",
        first_time=first_time, last_time=first_time,
        limit_times=1, consec_days=1, open_times=0,
        tag=None, limit_amount=None, float_mv=None, amount=None,
    )


def test_is_natural_limit_ohlc_none_late_first_time():
    """ohlc 缺失 + first_time = 09:35 → 自然涨停（True）。"""
    stock = _mk_stock("093500")
    assert is_natural_limit(stock, None) is True


def test_is_natural_limit_ohlc_none_early_first_time():
    """ohlc 缺失 + first_time = 09:29（开盘前/竞价区间）→ 一字（False）。

    边界：092900 < 093100，按退化逻辑判为一字。
    """
    stock = _mk_stock("092900")
    assert is_natural_limit(stock, None) is False


def test_is_natural_limit_ohlc_intraday_swing_overrides_first_time():
    """ohlc 显示日内有波动（high != low）→ 自然涨停，即使 first_time 在 09:30。"""
    stock = _mk_stock("093000")
    swing_ohlc = {"open": 10.5, "high": 11.0, "low": 10.3, "close": 11.0,
                  "pre_close": 10.0}  # 有上下波动
    assert is_natural_limit(stock, swing_ohlc) is True


# ══════════════════════════════════════════════════════════════════════════
# 3. 非交易日 load_sectors 应 raise（不静默退化）
# ══════════════════════════════════════════════════════════════════════════

async def test_load_sectors_weekend_raises(db):
    """20260502 是周六，传入应 raise ValueError。"""
    async with db() as s:
        with pytest.raises(ValueError, match="不是交易日"):
            await load_sectors(s, "20260502")


async def test_load_sectors_unknown_date_raises(db):
    """trade_cal 没有这一天的记录（is_open=NULL），也应 raise。"""
    async with db() as s:
        with pytest.raises(ValueError, match="不是交易日"):
            await load_sectors(s, "21000101")
