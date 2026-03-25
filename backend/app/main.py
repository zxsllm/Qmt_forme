import asyncio
import logging
import math
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

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


app = FastAPI(title="AI Trade", version="0.2.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trading_router)
app.include_router(backtest_router)


# ---------------------------------------------------------------------------
# Redis pub/sub → WebSocket bridge (async workers per channel)
# ---------------------------------------------------------------------------

NEWS_CHANNEL = "market:news"

logger = logging.getLogger(__name__)


async def _redis_ws_worker(channel: str) -> None:
    """Async worker: subscribe to one Redis channel, forward messages to WS clients."""
    import redis.asyncio as aioredis
    from app.core.redis import REDIS_URL

    r: aioredis.Redis | None = None
    while True:
        try:
            r = aioredis.from_url(REDIS_URL, decode_responses=True)
            ps = r.pubsub()
            await ps.subscribe(channel)
            logger.info("ws-bridge worker [%s] subscribed", channel)
            async for msg in ps.listen():
                if msg["type"] == "message":
                    await ws_manager.broadcast_text(msg["data"])
        except asyncio.CancelledError:
            break
        except Exception:
            logger.warning("ws-bridge worker [%s] error, reconnecting in 2s", channel, exc_info=True)
            await asyncio.sleep(2)
        finally:
            if r:
                try:
                    await r.aclose()
                except Exception:
                    pass


@app.on_event("startup")
async def startup_event():
    from app.core.startup import startup_checks
    app.state.startup_result = await startup_checks()
    asyncio.create_task(_redis_ws_worker(REDIS_CHANNEL))
    asyncio.create_task(_redis_ws_worker(NEWS_CHANNEL))


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
async def search_stocks(q: str = Query("", min_length=1, description="code, name or pinyin")):
    """Search stocks by ts_code, name prefix, or pinyin initials (max 20)."""
    if q.isalpha() and q.upper() == q:
        from app.shared.data.pinyin_cache import search_by_pinyin
        results = await search_by_pinyin(q, limit=20)
        if results:
            return {"count": len(results), "data": results}
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
    records = _df_to_records(df)

    from app.execution.feed.scheduler import get_rt_snapshot
    snap, snap_ts = get_rt_snapshot()
    if snap:
        today_str = datetime.now().strftime("%Y%m%d")
        last_date = records[-1]["trade_date"] if records else ""
        rt = snap.get(ts_code)
        if rt and rt.get("close", 0) > 0 and today_str != last_date:
            records.append({
                "ts_code": ts_code,
                "trade_date": today_str,
                "open": rt["open"], "high": rt["high"],
                "low": rt["low"], "close": rt["close"],
                "vol": rt["vol"], "amount": rt["amount"],
                "pre_close": rt["pre_close"],
                "pct_chg": rt.get("pct_chg", 0),
            })

    return {"count": len(records), "data": records}


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


# ── P2-Plus: Rankings / MoneyFlow / GlobalIndices / News / K-line ──


@app.get("/api/v1/market/rankings")
async def get_market_rankings(
    type: str = Query("gain", description="gain|lose|turnover"),
    limit: int = Query(10, ge=1, le=50),
):
    from app.execution.feed.scheduler import get_rt_rankings
    rt = get_rt_rankings(type, limit)
    if rt is not None:
        return {"count": len(rt), "data": rt, "source": "realtime"}
    loader = DataLoader()
    df = await loader.market_rankings(type, limit)
    return {"count": len(df), "data": _df_to_records(df), "source": "daily"}


@app.get("/api/v1/sector/rankings")
async def get_sector_rankings(limit: int = Query(10, ge=1, le=50)):
    from app.execution.feed.scheduler import get_rt_sector_rankings
    rt = get_rt_sector_rankings(limit * 3, "gain")
    if rt is not None:
        return {"count": len(rt), "data": rt, "source": "realtime"}
    loader = DataLoader()
    df = await loader.sector_rankings(limit)
    return {"count": len(df), "data": _df_to_records(df), "source": "daily"}


@app.get("/api/v1/market/moneyflow")
async def get_moneyflow(limit: int = Query(10, ge=1, le=50)):
    loader = DataLoader()
    df = await loader.moneyflow_top(limit)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/market/global-indices")
async def get_global_indices():
    from app.execution.feed.scheduler import get_rt_global_indices
    rt = get_rt_global_indices()
    if rt is not None:
        return {"count": len(rt), "data": rt, "source": "realtime"}
    loader = DataLoader()
    df = await loader.global_indices()
    return {"count": len(df), "data": _df_to_records(df), "source": "daily"}


@app.get("/api/v1/market/news")
async def get_market_news(limit: int = Query(50, ge=1, le=200)):
    loader = DataLoader()
    df = await loader.market_news(limit)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/stock/{ts_code}/news")
async def get_stock_news(ts_code: str, limit: int = Query(20, ge=1, le=100)):
    loader = DataLoader()
    df = await loader.stock_news(ts_code, limit)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/stock/{ts_code}/anns")
async def get_stock_anns(ts_code: str, limit: int = Query(20, ge=1, le=100)):
    loader = DataLoader()
    df = await loader.stock_anns(ts_code, limit)
    if df.empty:
        import pandas as pd
        def _fetch():
            from app.research.data.tushare_service import TushareService
            return TushareService().anns(ts_code=ts_code)
        try:
            rt_df = await asyncio.to_thread(_fetch)
            if not rt_df.empty:
                rt_df = rt_df.head(limit)
                df = rt_df
        except Exception:
            logging.getLogger(__name__).warning("anns fallback failed for %s", ts_code, exc_info=True)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/stock/{ts_code}/irm_qa")
async def get_stock_irm_qa(ts_code: str, limit: int = Query(20, ge=1, le=100)):
    import pandas as pd
    from app.research.data.tushare_service import TushareService

    exchange = ts_code.split(".")[-1].upper() if "." in ts_code else ""

    def _fetch():
        svc = TushareService()
        if exchange == "SH":
            return svc.irm_qa_sh(ts_code=ts_code, limit=limit)
        elif exchange == "SZ":
            return svc.irm_qa_sz(ts_code=ts_code, limit=limit)
        return pd.DataFrame()

    df = await asyncio.to_thread(_fetch)
    if df.empty:
        return {"count": 0, "data": []}
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/stock/{ts_code}/weekly")
async def get_stock_weekly(
    ts_code: str,
    start: str = Query("", description="YYYYMMDD"),
    end: str = Query("", description="YYYYMMDD"),
):
    loader = DataLoader()
    df = await loader.weekly(ts_code, start, end)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/stock/{ts_code}/monthly")
async def get_stock_monthly(
    ts_code: str,
    start: str = Query("", description="YYYYMMDD"),
    end: str = Query("", description="YYYYMMDD"),
):
    loader = DataLoader()
    df = await loader.monthly(ts_code, start, end)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/stock/{ts_code}/minutes")
async def get_stock_minutes(
    ts_code: str,
    start: str = Query("", description="datetime e.g. 2026-03-23 09:30:00"),
    end: str = Query("", description="datetime"),
    days: int = Query(1, ge=1, le=30, description="默认1天(今天), 最多30天"),
):
    if not start:
        from datetime import timedelta
        start_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
        start = start_dt.strftime("%Y-%m-%d %H:%M:%S")

    import pandas as pd

    loader = DataLoader()
    df = await loader.minutes(ts_code, start, end)

    today_str = datetime.now().strftime("%Y-%m-%d")
    has_today = False
    if not df.empty:
        last_ts = str(df["trade_time"].iloc[-1])
        has_today = today_str in last_ts

    if not has_today:
        def _fetch_today_mins():
            from app.research.data.tushare_service import TushareService
            svc = TushareService()
            return svc.stk_mins(ts_code=ts_code, freq="1min")
        try:
            rt_df = await asyncio.to_thread(_fetch_today_mins)
            if not rt_df.empty:
                rt_df = rt_df.rename(columns={"trade_time": "trade_time"})
                if "trade_time" in rt_df.columns:
                    rt_df["trade_time"] = pd.to_datetime(rt_df["trade_time"])
                    rt_df = rt_df.sort_values("trade_time")
                    if not df.empty:
                        df = pd.concat([df, rt_df], ignore_index=True)
                        df = df.drop_duplicates(subset=["ts_code", "trade_time"], keep="last")
                        df = df.sort_values("trade_time")
                    else:
                        df = rt_df
        except Exception:
            logging.getLogger(__name__).warning("stk_mins fallback failed for %s", ts_code, exc_info=True)

    start_date_str = start[:10].replace("-", "") if start else ""

    def _fetch_auction_o():
        from app.research.data.tushare_service import TushareService
        svc = TushareService()
        return svc.stk_auction_o(ts_code=ts_code, start_date=start_date_str)

    auction_df = await loader._query(
        "SELECT trade_date, price, vol, amount FROM stk_auction "
        "WHERE ts_code = :c AND trade_date >= :s ORDER BY trade_date",
        {"c": ts_code, "s": start_date_str},
    )

    auc_o_df = pd.DataFrame()
    try:
        auc_o_df = await asyncio.to_thread(_fetch_auction_o)
    except Exception:
        logger.warning("stk_auction_o failed for %s", ts_code, exc_info=True)

    auc_rows = []
    if not auc_o_df.empty:
        for _, arow in auc_o_df.iterrows():
            td = str(arow["trade_date"])
            prefix = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
            auc_close = float(arow.get("close", 0) or 0)
            if auc_close <= 0:
                continue
            auc_rows.append({
                "ts_code": ts_code, "trade_time": pd.Timestamp(f"{prefix} 09:25:00"),
                "open": float(arow.get("open", 0) or 0),
                "high": float(arow.get("high", 0) or 0),
                "low": float(arow.get("low", 0) or 0),
                "close": auc_close,
                "vol": float(arow.get("vol", 0) or 0),
                "amount": float(arow.get("amount", 0) or 0),
                "freq": "1min",
            })
    elif not auction_df.empty:
        for _, arow in auction_df.iterrows():
            td = str(arow["trade_date"])
            prefix = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
            price = float(arow["price"]) if arow["price"] else 0
            if price <= 0:
                continue
            auc_rows.append({
                "ts_code": ts_code, "trade_time": pd.Timestamp(f"{prefix} 09:25:00"),
                "open": price, "high": price, "low": price, "close": price,
                "vol": float(arow["vol"]) if arow["vol"] else 0,
                "amount": float(arow["amount"]) if arow["amount"] else 0,
                "freq": "1min",
            })

    if auc_rows:
        auc_df = pd.DataFrame(auc_rows)
        df = pd.concat([auc_df, df], ignore_index=True)
        df = df.drop_duplicates(subset=["ts_code", "trade_time"], keep="last")
        df = df.sort_values("trade_time")

    pre_close_val = None
    auc_row = await loader._query(
        "SELECT pre_close FROM stk_auction WHERE ts_code = :c "
        "ORDER BY trade_date DESC LIMIT 1",
        {"c": ts_code},
    )
    if not auc_row.empty:
        pre_close_val = float(auc_row["pre_close"].iloc[0])

    return {"count": len(df), "data": _df_to_records(df), "pre_close": pre_close_val}


# ── 集合竞价 ──────────────────────────────────────────────────

@app.get("/api/v1/market/auction")
async def get_stk_auction(
    trade_date: str = Query("", description="YYYYMMDD, defaults to latest trade date"),
    limit: int = Query(50, ge=1, le=200),
):
    loader = DataLoader()
    if not trade_date:
        td_df = await loader._query(
            "SELECT DISTINCT trade_date FROM stk_auction ORDER BY trade_date DESC LIMIT 1", {}
        )
        trade_date = td_df["trade_date"].iloc[0] if not td_df.empty else ""
    if not trade_date:
        return {"count": 0, "data": [], "trade_date": ""}
    df = await loader.stk_auction(trade_date, limit)
    return {"count": len(df), "data": _df_to_records(df), "trade_date": trade_date}


# ── 财经日历 ──────────────────────────────────────────────────

@app.get("/api/v1/market/eco-cal")
async def get_eco_cal(
    start: str = Query("", description="YYYYMMDD"),
    end: str = Query("", description="YYYYMMDD"),
    country: str = Query("", description="e.g. 中国, 美国"),
):
    from datetime import datetime, timedelta
    loader = DataLoader()
    if not start:
        start = (datetime.now() - timedelta(days=3)).strftime("%Y%m%d")
    if not end:
        end = (datetime.now() + timedelta(days=7)).strftime("%Y%m%d")
    df = await loader.eco_cal(start, end, country)
    return {"count": len(df), "data": _df_to_records(df)}


# ── 行业资金流向 (THS) ───────────────────────────────────────

@app.get("/api/v1/market/moneyflow-ind")
async def get_moneyflow_ind(
    trade_date: str = Query("", description="YYYYMMDD, defaults to latest trade date"),
    limit: int = Query(50, ge=1, le=200),
):
    loader = DataLoader()
    if not trade_date:
        td_df = await loader._query(
            "SELECT DISTINCT trade_date FROM moneyflow_ind_ths ORDER BY trade_date DESC LIMIT 1", {}
        )
        trade_date = td_df["trade_date"].iloc[0] if not td_df.empty else ""
    if not trade_date:
        return {"count": 0, "data": [], "trade_date": ""}
    df = await loader.moneyflow_ind_ths(trade_date, limit)
    return {"count": len(df), "data": _df_to_records(df), "trade_date": trade_date}
