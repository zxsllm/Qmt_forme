from fastapi import FastAPI, Query

from app.shared.data import DataLoader


import math


def _df_to_records(df):
    """Convert DataFrame to JSON-safe records, replacing NaN/Inf with None."""
    records = df.to_dict(orient="records")
    for row in records:
        for k, v in row.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                row[k] = None
    return records


app = FastAPI(title="AI Trade", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok", "phase": "1-data"}


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
