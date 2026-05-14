"""Trading Engine — orchestrates OMS, Risk, Matcher into a single service.

This is the central coordinator; API endpoints delegate to it.
Singleton instance is created at import time and shared across the app.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from app.shared.interfaces.types import OrderSide, OrderStatus, OrderType, RiskAction, AuditAction
from app.shared.interfaces.models import (
    Account, AuditEvent, BarData, FeeConfig, Order, Position, Signal,
)
from app.shared.data.data_loader import is_cb_code
from app.execution.oms.order_manager import OrderManager
from app.execution.oms.position_book import PositionBook
from app.execution.oms.account import AccountManager
from app.execution.risk.pre_trade import PreTradeRiskChecker
from app.execution.risk.realtime import RealtimeRiskMonitor
from app.execution.risk.kill_switch import KillSwitch
from app.execution.matcher import SimMatcher


def _next_trade_date(entry_date: str) -> str:
    """Naive next-trade-date: +1 day, skip Sat/Sun. For holidays, use trade_cal later."""
    d = datetime.strptime(entry_date, "%Y-%m-%d").date()
    d += timedelta(days=1)
    while d.weekday() >= 5:  # Sat=5, Sun=6
        d += timedelta(days=1)
    return d.strftime("%Y-%m-%d")

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
        self._price_limits: dict[str, tuple[float, float]] = {}

    def set_price_limits(self, limits: dict[str, tuple[float, float]]) -> None:
        """Set today's up/down limits (called by scheduler on new trade day).

        CB ts_codes (11*.SH / 12*.SZ) are skipped — CB price limits are ±20%
        and not enforced by matcher (Pattern1/2 backtest aligns with this).
        """
        clean = {ts: lim for ts, lim in limits.items() if not is_cb_code(ts)}
        self._price_limits = clean
        logger.info("price limits loaded for %d codes (CB skipped)", len(clean))

    def set_risk_limits(self, **kwargs) -> None:
        """Reconfigure pre-trade risk limits at runtime (e.g. max_daily_buys for Pattern1/2)."""
        for k, v in kwargs.items():
            if hasattr(self.pre_trade.limits, k):
                setattr(self.pre_trade.limits, k, v)
                logger.info("risk limit updated: %s=%s", k, v)

    # ------------------------------------------------------------------
    # Persistence bridge (sync → async, non-blocking)
    # ------------------------------------------------------------------

    def _persist(self, coro) -> None:
        """Schedule an async DB write without blocking the caller."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            pass  # no event loop (unit tests, CLI, etc.)

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

        from app.execution.persistence import save_batch
        self._persist(save_batch(
            orders=[order.model_copy()],
            account=self.account_mgr.account.model_copy(),
        ))
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

        from app.execution.persistence import save_batch
        self._persist(save_batch(
            orders=[order.model_copy()],
            account=self.account_mgr.account.model_copy(),
        ))
        return order

    # ------------------------------------------------------------------
    # Matching (called each bar)
    # ------------------------------------------------------------------

    def on_bar(self, bars: dict[str, BarData]) -> list[Order]:
        """Process a batch of bars: try to fill open orders, update positions."""
        filled_orders: list[Order] = []
        affected_codes: set[str] = set()

        for order in self.order_mgr.get_open_orders():
            bar = bars.get(order.ts_code)
            if bar is None:
                continue

            limits = self._price_limits.get(order.ts_code)
            up_lim = limits[0] if limits else None
            down_lim = limits[1] if limits else None
            result = self.matcher.try_fill(order, bar, up_lim, down_lim)
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

            # Lot metadata propagation: BUY creates a new lot, SELL matches lot_id (auto_close) or FIFO
            if order.side == OrderSide.BUY:
                entry_date = order.created_at.strftime("%Y-%m-%d")
                settlement = "T+0" if order.pick_kind == "cb" or is_cb_code(order.ts_code) else "T+1"
                sell_anchor_date = (
                    _next_trade_date(entry_date) if order.sell_anchor == "next_open" else ""
                )
                new_lot = self.position_book.apply_fill(
                    order.ts_code, order.side,
                    result.fill_qty, result.fill_price, result.fee,
                    lot_id=order.lot_id or str(uuid4()),
                    sell_anchor=order.sell_anchor,
                    sell_anchor_date=sell_anchor_date,
                    sell_anchor_time=order.sell_anchor_time or "",
                    sell_reason=order.sell_reason,
                    pick_role=order.pick_role,
                    pick_kind=order.pick_kind if order.pick_kind else ("cb" if is_cb_code(order.ts_code) else "stock"),
                    underlying_code=order.underlying_code,
                    settlement_rule=settlement,
                    entry_date=entry_date,
                )
                # Persist the new lot's lot_id back onto the order so persistence sees it
                if not order.lot_id:
                    order.lot_id = new_lot.lot_id
            else:
                self.position_book.apply_fill(
                    order.ts_code, order.side,
                    result.fill_qty, result.fill_price, result.fee,
                    lot_id=order.lot_id or None,
                )

            self._audit(AuditAction.ORDER_FILL, order_id=order.order_id,
                        ts_code=order.ts_code,
                        detail=f"{result.fill_qty}@{result.fill_price}")
            filled_orders.append(order)
            affected_codes.add(order.ts_code)

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

        if filled_orders:
            affected_lots: list[Position] = []
            for code in affected_codes:
                affected_lots.extend(self.position_book.get_active_lots(code))
            from app.execution.persistence import save_batch
            self._persist(save_batch(
                orders=[o.model_copy() for o in filled_orders],
                positions=[lot.model_copy() for lot in affected_lots],
                account=self.account_mgr.account.model_copy(),
            ))

        return filled_orders

    # ------------------------------------------------------------------
    # Auto-close (called by scheduler every rt_k tick)
    # ------------------------------------------------------------------

    def auto_close_check(self, now_dt: datetime, snapshot: dict[str, dict]) -> list[Order]:
        """Submit SELL orders for lots whose sell_anchor has triggered.

        snapshot: rt_k market snapshot {ts_code → {close, ...}}.
        Lots with pending_sell_qty > 0 are skipped (already-pending SELL).
        """
        if self.kill_switch.is_active:
            return []
        due_lots = self.position_book.iter_lots_due_for_close(now_dt)
        if not due_lots:
            return []

        out_orders: list[Order] = []
        for lot in due_lots:
            available_to_sell = lot.available_qty - lot.pending_sell_qty
            if available_to_sell <= 0:
                continue
            row = snapshot.get(lot.ts_code)
            price_est = (row or {}).get("close", lot.market_price) if row else lot.market_price
            sell_signal = Signal(
                ts_code=lot.ts_code,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                price=price_est or None,
                qty=available_to_sell,
                reason=f"auto_close:{lot.sell_anchor}:{lot.sell_reason}",
                sell_anchor=lot.sell_anchor,
                sell_anchor_time=lot.sell_anchor_time or None,
                sell_reason=lot.sell_reason,
                pick_kind=lot.pick_kind,
                pick_role=lot.pick_role,
                buy_anchor="auto_close",
                underlying_code=lot.underlying_code,
                metadata={"lot_id": lot.lot_id},
            )
            result = self.submit_signal(sell_signal)
            if isinstance(result, Order):
                lot.pending_sell_qty += available_to_sell
                out_orders.append(result)
            else:
                logger.warning("auto_close SELL rejected for lot %s %s: %s",
                               lot.lot_id[:8], lot.ts_code, result)
        return out_orders

    # ------------------------------------------------------------------
    # Day lifecycle
    # ------------------------------------------------------------------

    def begin_day(self) -> None:
        self.position_book.begin_day()
        self.account_mgr.begin_day()
        self.pre_trade.reset_daily()
        self.realtime_risk.reset()

    def end_day(self) -> Account:
        acct = self.account_mgr.end_day(self.position_book)
        self._audit(AuditAction.SETTLEMENT,
                    detail=f"total={acct.total_asset:.2f} pnl={acct.today_pnl:.2f}")

        from app.execution.persistence import save_batch
        all_positions = self.position_book.get_all_including_closed()
        self._persist(save_batch(
            positions=[p.model_copy() for p in all_positions],
            account=acct.model_copy(),
        ))
        return acct

    async def restore_from_db(self) -> dict:
        """Rebuild in-memory OMS state from DB (called at startup)."""
        from app.execution.persistence import load_all_state

        orders, positions, account = await load_all_state()

        self.order_mgr = OrderManager()
        for o in orders:
            self.order_mgr._orders[o.order_id] = o
            self.order_mgr._signal_index[o.signal_id] = o.order_id

        self.position_book = PositionBook()
        for p in positions:
            self.position_book._lots.setdefault(p.ts_code, []).append(p)

        if account:
            self.account_mgr._account = account
            self.account_mgr._day_start_asset = account.total_asset

        active = [o for o in orders if o.status in (
            OrderStatus.SUBMITTED, OrderStatus.PARTIAL_FILLED,
        )]
        held = [p for p in positions if p.qty > 0]

        summary = {
            "total_orders": len(orders),
            "active_orders": len(active),
            "positions": len(held),
            "account_restored": account is not None,
        }
        logger.info("OMS state restored: %s", summary)
        return summary

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
