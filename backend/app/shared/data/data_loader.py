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

    # ── P2-Plus: Rankings ────────────────────────────────────────

    async def latest_trade_date(self) -> str:
        df = await self._query(
            "SELECT MAX(trade_date) as td FROM stock_daily"
        )
        return df["td"].iloc[0] if not df.empty else ""

    async def market_rankings(
        self, rank_type: str = "gain", limit: int = 10
    ) -> pd.DataFrame:
        td = await self.latest_trade_date()
        if not td:
            return pd.DataFrame()

        order = {
            "gain": "d.pct_chg DESC NULLS LAST",
            "lose": "d.pct_chg ASC NULLS LAST",
            "turnover": "b.turnover_rate DESC NULLS LAST",
        }.get(rank_type, "d.pct_chg DESC NULLS LAST")

        return await self._query(
            f"""
            SELECT d.ts_code, s.name, d.close, d.pct_chg,
                   b.turnover_rate, d.amount, d.vol
            FROM stock_daily d
            JOIN stock_basic s ON d.ts_code = s.ts_code
            LEFT JOIN daily_basic b ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
            WHERE d.trade_date = :td AND s.list_status = 'L'
              AND d.pct_chg IS NOT NULL
            ORDER BY {order}
            LIMIT :lim
            """,
            {"td": td, "lim": limit},
        )

    async def sector_rankings(self, limit: int = 10) -> pd.DataFrame:
        td = await self.latest_trade_date()
        if not td:
            return pd.DataFrame()

        df = await self._query(
            """
            SELECT ts_code, name AS industry, pct_change AS avg_pct_chg,
                   close, pe, pb, vol, amount
            FROM sw_daily
            WHERE trade_date = :td
            ORDER BY pct_change DESC
            """,
            {"td": td},
        )
        if not df.empty:
            return df

        return await self._query(
            """
            SELECT s.industry, AVG(d.pct_chg) as avg_pct_chg,
                   COUNT(*) as stock_count
            FROM stock_daily d
            JOIN stock_basic s ON d.ts_code = s.ts_code
            WHERE d.trade_date = :td AND s.list_status = 'L'
              AND s.industry IS NOT NULL AND s.industry != ''
              AND d.pct_chg IS NOT NULL
            GROUP BY s.industry
            ORDER BY avg_pct_chg DESC
            """,
            {"td": td},
        )

    # ── P2-Plus: Money flow ──────────────────────────────────────

    async def moneyflow_top(self, limit: int = 10) -> pd.DataFrame:
        return await self._query(
            """
            SELECT m.ts_code, s.name, m.net_mf_amount,
                   m.buy_elg_amount, m.sell_elg_amount,
                   m.buy_lg_amount, m.sell_lg_amount
            FROM moneyflow_dc m
            JOIN stock_basic s ON m.ts_code = s.ts_code
            WHERE m.trade_date = (SELECT MAX(trade_date) FROM moneyflow_dc)
            ORDER BY m.net_mf_amount DESC NULLS LAST
            LIMIT :lim
            """,
            {"lim": limit},
        )

    # ── P2-Plus: Global indices ──────────────────────────────────

    async def global_indices(self) -> pd.DataFrame:
        codes = [
            "000001.SH", "399001.SZ", "399006.SZ", "000300.SH",
            "000905.SH", "000688.SH", "899050.BJ",
        ]
        code_list = ",".join(f"'{c}'" for c in codes)
        return await self._query(
            f"""
            SELECT i.ts_code, i.name,
                   d.close, d.pct_chg, d.vol
            FROM index_daily d
            JOIN index_basic i ON d.ts_code = i.ts_code
            WHERE d.trade_date = (
                SELECT MAX(trade_date) FROM index_daily
                WHERE ts_code IN ({code_list})
            )
            AND d.ts_code IN ({code_list})
            ORDER BY d.ts_code
            """
        )

    # ── ST stocks / Adj factor ────────────────────────────────────

    async def st_stocks(self, trade_date: str | None = None) -> pd.DataFrame:
        td = trade_date or await self.latest_trade_date()
        if not td:
            return pd.DataFrame()
        return await self._query(
            "SELECT ts_code, name, trade_date, type, type_name "
            "FROM stock_st WHERE trade_date = :td",
            {"td": td},
        )

    async def adj_factor(
        self, ts_code: str, start: str | None = None, end: str | None = None
    ) -> pd.DataFrame:
        sql = "SELECT ts_code, trade_date, adj_factor FROM adj_factor WHERE ts_code = :code"
        params: dict = {"code": ts_code}
        if start:
            sql += " AND trade_date >= :start"
            params["start"] = start
        if end:
            sql += " AND trade_date <= :end"
            params["end"] = end
        sql += " ORDER BY trade_date"
        return await self._query(sql, params)

    async def daily_qfq(
        self, ts_code: str, start: str | None = None, end: str | None = None
    ) -> pd.DataFrame:
        """Get forward-adjusted daily bars (前复权)."""
        daily_df = await self.daily(ts_code, start, end)
        adj_df = await self.adj_factor(ts_code, start, end)
        if daily_df.empty or adj_df.empty:
            return daily_df

        merged = daily_df.merge(adj_df[["trade_date", "adj_factor"]], on="trade_date", how="left")
        latest_factor = adj_df["adj_factor"].iloc[-1]
        if latest_factor and latest_factor > 0:
            ratio = merged["adj_factor"] / latest_factor
            for col in ["open", "high", "low", "close"]:
                if col in merged.columns:
                    merged[col] = (merged[col] * ratio).round(2)
        merged.drop(columns=["adj_factor"], inplace=True, errors="ignore")
        return merged

    # ── P2-Plus: News / Announcements ────────────────────────────

    async def market_news(self, limit: int = 50) -> pd.DataFrame:
        return await self._query(
            "SELECT id, datetime, content, channels, source "
            "FROM stock_news ORDER BY datetime DESC LIMIT :lim",
            {"lim": limit},
        )

    async def stock_news(self, ts_code: str, limit: int = 20) -> pd.DataFrame:
        name_df = await self._query(
            "SELECT name FROM stock_basic WHERE ts_code = :c LIMIT 1",
            {"c": ts_code},
        )
        if name_df.empty:
            return pd.DataFrame()

        stock_name = name_df["name"].iloc[0]
        code_short = ts_code.split(".")[0]
        return await self._query(
            "SELECT id, datetime, content, channels, source "
            "FROM stock_news "
            "WHERE content ILIKE :q1 OR content ILIKE :q2 "
            "ORDER BY datetime DESC LIMIT :lim",
            {"q1": f"%{stock_name}%", "q2": f"%{code_short}%", "lim": limit},
        )

    async def stock_anns(self, ts_code: str, limit: int = 20) -> pd.DataFrame:
        return await self._query(
            "SELECT id, ts_code, ann_date, title, url "
            "FROM stock_anns WHERE ts_code = :c "
            "ORDER BY ann_date DESC LIMIT :lim",
            {"c": ts_code, "lim": limit},
        )

    # ── P2-Plus: K-line aggregation ──────────────────────────────

    async def weekly(
        self, ts_code: str, start_date: str = "", end_date: str = ""
    ) -> pd.DataFrame:
        sql = """
            SELECT ts_code,
                   MIN(trade_date) as trade_date,
                   (array_agg(open ORDER BY trade_date))[1] as open,
                   MAX(high) as high,
                   MIN(low) as low,
                   (array_agg(close ORDER BY trade_date DESC))[1] as close,
                   SUM(vol) as vol,
                   SUM(amount) as amount
            FROM stock_daily
            WHERE ts_code = :c
        """
        params: dict = {"c": ts_code}
        if start_date:
            sql += " AND trade_date >= :s"
            params["s"] = start_date
        if end_date:
            sql += " AND trade_date <= :e"
            params["e"] = end_date
        sql += """
            GROUP BY ts_code,
                     date_trunc('week', to_date(trade_date, 'YYYYMMDD'))
            ORDER BY trade_date
        """
        return await self._query(sql, params)

    async def monthly(
        self, ts_code: str, start_date: str = "", end_date: str = ""
    ) -> pd.DataFrame:
        sql = """
            SELECT ts_code,
                   MIN(trade_date) as trade_date,
                   (array_agg(open ORDER BY trade_date))[1] as open,
                   MAX(high) as high,
                   MIN(low) as low,
                   (array_agg(close ORDER BY trade_date DESC))[1] as close,
                   SUM(vol) as vol,
                   SUM(amount) as amount
            FROM stock_daily
            WHERE ts_code = :c
        """
        params: dict = {"c": ts_code}
        if start_date:
            sql += " AND trade_date >= :s"
            params["s"] = start_date
        if end_date:
            sql += " AND trade_date <= :e"
            params["e"] = end_date
        sql += """
            GROUP BY ts_code,
                     date_trunc('month', to_date(trade_date, 'YYYYMMDD'))
            ORDER BY trade_date
        """
        return await self._query(sql, params)
