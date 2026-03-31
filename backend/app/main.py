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
    if q.isascii() and q.replace(" ", "").isalpha():
        from app.shared.data.pinyin_cache import search_by_pinyin
        results = await search_by_pinyin(q.upper(), limit=20)
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


@app.get("/api/v1/sector/{industry}/stocks")
async def get_sector_stocks(industry: str):
    from app.execution.feed.scheduler import get_rt_snapshot, _industry_cache
    from datetime import date as _date

    snap, snap_ts = get_rt_snapshot()
    snap_is_today = (
        snap and snap_ts > 0
        and _date.fromtimestamp(snap_ts) == _date.today()
    )

    loader = DataLoader()

    if snap_is_today:
        codes_in_sector = [c for c, ind in _industry_cache.items() if ind == industry]
        circ_mv_map = await loader.circ_mv_map(codes_in_sector) if codes_in_sector else {}
        stocks = []
        for code in codes_in_sector:
            row = snap.get(code, {})
            if row.get("close", 0) <= 0:
                continue
            stocks.append({
                "ts_code": code,
                "name": row.get("name", ""),
                "close": row.get("close"),
                "pct_chg": row.get("pct_chg"),
                "vol": row.get("vol"),
                "amount": row.get("amount"),
                "circ_mv": circ_mv_map.get(code),
            })
        if stocks:
            stocks.sort(key=lambda x: x.get("pct_chg", 0) or 0, reverse=True)
            return {"count": len(stocks), "data": stocks, "source": "realtime"}

    df = await loader.sector_stocks(industry)
    return {"count": len(df), "data": _df_to_records(df), "source": "daily"}


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
    loader = DataLoader()
    rt_domestic = get_rt_global_indices()
    df = await loader.global_indices()
    all_records = _df_to_records(df)
    if rt_domestic:
        rt_codes = {r["ts_code"] for r in rt_domestic}
        intl = [r for r in all_records if r.get("ts_code") not in rt_codes]
        merged = rt_domestic + intl
        return {"count": len(merged), "data": merged, "source": "realtime+daily"}
    return {"count": len(all_records), "data": all_records, "source": "daily"}


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


@app.get("/api/v1/market/news/classified")
async def get_classified_news(
    scope: str = Query("", description="macro/industry/stock/mixed, empty=all"),
    time_slot: str = Query("", description="pre_open/intraday/after_hours, empty=all"),
    sentiment: str = Query("", description="positive/negative/neutral, empty=all"),
    start_date: str = Query("", description="YYYY-MM-DD"),
    end_date: str = Query("", description="YYYY-MM-DD"),
    limit: int = Query(50, ge=1, le=500),
):
    """Get classified news with filters."""
    from app.core.database import async_session
    from sqlalchemy import text
    async with async_session() as session:
        wheres, params = [], {}
        if scope:
            wheres.append("nc.news_scope = :scope")
            params["scope"] = scope
        if time_slot:
            wheres.append("nc.time_slot = :time_slot")
            params["time_slot"] = time_slot
        if sentiment:
            wheres.append("nc.sentiment = :sentiment")
            params["sentiment"] = sentiment
        if start_date:
            wheres.append("n.datetime >= :start_dt")
            params["start_dt"] = start_date + " 00:00:00"
        if end_date:
            wheres.append("n.datetime <= :end_dt")
            params["end_dt"] = end_date + " 23:59:59"
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""

        sql = text(f"""
            SELECT n.id, n.datetime, n.content, n.channels, n.source,
                   nc.news_scope, nc.time_slot, nc.sentiment,
                   nc.related_codes, nc.related_industries, nc.keywords
            FROM stock_news n
            JOIN news_classified nc ON n.id = nc.news_id
            {where_sql}
            ORDER BY n.datetime DESC
            LIMIT :limit
        """)
        params["limit"] = limit
        result = await session.execute(sql, params)
        rows = result.fetchall()
    data = []
    for r in rows:
        data.append({
            "id": r[0], "datetime": r[1], "content": r[2],
            "channels": r[3], "source": r[4],
            "news_scope": r[5], "time_slot": r[6], "sentiment": r[7],
            "related_codes": r[8], "related_industries": r[9], "keywords": r[10],
        })
    return {"count": len(data), "data": data}


