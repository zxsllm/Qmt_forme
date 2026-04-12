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
from app.shared.review_api import router as review_router
from app.shared.plan_api import router as plan_router
from app.shared.stock_scorer import scorer_router
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
app.include_router(review_router)
app.include_router(plan_router)
app.include_router(scorer_router)


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


@app.get("/api/v1/system/data-health")
async def data_health():
    from app.core.database import async_session
    from app.shared.data_health import run_health_check
    async with async_session() as session:
        return await run_health_check(session)


@app.get("/api/v1/stock/search")
async def search_stocks(
    q: str = Query("", min_length=1, description="code, name or pinyin"),
    include_index: bool = Query(False, description="also search indices"),
):
    """Search stocks (and optionally indices) by ts_code, name prefix, or pinyin."""
    if q.isascii() and q.replace(" ", "").isalpha():
        from app.shared.data.pinyin_cache import search_by_pinyin
        results = await search_by_pinyin(q.upper(), limit=20)
        if results:
            if include_index:
                loader = DataLoader()
                idx_df = await loader.search_index(q, limit=10)
                idx_data = [{"ts_code": r["ts_code"], "name": r["name"],
                             "industry": r.get("category", ""), "list_status": "INDEX",
                             "type": "index"} for r in _df_to_records(idx_df)]
                return {"count": len(results) + len(idx_data),
                        "data": results + idx_data}
            return {"count": len(results), "data": results}
    loader = DataLoader()
    df = await loader.search_stocks(q, limit=20)
    data = _df_to_records(df)
    if include_index:
        idx_df = await loader.search_index(q, limit=10)
        idx_data = [{"ts_code": r["ts_code"], "name": r["name"],
                     "industry": r.get("category", ""), "list_status": "INDEX",
                     "type": "index"} for r in _df_to_records(idx_df)]
        data = data + idx_data
    return {"count": len(data), "data": data}


@app.get("/api/v1/stock/{ts_code}/daily")
async def get_stock_daily(
    ts_code: str,
    start: str = Query("", description="YYYYMMDD"),
    end: str = Query("", description="YYYYMMDD"),
):
    from app.shared.data.data_loader import is_index_code
    loader = DataLoader()
    df = await loader.universal_daily(ts_code, start, end)
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
                "open": rt.get("open", rt["close"]),
                "high": rt.get("high", rt["close"]),
                "low": rt.get("low", rt["close"]),
                "close": rt["close"],
                "vol": rt.get("vol", 0),
                "amount": rt.get("amount", 0),
                "pre_close": rt.get("pre_close", 0),
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
    trade_date: str = Query("", description="YYYYMMDD, defaults to today"),
    limit_type: str = Query("", description="U=涨停 D=跌停 Z=炸板, empty=all"),
):
    from datetime import datetime as _dt
    _LT_MAP = {"U": "涨停池", "D": "跌停池", "Z": "炸板池"}
    today = _dt.now().strftime("%Y%m%d")
    if not trade_date:
        trade_date = today

    from app.core.database import async_session
    from sqlalchemy import text
    async with async_session() as session:
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

    if not data and trade_date == today:
        try:
            from app.execution.feed.scheduler import get_rt_snapshot
            snap, _ = get_rt_snapshot()
            if snap:
                for v in snap.values():
                    pct = v.get("pct_chg", 0)
                    code = v.get("ts_code", "")
                    name = v.get("name", "")
                    if not code or not pct:
                        continue
                    prefix = code.split(".")[0]
                    is_gem_star = prefix.startswith("3") or prefix.startswith("68")
                    is_bj = code.endswith(".BJ")
                    is_st = "ST" in name.upper()
                    thresh = 4.8 if is_st else (29.5 if is_bj else (19.5 if is_gem_star else 9.8))
                    lt = None
                    if pct >= thresh:
                        lt = "涨停池"
                    elif pct <= -thresh:
                        lt = "跌停池"
                    if lt is None:
                        continue
                    if limit_type:
                        db_lt = _LT_MAP.get(limit_type, limit_type)
                        if lt != db_lt:
                            continue
                    data.append({
                        "ts_code": code, "name": name, "pct_chg": round(pct, 2),
                        "trade_date": today, "limit_type": lt,
                        "limit_amount": v.get("amount"), "turnover_rate": None,
                        "tag": "", "status": "实时",
                        "open_num": None, "first_lu_time": None, "last_lu_time": None,
                    })
                data.sort(key=lambda x: -(x.get("pct_chg") or 0))
        except Exception:
            pass

    for d in data:
        for k, v in d.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                d[k] = None
    return {"count": len(data), "data": data, "trade_date": trade_date}


