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
    count_codes_above_pct_intraday,
    count_sector_limit_state_intraday,
    detect_emerging_sectors,
    fetch_minute_quotes,
    iter_trading_minutes,
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
# 4. 事中扫描工具函数（v6 严格事中）
# ══════════════════════════════════════════════════════════════════════════

async def test_iter_trading_minutes_count():
    """A 股交易分钟应是 上午 121 + 下午 121 = 242 根（含 11:30 / 15:00）。"""
    minutes = iter_trading_minutes("20260429")
    assert len(minutes) == 242
    assert minutes[0].strftime("%H%M") == "0930"
    assert minutes[120].strftime("%H%M") == "1130"
    assert minutes[121].strftime("%H%M") == "1300"
    assert minutes[-1].strftime("%H%M") == "1500"


async def test_fetch_minute_quotes_4_29(db):
    """4/29 国产芯片金螳螂应能取到全天 1min 数据 + 封板状态正确."""
    async with db() as s:
        quotes = await fetch_minute_quotes(s, "20260429", ["002081.SZ"])
    assert len(quotes) > 200, f"全天 1min 应 > 200 根，得 {len(quotes)}"
    from datetime import datetime
    # 09:48 那根（first_time=09:48:09 那秒封板，但 09:48:00 那根 K 线 close
    # 还未到涨停 5.39）— 验证 pct ≥ 9% 但 is_limit 可能为 False
    key_948 = ("002081.SZ", datetime(2026, 4, 29, 9, 48))
    assert key_948 in quotes
    assert quotes[key_948].pct >= 9.0
    # 09:49 那根应该已经封板了（前一分钟末已经封死）
    key_949 = ("002081.SZ", datetime(2026, 4, 29, 9, 49))
    assert key_949 in quotes
    assert quotes[key_949].is_limit, f"09:49 应已封板，pct={quotes[key_949].pct:.2f}%"


async def test_count_codes_above_pct_intraday(db):
    """4/29 09:47 国产芯片板块应 ≥ 3 只 ≥ 6%（影子龙触发前夕共识）."""
    async with db() as s:
        sectors = await load_sectors(s, "20260429")
        codes = sectors.get("国产芯片", [])
        if not codes:
            pytest.skip("国产芯片板块无成员")
        quotes = await fetch_minute_quotes(s, "20260429", codes)
    from datetime import datetime
    n = count_codes_above_pct_intraday(
        quotes, codes, datetime(2026, 4, 29, 9, 47), 6.0
    )
    assert n >= 3, f"4/29 09:47 国产芯片板块应 ≥3 只 ≥6%，得 {n}"


async def test_count_sector_limit_state_intraday_4_29(db):
    """4/29 09:48 国产芯片板块应 ≥ 1 只已封过板（金螳螂 09:48 首次封板）."""
    async with db() as s:
        sectors = await load_sectors(s, "20260429")
        codes = sectors.get("国产芯片", [])
        if not codes:
            pytest.skip("国产芯片板块无成员")
        quotes = await fetch_minute_quotes(s, "20260429", codes)
    from datetime import datetime
    ever_limit, broken = count_sector_limit_state_intraday(
        quotes, codes, datetime(2026, 4, 29, 9, 48)
    )
    assert ever_limit >= 1, f"09:48 板块应至少 1 只封过板，得 {ever_limit}"
    assert broken <= ever_limit, "炸板数不应超过封过板数"


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