@app.get("/api/v1/market/anns/classified")
async def get_classified_anns(
    ann_type: str = Query("", description="earnings_forecast/holder_change/buyback/... empty=all"),
    sentiment: str = Query("", description="positive/negative/neutral, empty=all"),
    limit: int = Query(50, ge=1, le=500),
):
    """Get classified announcements with filters."""
    from app.core.database import async_session
    from sqlalchemy import text
    async with async_session() as session:
        wheres, params = [], {}
        if ann_type:
            wheres.append("ac.ann_type = :ann_type")
            params["ann_type"] = ann_type
        if sentiment:
            wheres.append("ac.sentiment = :sentiment")
            params["sentiment"] = sentiment
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        sql = text(f"""
            SELECT a.id, a.ts_code, a.ann_date, a.title, a.url,
                   ac.ann_type, ac.sentiment, ac.keywords
            FROM stock_anns a
            JOIN anns_classified ac ON a.id = ac.anns_id
            {where_sql}
            ORDER BY a.ann_date DESC, a.id DESC
            LIMIT :limit
        """)
        params["limit"] = limit
        result = await session.execute(sql, params)
        rows = result.fetchall()
    data = []
    for r in rows:
        data.append({
            "id": r[0], "ts_code": r[1], "ann_date": r[2], "title": r[3],
            "url": r[4], "ann_type": r[5], "sentiment": r[6], "keywords": r[7],
        })
    return {"count": len(data), "data": data}


@app.get("/api/v1/market/news/stats")
async def get_news_stats(
    start_date: str = Query("", description="YYYY-MM-DD"),
    end_date: str = Query("", description="YYYY-MM-DD"),
):
    """Get news classification statistics for dashboard."""
    from app.core.database import async_session
    from sqlalchemy import text
    async with async_session() as session:
        wheres: list[str] = []
        params: dict = {}
        if start_date:
            wheres.append("n.datetime >= :start_dt")
            params["start_dt"] = start_date + " 00:00:00"
        if end_date:
            wheres.append("n.datetime <= :end_dt")
            params["end_dt"] = end_date + " 23:59:59"
        where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        result = await session.execute(text(f"""
            SELECT nc.news_scope, nc.time_slot, nc.sentiment, COUNT(*)
            FROM news_classified nc
            JOIN stock_news n ON n.id = nc.news_id
            {where_sql}
            GROUP BY nc.news_scope, nc.time_slot, nc.sentiment
            ORDER BY COUNT(*) DESC
        """), params)
        rows = result.fetchall()
    stats = [
        {"scope": r[0], "time_slot": r[1], "sentiment": r[2], "count": r[3]}
        for r in rows
    ]
    return {"data": stats}


# ── Sentiment / Limit Board endpoints ─────────────────────────

@app.get("/api/v1/sentiment/limit-board")
async def get_limit_board(
    trade_date: str = Query("", description="YYYYMMDD, defaults to latest"),
    limit_type: str = Query("", description="U=涨停 D=跌停 Z=炸板, empty=all"),
):
    _LT_MAP = {"U": "涨停池", "D": "跌停池", "Z": "炸板池"}
    from app.core.database import async_session
    from sqlalchemy import text
    async with async_session() as session:
        if not trade_date:
            r = await session.execute(text(
                "SELECT trade_date FROM limit_list_ths ORDER BY trade_date DESC LIMIT 1"
            ))
            row = r.fetchone()
            trade_date = row[0] if row else ""
        if not trade_date:
            return {"count": 0, "data": [], "trade_date": ""}
        wheres = ["trade_date = :td"]
        params: dict = {"td": trade_date}
        if limit_type:
            db_lt = _LT_MAP.get(limit_type, limit_type)
            wheres.append("limit_type = :lt")
            params["lt"] = db_lt
        where_sql = " AND ".join(wheres)
        result = await session.execute(text(f"""
            SELECT ts_code, name, pct_chg, trade_date, limit_type,
                   limit_amount, turnover_rate, tag, status,
                   open_num, first_lu_time, last_lu_time
            FROM limit_list_ths WHERE {where_sql}
            ORDER BY first_lu_time ASC NULLS LAST
        """), params)
        rows = result.fetchall()
    cols = ["ts_code", "name", "pct_chg", "trade_date", "limit_type",
            "limit_amount", "turnover_rate", "tag", "status",
            "open_num", "first_lu_time", "last_lu_time"]
    data = [dict(zip(cols, r)) for r in rows]
    for d in data:
        for k, v in d.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                d[k] = None
    return {"count": len(data), "data": data, "trade_date": trade_date}


