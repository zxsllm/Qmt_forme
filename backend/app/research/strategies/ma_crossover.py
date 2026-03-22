"""MA Crossover strategy — golden/death cross on MA(fast) vs MA(slow).

Demonstration strategy for Phase 4 backtest validation.
"""

from __future__ import annotations

from uuid import uuid4

import pandas as pd

from app.shared.interfaces.models import BacktestContext, BarData, Signal
from app.shared.interfaces.types import OrderSide
from app.shared.interfaces.strategy import IStrategy
from app.research.indicators import ma


class MACrossover(IStrategy):
    """Buy on golden cross (fast MA > slow MA), sell on death cross."""

    name = "ma_crossover"
    description = "MA golden/death cross"
    default_params = {
        "fast_period": 5,
        "slow_period": 20,
        "position_pct": 0.25,
    }

    def on_init(self, ctx: BacktestContext) -> None:
        self._close_history: dict[str, list[float]] = {}
        self._prev_above: dict[str, bool | None] = {}
        self._initial_capital = ctx.config.initial_capital
        self._universe = ctx.universe_codes

    def on_bar(self, bar_date: str, bars: dict[str, BarData]) -> list[Signal]:
        signals: list[Signal] = []
        fast_p = self.params["fast_period"]
        slow_p = self.params["slow_period"]
        pos_pct = self.params["position_pct"]

        for ts_code, bar in bars.items():
            if ts_code not in self._universe:
                continue

            self._close_history.setdefault(ts_code, []).append(bar.close)
            hist = self._close_history[ts_code]

            if len(hist) < slow_p:
                continue

            s = pd.Series(hist)
            fast_val = ma(s, fast_p).iloc[-1]
            slow_val = ma(s, slow_p).iloc[-1]

            if pd.isna(fast_val) or pd.isna(slow_val):
                continue

            above = fast_val > slow_val
            prev = self._prev_above.get(ts_code)
            self._prev_above[ts_code] = above

            if prev is not None and above and not prev:
                allocation = self._initial_capital * pos_pct
                qty = int(allocation / bar.close / 100) * 100
                if qty >= 100:
                    signals.append(Signal(
                        signal_id=uuid4(),
                        ts_code=ts_code,
                        side=OrderSide.BUY,
                        qty=qty,
                        reason=f"golden_cross MA{fast_p}/{slow_p}",
                    ))

            elif prev is not None and not above and prev:
                signals.append(Signal(
                    signal_id=uuid4(),
                    ts_code=ts_code,
                    side=OrderSide.SELL,
                    qty=0,
                    reason=f"death_cross MA{fast_p}/{slow_p}",
                ))

        return signals
