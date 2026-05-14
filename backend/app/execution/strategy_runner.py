"""StrategyRunner — bridges IStrategy with live TradingEngine.

订阅两条 Redis channel：
  - REDIS_CHANNEL ("market:bars")          单 bar 老协议 → 老策略（MA/OvernightGap）
  - MINUTE_BARS_CHANNEL ("market:minute_bars") 1min batch 新协议 → Pattern1/2

按策略名前缀决定订哪一条：name 以 "pattern_" 开头 → batch；否则单 bar。
避免一根 bar 双重 dispatch（Pattern 不会收到 5400 次 rt_k tick，老策略不会收到
每分钟一次的 batch）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from app.core.redis import redis_client
from app.execution.engine import TradingEngine, trading_engine
from app.execution.feed.market_feed import MINUTE_BARS_CHANNEL, REDIS_CHANNEL
from app.shared.interfaces.models import BacktestConfig, BacktestContext, BarData, Signal
from app.shared.interfaces.strategy import IStrategy

logger = logging.getLogger(__name__)


def _is_pattern_strategy(name: str) -> bool:
    return name.startswith("pattern_")


class _RunningStrategy:
    """Wrapper for a strategy instance running in live mode.

    每个策略持有独立 TradingEngine 实例 + 100 万初始资金（方案 A 资金池分开）。
    DB sim_* 表按 engine.strategy_name 隔离持久化。
    """

    def __init__(
        self,
        strategy: IStrategy,
        codes: list[str],
        engine: TradingEngine,
    ):
        self.strategy = strategy
        self.codes = codes
        self.engine = engine
        # 单 bar 模式（老策略）维护历史；batch 模式（Pattern1/2）由策略自管理 streaming 索引
        self.bar_history: dict[str, list[BarData]] = {}
        self.signals_today: list[Signal] = []
        self.total_signals = 0
        self.started_at = datetime.now()
        # batch_mode=True → 订 MINUTE_BARS_CHANNEL；False → 订 REDIS_CHANNEL
        self.batch_mode: bool = _is_pattern_strategy(strategy.name)

    def info(self) -> dict[str, Any]:
        acct = self.engine.account_mgr.account
        return {
            "name": self.strategy.name,
            "description": self.strategy.description,
            "params": self.strategy.params,
            "codes": self.codes[:10],
            "total_codes": len(self.codes),
            "signals_today": len(self.signals_today),
            "total_signals": self.total_signals,
            "started_at": self.started_at.isoformat(),
            "batch_mode": self.batch_mode,
            "account": {
                "total_asset": acct.total_asset,
                "cash": acct.cash,
                "market_value": acct.market_value,
                "today_pnl": acct.today_pnl,
            },
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

    async def start_strategy(
        self,
        strategy: IStrategy,
        codes: list[str] | None = None,
        initial_capital: float = 1_000_000.0,
    ) -> dict:
        """Register and start a strategy.

        Pattern1/2 不允许盘中（09:30 后）注册 — 这些策略依赖 warm_up 时锁定的
        盘前静态数据 + 09:30 一字开识别窗口；09:30 之后启动会错过整个 entry window。

        每个策略独立 TradingEngine 实例 + initial_capital（默认 100 万）。
        """
        name = strategy.name
        if name in self._strategies:
            return {"error": f"strategy '{name}' already running"}

        if _is_pattern_strategy(name):
            now = datetime.now().time()
            from datetime import time as dtime
            if dtime(9, 30) <= now <= dtime(15, 0):
                return {
                    "error": "409: Pattern strategies must be started before market open",
                    "now": now.strftime("%H:%M:%S"),
                }

        if not codes:
            codes = ["000001.SZ"]

        # 独立 engine — 同名 sim_* 行通过 strategy_name 隔离
        engine = TradingEngine(initial_capital=initial_capital, strategy_name=name)
        engine.set_risk_limits(max_daily_buys=80 if _is_pattern_strategy(name) else 20)
        # 先 restore（拿到隔夜持仓 + 上次账户余额），再 begin_day（重置 daily counter）
        try:
            await engine.restore_from_db()
        except Exception:
            logger.exception("[%s] restore_from_db error (continuing with fresh state)", name)
        engine.begin_day()

        ctx = BacktestContext(
            config=BacktestConfig(
                strategy_name=name,
                strategy_params=strategy.params,
                start_date=datetime.now().strftime("%Y%m%d"),
                end_date="99991231",
                initial_capital=initial_capital,
                universe=codes,
            ),
            universe_codes=codes,
            trade_dates=[],
        )
        strategy.on_init(ctx)

        rs = _RunningStrategy(strategy, codes, engine)
        self._strategies[name] = rs

        if not self._listening:
            self._start_listener()

        logger.info(
            "strategy '%s' started with %d codes, capital=%.0f (batch_mode=%s)",
            name, len(codes), initial_capital, rs.batch_mode,
        )
        return rs.info()

    def stop_strategy(self, name: str) -> dict:
        rs = self._strategies.pop(name, None)
        if rs is None:
            return {"error": f"strategy '{name}' not found"}
        rs.strategy.on_stop()
        # 落库当日状态（用户下次启动同名策略时可以 restore_from_db）
        try:
            rs.engine.end_day()
        except Exception:
            logger.exception("[%s] engine.end_day error", name)
        logger.info("strategy '%s' stopped", name)

        if not self._strategies and self._listening:
            self._stop_listener()

        return {"status": "stopped", "name": name}

    def get_engine(self, strategy_name: str) -> "TradingEngine | None":
        """API 端点用：拿到指定策略的 engine 实例。strategy_name='default' 返回全局 manual engine。"""
        if strategy_name == "default":
            return trading_engine
        rs = self._strategies.get(strategy_name)
        return rs.engine if rs else None

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
        """Subscribe to both single-bar and minute-batch channels via shared redis_client."""
        ps = redis_client.pubsub()
        ps.subscribe(REDIS_CHANNEL, MINUTE_BARS_CHANNEL)
        logger.info(
            "strategy runner listening on Redis channels: '%s' (single) + '%s' (batch)",
            REDIS_CHANNEL, MINUTE_BARS_CHANNEL,
        )

        while self._listening:
            try:
                msg = ps.get_message(ignore_subscribe_messages=True, timeout=0.5)
                if msg and msg["type"] == "message":
                    channel = msg.get("channel", "")
                    data = msg.get("data", "")
                    if channel == REDIS_CHANNEL:
                        bar_data = json.loads(data)
                        bar = BarData(**bar_data)
                        await self._on_single_bar(bar)
                    elif channel == MINUTE_BARS_CHANNEL:
                        payload = json.loads(data)
                        bars = [BarData(**b) for b in payload.get("bars", [])]
                        if bars:
                            await self._on_minute_batch(bars)
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("strategy runner listen error")
                await asyncio.sleep(5)

        try:
            ps.unsubscribe()
            ps.close()
        except Exception:
            pass

    async def _on_single_bar(self, bar: BarData) -> None:
        """老协议：单 bar 推送 → 只派发给非 batch_mode 策略（MA/OvernightGap）。"""
        bar_date = bar.timestamp.strftime("%Y%m%d")
        for rs in list(self._strategies.values()):
            if rs.batch_mode:
                continue
            if bar.ts_code not in rs.codes:
                continue

            rs.bar_history.setdefault(bar.ts_code, []).append(bar)

            bars_dict: dict[str, BarData] = {}
            for code in rs.codes:
                hist = rs.bar_history.get(code)
                if hist:
                    bars_dict[code] = hist[-1]

            if not bars_dict:
                continue

            await self._dispatch_and_submit(rs, bar_date, bars_dict)

    async def _on_minute_batch(self, bars: list[BarData]) -> None:
        """新协议：1min batch → 只派发给 batch_mode 策略（Pattern1/2）。

        策略内部按 _seen_minutes 幂等，所以 09:30 的 preview + final 两次 publish
        只会被 _scan_minute 处理一次。

        每分钟在策略 engine 上跑：
            1. engine.on_bar(bars)       — 撮合 T-1 提交的 BUY/SELL（用 T.open）
            2. strategy.on_bar → signals — 策略扫产 BUY/SELL
            3. engine.submit_signal      — 入队（T+1 撮合）
            4. engine.auto_close_check   — 派 SELL for due lots
        """
        bar_date = bars[0].timestamp.strftime("%Y%m%d")
        bars_dict: dict[str, BarData] = {b.ts_code: b for b in bars}
        minute_dt = bars[0].timestamp
        snapshot = {
            b.ts_code: {"close": b.close, "open": b.open, "high": b.high,
                        "low": b.low, "vol": b.vol, "pre_close": b.pre_close}
            for b in bars
        }
        for rs in list(self._strategies.values()):
            if not rs.batch_mode:
                continue
            # 1. 先撮合（T-1 提交的 BUY/SELL 用 T.open 成交）
            try:
                rs.engine.on_bar(bars_dict)
            except Exception:
                logger.exception("[%s] engine.on_bar error", rs.strategy.name)
            # 2/3. 策略扫描 + 提交
            await self._dispatch_and_submit(rs, bar_date, bars_dict)
            # 4. auto_close：next_open / intraday_at / today_close 到期 lots 派 SELL
            try:
                rs.engine.auto_close_check(minute_dt, snapshot)
            except Exception:
                logger.exception("[%s] auto_close_check error", rs.strategy.name)

    async def _dispatch_and_submit(
        self, rs: _RunningStrategy, bar_date: str, bars_dict: dict[str, BarData],
    ) -> None:
        try:
            signals = rs.strategy.on_bar(bar_date, bars_dict)
        except Exception:
            logger.exception("strategy '%s' on_bar error", rs.strategy.name)
            return
        for signal in signals:
            rs.signals_today.append(signal)
            rs.total_signals += 1
            result = rs.engine.submit_signal(signal)
            if isinstance(result, str):
                logger.warning("[%s] signal rejected: %s — %s",
                               rs.strategy.name, signal.ts_code, result)
            else:
                logger.info(
                    "[%s] signal submitted: %s %s %d",
                    rs.strategy.name, signal.side.value,
                    signal.ts_code, signal.qty,
                )

    def status(self) -> dict:
        return {
            "listening": self._listening,
            "strategies": self.list_strategies(),
        }


strategy_runner = StrategyRunner()