@app.get("/api/v1/sentiment/limit-step")
async def get_limit_step(
    trade_date: str = Query("", description="YYYYMMDD, defaults to latest"),
):
    from app.core.database import async_session
    from sqlalchemy import text
    async with async_session() as session:
        if not trade_date:
            r = await session.execute(text(
                "SELECT trade_date FROM limit_step ORDER BY trade_date DESC LIMIT 1"
            ))
            row = r.fetchone()
            trade_date = row[0] if row else ""
        if not trade_date:
            return {"count": 0, "data": [], "trade_date": ""}
        result = await session.execute(text("""
            SELECT ts_code, name, trade_date, nums
            FROM limit_step WHERE trade_date = :td
            ORDER BY CAST(nums AS INTEGER) DESC NULLS LAST
        """), {"td": trade_date})
        rows = result.fetchall()
    cols = ["ts_code", "name", "trade_date", "nums"]
    data = [dict(zip(cols, r)) for r in rows]
    return {"count": len(data), "data": data, "trade_date": trade_date}


@app.get("/api/v1/sentiment/dragon-tiger")
async def get_dragon_tiger(
    trade_date: str = Query("", description="YYYYMMDD, defaults to latest"),
    limit: int = Query(30, ge=1, le=100),
):
    from app.core.database import async_session
    from sqlalchemy import text
    async with async_session() as session:
        if not trade_date:
            r = await session.execute(text(
                "SELECT trade_date FROM top_list ORDER BY trade_date DESC LIMIT 1"
            ))
            row = r.fetchone()
            trade_date = row[0] if row else ""
        if not trade_date:
            return {"count": 0, "data": [], "trade_date": ""}
        result = await session.execute(text("""
            SELECT ts_code, name, trade_date, close, pct_change,
                   turnover_rate, amount, l_sell, l_buy, l_amount,
                   net_amount, net_rate, reason
            FROM top_list WHERE trade_date = :td
            ORDER BY amount DESC NULLS LAST
            LIMIT :lim
        """), {"td": trade_date, "lim": limit})
        rows = result.fetchall()
    cols = ["ts_code", "name", "trade_date", "close", "pct_change",
            "turnover_rate", "amount", "l_sell", "l_buy", "l_amount",
            "net_amount", "net_rate", "reason"]
    data = [dict(zip(cols, r)) for r in rows]
    for d in data:
        for k, v in d.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                d[k] = None
    return {"count": len(data), "data": data, "trade_date": trade_date}


