"""Report generator — compute standard quant performance metrics.

Takes a raw BacktestResult and fills in BacktestStats.
"""

from __future__ import annotations

import logging
import math
from collections import Counter

import numpy as np

from app.shared.interfaces.models import BacktestResult, BacktestStats
from app.shared.interfaces.types import OrderSide

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 244
RISK_FREE_RATE = 0.03


class ReportGenerator:
    """Compute aggregated statistics from a backtest result."""

    def generate(self, result: BacktestResult) -> BacktestResult:
        """Mutate result.stats in-place and return the result."""
        if not result.equity_curve:
            return result

        equity = np.array([e.total_asset for e in result.equity_curve])
        daily_returns = np.array([e.daily_return for e in result.equity_curve])
        benchmark_returns = np.array([e.benchmark_return for e in result.equity_curve])

        n_days = len(equity)
        initial = result.config.initial_capital
        final = equity[-1]

        total_return = (final - initial) / initial
        annual_return = self._annualize(total_return, n_days)

        dd, dd_amount = self._max_drawdown(equity)

        sharpe = self._sharpe(daily_returns)
        sortino = self._sortino(daily_returns)

        trades = result.trades
        total_trades = len(trades)

        buy_trades = [t for t in trades if t.side == OrderSide.BUY]
        sell_trades = [t for t in trades if t.side == OrderSide.SELL]

        gross_profit, gross_loss, winning, avg_hold = self._trade_stats(
            buy_trades, sell_trades
        )
        win_rate = winning / max(len(sell_trades), 1)
        profit_factor = gross_profit / max(abs(gross_loss), 1e-9)

        bm_cum = np.prod(1.0 + benchmark_returns) - 1.0

        result.stats = BacktestStats(
            total_return=round(total_return * 100, 4),
            annual_return=round(annual_return * 100, 4),
            max_drawdown=round(dd * 100, 4),
            max_drawdown_amount=round(dd_amount, 2),
            sharpe_ratio=round(sharpe, 4),
            sortino_ratio=round(sortino, 4),
            win_rate=round(win_rate * 100, 2),
            profit_factor=round(profit_factor, 4),
            total_trades=total_trades,
            avg_holding_days=round(avg_hold, 1),
            benchmark_return=round(float(bm_cum) * 100, 4),
        )

        logger.info(
            "Report: total_return=%.2f%%, sharpe=%.2f, max_dd=%.2f%%, trades=%d",
            result.stats.total_return, result.stats.sharpe_ratio,
            result.stats.max_drawdown, result.stats.total_trades,
        )
        return result

    def filtered_signal_summary(self, result: BacktestResult) -> dict[str, int]:
        return dict(Counter(fs.filter_reason.value for fs in result.filtered_signals))

    @staticmethod
    def _annualize(total_ret: float, n_days: int) -> float:
        if n_days <= 0:
            return 0.0
        return (1.0 + total_ret) ** (TRADING_DAYS_PER_YEAR / n_days) - 1.0

    @staticmethod
    def _max_drawdown(equity: np.ndarray) -> tuple[float, float]:
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / np.where(peak > 0, peak, 1.0)
        dd_amount = peak - equity
        idx = np.argmax(drawdown)
        return float(drawdown[idx]), float(dd_amount[idx])

    @staticmethod
    def _sharpe(daily_returns: np.ndarray) -> float:
        if len(daily_returns) < 2:
            return 0.0
        excess = daily_returns - RISK_FREE_RATE / TRADING_DAYS_PER_YEAR
        std = np.std(excess, ddof=1)
        if std < 1e-12:
            return 0.0
        return float(np.mean(excess) / std * math.sqrt(TRADING_DAYS_PER_YEAR))

    @staticmethod
    def _sortino(daily_returns: np.ndarray) -> float:
        if len(daily_returns) < 2:
            return 0.0
        excess = daily_returns - RISK_FREE_RATE / TRADING_DAYS_PER_YEAR
        downside = excess[excess < 0]
        if len(downside) < 1:
            return 0.0
        down_std = np.std(downside, ddof=1)
        if down_std < 1e-12:
            return 0.0
        return float(np.mean(excess) / down_std * math.sqrt(TRADING_DAYS_PER_YEAR))

    @staticmethod
    def _trade_stats(
        buy_trades: list, sell_trades: list
    ) -> tuple[float, float, int, float]:
        """Pair buy/sell trades by ts_code (FIFO) to compute PnL stats."""
        buy_queue: dict[str, list] = {}
        for t in buy_trades:
            buy_queue.setdefault(t.ts_code, []).append(t)

        gross_profit = 0.0
        gross_loss = 0.0
        winning = 0
        total_hold_days = 0
        paired = 0

        for sell in sell_trades:
            queue = buy_queue.get(sell.ts_code, [])
            if not queue:
                continue
            buy = queue.pop(0)
            pnl = (sell.price - buy.price) * sell.qty - sell.fee - buy.fee
            if pnl > 0:
                gross_profit += pnl
                winning += 1
            else:
                gross_loss += pnl

            try:
                from datetime import datetime
                d_buy = datetime.strptime(buy.trade_date, "%Y%m%d")
                d_sell = datetime.strptime(sell.trade_date, "%Y%m%d")
                total_hold_days += (d_sell - d_buy).days
            except Exception:
                pass
            paired += 1

        avg_hold = total_hold_days / max(paired, 1)
        return gross_profit, gross_loss, winning, avg_hold
