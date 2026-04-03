"""Unified data sync — all Tushare pull logic for in-process scheduler use.

Each function accepts a psycopg2 connection + TushareService, handles one
data domain, and returns the number of rows written. Functions are safe to
call repeatedly (idempotent via ON CONFLICT or date-existence checks).

Replaces the old daily_sync.py Phase 1+2 subprocess chain.
sync_minutes is intentionally excluded (runs as subprocess due to 30-60 min runtime).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time as _time
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

from app.research.data.tushare_service import TushareService

logger = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"

CORE_INDICES = [
    "000001.SH", "399001.SZ", "399006.SZ",
    "000300.SH", "000905.SH", "000688.SH", "899050.BJ",
]


def _db_url() -> str:
    return os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")


def _nan_safe(val):
    if val is None:
        return None
    if isinstance(val, float) and (str(val) == "nan" or val != val):
        return None
    return val


def _df_to_values(df) -> tuple[list[str], list[tuple]]:
    """Convert DataFrame to (columns, list-of-tuples) with NaN→None."""
    cols = list(df.columns)
    vals = [tuple(_nan_safe(r[c]) for c in cols) for _, r in df.iterrows()]
    return cols, vals


def _auto_widen_columns(conn, table: str, cols: list[str], df) -> None:
    """Auto-expand VARCHAR columns that are too narrow for the data."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, character_maximum_length "
                "FROM information_schema.columns "
                "WHERE table_name = %s AND data_type = 'character varying'",
                (table,),
            )
            varchar_cols = {row[0]: row[1] for row in cur.fetchall()}

        for col_name in cols:
            clean = col_name.strip('"')
            if clean not in varchar_cols or clean not in df.columns:
                continue
            max_len = varchar_cols[clean]
            if max_len is None:
                continue
            actual_max = df[clean].dropna().astype(str).str.len().max()
            if actual_max and actual_max > max_len:
                new_len = max(int(actual_max * 1.5), max_len * 2)
                with conn.cursor() as cur:
                    cur.execute(f'ALTER TABLE {table} ALTER COLUMN "{clean}" TYPE VARCHAR({new_len})')
                conn.commit()
                logger.info("auto-schema: widened %s.%s from %d to %d", table, clean, max_len, new_len)
    except Exception:
        conn.rollback()
        logger.warning("auto-widen failed for %s", table, exc_info=True)


def _auto_add_columns(conn, table: str, cols: list[str], df) -> None:
    """Auto-detect missing columns and ALTER TABLE to add them.

    Maps pandas dtypes to PostgreSQL types and adds any columns that exist
    in the DataFrame but not in the database table.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = %s", (table,)
            )
            existing = {row[0] for row in cur.fetchall()}

        missing = [c for c in cols if c.strip('"') not in existing]
        if not missing:
            return

        dtype_map = {
            "float64": "DOUBLE PRECISION",
            "int64": "BIGINT",
            "object": "TEXT",
            "bool": "BOOLEAN",
        }
        with conn.cursor() as cur:
            for col in missing:
                clean_col = col.strip('"')
                pg_type = "TEXT"
                if clean_col in df.columns:
                    pd_dtype = str(df[clean_col].dtype)
                    pg_type = dtype_map.get(pd_dtype, "TEXT")
                cur.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "{clean_col}" {pg_type}')
                logger.info("auto-schema: added column %s.%s (%s)", table, clean_col, pg_type)
            conn.commit()
    except Exception:
        conn.rollback()
        logger.warning("auto-schema failed for %s", table, exc_info=True)


def _get_trade_dates_desc(conn, ref_date: str, lookback: int = 3) -> list[str]:
    """Get ref_date + previous N trading days in descending order."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT cal_date FROM trade_cal WHERE is_open = 1 "
            "AND cal_date <= %s ORDER BY cal_date DESC LIMIT %s",
            (ref_date, lookback),
        )
        return [row[0] for row in cur.fetchall()]


def _get_trade_dates(cur, start: str, end: str) -> list[str]:
    cur.execute(
        "SELECT cal_date FROM trade_cal WHERE is_open = 1 "
        "AND cal_date >= %s AND cal_date <= %s ORDER BY cal_date",
        (start, end),
    )
    return [r[0] for r in cur.fetchall()]


def _max_date(cur, table: str, col: str = "trade_date") -> str | None:
    cur.execute(f"SELECT MAX({col}) FROM {table}")
    return cur.fetchone()[0]


# =====================================================================
# Individual sync functions — each handles one data domain
# =====================================================================

def sync_stock_basic(conn, svc: TushareService) -> int:
    """Full refresh stock_basic (L+D). ~11k rows."""
    import pandas as pd
    df_l = svc.stock_basic(list_status="L")
    df_d = svc.stock_basic(list_status="D")
    df = pd.concat([df_l, df_d], ignore_index=True)
    if df.empty:
        return 0
    cols, vals = _df_to_values(df)
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE stock_basic")
        execute_values(cur, f"INSERT INTO stock_basic ({','.join(cols)}) VALUES %s", vals)
    conn.commit()
    logger.info("sync: stock_basic refreshed %d rows", len(df))
    return len(df)


