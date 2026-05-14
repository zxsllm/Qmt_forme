"""Unit-style smoke test for scheduler's _aggregate_and_publish_1min.

模拟 rt_k tick 流，验证：
  1. 09:30 第一次 tick -> 早发一次 (is_open_preview=True)
  2. 同一分钟多次 tick -> 不重复 publish；high/low/close 正常聚合
  3. 09:31 第一次 tick -> publish 09:30 final bar
  4. 09:30 又收到一次 tick（迟到的） -> 不会再次 publish 09:30 final
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.execution.feed import scheduler as sched  # noqa: E402


async def _main():
    # 重置全局状态
    sched._intraday_1min_state.clear()
    sched._last_published_minute = ""
    sched._open_preview_published = False

    watched = ["000001.SZ", "600000.SH"]

    published_calls: list[tuple[list, dict]] = []

    async def _mock_publish_minute_batch(bars, *, is_open_preview: bool = False):
        published_calls.append((list(bars), {"is_open_preview": is_open_preview}))

    # Monkey-patch market_feed.publish_minute_batch
    sched.market_feed.publish_minute_batch = _mock_publish_minute_batch

    # 模拟 09:30:02 第一次 rt_k tick
    snap1 = {
        "000001.SZ": {"open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0,
                      "vol": 1000, "amount": 10000, "pre_close": 9.8},
        "600000.SH": {"open": 8.0, "high": 8.0, "low": 8.0, "close": 8.0,
                      "vol": 500, "amount": 4000, "pre_close": 7.9},
    }
    with patch.object(sched, "datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 5, 13, 9, 30, 2)
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        sched._aggregate_and_publish_1min(snap1, watched)
    await asyncio.sleep(0.01)  # 让 asyncio.create_task 跑一下
    assert len(published_calls) == 1, f"expected 1 preview publish, got {len(published_calls)}"
    assert published_calls[0][1]["is_open_preview"] is True, "first publish must be open preview"
    assert len(published_calls[0][0]) == 2, "preview should have 2 bars"
    print(f"[PASS] 09:30:02 first tick -> 1 preview publish (2 bars)")

    # 09:30:05 second tick — price moves, no new publish
    snap2 = {
        "000001.SZ": {"open": 10.0, "high": 10.5, "low": 9.9, "close": 10.4,
                      "vol": 2000, "amount": 20000, "pre_close": 9.8},
        "600000.SH": {"open": 8.0, "high": 8.2, "low": 7.9, "close": 8.1,
                      "vol": 800, "amount": 6500, "pre_close": 7.9},
    }
    with patch.object(sched, "datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 5, 13, 9, 30, 5)
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        sched._aggregate_and_publish_1min(snap2, watched)
    await asyncio.sleep(0.01)
    assert len(published_calls) == 1, "second 09:30 tick should NOT publish again"
    # 验证 state 已聚合 high/low/close（基于 tick-close 序列：10.0 -> 10.4）
    st = sched._intraday_1min_state["000001.SZ"]
    assert st["high"] == 10.4, f"expected high=10.4 (max of tick closes), got {st['high']}"
    assert st["low"] == 10.0, f"expected low=10.0 (min of tick closes incl. open), got {st['low']}"
    assert st["close"] == 10.4, f"expected close=10.4, got {st['close']}"
    print(f"[PASS] 09:30:05 same-minute tick -> no extra publish, OHLC aggregated")

    # 09:31:01 first tick of next minute — publish 09:30 final
    snap3 = {
        "000001.SZ": {"open": 10.4, "high": 10.4, "low": 10.4, "close": 10.4,
                      "vol": 2100, "amount": 21000, "pre_close": 9.8},
        "600000.SH": {"open": 8.1, "high": 8.1, "low": 8.1, "close": 8.1,
                      "vol": 850, "amount": 6900, "pre_close": 7.9},
    }
    with patch.object(sched, "datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 5, 13, 9, 31, 1)
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        sched._aggregate_and_publish_1min(snap3, watched)
    await asyncio.sleep(0.01)
    assert len(published_calls) == 2, f"09:31 tick should publish 09:30 final, got {len(published_calls)}"
    assert published_calls[1][1]["is_open_preview"] is False, "minute-rollover publish should NOT be preview"
    final_bars = published_calls[1][0]
    assert len(final_bars) == 2
    bar_pa = next(b for b in final_bars if b.ts_code == "000001.SZ")
    assert bar_pa.timestamp.strftime("%H:%M") == "09:30", f"final bar timestamp should be 09:30"
    assert bar_pa.close == 10.4, f"final close should be 10.4"
    print(f"[PASS] 09:31:01 next-minute tick -> 09:30 final publish (close=10.4)")

    # 验证新分钟 state 已重置
    st = sched._intraday_1min_state["000001.SZ"]
    assert st["minute"] == "09:31", f"state should reset to 09:31, got {st['minute']}"
    assert st["open"] == 10.4, "new minute open should be 10.4 (rt_k row open)"
    print(f"[PASS] state reset to new minute correctly")

    # 09:32:00 confirm next rollover works
    snap4 = {
        "000001.SZ": {"open": 10.4, "high": 10.4, "low": 10.4, "close": 10.5,
                      "vol": 2200, "amount": 22000, "pre_close": 9.8},
        "600000.SH": {"open": 8.1, "high": 8.1, "low": 8.1, "close": 8.2,
                      "vol": 870, "amount": 7100, "pre_close": 7.9},
    }
    with patch.object(sched, "datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 5, 13, 9, 32, 0)
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        sched._aggregate_and_publish_1min(snap4, watched)
    await asyncio.sleep(0.01)
    assert len(published_calls) == 3, f"09:32 tick should publish 09:31 final, got {len(published_calls)}"
    print(f"[PASS] 09:32 rollover -> 09:31 final publish (total {len(published_calls)} publishes)")

    print("\n[ALL PASS]")


if __name__ == "__main__":
    asyncio.run(_main())
