"""StrategyRunner — bridges IStrategy with live TradingEngine.

Listens for bar updates (from MarketDataScheduler via Redis pub/sub),
accumulates history, calls strategy.on_bar(), and submits signals to OMS.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from app.shared.interfaces.models import BacktestContext, BacktestConfig, BarData, Signal
from app.shared.interfaces.strategy import IStrategy
from app.execution.engine import trading_engine
from app.execution.feed.market_feed import REDIS_CHANNEL
from app.core.redis import redis_client

logger = logging.getLogger(__name__)


class _RunningStrategy:
    """Wrapper for a strategy instance running in live mode."""

    def __init__(self, strategy: IStrategy, codes: list[str]):
        self.strategy = strategy
        self.codes = codes
        self.bar_history: dict[str, list[BarData]] = {}
        self.signals_today: list[Signal] = []
        self.total_signals = 0
        self.started_at = datetime.now()

    def info(self) -> dict[str, Any]:
        return {
            "name": self.strategy.name,
            "description": self.strategy.description,
            "params": self.strategy.params,
            "codes": self.codes[:10],
            "total_codes": len(self.codes),
            "signals_today": len(self.signals_today),
            "total_signals": self.total_signals,
            "started_at": self.started_at.isoformat(),
        }


class StrategyRunner:
    """Manages live strategy execution."""

    def __init__(self):
        self._strategies: dict[str, _RunningStrategy] = {}
        self._listening = False
        self._listen_task: asyncio.Task | None = None

    @property
    def running_strategies(self) -> dict[str, _RunningStrategy]:
        return self._strategies

    def start_strategy(
        self,
        strategy: IStrategy,
        codes: list[str] | None = None,
    ) -> dict:
        """Register and start a strategy."""
        name = strategy.name
        if name in self._strategies:
            return {"error": f"strategy '{name}' already running"}

        if not codes:
            codes = ["000001.SZ"]

        ctx = BacktestContext(
            config=BacktestConfig(
                strategy_name=name,
                strategy_params=strategy.params,
                start_date=datetime.now().strftime("%Y%m%d"),
                end_date="99991231",
                initial_capital=trading_engine.account_mgr.account.total_asset,
                universe=codes,
            ),
            universe_codes=codes,
            trade_dates=[],
        )
        strategy.on_init(ctx)

        rs = _RunningStrategy(strategy, codes)
        self._strategies[name] = rs

        if not self._listening:
            self._start_listener()

        logger.info("strategy '%s' started with %d codes", name, len(codes))
        return rs.info()

    def stop_strategy(self, name: str) -> dict:
        rs = self._strategies.pop(name, None)
        if rs is None:
            return {"error": f"strategy '{name}' not found"}
        rs.strategy.on_stop()
        logger.info("strategy '%s' stopped", name)

        if not self._strategies and self._listening:
            self._stop_listener()

        return {"status": "stopped", "name": name}

    def list_strategies(self) -> list[dict]:
        return [rs.info() for rs in self._strategies.values()]

    def _start_listener(self) -> None:
        self._listening = True
        self._listen_task = asyncio.create_task(self._listen_loop())

    def _stop_listener(self) -> None:
        self._listening = False
        if self._listen_task:
            self._listen_task.cancel()
            self._listen_task = None

    async def _listen_loop(self) -> None:
        """Subscribe to Redis bars and dispatch to strategies."""
        import redis as _redis
        sub = _redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        ps = sub.pubsub()
        ps.subscribe(REDIS_CHANNEL)
        logger.info("strategy runner listening on Redis channel '%s'", REDIS_CHANNEL)

        while self._listening:
            try:
                msg = ps.get_message(ignore_subscribe_messages=True, timeout=0.5)
                if msg and msg["type"] == "message":
                    bar_data = json.loads(msg["data"])
                    bar = BarData(**bar_data)
                    await self._on_bar_received(bar)
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("strategy runner listen error")
                await asyncio.sleep(5)

        ps.unsubscribe()
        sub.close()

    async def _on_bar_received(self, bar: BarData) -> None:
        """Process a single bar: accumulate + call strategies."""
        bar_date = bar.timestamp.strftime("%Y%m%d")

        for rs in list(self._strategies.values()):
            if bar.ts_code not in rs.codes:
                continue

            rs.bar_history.setdefault(bar.ts_code, []).append(bar)

            bars_dict = {}
            for code in rs.codes:
                hist = rs.bar_history.get(code)
                if hist:
                    bars_dict[code] = hist[-1]

            if not bars_dict:
                continue

            try:
                signals = rs.strategy.on_bar(bar_date, bars_dict)
            except Exception:
                logger.exception("strategy '%s' on_bar error", rs.strategy.name)
                continue

            for signal in signals:
                rs.signals_today.append(signal)
                rs.total_signals += 1
                result = trading_engine.submit_signal(signal)
                if isinstance(result, str):
                    logger.warning("signal rejected: %s — %s", signal.ts_code, result)
                else:
                    logger.info(
                        "strategy '%s' signal submitted: %s %s %d",
                        rs.strategy.name, signal.side.value,
                        signal.ts_code, signal.qty,
                    )

    def status(self) -> dict:
        return {
            "listening": self._listening,
            "strategies": self.list_strategies(),
        }


strategy_runner = StrategyRunner()
