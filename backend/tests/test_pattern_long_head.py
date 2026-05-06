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
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:zxslchj12345@localhost:5432/ai_trade",
)

from app.research.signals.long_head_detector import (
    LimitUpStock,
    count_near_limit_at_minute,
    detect_emerging_sectors,
    find_entry_trigger,
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


# ══════════════════════════════════════════════════════════════════════════
# 4. find_entry_trigger（4/29 真实数据回归）
# ══════════════════════════════════════════════════════════════════════════

async def test_entry_trigger_advances_before_first_time(db):
    """影子龙 first_time=09:48:09 时，entry_trigger 应提前到封板前的某分钟。

    4/29 国产芯片影子龙 002081.SZ 金螳螂 first=09:48:09，
    封板前 1 分钟（09:47）板块共识已达标，entry_trigger 应 < first_time。
    """
    async with db() as s:
        sectors = await load_sectors(s, "20260429")
        codes = sectors.get("国产芯片", [])
        if not codes:
            pytest.skip("国产芯片板块无成员（lookback 数据缺）")
        entry_t, entry_close = await find_entry_trigger(
            s, "20260429", "002081.SZ", codes, "094809",
        )
    assert entry_t < "094809", f"entry_trigger 应早于 first_time，得 {entry_t}"
    assert entry_close is not None and entry_close > 0
    # 入场价应明显低于涨停价（pre_close 约 4.9，涨停约 5.39，entry ≈ 5.31 = +8.4%）
    assert entry_close < 5.4, f"entry_close 应低于涨停价，得 {entry_close}"


async def test_emerging_sectors_4_29_three_industries(db):
    """4/29 11:30 前名单外涨停股按行业分组，应至少含 3 个 ≥3 只的行业.

    返回 {industry: (codes, identification_time)}，
    identification_time = 第 3 只票封板时刻（动态识别时刻）。
    """
    async with db() as s:
        from app.research.strategies.base_pattern import load_sectors
        sectors = await load_sectors(s, "20260429")
        known = {c for cs in sectors.values() for c in cs}
        emerging = await detect_emerging_sectors(s, "20260429", known, "113000", 3)
    # 期望至少含 09:45 前已确认的电气设备/食品/专用机械
    for ind in ("电气设备", "食品", "专用机械"):
        assert ind in emerging, f"行业 {ind} 应被识别为萌芽，得 {list(emerging)}"
        codes, id_time = emerging[ind]
        assert len(codes) >= 3
        assert len(id_time) == 6, f"identification_time 应是 HHMMSS 6 位，得 {id_time}"
        # 第 3 只票封板必然在 11:30 之前
        assert id_time <= "113000"


async def test_emerging_sectors_excludes_known_codes(db):
    """已在 known_codes 的票应被剔除，不计入萌芽."""
    async with db() as s:
        all_codes_rows = (await s.execute(
            text(
                "SELECT DISTINCT ts_code FROM limit_stats "
                "WHERE trade_date='20260429' AND \"limit\"='U'"
            )
        )).fetchall()
        all_codes = {r[0] for r in all_codes_rows}
        emerging = await detect_emerging_sectors(s, "20260429", all_codes, "113000", 3)
    assert emerging == {}, f"全市场已知应无萌芽，得 {emerging}"


async def test_entry_trigger_fallback_to_first_time_at_open(db):
    """龙1 first_time=09:31:36 时，前序窗口只有 09:30~09:31:35，
    板块共识尚未形成 → fallback 到 first_time（涨停价）。

    4/29 国产芯片龙1 002652.SZ 扬子新材 first=09:31:36，
    entry_trigger 应等于 first_time（无前序触发分钟）。
    """
    async with db() as s:
        sectors = await load_sectors(s, "20260429")
        codes = sectors.get("国产芯片", [])
        if not codes:
            pytest.skip("国产芯片板块无成员")
        entry_t, entry_close = await find_entry_trigger(
            s, "20260429", "002652.SZ", codes, "093136",
        )
    assert entry_t == "093136", f"entry_trigger 应 fallback 到 first_time，得 {entry_t}"
    assert entry_close is not None and entry_close > 0
