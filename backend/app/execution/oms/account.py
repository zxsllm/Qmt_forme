"""Account Manager — simulated capital ledger."""

from __future__ import annotations

import logging
from datetime import datetime

from app.shared.interfaces.models import Account
from app.execution.oms.position_book import PositionBook

logger = logging.getLogger(__name__)


class AccountManager:
    """Manages a single simulated trading account.

    Works alongside PositionBook to maintain consistent state.
    """

    def __init__(self, initial_capital: float = 1_000_000.0):
        self._account = Account(
            total_asset=initial_capital,
            cash=initial_capital,
        )
        self._initial_capital = initial_capital
        self._day_start_asset: float = initial_capital

    @property
    def account(self) -> Account:
        return self._account

    def freeze(self, amount: float) -> None:
        """Lock funds for a pending buy order."""
        if amount > self._account.cash:
            raise ValueError(
                f"insufficient cash: need {amount:.2f}, have {self._account.cash:.2f}"
            )
        self._account.cash -= amount
        self._account.frozen += amount
        self._touch()

    def unfreeze(self, amount: float) -> None:
        """Release frozen funds (order cancel / partial fill remainder)."""
        release = min(amount, self._account.frozen)
        self._account.frozen -= release
        self._account.cash += release
        self._touch()

    def on_buy_fill(self, cost: float, fee: float) -> None:
        """Deduct from frozen on buy fill (cost = price * qty)."""
        total = cost + fee
        deduct_frozen = min(total, self._account.frozen)
        self._account.frozen -= deduct_frozen
        remainder = total - deduct_frozen
        if remainder > 0:
            self._account.cash -= remainder
        self._touch()

    def on_sell_fill(self, proceeds: float, fee: float) -> None:
        """Credit cash on sell fill."""
        self._account.cash += proceeds - fee
        self._touch()

    def refresh(self, position_book: PositionBook) -> Account:
        """Recalculate total asset / market value / PnL from positions."""
        mv = position_book.total_market_value()
        self._account.market_value = mv
        self._account.total_asset = self._account.cash + self._account.frozen + mv
        self._account.total_pnl = self._account.total_asset - self._initial_capital
        self._account.today_pnl = self._account.total_asset - self._day_start_asset
        self._touch()
        return self._account

    def begin_day(self) -> None:
        """Snapshot asset at day open for today_pnl calculation."""
        self._day_start_asset = self._account.total_asset
        self._account.today_pnl = 0.0
        self._touch()
        logger.info("day start asset snapshot: %.2f", self._day_start_asset)

    def end_day(self, position_book: PositionBook) -> Account:
        """Settlement: recalc everything and log daily summary."""
        acct = self.refresh(position_book)
        logger.info(
            "settlement: total=%.2f cash=%.2f mv=%.2f today_pnl=%.2f total_pnl=%.2f",
            acct.total_asset, acct.cash, acct.market_value,
            acct.today_pnl, acct.total_pnl,
        )
        return acct

    def _touch(self) -> None:
        self._account.updated_at = datetime.now()
