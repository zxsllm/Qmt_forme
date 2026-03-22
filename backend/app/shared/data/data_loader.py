"""
DataLoader: unified read-only data access layer.

All strategy, backtest, and UI code should read market data through this
module instead of writing raw SQL. Async-first, returns pandas DataFrames.
"""

from datetime import datetime

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session


class DataLoader:
    """Async data access facade backed by PostgreSQL."""

    def __init__(self, session: AsyncSession | None = None):
        self._external_session = session

    async def _get_session(self) -> AsyncSession:
        if self._external_session:
            return self._external_session
        return async_session()

    async def _query(self, sql: str, params: dict | None = None) -> pd.DataFrame:
        session = await self._get_session()
        try:
            result = await session.execute(text(sql), params or {})
            rows = result.fetchall()
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame(rows, columns=result.keys())
        finally:
            if not self._external_session:
                await session.close()

    # ── Stock universe ──────────────────────────────────────────────

    async def stock_list(self, status: str = "L") -> pd.DataFrame:
        return await self._query(
            "SELECT * FROM stock_basic WHERE list_status = :s ORDER BY ts_code",
            {"s": status},
        )

    async def search_stocks(self, q: str, limit: int = 20) -> pd.DataFrame:
        """Search stocks by ts_code or name prefix (for autocomplete)."""
        like = f"{q}%"
        return await self._query(
            "SELECT ts_code, name, industry, list_status "
            "FROM stock_basic "
            "WHERE (ts_code ILIKE :q OR name ILIKE :q) AND list_status = 'L' "
            "ORDER BY ts_code LIMIT :lim",
            {"q": like, "lim": limit},
        )

    async def trade_calendar(
        self, start: str, end: str, is_open: bool = True
    ) -> list[str]:
        df = await self._query(
            "SELECT cal_date FROM trade_cal "
            "WHERE cal_date >= :s AND cal_date <= :e AND is_open = :o "
            "ORDER BY cal_date",
            {"s": start, "e": end, "o": 1 if is_open else 0},
        )
        return df["cal_date"].tolist() if not df.empty else []

    # ── Daily bars ──────────────────────────────────────────────────

    async def daily(
        self,
        ts_code: str,
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        sql = "SELECT * FROM stock_daily WHERE ts_code = :c"
        params: dict = {"c": ts_code}
        if start_date:
            sql += " AND trade_date >= :s"
            params["s"] = start_date
        if end_date:
            sql += " AND trade_date <= :e"
            params["e"] = end_date
        sql += " ORDER BY trade_date"
        return await self._query(sql, params)

    async def daily_basic(
        self,
        ts_code: str,
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        sql = "SELECT * FROM daily_basic WHERE ts_code = :c"
        params: dict = {"c": ts_code}
        if start_date:
            sql += " AND trade_date >= :s"
            params["s"] = start_date
        if end_date:
            sql += " AND trade_date <= :e"
            params["e"] = end_date
        sql += " ORDER BY trade_date"
        return await self._query(sql, params)

    async def daily_with_basic(
        self,
        ts_code: str,
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """Join stock_daily + daily_basic on (ts_code, trade_date)."""
        sql = """
            SELECT d.*, b.turnover_rate, b.turnover_rate_f, b.volume_ratio,
                   b.pe, b.pe_ttm, b.pb, b.ps, b.ps_ttm,
                   b.dv_ratio, b.dv_ttm, b.total_share, b.float_share,
                   b.free_share, b.total_mv, b.circ_mv
            FROM stock_daily d
            LEFT JOIN daily_basic b ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
            WHERE d.ts_code = :c
        """
        params: dict = {"c": ts_code}
        if start_date:
            sql += " AND d.trade_date >= :s"
            params["s"] = start_date
        if end_date:
            sql += " AND d.trade_date <= :e"
            params["e"] = end_date
        sql += " ORDER BY d.trade_date"
        return await self._query(sql, params)

    # ── Minute bars ─────────────────────────────────────────────────

    async def minutes(
        self,
        ts_code: str,
        start_time: str | datetime = "",
        end_time: str | datetime = "",
        freq: str = "1min",
    ) -> pd.DataFrame:
        sql = "SELECT * FROM stock_min_kline WHERE ts_code = :c AND freq = :f"
        params: dict = {"c": ts_code, "f": freq}
        if start_time:
            sql += " AND trade_time >= :s"
            params["s"] = str(start_time)
        if end_time:
            sql += " AND trade_time <= :e"
            params["e"] = str(end_time)
        sql += " ORDER BY trade_time"
        return await self._query(sql, params)

    # ── Index data ──────────────────────────────────────────────────

    async def index_list(self, market: str = "") -> pd.DataFrame:
        if market:
            return await self._query(
                "SELECT * FROM index_basic WHERE market = :m ORDER BY ts_code",
                {"m": market},
            )
        return await self._query("SELECT * FROM index_basic ORDER BY ts_code")

    async def index_daily(
        self,
        ts_code: str,
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        sql = "SELECT * FROM index_daily WHERE ts_code = :c"
        params: dict = {"c": ts_code}
        if start_date:
            sql += " AND trade_date >= :s"
            params["s"] = start_date
        if end_date:
            sql += " AND trade_date <= :e"
            params["e"] = end_date
        sql += " ORDER BY trade_date"
        return await self._query(sql, params)

    # ── Industry classification ─────────────────────────────────────

    async def sw_classify(self, level: str = "") -> pd.DataFrame:
        if level:
            return await self._query(
                "SELECT * FROM index_classify WHERE level = :l ORDER BY index_code",
                {"l": level},
            )
        return await self._query("SELECT * FROM index_classify ORDER BY index_code")

    # ── Cross-sectional snapshot ────────────────────────────────────

    async def market_snapshot(self, trade_date: str) -> pd.DataFrame:
        """Get all stocks' daily + basic data for a single date."""
        return await self._query(
            """
            SELECT d.ts_code, s.name, s.industry, d.open, d.high, d.low, d.close,
                   d.pct_chg, d.vol, d.amount,
                   b.pe, b.pb, b.total_mv, b.circ_mv, b.turnover_rate
            FROM stock_daily d
            JOIN stock_basic s ON d.ts_code = s.ts_code
            LEFT JOIN daily_basic b ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
            WHERE d.trade_date = :td
            ORDER BY d.pct_chg DESC
            """,
            {"td": trade_date},
        )

    # ── Limit prices (涨跌停) ──────────────────────────────────────

    async def stk_limit(
        self, ts_code: str, trade_date: str
    ) -> dict | None:
        """Get up/down limit prices for a single stock on a single date."""
        df = await self._query(
            "SELECT up_limit, down_limit, pre_close FROM stock_limit "
            "WHERE ts_code = :c AND trade_date = :d",
            {"c": ts_code, "d": trade_date},
        )
        if df.empty:
            return None
        row = df.iloc[0]
        return {"up_limit": row["up_limit"], "down_limit": row["down_limit"], "pre_close": row["pre_close"]}

    async def stk_limit_batch(self, trade_date: str) -> pd.DataFrame:
        """Get all stocks' limit prices for a single date."""
        return await self._query(
            "SELECT ts_code, up_limit, down_limit, pre_close FROM stock_limit "
            "WHERE trade_date = :d",
            {"d": trade_date},
        )

    async def stk_limit_batch_range(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Get all stocks' limit prices for a date range (for backtest preloading)."""
        return await self._query(
            "SELECT ts_code, trade_date, up_limit, down_limit, pre_close FROM stock_limit "
            "WHERE trade_date >= :s AND trade_date <= :e",
            {"s": start_date, "e": end_date},
        )

    # ── Suspension (停复牌) ─────────────────────────────────────────

    async def is_suspended(self, ts_code: str, trade_date: str) -> bool:
        """Check if a stock is suspended on a given date."""
        df = await self._query(
            "SELECT 1 FROM suspend_d "
            "WHERE ts_code = :c AND trade_date = :d AND suspend_type = 'S' "
            "LIMIT 1",
            {"c": ts_code, "d": trade_date},
        )
        return not df.empty

    async def suspended_stocks(self, trade_date: str) -> set[str]:
        """Get all suspended stock codes for a given date."""
        df = await self._query(
            "SELECT ts_code FROM suspend_d "
            "WHERE trade_date = :d AND suspend_type = 'S'",
            {"d": trade_date},
        )
        return set(df["ts_code"].tolist()) if not df.empty else set()
