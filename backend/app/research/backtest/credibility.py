"""Tradability filter — enforces backtest credibility rules.

Pre-loads stk_limit + suspend_d + stock_basic data for the entire
backtest period into memory dicts for O(1) per-signal lookups.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from app.shared.interfaces.types import FilterReason, OrderSide

logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    tradable: bool
    reason: FilterReason | None = None
    detail: str = ""


class TradabilityFilter:
    """Check whether a signal is executable given A-share market rules.

    Initialize with pre-loaded DataFrames covering the backtest period.
    All lookups are dict-based (no DB calls during the backtest loop).
    """

    def __init__(
        self,
        limit_df: pd.DataFrame,
        suspend_df: pd.DataFrame,
        stock_basic_df: pd.DataFrame,
    ):
        self._limits: dict[tuple[str, str], tuple[float, float]] = {}
        for _, row in limit_df.iterrows():
            key = (row["ts_code"], row["trade_date"])
            self._limits[key] = (float(row["up_limit"]), float(row["down_limit"]))

        self._suspended: dict[str, set[str]] = {}
        for _, row in suspend_df.iterrows():
            self._suspended.setdefault(row["trade_date"], set()).add(row["ts_code"])

        self._list_dates: dict[str, str] = {}
        self._st_names: set[str] = set()
        for _, row in stock_basic_df.iterrows():
            tc = row["ts_code"]
            if pd.notna(row.get("list_date")):
                self._list_dates[tc] = str(row["list_date"])
            name = str(row.get("name", ""))
            if "ST" in name or "st" in name:
                self._st_names.add(tc)

        logger.info(
            "TradabilityFilter loaded: %d limit entries, %d suspend dates, %d stocks",
            len(self._limits), len(self._suspended), len(self._list_dates),
        )

    def check(
        self,
        ts_code: str,
        trade_date: str,
        side: OrderSide,
        price: float | None,
        bar_open: float | None = None,
        bar_high: float | None = None,
        bar_low: float | None = None,
        bar_close: float | None = None,
    ) -> FilterResult:
        if self._is_suspended(ts_code, trade_date):
            return FilterResult(False, FilterReason.SUSPENDED, f"{ts_code} suspended on {trade_date}")

        if self._list_dates.get(ts_code) == trade_date:
            return FilterResult(False, FilterReason.IPO_FIRST_DAY, f"{ts_code} IPO day {trade_date}")

        limits = self._limits.get((ts_code, trade_date))
        if limits is not None:
            up_limit, down_limit = limits

            if self._is_one_board(bar_open, bar_high, bar_low, bar_close, up_limit, down_limit):
                return FilterResult(False, FilterReason.ONE_BOARD, f"{ts_code} one-board on {trade_date}")

            exec_price = price if price is not None else bar_open

            if side == OrderSide.BUY and exec_price is not None:
                if exec_price >= up_limit:
                    return FilterResult(False, FilterReason.UP_LIMIT, f"{ts_code} buy at {exec_price} >= up_limit {up_limit}")

            if side == OrderSide.SELL and exec_price is not None:
                if exec_price <= down_limit:
                    return FilterResult(False, FilterReason.DOWN_LIMIT, f"{ts_code} sell at {exec_price} <= down_limit {down_limit}")

        return FilterResult(True)

    def is_st(self, ts_code: str) -> bool:
        return ts_code in self._st_names

    def _is_suspended(self, ts_code: str, trade_date: str) -> bool:
        return ts_code in self._suspended.get(trade_date, set())

    @staticmethod
    def _is_one_board(
        bar_open: float | None,
        bar_high: float | None,
        bar_low: float | None,
        bar_close: float | None,
        up_limit: float,
        down_limit: float,
    ) -> bool:
        """One-board (一字板): open == close == high == low at limit price."""
        if any(v is None for v in (bar_open, bar_high, bar_low, bar_close)):
            return False
        if bar_open == bar_high == bar_low == bar_close:
            if bar_close >= up_limit or bar_close <= down_limit:
                return True
        return False
