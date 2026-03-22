"""Strategy interface — the contract between research and execution layers.

All strategies (backtest or live) must implement IStrategy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.shared.interfaces.models import BacktestContext, BarData, Signal


class IStrategy(ABC):
    """Base class for all trading strategies.

    Lifecycle:
        1. on_init(ctx)   — called once before the first bar
        2. on_bar(...)     — called for each bar in chronological order
        3. on_stop()       — called after the last bar (cleanup)
    """

    name: str = "unnamed"
    description: str = ""
    default_params: dict = {}

    def __init__(self, params: dict | None = None):
        self.params = {**self.default_params, **(params or {})}

    @abstractmethod
    def on_init(self, ctx: BacktestContext) -> None:
        """Initialize strategy state. Called once before backtesting starts.

        Use ctx to access indicator helpers, universe info, etc.
        """

    @abstractmethod
    def on_bar(self, bar_date: str, bars: dict[str, BarData]) -> list[Signal]:
        """Process one bar (date) and return a list of signals.

        Args:
            bar_date: Trade date string (YYYYMMDD).
            bars: Dict of ts_code → BarData for all stocks in the universe
                  that traded on this date.

        Returns:
            List of Signal objects. These will be executed at the NEXT bar's
            open price (T+1 rule). Return an empty list for no action.
        """

    def on_stop(self) -> None:
        """Cleanup after backtesting. Override if needed."""