def sync_trade_cal(conn, svc: TushareService) -> int:
    """Extend trade_cal 90 days into future."""
    with conn.cursor() as cur:
        last = _max_date(cur, "trade_cal", "cal_date") or "20200101"
    future = (datetime.now() + timedelta(days=90)).strftime("%Y%m%d")
    df = svc.trade_cal(start_date=last, end_date=future)
    if df is None or df.empty:
        return 0
    cols, vals = _df_to_values(df)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM trade_cal WHERE cal_date >= %s", (last,))
        execute_values(cur, f"INSERT INTO trade_cal ({','.join(cols)}) VALUES %s", vals)
    conn.commit()
    logger.info("sync: trade_cal extended to %s (+%d)", future, len(df))
    return len(df)


def sync_daily_bars(conn, svc: TushareService) -> int:
    """Incremental stock_daily + daily_basic + index_daily."""
    today = datetime.now().strftime("%Y%m%d")
    total = 0
    with conn.cursor() as cur:
        for table, pull_fn in [("stock_daily", svc.daily), ("daily_basic", lambda **kw: svc.daily_basic(ts_code="", **kw))]:
            last = _max_date(cur, table) or "20200101"
            next_day = str(int(last) + 1)
            dates = _get_trade_dates(cur, next_day, today)
            for td in dates:
                try:
                    df = pull_fn(trade_date=td)
                    if df is None or df.empty:
                        continue
                    cur.execute(f"DELETE FROM {table} WHERE trade_date = %s", (td,))
                    cols, vals = _df_to_values(df)
                    execute_values(cur, f"INSERT INTO {table} ({','.join(cols)}) VALUES %s", vals)
                    conn.commit()
                    total += len(df)
                except Exception:
                    conn.rollback()
                    logger.warning("sync %s failed for %s", table, td, exc_info=True)

        last_idx = _max_date(cur, "index_daily") or "20200101"
        next_day = str(int(last_idx) + 1)
        for idx_code in CORE_INDICES:
            try:
                df = svc.index_daily(ts_code=idx_code, start_date=next_day, end_date=today)
                if df is None or df.empty:
                    continue
                cur.execute("DELETE FROM index_daily WHERE ts_code = %s AND trade_date >= %s", (idx_code, next_day))
                cols, vals = _df_to_values(df)
                execute_values(cur, f"INSERT INTO index_daily ({','.join(cols)}) VALUES %s", vals)
                conn.commit()
                total += len(df)
            except Exception:
                conn.rollback()
                logger.warning("sync index_daily failed for %s", idx_code, exc_info=True)

    logger.info("sync: daily_bars +%d rows", total)
    return total


def sync_stk_limit(conn, svc: TushareService, trade_date: str) -> int:
    """stock_limit + suspend_d for one trade date."""
    total = 0
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM stock_limit WHERE trade_date = %s", (trade_date,))
        if cur.fetchone()[0] > 0:
            return 0
        df = svc.stk_limit(trade_date=trade_date)
        if df is not None and not df.empty:
            cols, vals = _df_to_values(df)
            execute_values(cur, f"INSERT INTO stock_limit ({','.join(cols)}) VALUES %s", vals)
            conn.commit()
            total += len(df)

        try:
            df2 = svc.query("suspend_d", suspend_type="S", trade_date=trade_date)
            if df2 is not None and not df2.empty:
                cur.execute("SELECT count(*) FROM suspend_d WHERE trade_date = %s", (trade_date,))
                if cur.fetchone()[0] == 0:
                    cols2, vals2 = _df_to_values(df2)
                    execute_values(cur, f"INSERT INTO suspend_d ({','.join(cols2)}) VALUES %s", vals2)
                    conn.commit()
                    total += len(df2)
        except Exception:
            conn.rollback()
            logger.warning("sync suspend_d failed for %s", trade_date, exc_info=True)

    logger.info("sync: stk_limit %s +%d rows", trade_date, total)
    return total


