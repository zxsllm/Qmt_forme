import asyncio
import json
import math

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.shared.data import DataLoader
from app.execution.api import router as trading_router
from app.research.api import router as backtest_router
from app.execution.feed.ws_manager import ws_manager
from app.execution.feed.market_feed import REDIS_CHANNEL
from app.execution.feed.scheduler import scheduler
from app.core.redis import redis_client


def _df_to_records(df):
    """Convert DataFrame to JSON-safe records, replacing NaN/Inf with None."""
    records = df.to_dict(orient="records")
    for row in records:
        for k, v in row.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                row[k] = None
    return records


app = FastAPI(title="AI Trade", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trading_router)
app.include_router(backtest_router)


# ---------------------------------------------------------------------------
# Redis pub/sub → WebSocket bridge (background task)
# ---------------------------------------------------------------------------

async def _redis_to_ws_bridge() -> None:
    """Subscribe to Redis market channel and forward to all WS clients."""
    import redis as _redis
    sub = _redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    ps = sub.pubsub()
    ps.subscribe(REDIS_CHANNEL)

    while True:
        msg = ps.get_message(ignore_subscribe_messages=True, timeout=0.5)
        if msg and msg["type"] == "message":
            await ws_manager.broadcast_text(msg["data"])
        await asyncio.sleep(0.05)


@app.on_event("startup")
async def startup_event():
    from app.core.startup import startup_checks
    app.state.startup_result = await startup_checks()
    asyncio.create_task(_redis_to_ws_bridge())


@app.websocket("/ws/market")
async def ws_market(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)


@app.get("/health")
async def health():
    result = getattr(app.state, "startup_result", {})
    return {"status": "ok", "phase": "4.6-lifecycle", "startup": result}


@app.get("/api/v1/stock/search")
async def search_stocks(q: str = Query("", min_length=1, description="code or name")):
    """Search stocks by ts_code or name prefix (max 20 results)."""
    loader = DataLoader()
    df = await loader.search_stocks(q, limit=20)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/stock/{ts_code}/daily")
async def get_stock_daily(
    ts_code: str,
    start: str = Query("", description="YYYYMMDD"),
    end: str = Query("", description="YYYYMMDD"),
):
    loader = DataLoader()
    df = await loader.daily_with_basic(ts_code, start, end)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/market/snapshot/{trade_date}")
async def get_market_snapshot(trade_date: str):
    loader = DataLoader()
    df = await loader.market_snapshot(trade_date)
    return {"count": len(df), "data": _df_to_records(df.head(20))}


@app.get("/api/v1/index/{ts_code}/daily")
async def get_index_daily(
    ts_code: str,
    start: str = Query("", description="YYYYMMDD"),
    end: str = Query("", description="YYYYMMDD"),
):
    loader = DataLoader()
    df = await loader.index_daily(ts_code, start, end)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/classify/sw")
async def get_sw_classify(level: str = Query("", description="L1/L2/L3")):
    loader = DataLoader()
    df = await loader.sw_classify(level)
    return {"count": len(df), "data": _df_to_records(df)}