@app.get("/api/v1/sentiment/limit-step")
async def get_limit_step(
    trade_date: str = Query("", description="YYYYMMDD, defaults to today"),
):
    from datetime import datetime as _dt
    from app.core.database import async_session
    from sqlalchemy import text
    if not trade_date:
        trade_date = _dt.now().strftime("%Y%m%d")
    async with async_session() as session:
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
    trade_date: str = Query("", description="YYYYMMDD, defaults to today"),
    limit: int = Query(30, ge=1, le=200),
):
    from datetime import datetime as _dt
    from app.core.database import async_session
    from sqlalchemy import text
    if not trade_date:
        trade_date = _dt.now().strftime("%Y%m%d")
    async with async_session() as session:
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


@app.get("/api/v1/sentiment/dragon-tiger-seats")
async def get_dragon_tiger_seats(
    ts_code: str = Query(..., description="Stock code"),
    trade_date: str = Query(..., description="YYYYMMDD"),
):
    """Seat detail (buy/sell breakdown) for a single stock on dragon-tiger list."""
    from app.core.database import async_session
    from sqlalchemy import text

    async with async_session() as session:
        result = await session.execute(text("""
            SELECT exalter, side, buy, sell, net_buy
            FROM top_inst
            WHERE ts_code = :code AND trade_date = :td
            ORDER BY side, ABS(net_buy) DESC
        """), {"code": ts_code, "td": trade_date})
        rows = result.fetchall()

        # 游资匹配: hm_detail 按 (trade_date, ts_code) 查出所有游资交易记录
        hm_r = await session.execute(text("""
            SELECT hm_name, buy_amount, sell_amount
            FROM hm_detail
            WHERE ts_code = :code AND trade_date = :td
        """), {"code": ts_code, "td": trade_date})
        hm_rows = hm_r.fetchall()

    # 构建游资金额索引，按买入金额匹配（容差 0.5%）
    hm_map: list[tuple[str, float, float]] = [
        (name, buy_amt or 0, sell_amt or 0) for name, buy_amt, sell_amt in hm_rows
    ]
    used_hm: set[str] = set()

    def match_hm(buy: float, sell: float) -> str | None:
        """尝试通过金额匹配游资名称"""
        for hm_name, hm_buy, hm_sell in hm_map:
            if hm_name in used_hm:
                continue
            if hm_buy > 0 and buy > 0 and abs(hm_buy - buy) / max(hm_buy, 1) < 0.005:
                used_hm.add(hm_name)
                return hm_name
            if hm_sell > 0 and sell > 0 and abs(hm_sell - sell) / max(hm_sell, 1) < 0.005:
                used_hm.add(hm_name)
                return hm_name
        return None

    buy_seats, sell_seats = [], []
    for row in rows:
        exalter, side, buy, sell, net_buy = row
        hm_name = match_hm(buy or 0, sell or 0)
        seat_type = "机构" if ("机构" in (exalter or "") or "专用" in (exalter or "")) else \
                    "游资" if hm_name else "券商"
        rec = {"exalter": exalter, "buy": buy, "sell": sell, "net_buy": net_buy,
               "seat_type": seat_type, "hm_name": hm_name}
        if side == "0":
            buy_seats.append(rec)
        else:
            sell_seats.append(rec)

    return {"buy_seats": buy_seats, "sell_seats": sell_seats}


@app.get("/api/v1/sentiment/hot-list")
async def get_hot_list(
    trade_date: str = Query("", description="YYYYMMDD, defaults to today"),
    limit: int = Query(30, ge=1, le=100),
):
    from datetime import datetime as _dt
    from app.core.database import async_session
    from sqlalchemy import text
    if not trade_date:
        trade_date = _dt.now().strftime("%Y%m%d")
    async with async_session() as session:
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
    df = await loader.universal_weekly(ts_code, start, end)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/stock/{ts_code}/monthly")