@app.get("/api/v1/sentiment/hot-list")
async def get_hot_list(
    trade_date: str = Query("", description="YYYYMMDD, defaults to latest"),
    limit: int = Query(30, ge=1, le=100),
):
    from app.core.database import async_session
    from sqlalchemy import text
    async with async_session() as session:
        if not trade_date:
            r = await session.execute(text(
                "SELECT trade_date FROM dc_hot ORDER BY trade_date DESC LIMIT 1"
            ))
            row = r.fetchone()
            trade_date = row[0] if row else ""
        if not trade_date:
            return {"count": 0, "data": [], "trade_date": ""}
        result = await session.execute(text("""
            SELECT ts_code, ts_name, data_type, trade_date, pct_change,
                   rank, current_price
            FROM dc_hot WHERE trade_date = :td
            ORDER BY rank ASC NULLS LAST
            LIMIT :lim
        """), {"td": trade_date, "lim": limit})
        rows = result.fetchall()
    cols = ["ts_code", "ts_name", "data_type", "trade_date", "pct_change",
            "rank", "current_price"]
    data = [dict(zip(cols, r)) for r in rows]
    return {"count": len(data), "data": data, "trade_date": trade_date}


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
    import pandas as pd
    from datetime import timedelta

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    in_trading_hours = 9 <= now.hour < 16
    user_gave_start = bool(start)

    if not start:
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
        start = start_dt.strftime("%Y-%m-%d %H:%M:%S")

    loader = DataLoader()
    df = await loader.minutes(ts_code, start, end)

    if not user_gave_start and days == 1:
        from app.execution.feed.scheduler import get_intraday_minutes
        rt_bars = get_intraday_minutes(ts_code)
        if rt_bars:
            rt_df = pd.DataFrame(rt_bars)
            rt_df["trade_time"] = pd.to_datetime(rt_df["trade_time"])
            df = rt_df.sort_values("trade_time")

    if df.empty and not user_gave_start and days == 1:
        # Fallback 1: Tushare stk_mins (prioritize fresh data over stale DB)
        def _fetch_latest_mins():
            from app.research.data.tushare_service import TushareService
            svc = TushareService()
            for days_back in range(0, 8):
                d = now - timedelta(days=days_back)
                ds = d.strftime("%Y-%m-%d")
                result = svc.stk_mins(
                    ts_code=ts_code, freq="1min",
                    start_date=f"{ds} 09:00:00",
                    end_date=f"{ds} 15:30:00",
                )
                if not result.empty:
                    return result
            return pd.DataFrame()
        try:
            stk_df = await asyncio.to_thread(_fetch_latest_mins)
            if not stk_df.empty and "trade_time" in stk_df.columns:
                stk_df["trade_time"] = pd.to_datetime(stk_df["trade_time"])
                df = stk_df.sort_values("trade_time")
        except Exception:
            logger.warning("stk_mins fallback failed for %s", ts_code, exc_info=True)

    if df.empty and not user_gave_start and days == 1:
        # Fallback 2: DB wider range (30 days) — pick the most recent day
        fallback_start = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        df = await loader.minutes(ts_code, fallback_start, "")
        if not df.empty:
            latest_date = str(df["trade_time"].iloc[-1])[:10]
            df = df[df["trade_time"].astype(str).str[:10] == latest_date]

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
    from app.execution.feed.scheduler import get_rt_snapshot
    snap, snap_ts = get_rt_snapshot()
    if ts_code in snap:
        pre_close_val = snap[ts_code].get("pre_close")
    if not pre_close_val:
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


# ── Fundamental endpoints ─────────────────────────────────────

@app.get("/api/v1/fundamental/industries")
async def get_fundamental_industries():
    from app.core.database import async_session
    from app.shared.fundamental import industry_list
    async with async_session() as session:
        data = await industry_list(session)
    return {"data": data}


@app.get("/api/v1/fundamental/concepts")
async def get_fundamental_concepts():
    from app.core.database import async_session
    from app.shared.fundamental import concept_list_all
    async with async_session() as session:
        data = await concept_list_all(session)
    return {"data": data}


@app.get("/api/v1/fundamental/industry/{industry}")
async def get_industry_profile(industry: str):
    from app.core.database import async_session
    from app.shared.fundamental import industry_profile
    async with async_session() as session:
        data = await industry_profile(session, industry)
    return {"count": len(data), "data": data}


@app.get("/api/v1/fundamental/concept/{code}")
async def get_concept_stocks(code: str):
    from app.core.database import async_session
    from app.shared.fundamental import concept_stocks
    async with async_session() as session:
        data = await concept_stocks(session, code)
    return {"count": len(data), "data": data}


