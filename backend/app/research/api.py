"""Backtest REST API endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.shared.interfaces.models import BacktestConfig
from app.shared.models import BacktestRun, StrategyMeta
from app.research.backtest.engine import BacktestEngine
from app.research.backtest.report import ReportGenerator
from app.research.strategies.ma_crossover import MACrossover

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/backtest", tags=["backtest"])

STRATEGY_REGISTRY: dict[str, type] = {
    "ma_crossover": MACrossover,
}


class RunBacktestRequest(BaseModel):
    strategy_name: str
    strategy_params: dict = {}
    start_date: str
    end_date: str
    initial_capital: float = 1_000_000.0
    benchmark: str = "000300.SH"
    universe: list[str] = []


async def _run_backtest_async(config: BacktestConfig, strategy_cls: type) -> dict:
    """Run backtest in the main event loop (Phase 4 MVP — acceptable blocking)."""
    strategy = strategy_cls(config.strategy_params)
    engine = BacktestEngine()
    result = await engine._run_async(strategy, config)
    reporter = ReportGenerator()
    result = reporter.generate(result)

    return {
        "config": result.config.model_dump(),
        "stats": result.stats.model_dump(),
        "equity_curve": [e.model_dump() for e in result.equity_curve],
        "trades": [t.model_dump() for t in result.trades],
        "filtered_signals": [f.model_dump() for f in result.filtered_signals],
        "started_at": result.started_at.isoformat() if result.started_at else None,
        "finished_at": result.finished_at.isoformat() if result.finished_at else None,
    }


@router.post("/run")
async def run_backtest(req: RunBacktestRequest):
    """Submit and run a backtest. Returns results when done."""
    strategy_cls = STRATEGY_REGISTRY.get(req.strategy_name)
    if not strategy_cls:
        raise HTTPException(404, f"Strategy '{req.strategy_name}' not found. Available: {list(STRATEGY_REGISTRY.keys())}")

    config = BacktestConfig(
        strategy_name=req.strategy_name,
        strategy_params=req.strategy_params,
        start_date=req.start_date,
        end_date=req.end_date,
        initial_capital=req.initial_capital,
        benchmark=req.benchmark,
        universe=req.universe,
    )

    run_id = str(uuid4())

    session: AsyncSession = async_session()
    try:
        run_record = BacktestRun(
            run_id=run_id,
            strategy_name=req.strategy_name,
            config_json=json.dumps(config.model_dump(), ensure_ascii=False),
            status="RUNNING",
        )
        session.add(run_record)
        await session.commit()
    finally:
        await session.close()

    try:
        data = await _run_backtest_async(config, strategy_cls)
    except Exception as e:
        session = async_session()
        try:
            await session.execute(
                text("UPDATE backtest_run SET status='FAILED' WHERE run_id = :rid"),
                {"rid": run_id},
            )
            await session.commit()
        finally:
            await session.close()
        logger.exception("Backtest %s failed", run_id)
        raise HTTPException(500, f"Backtest failed: {str(e)}")

    finished_at = datetime.fromisoformat(data["finished_at"]) if data["finished_at"] else datetime.now()

    session = async_session()
    try:
        await session.execute(
            text(
                "UPDATE backtest_run SET "
                "stats_json = :stats, equity_json = :eq, trades_json = :tr, "
                "filtered_json = :filt, finished_at = :fin, status = 'DONE' "
                "WHERE run_id = :rid"
            ),
            {
                "stats": json.dumps(data["stats"], ensure_ascii=False),
                "eq": json.dumps(data["equity_curve"], ensure_ascii=False),
                "tr": json.dumps(data["trades"], ensure_ascii=False, default=str),
                "filt": json.dumps(data["filtered_signals"], ensure_ascii=False, default=str),
                "fin": finished_at,
                "rid": run_id,
            },
        )
        await session.commit()
    finally:
        await session.close()

    return {"run_id": run_id, **data}


@router.get("/list")
async def list_backtest_runs(limit: int = 20):
    """List recent backtest runs."""
    session: AsyncSession = async_session()
    try:
        result = await session.execute(
            select(BacktestRun)
            .order_by(BacktestRun.started_at.desc())
            .limit(limit)
        )
        runs = result.scalars().all()
        return [
            {
                "run_id": r.run_id,
                "strategy_name": r.strategy_name,
                "status": r.status,
                "stats": json.loads(r.stats_json) if r.stats_json != "{}" else None,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in runs
        ]
    finally:
        await session.close()


@router.get("/result/{run_id}")
async def get_backtest_result(run_id: str):
    """Get a stored backtest result by run_id."""
    session: AsyncSession = async_session()
    try:
        result = await session.execute(
            select(BacktestRun).where(BacktestRun.run_id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            raise HTTPException(404, "Backtest run not found")
        return {
            "run_id": run.run_id,
            "strategy_name": run.strategy_name,
            "status": run.status,
            "config": json.loads(run.config_json),
            "stats": json.loads(run.stats_json),
            "equity_curve": json.loads(run.equity_json),
            "trades": json.loads(run.trades_json),
            "filtered_signals": json.loads(run.filtered_json),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }
    finally:
        await session.close()


@router.get("/strategies")
async def list_strategies():
    """List all registered strategies."""
    strategies = []
    for name, cls in STRATEGY_REGISTRY.items():
        strategies.append({
            "name": name,
            "description": getattr(cls, "description", ""),
            "default_params": getattr(cls, "default_params", {}),
        })
    return strategies
