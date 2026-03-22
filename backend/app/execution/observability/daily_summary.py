"""Daily summary — collects trading day statistics for review."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DailySummary:
    trade_date: str = ""
    orders_submitted: int = 0
    orders_filled: int = 0
    orders_rejected: int = 0
    orders_canceled: int = 0
    risk_blocks: int = 0
    kill_switch_activations: int = 0
    data_gaps: int = 0
    connection_errors: int = 0
    total_pnl: float = 0.0
    total_fee: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "trade_date": self.trade_date,
            "orders_submitted": self.orders_submitted,
            "orders_filled": self.orders_filled,
            "orders_rejected": self.orders_rejected,
            "orders_canceled": self.orders_canceled,
            "risk_blocks": self.risk_blocks,
            "kill_switch_activations": self.kill_switch_activations,
            "data_gaps": self.data_gaps,
            "connection_errors": self.connection_errors,
            "total_pnl": self.total_pnl,
            "total_fee": self.total_fee,
            "warnings": self.warnings,
        }


def build_summary(
    trade_date: str,
    orders: list,
    audit_events: list,
    account_pnl: float,
) -> DailySummary:
    """Build end-of-day summary from in-memory data."""
    summary = DailySummary(trade_date=trade_date, total_pnl=account_pnl)

    for o in orders:
        summary.orders_submitted += 1
        status = o.status if isinstance(o.status, str) else o.status.value
        if status == "FILLED":
            summary.orders_filled += 1
            summary.total_fee += o.fee
        elif status == "REJECTED":
            summary.orders_rejected += 1
        elif status == "CANCELED":
            summary.orders_canceled += 1

    for evt in audit_events:
        action = evt.action if isinstance(evt.action, str) else evt.action.value
        if action == "RISK_BLOCK":
            summary.risk_blocks += 1
        elif action == "KILL_SWITCH_ON":
            summary.kill_switch_activations += 1
        elif action == "SYSTEM_ERROR":
            summary.warnings.append(evt.detail)

    return summary
