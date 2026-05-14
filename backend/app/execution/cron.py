"""每日定时任务（09:25 自动启策略 / 15:05 对账报告）。

独立的 asyncio 循环每 30s 检查一次时间，避免污染 scheduler._loop。
所有任务做 "今天只跑一次" 的幂等保证。

启动入口：app.main 在 lifespan 里调 start_cron()。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time as dtime
from pathlib import Path

logger = logging.getLogger(__name__)

# 任务执行去重：每个任务 today-only 幂等
_state: dict[str, str] = {
    "patterns_started_date": "",
    "reconcile_done_date": "",
}

_task: asyncio.Task | None = None
_running: bool = False


# ---------------------------------------------------------------------------
# 09:25 自动启动 Pattern1 / Pattern2
# ---------------------------------------------------------------------------

async def _auto_start_patterns(today_str: str) -> None:
    """09:25 在交易日自动启 Pattern1/2，各 100 万独立资金池。"""
    from app.core.startup import is_trade_date
    if not await is_trade_date():
        logger.info("[cron] 09:25 reached but %s is not trade date — skip", today_str)
        return

    from app.execution.strategy_runner import strategy_runner
    from app.research.strategies.pattern_01_long1_natural import Pattern01
    from app.research.strategies.pattern_02_long1_yizi import Pattern02
    from app.execution.feed.scheduler import scheduler
    from app.core.database import async_session

    for cls, name in [(Pattern01, "pattern_01"), (Pattern02, "pattern_02")]:
        if name in strategy_runner.running_strategies:
            logger.info("[cron] %s already running — skip", name)
            continue
        try:
            strategy = cls()
            async with async_session() as session:
                await strategy.warm_up(session, today_str)
            universe = strategy.get_universe()
            if not universe:
                logger.warning("[cron] %s warm_up empty — sectors data missing?", name)
                continue
            for c in universe:
                scheduler.add_watch_code(c)
            result = await strategy_runner.start_strategy(
                strategy, universe, initial_capital=1_000_000.0,
            )
            if "error" in result:
                logger.warning("[cron] %s start failed: %s", name, result["error"])
            else:
                logger.info("[cron] auto-started %s with %d codes", name, len(universe))
        except Exception:
            logger.exception("[cron] auto-start %s failed", name)


# ---------------------------------------------------------------------------
# 15:05 对账报告
# ---------------------------------------------------------------------------

async def _daily_reconcile(today_str: str) -> None:
    """15:05 跑 OMS 实盘 vs 回测对账，输出到 reports/oms_reconcile/YYYYMMDD/。"""
    from app.core.startup import is_trade_date
    if not await is_trade_date():
        return

    reports_dir = Path(__file__).resolve().parents[3] / "reports" / "oms_reconcile" / today_str
    reports_dir.mkdir(parents=True, exist_ok=True)

    try:
        from app.execution.reconcile import generate_daily_reconcile
        await generate_daily_reconcile(today_str, reports_dir)
        logger.info("[cron] daily reconcile report → %s", reports_dir)
    except Exception:
        logger.exception("[cron] daily reconcile failed")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

# 触发窗口：避免错过 09:25:00 这一秒，给 60s 容差
START_TRIGGER = dtime(9, 25)
START_DEADLINE = dtime(9, 30)  # 09:30 前必须起完
RECONCILE_TRIGGER = dtime(15, 5)
RECONCILE_DEADLINE = dtime(15, 30)


async def _tick():
    now = datetime.now()
    now_time = now.time()
    today_str = now.strftime("%Y%m%d")

    # 09:25 auto-start
    if (START_TRIGGER <= now_time < START_DEADLINE
            and _state["patterns_started_date"] != today_str):
        _state["patterns_started_date"] = today_str  # 占位避免并发触发
        try:
            await _auto_start_patterns(today_str)
        except Exception:
            logger.exception("[cron] auto-start crashed")

    # 15:05 reconcile
    if (RECONCILE_TRIGGER <= now_time < RECONCILE_DEADLINE
            and _state["reconcile_done_date"] != today_str):
        _state["reconcile_done_date"] = today_str
        try:
            await _daily_reconcile(today_str)
        except Exception:
            logger.exception("[cron] reconcile crashed")


async def _loop():
    logger.info("[cron] daily cron loop started — auto-start@%s reconcile@%s",
                START_TRIGGER, RECONCILE_TRIGGER)
    while _running:
        try:
            await _tick()
        except Exception:
            logger.exception("[cron] tick error")
        await asyncio.sleep(30)
    logger.info("[cron] daily cron loop stopped")


def start_cron() -> None:
    global _task, _running
    if _running:
        return
    _running = True
    _task = asyncio.create_task(_loop())


def stop_cron() -> None:
    global _running, _task
    _running = False
    if _task:
        _task.cancel()
        _task = None
