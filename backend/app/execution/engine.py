"""Trading Engine — orchestrates OMS, Risk, Matcher into a single service.

This is the central coordinator; API endpoints delegate to it.
Singleton instance is created at import time and shared across the app.
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from app.shared.interfaces.types import OrderSide, OrderStatus, RiskAction, AuditAction
from app.shared.interfaces.models import (
    Account, AuditEvent, BarData, FeeConfig, Order, Position, Signal,
)
from app.execution.oms.order_manager import OrderManager
from app.execution.oms.position_book import PositionBook
from app.execution.oms.account import AccountManager
from app.execution.risk.pre_trade import PreTradeRiskChecker
from app.execution.risk.realtime import RealtimeRiskMonitor
from app.execution.risk.kill_switch import KillSwitch
from app.execution.matcher import SimMatcher

logger = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self, initial_capital: float = 1_000_000.0):
        self.order_mgr = OrderManager()
        self.position_book = PositionBook()
        self.account_mgr = AccountManager(initial_capital)
        self.pre_trade = PreTradeRiskChecker()
        self.realtime_risk = RealtimeRiskMonitor()
        self.kill_switch = KillSwitch()
        self.matcher = SimMatcher()
        self._audit_buffer: list[AuditEvent] = []

    # ------------------------------------------------------------------
    # Order flow
    # ------------------------------------------------------------------

    def submit_signal(self, signal: Signal) -> Order | str:
        """Full pipeline: signal → dedup → risk → submit → return Order or error."""
        if self.kill_switch.is_active:
            return f"kill switch active: {self.kill_switch.reason}"

        req = self.order_mgr.signal_to_request(signal)
        if req is None:
            return "signal deduplicated"

        position = self.position_book.get(signal.ts_code)

        risk_result = self.pre_trade.check(
            req, self.account_mgr.account, position,
            limit_price=signal.price,
        )
        if risk_result.action == RiskAction.REJECT:
            self._audit(AuditAction.RISK_BLOCK, ts_code=signal.ts_code,
                        detail=risk_result.reason)
            return f"risk rejected: {risk_result.reason}"

        if signal.side == OrderSide.BUY:
            est_cost = (signal.price or 0) * signal.qty
            if est_cost > 0:
                try:
                    self.account_mgr.freeze(est_cost)
                except ValueError as e:
                    return str(e)

        order = self.order_mgr.submit(req)
        self._audit(AuditAction.ORDER_SUBMIT, order_id=order.order_id,
                    ts_code=order.ts_code,
                    detail=f"{order.side.value} {order.qty}@{order.price or 'MKT'}")
        return order

    def cancel_order(self, order_id: UUID) -> Order | str:
        """Cancel a live order and release frozen funds."""
        order = self.order_mgr.get(order_id)
        if order is None:
            return "order not found"

        try:
            order = self.order_mgr.cancel(order_id)
        except ValueError as e:
            return str(e)

        if order.side == OrderSide.BUY:
            remaining_cost = (order.price or 0) * (order.qty - order.filled_qty)
            if remaining_cost > 0:
                self.account_mgr.unfreeze(remaining_cost)

        self._audit(AuditAction.ORDER_CANCEL, order_id=order_id,
                    ts_code=order.ts_code)
        return order

    # ------------------------------------------------------------------
    # Matching (called each bar)
    # ------------------------------------------------------------------

    def on_bar(self, bars: dict[str, BarData]) -> list[Order]:
        """Process a batch of bars: try to fill open orders, update positions."""
        filled_orders: list[Order] = []

        for order in self.order_mgr.get_open_orders():
            bar = bars.get(order.ts_code)
            if bar is None:
                continue

            result = self.matcher.try_fill(order, bar)
            if result is None:
                continue

            new_status = OrderStatus.FILLED if result.fully_filled else OrderStatus.PARTIAL_FILLED
            self.order_mgr.transition(
                order.order_id, new_status,
                filled_qty=result.fill_qty,
                filled_price=result.fill_price,
                fee=result.fee,
                slippage=result.slippage,
            )

            if order.side == OrderSide.BUY:
                self.account_mgr.on_buy_fill(
                    result.fill_price * result.fill_qty, result.fee)
            else:
                self.account_mgr.on_sell_fill(
                    result.fill_price * result.fill_qty, result.fee)

            self.position_book.apply_fill(
                order.ts_code, order.side,
                result.fill_qty, result.fill_price, result.fee)

            self._audit(AuditAction.ORDER_FILL, order_id=order.order_id,
                        ts_code=order.ts_code,
                        detail=f"{result.fill_qty}@{result.fill_price}")
            filled_orders.append(order)

        for ts_code, bar in bars.items():
            self.position_book.update_market_price(ts_code, bar.close)

        self.account_mgr.refresh(self.position_book)

        rt_state = self.realtime_risk.check(
            self.account_mgr.account,
            self.position_book.get_all(),
            self.account_mgr._day_start_asset,
        )
        if rt_state.is_halted:
            self.kill_switch.activate(rt_state.halt_reason)
            self._audit(AuditAction.KILL_SWITCH_ON, detail=rt_state.halt_reason)

        return filled_orders

    # ------------------------------------------------------------------
    # Day lifecycle
    # ------------------------------------------------------------------

    def begin_day(self) -> None:
        self.account_mgr.begin_day()
        self.pre_trade.reset_daily()
        self.realtime_risk.reset()

    def end_day(self) -> Account:
        acct = self.account_mgr.end_day(self.position_book)
        self._audit(AuditAction.SETTLEMENT,
                    detail=f"total={acct.total_asset:.2f} pnl={acct.today_pnl:.2f}")
        return acct

    # ------------------------------------------------------------------
    # Kill switch
    # ------------------------------------------------------------------

    def activate_kill_switch(self, reason: str = "manual") -> dict:
        self.kill_switch.activate(reason)
        self._audit(AuditAction.KILL_SWITCH_ON, detail=reason)
        return self.kill_switch.status()

    def deactivate_kill_switch(self) -> dict:
        self.kill_switch.deactivate()
        self._audit(AuditAction.KILL_SWITCH_OFF)
        return self.kill_switch.status()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_account(self) -> Account:
        return self.account_mgr.account

    def get_positions(self) -> list[Position]:
        return self.position_book.get_all()

    def get_orders(self, *, status: OrderStatus | None = None) -> list[Order]:
        orders = self.order_mgr.get_all_orders()
        if status:
            orders = [o for o in orders if o.status == status]
        return orders

    def get_risk_status(self) -> dict:
        return {
            "kill_switch": self.kill_switch.status(),
            "realtime_halted": self.realtime_risk.is_halted,
            "halt_reason": self.realtime_risk.halt_reason,
            "daily_buy_count": self.pre_trade._daily_buy_count,
        }

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def flush_audit(self) -> list[AuditEvent]:
        events = self._audit_buffer[:]
        self._audit_buffer.clear()
        return events

    def _audit(self, action: AuditAction, *,
               order_id: UUID | None = None,
               ts_code: str = "",
               detail: str = "") -> None:
        evt = AuditEvent(
            action=action, order_id=order_id, ts_code=ts_code, detail=detail,
        )
        self._audit_buffer.append(evt)


# Singleton
trading_engine = TradingEngine()