@app.get("/api/v1/fundamental/company/{ts_code}")
async def get_company_profile(ts_code: str):
    from app.core.database import async_session
    from app.shared.fundamental import company_profile
    async with async_session() as session:
        data = await company_profile(session, ts_code)
    return data


@app.get("/api/v1/fundamental/events")
async def get_event_calendar(
    start: str = Query("", description="YYYYMMDD"),
    end: str = Query("", description="YYYYMMDD"),
):
    from datetime import datetime, timedelta
    from app.core.database import async_session
    from app.shared.fundamental import event_calendar
    if not start:
        start = datetime.now().strftime("%Y%m%d")
    if not end:
        end = (datetime.now() + timedelta(days=30)).strftime("%Y%m%d")
    async with async_session() as session:
        data = await event_calendar(session, start, end)
    return data


# ── Sentiment analysis endpoints ──────────────────────────────

@app.get("/api/v1/sentiment/temperature")
async def get_market_temperature(
    trade_date: str = Query("", description="YYYYMMDD, defaults to latest"),
):
    from app.core.database import async_session
    from app.shared.sentiment import market_temperature
    async with async_session() as session:
        return await market_temperature(session, trade_date)


@app.get("/api/v1/sentiment/leaders")
async def get_board_leaders(
    trade_date: str = Query("", description="YYYYMMDD, defaults to latest"),
    concept: str = Query("", description="Filter by concept/tag keyword"),
):
    from app.core.database import async_session
    from app.shared.sentiment import board_leader
    async with async_session() as session:
        return await board_leader(session, trade_date, concept)


@app.get("/api/v1/sentiment/continuation/{ts_code}")
async def get_continuation_analysis(ts_code: str):
    from app.core.database import async_session
    from app.shared.sentiment import continuation_analysis
    async with async_session() as session:
        return await continuation_analysis(session, ts_code)


@app.get("/api/v1/sentiment/hot-money")
async def get_hot_money_signal(
    trade_date: str = Query("", description="YYYYMMDD, defaults to latest"),
):
    from app.core.database import async_session
    from app.shared.sentiment import hot_money_signal
    async with async_session() as session:
        return await hot_money_signal(session, trade_date)


@app.get("/api/v1/premarket/plan")
async def get_premarket_plan(
    date: str = Query("", description="YYYYMMDD, defaults to today"),
):
    from datetime import datetime
    from app.core.database import async_session
    from app.shared.premarket import generate_premarket_plan
    if not date:
        date = datetime.now().strftime("%Y%m%d")
    async with async_session() as session:
        return await generate_premarket_plan(session, date)


# ── Technical signal endpoints ────────────────────────────────

@app.get("/api/v1/tech/{ts_code}/volume")
async def get_volume_anomaly(ts_code: str, trade_date: str = Query("")):
    from app.core.database import async_session
    from app.shared.tech_signal import volume_anomaly
    async with async_session() as session:
        return await volume_anomaly(session, ts_code, trade_date)


@app.get("/api/v1/tech/{ts_code}/gaps")
async def get_gaps(ts_code: str, trade_date: str = Query("")):
    from app.core.database import async_session
    from app.shared.tech_signal import gap_analysis
    async with async_session() as session:
        return await gap_analysis(session, ts_code, trade_date)


@app.get("/api/v1/tech/{ts_code}/support-resistance")
async def get_support_resistance(ts_code: str, days: int = Query(60, ge=10, le=250)):
    from app.core.database import async_session
    from app.shared.tech_signal import support_resistance
    async with async_session() as session:
        return await support_resistance(session, ts_code, days)


@app.get("/api/v1/tech/{ts_code}/risk-check")
async def get_tech_risk_check(ts_code: str, trade_date: str = Query("")):
    from app.core.database import async_session
    from app.shared.tech_signal import risk_check
    async with async_session() as session:
        return await risk_check(session, ts_code, trade_date)


@app.get("/api/v1/risk/alerts")
async def get_risk_alerts():
    from app.core.database import async_session
    from app.shared.risk_alerts import generate_risk_alerts
    async with async_session() as session:
        return await generate_risk_alerts(session)