def sync_st_list(conn, svc: TushareService, trade_date: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM stock_st WHERE trade_date = %s", (trade_date,))
        if cur.fetchone()[0] > 0:
            return 0
        df = svc.stock_st(trade_date=trade_date)
        if df is None or df.empty:
            return 0
        cols, vals = _df_to_values(df)
        execute_values(cur, f"INSERT INTO stock_st ({','.join(cols)}) VALUES %s ON CONFLICT (ts_code, trade_date) DO NOTHING", vals)
    conn.commit()
    logger.info("sync: stock_st %s +%d rows", trade_date, len(df))
    return len(df)


def sync_forecast(conn, svc: TushareService) -> int:
    """Pull forecast by ann_date for recent days (including tomorrow for evening announcements)."""
    today = datetime.now().strftime("%Y%m%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
    total = 0
    for ann_d in [tomorrow, today, yesterday]:
        try:
            df = svc.forecast(ann_date=ann_d)
            if df is None or df.empty:
                continue
            df = df.drop_duplicates(subset=["ts_code", "ann_date", "end_date"], keep="last")
            cols, vals = _df_to_values(df)
            conflict_cols = ("ts_code", "ann_date", "end_date")
            update_cols = [c for c in cols if c not in conflict_cols]
            sql = (
                f"INSERT INTO forecast ({','.join(cols)}) VALUES %s "
                f"ON CONFLICT (ts_code, ann_date, end_date) DO UPDATE SET "
                + ", ".join(f"{c}=EXCLUDED.{c}" for c in update_cols)
            )
            with conn.cursor() as cur:
                execute_values(cur, sql, vals)
            conn.commit()
            total += len(df)
        except Exception:
            conn.rollback()
            logger.warning("sync forecast(%s) failed", ann_d, exc_info=True)
    if total:
        logger.info("sync: forecast +%d rows", total)
    return total


def sync_disclosure(conn, svc: TushareService) -> int:
    """Pull disclosure_date for recent quarters."""
    total = 0
    now = datetime.now()
    year = now.year
    month = now.month
    quarters = []
    for y in [year - 1, year]:
        for q_end in ["0331", "0630", "0930", "1231"]:
            quarters.append(f"{y}{q_end}")
    quarters = [q for q in quarters if q <= now.strftime("%Y%m%d")][-4:]

    for end_date in quarters:
        try:
            df = svc.query("disclosure_date", end_date=end_date,
                           fields="ts_code,end_date,pre_date,actual_date,modify_date")
            if df is None or df.empty:
                continue
            df = df.drop_duplicates(subset=["ts_code", "end_date"], keep="last")
            cols, vals = _df_to_values(df)
            sql = (
                f"INSERT INTO disclosure_date ({','.join(cols)}) VALUES %s "
                f"ON CONFLICT (ts_code, end_date) DO UPDATE SET "
                "pre_date=EXCLUDED.pre_date, actual_date=EXCLUDED.actual_date, modify_date=EXCLUDED.modify_date"
            )
            with conn.cursor() as cur:
                execute_values(cur, sql, vals)
            conn.commit()
            total += len(df)
        except Exception:
            conn.rollback()
            logger.warning("sync disclosure(%s) failed", end_date, exc_info=True)
    if total:
        logger.info("sync: disclosure_date +%d rows", total)
    return total


def sync_limit_board(conn, svc: TushareService, trade_date: str) -> int:
    """7-in-1 limit board sync for one trade date."""
    total = 0
    tasks = [
        ("limit_list_ths", ["涨停池", "跌停池", "炸板池"], "limit_type", svc.limit_list_ths),
        ("limit_stats", ["U", "D", "Z"], "limit_type", svc.limit_list_d),
    ]
    for table, types, type_param, api_fn in tasks:
        for lt in types:
            try:
                _time.sleep(1.3)
                df = api_fn(trade_date=trade_date, **{type_param: lt})
                if df is None or df.empty:
                    continue
                cols, vals = _df_to_values(df)
                if table == "limit_stats" and '"limit"' not in ','.join(cols):
                    cols = [f'"limit"' if c == "limit" else c for c in cols]
                execute_values(
                    conn.cursor(),
                    f"INSERT INTO {table} ({','.join(cols)}) VALUES %s ON CONFLICT DO NOTHING",
                    vals,
                )
                conn.commit()
                total += len(df)
            except Exception:
                conn.rollback()
                logger.warning("sync %s(%s) failed", table, lt, exc_info=True)

    single_apis = [
        ("limit_step", svc.limit_step),
        ("top_list", svc.query),
        ("hm_detail", svc.query),
        ("limit_cpt_list", svc.limit_cpt_list),
        ("dc_hot", svc.query),
    ]
    for table, api_fn in single_apis:
        try:
            _time.sleep(1.3)
            if table in ("top_list", "hm_detail", "dc_hot"):
                df = api_fn(table, trade_date=trade_date)
            else:
                df = api_fn(trade_date=trade_date)
            if df is None or df.empty:
                continue
            cols, vals = _df_to_values(df)
            if table == "limit_stats" and "limit" in cols:
                cols = [f'"limit"' if c == "limit" else c for c in cols]
            _auto_add_columns(conn, table, cols, df)
            execute_values(
                conn.cursor(),
                f"INSERT INTO {table} ({','.join(cols)}) VALUES %s ON CONFLICT DO NOTHING",
                vals,
            )
            conn.commit()
            total += len(df)
        except Exception as exc:
            conn.rollback()
            logger.warning("sync %s failed", table, exc_info=True)
            try:
                from app.shared.sync_tracker import sync_tracker
                sync_tracker.fail(table, exc)
            except Exception:
                pass

    logger.info("sync: limit_board %s +%d rows", trade_date, total)
    return total


def sync_cb(conn, svc: TushareService, trade_date: str) -> int:
    """cb_basic (upsert) + cb_call (truncate+insert) + cb_daily (incremental)."""
    total = 0

    try:
        df = svc.cb_basic()
        if df is not None and not df.empty:
            cols, vals = _df_to_values(df)
            update_cols = [c for c in cols if c != "ts_code"]
            sql = (
                f"INSERT INTO cb_basic ({','.join(cols)}) VALUES %s "
                f"ON CONFLICT (ts_code) DO UPDATE SET "
                + ", ".join(f"{c}=EXCLUDED.{c}" for c in update_cols)
            )
            with conn.cursor() as cur:
                execute_values(cur, sql, vals)
            conn.commit()
            total += len(df)
    except Exception:
        conn.rollback()
        logger.warning("sync cb_basic failed", exc_info=True)

    try:
        df = svc.cb_call()
        if df is not None and not df.empty:
            cols, vals = _df_to_values(df)
            with conn.cursor() as cur:
                cur.execute("TRUNCATE cb_call")
                execute_values(cur, f"INSERT INTO cb_call ({','.join(cols)}) VALUES %s", vals)
            conn.commit()
            total += len(df)
    except Exception:
        conn.rollback()
        logger.warning("sync cb_call failed", exc_info=True)

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM cb_daily WHERE trade_date = %s", (trade_date,))
            if cur.fetchone()[0] == 0:
                df = svc.cb_daily(trade_date=trade_date)
                if df is not None and not df.empty:
                    cols, vals = _df_to_values(df)
                    execute_values(
                        cur,
                        f"INSERT INTO cb_daily ({','.join(cols)}) VALUES %s ON CONFLICT (ts_code, trade_date) DO NOTHING",
                        vals,
                    )
                    conn.commit()
                    total += len(df)
    except Exception:
        conn.rollback()
        logger.warning("sync cb_daily failed", exc_info=True)

    logger.info("sync: cb %s +%d rows", trade_date, total)
    return total


def sync_classify_news(conn) -> int:
    """Classify unclassified news + announcements using rule engine."""
    try:
        from app.shared.news_classifier import NewsClassifier
        clf = NewsClassifier()
        with conn.cursor() as cur:
            cur.execute("SELECT ts_code, name FROM stock_basic WHERE name IS NOT NULL")
            stock_rows = cur.fetchall()
            cur.execute("SELECT DISTINCT industry_name FROM index_classify WHERE industry_name IS NOT NULL")
            ind_names = [r[0] for r in cur.fetchall()]
            clf.load_reference_data(stock_rows, ind_names)

            total = 0
            # News
            cur.execute(
                "SELECT n.id, n.content, n.datetime FROM stock_news n "
                "LEFT JOIN news_classified nc ON n.id = nc.news_id "
                "WHERE nc.news_id IS NULL ORDER BY n.id"
            )
            news_batch = []
            for nid, content, dt_str in cur.fetchall():
                r = clf.classify_news(nid, content or "", dt_str or "")
                d = r.to_db_dict(nid)
                news_batch.append((
                    d["news_id"], d["news_scope"], d["time_slot"],
                    d["sentiment"], d["related_codes"],
                    d["related_industries"], d["keywords"],
                ))
            if news_batch:
                execute_values(
                    cur,
                    "INSERT INTO news_classified "
                    "(news_id, news_scope, time_slot, sentiment, related_codes, related_industries, keywords) "
                    "VALUES %s ON CONFLICT (news_id) DO NOTHING",
                    news_batch,
                )
                total += len(news_batch)

            # Announcements
            cur.execute(
                "SELECT a.id, a.title, '' FROM stock_anns a "
                "LEFT JOIN anns_classified ac ON a.id = ac.anns_id "
                "WHERE ac.anns_id IS NULL ORDER BY a.id"
            )
            anns_batch = []
            for aid, title, dt_str in cur.fetchall():
                r = clf.classify_anns(aid, title or "", dt_str or "")
                d = r.to_db_dict(aid)
                anns_batch.append((
                    d.get("anns_id", aid), d.get("news_scope", ""), d.get("time_slot", ""),
                    d.get("sentiment", ""), d.get("related_codes", ""),
                    d.get("related_industries", ""), d.get("keywords", ""),
                ))
            if anns_batch:
                execute_values(
                    cur,
                    "INSERT INTO anns_classified "
                    "(anns_id, news_scope, time_slot, sentiment, related_codes, related_industries, keywords) "
                    "VALUES %s ON CONFLICT (anns_id) DO NOTHING",
                    anns_batch,
                )
                total += len(anns_batch)

        conn.commit()
        logger.info("sync: classify_news +%d items", total)
        return total
    except Exception:
        conn.rollback()
        logger.warning("sync classify_news failed", exc_info=True)
        return 0


def sync_moneyflow(conn, svc: TushareService, trade_date: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM moneyflow_dc WHERE trade_date = %s", (trade_date,))
        if cur.fetchone()[0] > 0:
            return 0
        df = svc.moneyflow_dc(trade_date=trade_date)
        if df is None or df.empty:
            return 0
        if "net_amount" in df.columns:
            df = df.rename(columns={"net_amount": "net_mf_amount"})
        cols = [c for c in ["ts_code", "trade_date", "buy_sm_amount", "buy_md_amount",
                "buy_lg_amount", "buy_elg_amount", "net_mf_amount"] if c in df.columns]
        df = df[cols].dropna(subset=["ts_code", "trade_date"])
        buf = StringIO()
        df.to_csv(buf, index=False, header=False, sep="\t", na_rep="\\N")
        buf.seek(0)
        cur.copy_from(buf, "moneyflow_dc", columns=cols, sep="\t", null="\\N")
    conn.commit()
    logger.info("sync: moneyflow_dc %s +%d rows", trade_date, len(df))
    return len(df)


def sync_news_batch(conn, svc: TushareService) -> int:
    """Batch pull recent news (beyond real-time 5s polling)."""
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(datetime) FROM stock_news")
        last_dt = cur.fetchone()[0]

    sources = ["sina", "wallstreetcn", "10jqka", "eastmoney", "yuncaijing"]
    total = 0
    for src in sources:
        try:
            df = svc.news(src=src, start_date=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"))
            if df is None or df.empty:
                continue
            if "pub_time" in df.columns:
                df = df.rename(columns={"pub_time": "datetime"})
            df = df.drop_duplicates(subset=["datetime", "content"])
            if last_dt:
                df = df[df["datetime"] > last_dt]
            if df.empty:
                continue
            cols, vals = _df_to_values(df)
            with conn.cursor() as cur:
                execute_values(cur, f"INSERT INTO stock_news ({','.join(cols)}) VALUES %s", vals)
            conn.commit()
            total += len(df)
        except Exception:
            conn.rollback()
            logger.warning("sync news(%s) failed", src, exc_info=True)
    if total:
        logger.info("sync: news_batch +%d rows", total)
    return total


def sync_anns(conn, svc: TushareService, trade_date: str) -> int:
    ann_date = trade_date
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM stock_anns WHERE ann_date = %s", (ann_date,))
        if cur.fetchone()[0] > 0:
            return 0
    try:
        df = svc.anns(ann_date=ann_date)
        if df is None or df.empty:
            return 0
        cols_want = ["ts_code", "ann_date", "title", "url"]
        cols = [c for c in cols_want if c in df.columns]
        df = df[cols]
        cols_list, vals = _df_to_values(df)
        with conn.cursor() as cur:
            execute_values(cur, f"INSERT INTO stock_anns ({','.join(cols_list)}) VALUES %s", vals)
        conn.commit()
        logger.info("sync: anns %s +%d rows", ann_date, len(df))
        return len(df)
    except Exception:
        conn.rollback()
        logger.warning("sync anns(%s) failed", ann_date, exc_info=True)
        return 0


def sync_adj_factor(conn, svc: TushareService, trade_date: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM adj_factor WHERE trade_date = %s", (trade_date,))
        if cur.fetchone()[0] > 0:
            return 0
        df = svc.adj_factor(trade_date=trade_date)
        if df is None or df.empty:
            return 0
        cur.execute("DELETE FROM adj_factor WHERE trade_date = %s", (trade_date,))
        cols, vals = _df_to_values(df)
        execute_values(cur, f"INSERT INTO adj_factor ({','.join(cols)}) VALUES %s", vals)
    conn.commit()
    logger.info("sync: adj_factor %s +%d rows", trade_date, len(df))
    return len(df)


def sync_sw_daily(conn, svc: TushareService, trade_date: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM sw_daily WHERE trade_date = %s", (trade_date,))
        if cur.fetchone()[0] > 0:
            return 0
        df = svc.sw_daily(trade_date=trade_date)
        if df is None or df.empty:
            return 0
        cur.execute("DELETE FROM sw_daily WHERE trade_date = %s", (trade_date,))
        cols, vals = _df_to_values(df)
        execute_values(cur, f"INSERT INTO sw_daily ({','.join(cols)}) VALUES %s", vals)
    conn.commit()
    logger.info("sync: sw_daily %s +%d rows", trade_date, len(df))
    return len(df)


def sync_stk_auction(conn, svc: TushareService, trade_date: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM stk_auction WHERE trade_date = %s", (trade_date,))
        if cur.fetchone()[0] > 0:
            return 0
        df = svc.stk_auction(trade_date=trade_date)
        if df is None or df.empty:
            return 0
        cur.execute("DELETE FROM stk_auction WHERE trade_date = %s", (trade_date,))
        cols, vals = _df_to_values(df)
        execute_values(cur, f"INSERT INTO stk_auction ({','.join(cols)}) VALUES %s", vals)
    conn.commit()
    logger.info("sync: stk_auction %s +%d rows", trade_date, len(df))
    return len(df)


def sync_eco_cal(conn, svc: TushareService) -> int:
    import pandas as pd
    start = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
    end = (datetime.now() + timedelta(days=14)).strftime("%Y%m%d")
    frames = []
    d = datetime.strptime(start, "%Y%m%d")
    end_d = datetime.strptime(end, "%Y%m%d")
    while d <= end_d:
        try:
            df = svc.eco_cal(date=d.strftime("%Y%m%d"))
            if df is not None and not df.empty:
                frames.append(df)
        except Exception:
            pass
        d += timedelta(days=1)
    if not frames:
        return 0
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["date", "time", "event"], keep="last")
    with conn.cursor() as cur:
        cur.execute("DELETE FROM eco_cal WHERE date >= %s AND date <= %s", (start, end))
        cols, vals = _df_to_values(df)
        execute_values(cur, f"INSERT INTO eco_cal ({','.join(cols)}) VALUES %s", vals)
    conn.commit()
    logger.info("sync: eco_cal +%d rows (%s~%s)", len(df), start, end)
    return len(df)


def sync_moneyflow_ind(conn, svc: TushareService, trade_date: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM moneyflow_ind_ths WHERE trade_date = %s", (trade_date,))
        if cur.fetchone()[0] > 0:
            return 0
        df = svc.moneyflow_ind_ths(trade_date=trade_date)
        if df is None or df.empty:
            return 0
        cur.execute("DELETE FROM moneyflow_ind_ths WHERE trade_date = %s", (trade_date,))
        cols, vals = _df_to_values(df)
        execute_values(cur, f"INSERT INTO moneyflow_ind_ths ({','.join(cols)}) VALUES %s", vals)
    conn.commit()
    logger.info("sync: moneyflow_ind %s +%d rows", trade_date, len(df))
    return len(df)


def sync_index_global(conn, svc: TushareService) -> int:
    import pandas as pd
    INDEX_CODES = [
        "XIN9", "SPX", "DJI", "IXIC", "FTSE", "FCHI", "GDAXI",
        "N225", "KS11", "AS51", "SENSEX", "MXX",
    ]
    start = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
    end = datetime.now().strftime("%Y%m%d")
    total = 0
    for code in INDEX_CODES:
        try:
            df = svc.index_global(ts_code=code, start_date=start, end_date=end)
            if df is None or df.empty:
                continue
            for col in df.select_dtypes(include=["object"]).columns:
                if col not in ("ts_code", "trade_date"):
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM index_global WHERE ts_code = %s AND trade_date >= %s AND trade_date <= %s",
                    (code, start, end),
                )
                cols, vals = _df_to_values(df)
                execute_values(cur, f"INSERT INTO index_global ({','.join(cols)}) VALUES %s", vals)
            conn.commit()
            total += len(df)
        except Exception:
            conn.rollback()
            logger.warning("sync index_global(%s) failed", code, exc_info=True)
    if total:
        logger.info("sync: index_global +%d rows", total)
    return total


def sync_concepts(conn, svc: TushareService) -> int:
    """concept_list + concept_detail full refresh."""
    total = 0
    try:
        df = svc.concept()
        if df is not None and not df.empty:
            cols, vals = _df_to_values(df)
            sql = (
                f"INSERT INTO concept_list ({','.join(cols)}) VALUES %s "
                "ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name, src=EXCLUDED.src"
            )
            with conn.cursor() as cur:
                execute_values(cur, sql, vals)
            conn.commit()
            total += len(df)

            for _, row in df.iterrows():
                try:
                    _time.sleep(1.3)
                    det = svc.concept_detail(id=row["code"])
                    if det is None or det.empty:
                        continue
                    if "id" in det.columns:
                        det = det.rename(columns={"id": "concept_code"})
                    cols2, vals2 = _df_to_values(det)
                    sql2 = (
                        f"INSERT INTO concept_detail ({','.join(cols2)}) VALUES %s "
                        "ON CONFLICT (concept_code, ts_code) DO UPDATE SET "
                        "concept_name=EXCLUDED.concept_name, name=EXCLUDED.name"
                    )
                    with conn.cursor() as cur:
                        execute_values(cur, sql2, vals2)
                    conn.commit()
                    total += len(det)
                except Exception:
                    conn.rollback()
                    logger.warning("sync concept_detail(%s) failed", row.get("code"), exc_info=True)
    except Exception:
        conn.rollback()
        logger.warning("sync concepts failed", exc_info=True)
    if total:
        logger.info("sync: concepts +%d rows", total)
    return total


# ── Phase 4.9: 8 new sync functions ───────────────────────────


def sync_share_float(conn, svc: TushareService, trade_date: str) -> int:
    """Restricted share unlock schedule — pull upcoming 60 days."""
    start = trade_date
    end = (datetime.strptime(trade_date, "%Y%m%d") + timedelta(days=60)).strftime("%Y%m%d")
    df = svc.share_float(start_date=start, end_date=end)
    if df is None or df.empty:
        return 0
    cols, vals = _df_to_values(df)
    sql = (
        f"INSERT INTO share_float ({','.join(cols)}) VALUES %s "
        f"ON CONFLICT ON CONSTRAINT uq_share_float DO NOTHING"
    )
    with conn.cursor() as cur:
        execute_values(cur, sql, vals)
    conn.commit()
    logger.info("sync: share_float +%d rows", len(df))
    return len(df)


def sync_stk_holdertrade(conn, svc: TushareService, trade_date: str) -> int:
    """Shareholder increase/decrease — pull by ann_date range (last 30 days)."""
    start = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=30)).strftime("%Y%m%d")
    total = 0
    for ttype in ("IN", "DE"):
        df = svc.stk_holdertrade(start_date=start, end_date=trade_date, trade_type=ttype)
        if df is None or df.empty:
            continue
        df = df.drop_duplicates(subset=["ts_code", "ann_date", "holder_name", "in_de", "change_vol"], keep="last")
        cols, vals = _df_to_values(df)
        sql = (
            f"INSERT INTO stk_holdertrade ({','.join(cols)}) VALUES %s "
            f"ON CONFLICT ON CONSTRAINT uq_stk_holdertrade DO NOTHING"
        )
        with conn.cursor() as cur:
            execute_values(cur, sql, vals)
        conn.commit()
        total += len(df)
    logger.info("sync: stk_holdertrade +%d rows", total)
    return total


def sync_margin(conn, svc: TushareService, trade_date: str) -> int:
    """Daily margin trading summary. T+1 data: tries trade_date, then prev days."""
    dates_to_try = _get_trade_dates_desc(conn, trade_date, lookback=3)
    for d in dates_to_try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM margin WHERE trade_date = %s", (d,))
            if cur.fetchone()[0] > 0:
                return 0
        df = svc.margin(trade_date=d)
        if df is not None and not df.empty:
            cols, vals = _df_to_values(df)
            _auto_add_columns(conn, "margin", cols, df)
            _auto_widen_columns(conn, "margin", cols, df)
            sql = (
                f"INSERT INTO margin ({','.join(cols)}) VALUES %s "
                f"ON CONFLICT ON CONSTRAINT uq_margin_date_exch DO NOTHING"
            )
            with conn.cursor() as cur:
                execute_values(cur, sql, vals)
            conn.commit()
            logger.info("sync: margin %s +%d rows", d, len(df))
            return len(df)
        _time.sleep(0.3)
    logger.info("sync: margin %s +0 rows (T+1 not available)", trade_date)
    return 0


def sync_top_inst(conn, svc: TushareService, trade_date: str) -> int:
    """Dragon-tiger list institutional details."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM top_inst WHERE trade_date = %s", (trade_date,))
        if cur.fetchone()[0] > 0:
            return 0
    df = svc.top_inst(trade_date=trade_date)
    if df is None or df.empty:
        return 0
    df = df.drop_duplicates(subset=["trade_date", "ts_code", "exalter", "side"], keep="last")
    cols, vals = _df_to_values(df)
    sql = (
        f"INSERT INTO top_inst ({','.join(cols)}) VALUES %s "
        f"ON CONFLICT ON CONSTRAINT uq_top_inst DO NOTHING"
    )
    with conn.cursor() as cur:
        execute_values(cur, sql, vals)
    conn.commit()
    logger.info("sync: top_inst %s +%d rows", trade_date, len(df))
    return len(df)


def sync_index_dailybasic(conn, svc: TushareService, trade_date: str) -> int:
    """Major index daily valuation (PE/PB/turnover)."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM index_dailybasic WHERE trade_date = %s", (trade_date,))
        if cur.fetchone()[0] > 0:
            return 0
    df = svc.index_dailybasic(trade_date=trade_date)
    if df is None or df.empty:
        return 0
    cols, vals = _df_to_values(df)
    sql = (
        f"INSERT INTO index_dailybasic ({','.join(cols)}) VALUES %s "
        f"ON CONFLICT ON CONSTRAINT uq_idx_dailybasic DO NOTHING"
    )
    with conn.cursor() as cur:
        execute_values(cur, sql, vals)
    conn.commit()
    logger.info("sync: index_dailybasic %s +%d rows", trade_date, len(df))
    return len(df)


def sync_top10_floatholders(conn, svc: TushareService) -> int:
    """Top 10 float holders — try recent quarter ends until data is found."""
    now = datetime.now()
    candidates = []
    for y in (now.year, now.year - 1):
        for m, d in ((12, "31"), (9, "30"), (6, "30"), (3, "31")):
            end = f"{y}{m:02d}{d}"
            if end <= now.strftime("%Y%m%d"):
                candidates.append(end)
    candidates.sort(reverse=True)

    for period in candidates[:4]:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM top10_floatholders WHERE end_date = %s", (period,))
            if cur.fetchone()[0] > 0:
                logger.info("sync: top10_floatholders (period=%s) already exists", period)
                return 0

        total = 0
        offset = 0
        while True:
            try:
                df = svc.top10_floatholders(period=period, offset=str(offset), limit="3000")
            except Exception:
                logger.warning("top10_floatholders fetch period=%s offset=%d failed", period, offset, exc_info=True)
                break
            if df is None or df.empty:
                break
            df = df.drop_duplicates(subset=["ts_code", "end_date", "holder_name"], keep="last")
            cols, vals = _df_to_values(df)
            _auto_add_columns(conn, "top10_floatholders", cols, df)
            _auto_widen_columns(conn, "top10_floatholders", cols, df)
            sql = (
                f"INSERT INTO top10_floatholders ({','.join(cols)}) VALUES %s "
                f"ON CONFLICT ON CONSTRAINT uq_top10_float DO NOTHING"
            )
            with conn.cursor() as cur:
                execute_values(cur, sql, vals)
            conn.commit()
            total += len(df)
            if len(df) < 3000:
                break
            offset += 3000
            _time.sleep(0.6)

        if total > 0:
            logger.info("sync: top10_floatholders (period=%s) +%d rows", period, total)
            return total
        logger.info("sync: top10_floatholders (period=%s) empty, trying older quarter", period)

    logger.info("sync: top10_floatholders no data found in recent quarters")
    return 0


def sync_stk_holdernumber(conn, svc: TushareService) -> int:
    """Shareholder count — pull last 90 days."""
    now = datetime.now()
    start = (now - timedelta(days=90)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    total = 0
    offset = 0
    while True:
        try:
            df = svc.stk_holdernumber(start_date=start, end_date=end,
                                      offset=str(offset), limit="3000")
        except Exception:
            logger.warning("stk_holdernumber fetch offset=%d failed", offset, exc_info=True)
            break
        if df is None or df.empty:
            break
        df = df.drop_duplicates(subset=["ts_code", "end_date", "ann_date"], keep="last")
        cols, vals = _df_to_values(df)
        sql = (
            f"INSERT INTO stk_holdernumber ({','.join(cols)}) VALUES %s "
            f"ON CONFLICT ON CONSTRAINT uq_stk_holdernumber DO NOTHING"
        )
        with conn.cursor() as cur:
            execute_values(cur, sql, vals)
        conn.commit()
        total += len(df)
        if len(df) < 3000:
            break
        offset += 3000
        _time.sleep(0.6)
    logger.info("sync: stk_holdernumber +%d rows", total)
    return total


# =====================================================================
# Orchestrator — called by scheduler at 15:30
# =====================================================================

def run_post_market_sync(trade_date: str) -> dict[str, bool]:
    """Run all post-market data syncs in-process. Returns {name: success}."""
    from app.shared.sync_tracker import sync_tracker

    logger.info("=== post-market sync started (trade_date=%s) ===", trade_date)
    t0 = _time.time()
    db_url = _db_url()
    svc = TushareService()
    results: dict[str, bool] = {}

    def _run(name: str, fn, *args):
        sync_tracker.begin(name, trade_date)
        try:
            row_count = fn(*args)
            results[name] = True
            sync_tracker.success(name, row_count if isinstance(row_count, int) else 0)
        except Exception as exc:
            results[name] = False
            sync_tracker.fail(name, exc)
            logger.exception("post-market sync [%s] failed", name)

    with psycopg2.connect(db_url) as conn:
        conn.autocommit = False

        _run("stock_basic", sync_stock_basic, conn, svc)
        _run("trade_cal", sync_trade_cal, conn, svc)
        _run("daily_bars", sync_daily_bars, conn, svc)
        _run("stk_limit", sync_stk_limit, conn, svc, trade_date)
        _run("st_list", sync_st_list, conn, svc, trade_date)
        _run("forecast", sync_forecast, conn, svc)
        _run("disclosure", sync_disclosure, conn, svc)
        _run("limit_board", sync_limit_board, conn, svc, trade_date)
        _run("cb", sync_cb, conn, svc, trade_date)
        _run("moneyflow", sync_moneyflow, conn, svc, trade_date)
        _run("news_batch", sync_news_batch, conn, svc)
        _run("anns", sync_anns, conn, svc, trade_date)
        _run("classify_news", sync_classify_news, conn)
        _run("adj_factor", sync_adj_factor, conn, svc, trade_date)
        _run("sw_daily", sync_sw_daily, conn, svc, trade_date)
        _run("stk_auction", sync_stk_auction, conn, svc, trade_date)
        _run("eco_cal", sync_eco_cal, conn, svc)
        _run("moneyflow_ind", sync_moneyflow_ind, conn, svc, trade_date)
        _run("index_global", sync_index_global, conn, svc)
        _run("concepts", sync_concepts, conn, svc)
        _run("share_float", sync_share_float, conn, svc, trade_date)
        _run("stk_holdertrade", sync_stk_holdertrade, conn, svc, trade_date)
        _run("margin", sync_margin, conn, svc, trade_date)
        _run("top_inst", sync_top_inst, conn, svc, trade_date)
        _run("index_dailybasic", sync_index_dailybasic, conn, svc, trade_date)
        _run("top10_floatholders", sync_top10_floatholders, conn, svc)
        _run("stk_holdernumber", sync_stk_holdernumber, conn, svc)

    elapsed = _time.time() - t0
    ok = sum(1 for v in results.values() if v)
    fail = sum(1 for v in results.values() if not v)
    logger.info("=== post-market sync done: %d OK, %d FAIL, %.1fs ===", ok, fail, elapsed)
    for name, success in results.items():
        if not success:
            logger.warning("  FAILED: %s", name)
    return results


def run_minutes_subprocess() -> None:
    """Launch sync_minutes_incremental.py as isolated subprocess."""
    script = SCRIPTS_DIR / "sync_minutes_incremental.py"
    if not script.exists():
        logger.error("sync_minutes script not found: %s", script)
        return
    try:
        log_dir = SCRIPTS_DIR.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        from datetime import date
        log_file = log_dir / f"sync_minutes_{date.today().strftime('%Y%m%d')}.log"
        fh = open(log_file, "a", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            cwd=str(SCRIPTS_DIR.parent),
            stdout=fh,
            stderr=subprocess.STDOUT,
        )
        logger.info("sync_minutes subprocess started (PID=%d), log=%s", proc.pid, log_file)
    except Exception:
        logger.exception("failed to start sync_minutes subprocess")