async def get_stock_monthly(
    ts_code: str,
    start: str = Query("", description="YYYYMMDD"),
    end: str = Query("", description="YYYYMMDD"),
):
    loader = DataLoader()
    df = await loader.universal_monthly(ts_code, start, end)
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
    from app.shared.data.data_loader import is_index_code

    now = datetime.now()
    user_gave_start = bool(start)
    _is_idx = is_index_code(ts_code)

    if not start:
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
        start = start_dt.strftime("%Y-%m-%d %H:%M:%S")

    # Fast path: in-memory rt_k data (works for both stocks and indices)
    has_rt_data = False
    df = pd.DataFrame()
    if not user_gave_start and days == 1:
        from app.execution.feed.scheduler import get_intraday_minutes
        rt_bars = get_intraday_minutes(ts_code)
        if rt_bars and len(rt_bars) >= 10:
            rt_df = pd.DataFrame(rt_bars)
            rt_df["trade_time"] = pd.to_datetime(rt_df["trade_time"])
            df = rt_df.sort_values("trade_time")
            has_rt_data = True

    # Slow path: DB (stocks only) + Tushare fallbacks
    if not has_rt_data and not _is_idx:
        loader = DataLoader()
        df = await loader.minutes(ts_code, start, end)

    if df.empty and not user_gave_start and days == 1 and not has_rt_data:
        def _fetch_latest_mins():
            from app.research.data.tushare_service import TushareService
            svc = TushareService()
            api_fn = svc.idx_mins if _is_idx else svc.stk_mins
            for days_back in range(0, 8):
                d = now - timedelta(days=days_back)
                ds = d.strftime("%Y-%m-%d")
                result = api_fn(
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
            logger.warning("mins fallback failed for %s", ts_code, exc_info=True)

    if df.empty and not user_gave_start and days == 1 and not _is_idx:
        loader = DataLoader()
        fallback_start = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        df = await loader.minutes(ts_code, fallback_start, "")
        if not df.empty:
            latest_date = str(df["trade_time"].iloc[-1])[:10]
            df = df[df["trade_time"].astype(str).str[:10] == latest_date]

    # Auction data: stocks only (indices have no auction)
    start_date_str = start[:10].replace("-", "") if start else ""
    if not has_rt_data and not _is_idx:
        loader = DataLoader()
        auction_df = await loader._query(
            "SELECT trade_date, price, vol, amount FROM stk_auction "
            "WHERE ts_code = :c AND trade_date >= :s ORDER BY trade_date",
            {"c": ts_code, "s": start_date_str},
        )
        auc_o_df = pd.DataFrame()
        def _fetch_auction_o():
            from app.research.data.tushare_service import TushareService
            svc = TushareService()
            return svc.stk_auction_o(ts_code=ts_code, start_date=start_date_str)
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
    if not pre_close_val and not _is_idx:
        loader = DataLoader()
        auc_row = await loader._query(
            "SELECT pre_close FROM stk_auction WHERE ts_code = :c "
            "ORDER BY trade_date DESC LIMIT 1",
            {"c": ts_code},
        )
        if not auc_row.empty:
            pre_close_val = float(auc_row["pre_close"].iloc[0])
    if not pre_close_val and _is_idx:
        loader = DataLoader()
        idx_row = await loader._query(
            "SELECT pre_close FROM index_daily WHERE ts_code = :c "
            "ORDER BY trade_date DESC LIMIT 1",
            {"c": ts_code},
        )
        if not idx_row.empty:
            pre_close_val = float(idx_row["pre_close"].iloc[0])

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


# ── Phase 4.9: Index K-line (weekly/monthly) + search + 8 new data APIs ──


@app.get("/api/v1/index/{ts_code}/weekly")
async def get_index_weekly(
    ts_code: str,
    start: str = Query("", description="YYYYMMDD"),
    end: str = Query("", description="YYYYMMDD"),
):
    loader = DataLoader()
    df = await loader.index_weekly(ts_code, start, end)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/index/{ts_code}/monthly")
async def get_index_monthly(
    ts_code: str,
    start: str = Query("", description="YYYYMMDD"),
    end: str = Query("", description="YYYYMMDD"),
):
    loader = DataLoader()
    df = await loader.index_monthly(ts_code, start, end)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/index/search")
async def search_index(q: str = Query("", min_length=1)):
    loader = DataLoader()
    df = await loader.search_index(q, limit=20)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/stock/{ts_code}/share-float")
async def get_share_float(
    ts_code: str,
    start: str = Query("", description="YYYYMMDD float_date start"),
    end: str = Query("", description="YYYYMMDD float_date end"),
):
    loader = DataLoader()
    sql = "SELECT * FROM share_float WHERE ts_code = :c"
    params: dict = {"c": ts_code}
    if start:
        sql += " AND float_date >= :s"
        params["s"] = start
    if end:
        sql += " AND float_date <= :e"
        params["e"] = end
    sql += " ORDER BY float_date DESC LIMIT 100"
    df = await loader._query(sql, params)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/stock/{ts_code}/holdertrade")
async def get_holdertrade(
    ts_code: str,
    start: str = Query("", description="YYYYMMDD ann_date start"),
    end: str = Query("", description="YYYYMMDD ann_date end"),
):
    loader = DataLoader()
    sql = "SELECT * FROM stk_holdertrade WHERE ts_code = :c"
    params: dict = {"c": ts_code}
    if start:
        sql += " AND ann_date >= :s"
        params["s"] = start
    if end:
        sql += " AND ann_date <= :e"
        params["e"] = end
    sql += " ORDER BY ann_date DESC LIMIT 100"
    df = await loader._query(sql, params)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/market/margin")
async def get_margin(
    start: str = Query("", description="YYYYMMDD"),
    end: str = Query("", description="YYYYMMDD"),
    days: int = Query(30, ge=1, le=365),
):
    loader = DataLoader()
    sql = "SELECT * FROM margin WHERE 1=1"
    params: dict = {}
    if start:
        sql += " AND trade_date >= :s"
        params["s"] = start
    if end:
        sql += " AND trade_date <= :e"
        params["e"] = end
    if not start and not end:
        sql += " AND trade_date >= :s"
        from datetime import datetime, timedelta
        params["s"] = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    sql += " ORDER BY trade_date DESC, exchange_id LIMIT 1000"
    df = await loader._query(sql, params)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/market/top-inst")
async def get_top_inst(
    trade_date: str = Query("", description="YYYYMMDD"),
    ts_code: str = Query("", description="individual stock filter"),
):
    loader = DataLoader()
    sql = "SELECT * FROM top_inst WHERE 1=1"
    params: dict = {}
    if trade_date:
        sql += " AND trade_date = :td"
        params["td"] = trade_date
    elif ts_code:
        sql += " AND ts_code = :c"
        params["c"] = ts_code
    else:
        sql += " AND trade_date = (SELECT MAX(trade_date) FROM top_inst)"
    if ts_code and trade_date:
        sql += " AND ts_code = :c"
        params["c"] = ts_code
    sql += " ORDER BY ABS(net_buy) DESC LIMIT 200"
    df = await loader._query(sql, params)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/index/{ts_code}/valuation")
async def get_index_valuation(
    ts_code: str,
    start: str = Query("", description="YYYYMMDD"),
    end: str = Query("", description="YYYYMMDD"),
    days: int = Query(60, ge=1, le=365),
):
    loader = DataLoader()
    sql = "SELECT * FROM index_dailybasic WHERE ts_code = :c"
    params: dict = {"c": ts_code}
    if start:
        sql += " AND trade_date >= :s"
        params["s"] = start
    if end:
        sql += " AND trade_date <= :e"
        params["e"] = end
    if not start and not end:
        from datetime import datetime, timedelta
        sql += " AND trade_date >= :s"
        params["s"] = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    sql += " ORDER BY trade_date LIMIT 500"
    df = await loader._query(sql, params)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/stock/{ts_code}/top10-holders")
async def get_top10_holders(
    ts_code: str,
    periods: int = Query(4, ge=1, le=12, description="recent N reporting periods"),
):
    loader = DataLoader()
    sql = (
        "SELECT * FROM top10_floatholders WHERE ts_code = :c "
        "AND end_date IN ("
        "  SELECT DISTINCT end_date FROM top10_floatholders "
        "  WHERE ts_code = :c ORDER BY end_date DESC LIMIT :n"
        ") ORDER BY end_date DESC, hold_amount DESC"
    )
    df = await loader._query(sql, {"c": ts_code, "n": periods})
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/stock/{ts_code}/holder-number")
async def get_holder_number(
    ts_code: str,
    start: str = Query("", description="YYYYMMDD"),
    end: str = Query("", description="YYYYMMDD"),
):
    loader = DataLoader()
    sql = "SELECT * FROM stk_holdernumber WHERE ts_code = :c"
    params: dict = {"c": ts_code}
    if start:
        sql += " AND end_date >= :s"
        params["s"] = start
    if end:
        sql += " AND end_date <= :e"
        params["e"] = end
    sql += " ORDER BY end_date DESC LIMIT 50"
    df = await loader._query(sql, params)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/market/share-float-upcoming")
async def get_upcoming_share_float(days: int = Query(30, ge=1, le=90)):
    """Upcoming restricted share unlocks in the next N days."""
    from datetime import datetime, timedelta
    loader = DataLoader()
    today = datetime.now().strftime("%Y%m%d")
    end = (datetime.now() + timedelta(days=days)).strftime("%Y%m%d")
    sql = (
        "SELECT sf.*, sb.name FROM share_float sf "
        "LEFT JOIN stock_basic sb ON sf.ts_code = sb.ts_code "
        "WHERE sf.float_date >= :s AND sf.float_date <= :e "
        "ORDER BY sf.float_date, sf.float_share DESC LIMIT 500"
    )
    df = await loader._query(sql, {"s": today, "e": end})
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/market/holdertrade-recent")
async def get_recent_holdertrade(
    days: int = Query(7, ge=1, le=30),
    trade_type: str = Query("", description="IN=increase, DE=decrease"),
):
    """Recent shareholder increase/decrease across all stocks."""
    from datetime import datetime, timedelta
    loader = DataLoader()
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    sql = (
        "SELECT ht.*, sb.name FROM stk_holdertrade ht "
        "LEFT JOIN stock_basic sb ON ht.ts_code = sb.ts_code "
        "WHERE ht.ann_date >= :s"
    )
    params: dict = {"s": start}
    if trade_type:
        sql += " AND ht.in_de = :tt"
        params["tt"] = trade_type
    sql += " ORDER BY ht.ann_date DESC, ABS(ht.change_vol) DESC LIMIT 200"
    df = await loader._query(sql, params)
    return {"count": len(df), "data": _df_to_records(df)}


@app.get("/api/v1/market/st-predict")
async def get_st_predict():
    """ST prediction based on annual report / forecast data (dynamic year).

    Rules per exchange listing rules (2025 revision):
      沪深主板 9.3.2/9.3.1: 利润孰低<0 AND 营收<3亿, OR 净资产<0
      创业板 10.3.1 / 科创板 12.4.2: 同上, 但营收门槛 1亿
    Two groups:
      A) 年报已发 → 用实际数据判断
      B) 年报未发 → 用续亏/首亏预告 + 上年营收推算
    """
    from sqlalchemy import text
    from app.core.database import async_session

    # 动态计算报告期年份: 当前年份-1 = 年报对应年度
    report_year = datetime.now().year - 1
    prev_year = report_year - 1
    report_end = f"{report_year}1231"
    prev_end = f"{prev_year}1231"
    cal_start = f"{report_year + 1}0101"

    async with async_session() as session:
        r = await session.execute(text("""
            WITH
            -- ═══ 基础数据 ═══
            -- A: 年报已发 (实际数据)
            published AS (
                SELECT DISTINCT ON (ts_code) ts_code, n_income_attr_p, revenue, total_profit
                FROM income
                WHERE end_date = :report_end AND report_type = '1'
                ORDER BY ts_code, ann_date DESC
            ),
            -- B: 业绩预告 (续亏/首亏 → 预测净利润为负)
            forecast_bad AS (
                SELECT DISTINCT ON (ts_code) ts_code, type, net_profit_min,
                       net_profit_max, ann_date
                FROM forecast
                WHERE end_date = :report_end AND type IN ('续亏', '首亏')
                ORDER BY ts_code, ann_date DESC
            ),
            -- 好预告 → 排除
            forecast_good AS (
                SELECT DISTINCT ts_code FROM forecast
                WHERE end_date = :report_end AND type IN ('扭亏', '预增', '续盈', '略增')
            ),
            -- 上年营收 (对未发年报的推算参考)
            income_prev AS (
                SELECT DISTINCT ON (ts_code) ts_code, revenue
                FROM income
                WHERE end_date = :prev_end AND report_type = '1'
                ORDER BY ts_code, ann_date DESC
            ),
            -- 最新财务指标 (取bps, 扣非)
            fina_latest AS (
                SELECT DISTINCT ON (ts_code) ts_code, bps, profit_dedt
                FROM fina_indicator
                ORDER BY ts_code, end_date DESC, ann_date DESC
            ),
            -- 年报对应的fina (取扣非)
            fina_report AS (
                SELECT DISTINCT ON (ts_code) ts_code, bps, profit_dedt
                FROM fina_indicator
                WHERE end_date = :report_end
                ORDER BY ts_code, ann_date DESC
            ),
            -- 风险提示公告次数
            risk_ann_count AS (
                SELECT ts_code, count(*) AS warn_count
                FROM stock_anns
                WHERE title LIKE '%%可能被实施%%风险警示%%'
                   OR title LIKE '%%可能被实施%%退市风险%%'
                GROUP BY ts_code
            ),
            disc AS (
                SELECT ts_code, actual_date, pre_date
                FROM disclosure_date WHERE end_date = :report_end
            ),
            current_st AS (
                SELECT DISTINCT ts_code FROM stock_st
                WHERE trade_date = (SELECT MAX(trade_date) FROM stock_st)
            ),
            trade_days AS (
                SELECT cal_date FROM trade_cal
                WHERE is_open = 1 AND exchange = 'SSE'
                      AND cal_date >= :cal_start
                ORDER BY cal_date
            ),

            -- ═══ Group A: 年报已发，触发ST条件 ═══
            group_a AS (
                SELECT p.ts_code,
                       p.n_income_attr_p AS profit, p.revenue, p.total_profit,
                       COALESCE(fr.bps, fl.bps) AS bps,
                       COALESCE(fr.profit_dedt, fl.profit_dedt) AS profit_dedt,
                       fb.type AS fc_type, fb.net_profit_min, fb.net_profit_max,
                       fb.ann_date AS forecast_ann_date,
                       'published' AS src
                FROM published p
                LEFT JOIN fina_report fr ON p.ts_code = fr.ts_code
                LEFT JOIN fina_latest fl ON p.ts_code = fl.ts_code
                LEFT JOIN forecast_bad fb ON p.ts_code = fb.ts_code
                WHERE
                  (  -- 规则1: 利润孰低<0 AND 营收<门槛
                    LEAST(
                        COALESCE(p.total_profit, p.n_income_attr_p),
                        p.n_income_attr_p,
                        COALESCE(fr.profit_dedt, fl.profit_dedt, p.n_income_attr_p)
                    ) < 0
                    AND p.revenue < CASE
                        WHEN p.ts_code LIKE '3%%' OR p.ts_code LIKE '688%%' OR p.ts_code LIKE '%%.BJ' THEN 1e8
                        ELSE 3e8 END
                  )
                  OR -- 规则2: 净资产<0
                  (COALESCE(fr.bps, fl.bps) IS NOT NULL AND COALESCE(fr.bps, fl.bps) < 0)
            ),

            -- ═══ Group B: 年报未发，预告续亏/首亏 + 上年营收推算 ═══
            group_b AS (
                SELECT fb.ts_code,
                       NULL::float8 AS profit, ip.revenue, NULL::float8 AS total_profit,
                       fl.bps, fl.profit_dedt,
                       fb.type AS fc_type, fb.net_profit_min, fb.net_profit_max,
                       fb.ann_date AS forecast_ann_date,
                       'forecast' AS src
                FROM forecast_bad fb
                LEFT JOIN income_prev ip ON fb.ts_code = ip.ts_code
                LEFT JOIN fina_latest fl ON fb.ts_code = fl.ts_code
                WHERE NOT EXISTS (SELECT 1 FROM published WHERE ts_code = fb.ts_code)
                  AND (
                    -- 续亏/首亏 + 上年营收低于门槛 → 推测不达标
                    ip.revenue < CASE
                        WHEN fb.ts_code LIKE '3%%' OR fb.ts_code LIKE '688%%' OR fb.ts_code LIKE '%%.BJ' THEN 1e8
                        ELSE 3e8 END
                    -- 或净资产为负
                    OR (fl.bps IS NOT NULL AND fl.bps < 0)
                  )
            ),

            candidates AS (
                SELECT * FROM group_a
                UNION ALL
                SELECT * FROM group_b
            )
            SELECT
                c.ts_code, b.name, b.market,
                c.profit, c.revenue, c.total_profit, c.bps, c.profit_dedt,
                c.fc_type, c.net_profit_min, c.net_profit_max,
                c.forecast_ann_date, c.src,
                d.pre_date, d.actual_date,
                (SELECT MIN(cal_date) FROM trade_days
                 WHERE cal_date > d.pre_date) AS predicted_st_date,
                COALESCE(ra.warn_count, 0) AS warn_count
            FROM candidates c
            JOIN stock_basic b ON c.ts_code = b.ts_code
            LEFT JOIN disc d ON c.ts_code = d.ts_code
            LEFT JOIN risk_ann_count ra ON c.ts_code = ra.ts_code
            WHERE NOT EXISTS (SELECT 1 FROM current_st WHERE ts_code = c.ts_code)
              AND NOT EXISTS (SELECT 1 FROM forecast_good WHERE ts_code = c.ts_code)
              AND b.name NOT LIKE '%%-U' AND b.name NOT LIKE '%%-U_'
            ORDER BY d.pre_date ASC NULLS LAST
        """), {"report_end": report_end, "prev_end": prev_end, "cal_start": cal_start})
        rows = r.fetchall()
        cols = r.keys()

        items = []
        seen = set()
        for row in rows:
            rec = dict(zip(cols, row))
            if rec["ts_code"] in seen:
                continue
            seen.add(rec["ts_code"])
            for k, v in rec.items():
                if isinstance(v, float) and (v != v):
                    rec[k] = None
            rec["disclosure_date"] = rec["pre_date"] or ""

            # ── 生成预测理由 ──
            profit = rec.get("profit")
            rev = rec.get("revenue")
            tp = rec.get("total_profit")
            bps = rec.get("bps")
            deducted = rec.get("profit_dedt")
            mn = rec.get("net_profit_min")
            mx = rec.get("net_profit_max")
            src = rec.get("src")
            code = rec["ts_code"]
            is_small = code.startswith("3") or code.startswith("688") or code.endswith(".BJ")
            threshold = 1e8 if is_small else 3e8
            label = "1亿" if is_small else "3亿"

            rules = []

            if src == "published":
                # 已发年报 → 用实际数据
                profit_vals = [v for v in [tp, profit, deducted] if v is not None]
                worst = min(profit_vals) if profit_vals else None
                if worst is not None and worst < 0 and rev is not None and rev < threshold:
                    rules.append(f"{report_year}年报: 利润孰低为负且营收{rev/1e8:.2f}亿<{label}(9.3.2①)")
                if bps is not None and bps < 0:
                    rules.append(f"{report_year}年报: 净资产{bps:.2f}元<0(9.3.2②)")
            else:
                # 未发年报 → 预告+推算
                fc_type = rec.get("fc_type") or "续亏"
                if rev is not None and rev < threshold:
                    rules.append(f"预告{fc_type}+{prev_year}营收{rev/1e8:.2f}亿<{label}，预测触发*ST(9.3.2①)")
                if bps is not None and bps < 0:
                    rules.append(f"最新净资产{bps:.2f}元<0，预测触发*ST(9.3.2②)")
                if mn is not None:
                    # net_profit_min/max 单位: 万元
                    rules.append(f"预告净利润{mn:.0f}~{(mx or mn):.0f}万")

            if not rules:
                rules.append("财务指标异常")
            rec["reason"] = "；".join(rules)

            # net_profit_min/max: 万元 → 元 (统一单位给前端 fmtWan)
            if rec.get("net_profit_min") is not None:
                rec["net_profit_min"] = rec["net_profit_min"] * 1e4
            if rec.get("net_profit_max") is not None:
                rec["net_profit_max"] = rec["net_profit_max"] * 1e4

            for k in ("market", "total_profit", "profit_dedt",
                       "src", "actual_date", "fc_type"):
                rec.pop(k, None)

            items.append(rec)

        return {"count": len(items), "data": items, "report_year": report_year}


# ── Monitor: Index-Sector Resonance ──────────────────────────────

@app.get("/api/v1/monitor/index-sector-resonance")
async def get_index_sector_resonance(
    index_code: str = Query("000001.SH", description="Index ts_code"),
    days: int = Query(20, ge=5, le=60, description="Lookback days"),
    level: str = Query("L1", description="SW level: L1/L2/L3/all"),
):
    """Pearson correlation of each SW sector with a major index over recent N days."""
    from sqlalchemy import text as sa_text
    from app.core.database import async_session

    async with async_session() as sess:
        idx_rows = (await sess.execute(sa_text("""
            SELECT trade_date, pct_chg FROM index_daily
            WHERE ts_code = :code
            ORDER BY trade_date DESC LIMIT :n
        """), {"code": index_code, "n": days})).fetchall()

        if len(idx_rows) < 5:
            return {"index_code": index_code, "days": days, "sectors": []}

        dates = [r[0] for r in idx_rows]
        idx_map = {r[0]: float(r[1] or 0) for r in idx_rows}
        min_date, max_date = min(dates), max(dates)

        if level != "all":
            l1_codes = (await sess.execute(sa_text(
                "SELECT index_code FROM index_classify WHERE src='SW2021' AND level = :lv"
            ), {"lv": level})).fetchall()
            allowed = {r[0] for r in l1_codes}
        else:
            allowed = None

        sw_rows = (await sess.execute(sa_text("""
            SELECT ts_code, name, trade_date, pct_change, close, vol
            FROM sw_daily
            WHERE trade_date >= :d0 AND trade_date <= :d1
            ORDER BY ts_code, trade_date
        """), {"d0": min_date, "d1": max_date})).fetchall()

    from collections import defaultdict
    sector_data: dict[str, dict] = {}
    sector_daily: dict[str, list[tuple[str, float]]] = defaultdict(list)

    for r in sw_rows:
        code, name, td, pct, close, vol = r
        if allowed is not None and code not in allowed:
            continue
        if code not in sector_data:
            sector_data[code] = {"name": name, "close": None, "vol": None}
        sector_data[code]["close"] = float(close) if close else sector_data[code]["close"]
        sector_data[code]["vol"] = float(vol) if vol else sector_data[code]["vol"]
        sector_daily[code].append((td, float(pct or 0)))

    import math

    def pearson(xs: list[float], ys: list[float]) -> float:
        n = len(xs)
        if n < 3:
            return 0.0
        mx = sum(xs) / n
        my = sum(ys) / n
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
        sy = math.sqrt(sum((y - my) ** 2 for y in ys))
        if sx == 0 or sy == 0:
            return 0.0
        return sxy / (sx * sy)

    sectors = []
    for code, pairs in sector_daily.items():
        td_map = {td: pct for td, pct in pairs}
        common_dates = [d for d in dates if d in td_map]
        if len(common_dates) < 5:
            continue

        idx_vals = [idx_map[d] for d in common_dates]
        sec_vals = [td_map[d] for d in common_dates]

        corr = pearson(idx_vals, sec_vals)
        cum_return = sum(sec_vals)
        info = sector_data.get(code, {})
        latest_pct = pairs[-1][1] if pairs else 0

        sectors.append({
            "ts_code": code,
            "name": info.get("name", ""),
            "correlation": round(corr, 4),
            "cum_return": round(cum_return, 2),
            "latest_pct": round(latest_pct, 2),
            "close": info.get("close"),
            "days_matched": len(common_dates),
        })

    sectors.sort(key=lambda s: abs(s["correlation"]), reverse=True)

    return {
        "index_code": index_code,
        "days": days,
        "total_dates": len(dates),
        "sectors": sectors,
    }


# ── Monitor: Real-time snapshot ──────────────────────────────────

@app.get("/api/v1/monitor/snapshot")
async def get_monitor_snapshot():
    """Real-time intraday monitoring: index anomalies + sector attribution."""
    from app.execution.feed.monitor_engine import monitor_engine
    return monitor_engine.get_snapshot()
