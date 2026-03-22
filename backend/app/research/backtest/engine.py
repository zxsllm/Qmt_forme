"""Backtest engine — event-driven, bar-by-bar with strict T+1 execution.

Reuses Phase 3 OMS/Matcher/Fee/Slippage but creates independent instances
per run (never touches the live TradingEngine singleton).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import pandas as pd

from app.shared.interfaces.types import FilterReason, OrderSide, OrderStatus
from app.shared.interfaces.models import (
    BacktestConfig,
    BacktestContext,
    BacktestResult,
    BacktestStats,
    BarData,
    EquityPoint,
    FeeConfig,
    FilteredSignal,
    Signal,
    TradeRecord,
)
from app.shared.interfaces.strategy import IStrategy
from app.shared.data.data_loader import DataLoader
from app.execution.oms.order_manager import OrderManager
from app.execution.oms.position_book import PositionBook
from app.execution.oms.account import AccountManager
from app.execution.matcher import SimMatcher
from app.research.backtest.credibility import TradabilityFilter

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Run a strategy against historical data with full credibility checks."""

    def run(self, strategy: IStrategy, config: BacktestConfig) -> BacktestResult:
        """Synchronous entry point — loads data, runs loop, returns result."""
        return asyncio.run(self._run_async(strategy, config))

    async def _run_async(self, strategy: IStrategy, config: BacktestConfig) -> BacktestResult:
        result = BacktestResult(config=config, started_at=datetime.now())

        dl = DataLoader()
        trade_dates = await dl.trade_calendar(config.start_date, config.end_date)
        if not trade_dates:
            logger.error("No trade dates in range %s ~ %s", config.start_date, config.end_date)
            result.finished_at = datetime.now()
            return result

        logger.info("Backtest %s: %d trade dates (%s ~ %s)",
                     strategy.name, len(trade_dates), trade_dates[0], trade_dates[-1])

        universe = await self._resolve_universe(dl, config)
        daily_data = await self._load_daily_data(dl, universe, config)
        limit_df = await dl.stk_limit_batch_range(config.start_date, config.end_date)
        suspend_df = await self._load_suspend(dl, config)
        stock_basic_df = await dl.stock_list("L")
        stock_basic_d = await dl.stock_list("D")
        stock_basic_all = pd.concat([stock_basic_df, stock_basic_d], ignore_index=True)

        benchmark_df = await dl.index_daily(config.benchmark, config.start_date, config.end_date)

        tradability = TradabilityFilter(limit_df, suspend_df, stock_basic_all)

        order_mgr = OrderManager(dedup_window_minutes=0)
        position_book = PositionBook()
        account_mgr = AccountManager(config.initial_capital)
        matcher = SimMatcher(config.fee_config)

        ctx = BacktestContext(
            config=config,
            trade_dates=trade_dates,
            universe_codes=universe,
        )
        strategy.on_init(ctx)

        pending_signals: list[Signal] = []
        prev_equity = config.initial_capital

        for idx, trade_date in enumerate(trade_dates):
            bars = self._get_bars_for_date(daily_data, trade_date)
            if not bars:
                continue

            account_mgr.begin_day()

            if pending_signals:
                for sig in pending_signals:
                    bar = bars.get(sig.ts_code)
                    if bar is None:
                        result.filtered_signals.append(FilteredSignal(
                            signal_date=trade_dates[idx - 1] if idx > 0 else trade_date,
                            ts_code=sig.ts_code, side=sig.side,
                            price=sig.price, qty=sig.qty,
                            filter_reason=FilterReason.SUSPENDED,
                            detail="no bar data on execution date",
                        ))
                        continue

                    filt = tradability.check(
                        sig.ts_code, trade_date, sig.side, bar.open,
                        bar.open, bar.high, bar.low, bar.close,
                    )
                    if not filt.tradable:
                        result.filtered_signals.append(FilteredSignal(
                            signal_date=trade_dates[idx - 1] if idx > 0 else trade_date,
                            ts_code=sig.ts_code, side=sig.side,
                            price=sig.price, qty=sig.qty,
                            filter_reason=filt.reason,
                            detail=filt.detail,
                        ))
                        continue

                    if sig.side == OrderSide.SELL:
                        pos = position_book.get(sig.ts_code)
                        if pos is None or pos.qty <= 0:
                            continue
                        if sig.qty == 0:
                            sig = sig.model_copy(update={"qty": pos.qty})
                        elif pos.qty < sig.qty:
                            continue

                    req = order_mgr.signal_to_request(sig)
                    if req is None:
                        continue
                    order = order_mgr.submit(req)

                    fill = matcher.try_fill(order, bar)
                    if fill is not None:
                        new_status = OrderStatus.FILLED if fill.fully_filled else OrderStatus.PARTIAL_FILLED
                        order_mgr.transition(
                            order.order_id, new_status,
                            filled_qty=fill.fill_qty,
                            filled_price=fill.fill_price,
                            fee=fill.fee,
                            slippage=fill.slippage,
                        )
                        if sig.side == OrderSide.BUY:
                            account_mgr.on_buy_fill(fill.fill_price * fill.fill_qty, fill.fee)
                        else:
                            account_mgr.on_sell_fill(fill.fill_price * fill.fill_qty, fill.fee)

                        position_book.apply_fill(
                            sig.ts_code, sig.side,
                            fill.fill_qty, fill.fill_price, fill.fee,
                        )

                        result.trades.append(TradeRecord(
                            trade_date=trade_date,
                            signal_date=trade_dates[idx - 1] if idx > 0 else trade_date,
                            ts_code=sig.ts_code,
                            side=sig.side,
                            price=fill.fill_price,
                            qty=fill.fill_qty,
                            amount=fill.fill_price * fill.fill_qty,
                            fee=fill.fee,
                            slippage=fill.slippage,
                            reason=sig.reason,
                        ))

                pending_signals.clear()

            for ts_code, bar in bars.items():
                position_book.update_market_price(ts_code, bar.close)
            account_mgr.refresh(position_book)

            bar_data_dict: dict[str, BarData] = bars
            new_signals = strategy.on_bar(trade_date, bar_data_dict)
            if new_signals:
                pending_signals.extend(new_signals)

            acct = account_mgr.account
            daily_ret = (acct.total_asset - prev_equity) / prev_equity if prev_equity > 0 else 0.0
            bm_ret = self._get_benchmark_return(benchmark_df, trade_date)

            result.equity_curve.append(EquityPoint(
                date=trade_date,
                total_asset=acct.total_asset,
                cash=acct.cash,
                market_value=acct.market_value,
                daily_return=daily_ret,
                benchmark_return=bm_ret,
            ))
            prev_equity = acct.total_asset

        strategy.on_stop()
        result.finished_at = datetime.now()

        logger.info(
            "Backtest done: %d trades, %d filtered signals, final equity %.2f",
            len(result.trades), len(result.filtered_signals),
            result.equity_curve[-1].total_asset if result.equity_curve else config.initial_capital,
        )
        return result

    async def _resolve_universe(self, dl: DataLoader, config: BacktestConfig) -> list[str]:
        if config.universe:
            return config.universe
        df = await dl.stock_list("L")
        return df["ts_code"].tolist()

    async def _load_daily_data(
        self, dl: DataLoader, universe: list[str], config: BacktestConfig
    ) -> dict[str, pd.DataFrame]:
        """Batch-load daily bars for the entire universe in one query."""
        if config.universe:
            codes_csv = ",".join(f"'{c}'" for c in universe)
            where_clause = f"AND ts_code IN ({codes_csv}) "
        else:
            where_clause = ""

        all_df = await dl._query(
            f"SELECT * FROM stock_daily WHERE trade_date >= :s AND trade_date <= :e "
            f"{where_clause}ORDER BY ts_code, trade_date",
            {"s": config.start_date, "e": config.end_date},
        )
        if all_df.empty:
            return {}

        data: dict[str, pd.DataFrame] = {}
        for ts_code, group in all_df.groupby("ts_code"):
            data[str(ts_code)] = group.reset_index(drop=True)

        logger.info("Loaded daily data: %d rows for %d stocks", len(all_df), len(data))
        return data

    async def _load_suspend(self, dl: DataLoader, config: BacktestConfig) -> pd.DataFrame:
        return await dl._query(
            "SELECT ts_code, trade_date, suspend_type FROM suspend_d "
            "WHERE trade_date >= :s AND trade_date <= :e AND suspend_type = 'S'",
            {"s": config.start_date, "e": config.end_date},
        )

    def _get_bars_for_date(
        self, daily_data: dict[str, pd.DataFrame], trade_date: str
    ) -> dict[str, BarData]:
        bars: dict[str, BarData] = {}
        for ts_code, df in daily_data.items():
            row = df[df["trade_date"] == trade_date]
            if row.empty:
                continue
            r = row.iloc[0]
            bars[ts_code] = BarData(
                ts_code=ts_code,
                timestamp=datetime.strptime(trade_date, "%Y%m%d"),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                vol=float(r["vol"]) if pd.notna(r["vol"]) else 0.0,
                amount=float(r["amount"]) if pd.notna(r.get("amount", 0)) else 0.0,
                freq="daily",
            )
        return bars

    @staticmethod
    def _get_benchmark_return(benchmark_df: pd.DataFrame, trade_date: str) -> float:
        if benchmark_df.empty:
            return 0.0
        row = benchmark_df[benchmark_df["trade_date"] == trade_date]
        if row.empty:
            return 0.0
        pct = row.iloc[0].get("pct_chg", 0.0)
        return float(pct) / 100.0 if pd.notna(pct) else 0.0
