"""Pre-trade risk checks — run before every order submission."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.shared.interfaces.types import OrderSide, RiskAction
from app.shared.interfaces.models import OrderRequest, RiskCheckResult, Account, Position

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    max_position_pct: float = 0.20      # single stock <= 20% of total asset
    max_single_order: float = 200_000   # single order amount cap
    max_daily_buys: int = 20            # max buy orders per day
    min_cash_reserve: float = 0.0       # minimum cash to keep


class PreTradeRiskChecker:
    """Stateful checker that tracks daily counters."""

    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()
        self._daily_buy_count: int = 0

    def reset_daily(self) -> None:
        self._daily_buy_count = 0

    def check(
        self,
        req: OrderRequest,
        account: Account,
        position: Position | None,
        *,
        limit_price: float | None = None,
        up_limit: float | None = None,
        down_limit: float | None = None,
        is_suspended: bool = False,
        is_st: bool = False,
    ) -> RiskCheckResult:
        """Run all pre-trade checks; return first failure or PASS."""

        price_est = req.price or limit_price or 0.0
        order_amount = price_est * req.qty

        if is_suspended:
            return self._reject(f"{req.ts_code} is suspended")

        if req.side == OrderSide.BUY:
            if up_limit and price_est >= up_limit:
                return self._reject(f"{req.ts_code} at up-limit {up_limit}, buy blocked")

            if self._daily_buy_count >= self.limits.max_daily_buys:
                return self._reject(f"daily buy count {self._daily_buy_count} >= limit {self.limits.max_daily_buys}")

            if order_amount > self.limits.max_single_order:
                return self._reject(f"order amount {order_amount:.0f} > limit {self.limits.max_single_order:.0f}")

            avail = account.cash - self.limits.min_cash_reserve
            if order_amount > avail:
                return self._reject(f"insufficient cash: need {order_amount:.0f}, avail {avail:.0f}")

            if account.total_asset > 0:
                current_mv = (position.market_price * position.qty) if position and position.qty else 0.0
                projected_pct = (current_mv + order_amount) / account.total_asset
                if projected_pct > self.limits.max_position_pct:
                    return self._reject(
                        f"{req.ts_code} position would be {projected_pct:.1%} > {self.limits.max_position_pct:.0%}"
                    )

            self._daily_buy_count += 1

        elif req.side == OrderSide.SELL:
            if down_limit and price_est and price_est <= down_limit:
                return self._reject(f"{req.ts_code} at down-limit {down_limit}, sell blocked")

            held = position.qty if position else 0
            if req.qty > held:
                return self._reject(f"cannot sell {req.qty}, only hold {held}")

        return RiskCheckResult(action=RiskAction.PASS)

    @staticmethod
    def _reject(reason: str) -> RiskCheckResult:
        logger.warning("risk REJECT: %s", reason)
        return RiskCheckResult(action=RiskAction.REJECT, reason=reason)
