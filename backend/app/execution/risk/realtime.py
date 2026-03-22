"""Realtime risk monitor — runs during trading hours."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.shared.interfaces.models import Account, Position

logger = logging.getLogger(__name__)


@dataclass
class RealtimeLimits:
    max_daily_drawdown_pct: float = 0.05    # 5% daily loss → halt
    max_single_loss_pct: float = 0.10       # 10% single-stock loss → force close
    volatility_threshold_pct: float = 0.08  # 8% intrabar move → pause


@dataclass
class RealtimeRiskState:
    is_halted: bool = False
    halt_reason: str = ""
    stocks_to_force_close: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class RealtimeRiskMonitor:
    """Checks account/positions for intraday risk breaches."""

    def __init__(self, limits: RealtimeLimits | None = None):
        self.limits = limits or RealtimeLimits()
        self._halted = False
        self._halt_reason = ""

    @property
    def is_halted(self) -> bool:
        return self._halted

    @property
    def halt_reason(self) -> str:
        return self._halt_reason

    def check(self, account: Account, positions: list[Position],
              day_start_asset: float) -> RealtimeRiskState:
        """Run all realtime checks.  Called periodically (e.g. every bar)."""
        state = RealtimeRiskState()

        if self._halted:
            state.is_halted = True
            state.halt_reason = self._halt_reason
            return state

        if day_start_asset > 0:
            drawdown = (day_start_asset - account.total_asset) / day_start_asset
            if drawdown >= self.limits.max_daily_drawdown_pct:
                self._halted = True
                self._halt_reason = (
                    f"daily drawdown {drawdown:.2%} >= {self.limits.max_daily_drawdown_pct:.0%}"
                )
                state.is_halted = True
                state.halt_reason = self._halt_reason
                logger.critical("HALT: %s", self._halt_reason)
                return state

        for pos in positions:
            if pos.qty <= 0 or pos.avg_cost <= 0:
                continue
            loss_pct = (pos.avg_cost - pos.market_price) / pos.avg_cost
            if loss_pct >= self.limits.max_single_loss_pct:
                state.stocks_to_force_close.append(pos.ts_code)
                msg = f"{pos.ts_code} loss {loss_pct:.2%} >= {self.limits.max_single_loss_pct:.0%}"
                state.warnings.append(msg)
                logger.warning("force close: %s", msg)

        return state

    def reset(self) -> None:
        """Reset halt state (e.g. at day start or after manual review)."""
        self._halted = False
        self._halt_reason = ""
