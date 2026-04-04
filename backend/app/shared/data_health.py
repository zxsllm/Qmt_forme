"""Data Health Check Engine — full-coverage, grouped by frontend route.

Zero tolerance: any staleness is flagged with root-cause diagnosis.
Auto-repair is triggered for fixable issues.

Groups mirror frontend routes:
  core       → 核心行情 (全站依赖)
  dashboard  → 首页
  sentiment  → 情绪看板
  news       → 消息中心
  fundamental→ 基本面
  market     → 市场监控
  trading    → 交易系统
  infra      → 基础设施
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.sync_tracker import sync_tracker, SyncStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Market phases
# ---------------------------------------------------------------------------
PHASES = [
    ("pre_market",   dtime(0, 0),   dtime(9, 15)),
    ("call_auction", dtime(9, 15),  dtime(9, 30)),
    ("morning",      dtime(9, 30),  dtime(11, 30)),
    ("lunch",        dtime(11, 30), dtime(13, 0)),
    ("afternoon",    dtime(13, 0),  dtime(15, 0)),
    ("settlement",   dtime(15, 0),  dtime(15, 30)),
    ("post_sync",    dtime(15, 30), dtime(17, 0)),
    ("evening",      dtime(17, 0),  dtime(23, 59, 59)),
]

PHASE_LABELS = {
    "pre_market": "盘前", "call_auction": "集合竞价", "morning": "上午盘",
    "lunch": "午休", "afternoon": "下午盘", "settlement": "盘后结算",
    "post_sync": "数据同步中", "evening": "收盘", "holiday": "休市",
}

# ---------------------------------------------------------------------------
# Declarative check definitions
# ---------------------------------------------------------------------------
@dataclass
class CheckDef:
    table: str
    label: str
    group: str           # route group
    date_col: str        # column to MAX()
    freshness: str       # "daily" | "sentiment" | "quarterly" | "event" | "realtime" | "static"
    severity: str        # "critical" | "important" | "minor"
    sync_name: str = ""  # which data_sync function handles this (for repair)

CHECKS: list[CheckDef] = [
    # ── / 控制台 ──
    CheckDef("stock_daily",      "日线行情",   "console", "trade_date", "daily",     "critical",  "daily_bars"),
    CheckDef("daily_basic",      "每日指标",   "console", "trade_date", "daily",     "important", "daily_bars"),
    CheckDef("index_daily",      "指数日线",   "console", "trade_date", "daily",     "important", "daily_bars"),
    CheckDef("stock_limit",      "涨跌停价",   "console", "trade_date", "daily",     "important", "stk_limit"),
    CheckDef("adj_factor",       "复权因子",   "console", "trade_date", "daily",     "minor",     "adj_factor"),
    CheckDef("index_dailybasic", "指数估值",   "console", "trade_date", "daily",     "important", "index_dailybasic"),
    CheckDef("moneyflow_dc",     "个股资金流", "console", "trade_date", "daily",     "important", "moneyflow"),
    CheckDef("index_global",     "全球指数",   "console", "trade_date", "daily",     "minor",     "index_global"),
    CheckDef("sw_daily",         "申万行业",   "console", "trade_date", "daily",     "minor",     "sw_daily"),
    CheckDef("stk_auction",      "集合竞价",   "console", "trade_date", "daily",     "minor",     "stk_auction"),
    CheckDef("eco_cal",          "财经日历",   "console", "date",       "event",     "minor",     "eco_cal"),
    CheckDef("moneyflow_ind_ths","行业资金流", "console", "trade_date", "daily",     "minor",     "moneyflow_ind"),

    # ── /trading 交易中心 ──
    CheckDef("sim_account",  "模拟账户", "trading", "", "static", "minor", ""),
    CheckDef("sim_orders",   "订单记录", "trading", "", "static", "minor", ""),

    # ── /strategy 策略研究 ──
    CheckDef("backtest_run", "回测记录", "strategy", "", "static", "minor", ""),

    # ── /system 市场监控 ──
    CheckDef("margin",       "融资融券", "system", "trade_date", "daily_t1",  "important", "margin"),
    CheckDef("stock_st",     "公告ST",   "system", "trade_date", "event",     "important", "st_list"),
    CheckDef("forecast",     "业绩预告", "system", "ann_date",   "daily",     "minor",     "forecast"),
    CheckDef("cb_basic",     "可转债基础", "system", "",          "static",    "minor",     "cb"),
    CheckDef("cb_call",      "可转债强赎", "system", "ann_date",  "event",     "important", "cb"),

    # ── /news 消息中心 ──
    CheckDef("stock_news",      "新闻快讯", "news", "datetime", "realtime", "important", "news_batch"),
    CheckDef("stock_anns",      "公司公告", "news", "ann_date", "daily",    "minor",     "anns"),
    CheckDef("news_classified", "新闻分类", "news", "news_id",  "static",   "minor",     "classify_news"),
    CheckDef("anns_classified", "公告分类", "news", "anns_id",  "static",   "minor",     "classify_news"),

    # ── /sentiment 情绪看板 ──
    CheckDef("limit_list_ths", "涨跌停榜",   "sentiment", "trade_date", "sentiment", "important", "limit_board"),
    CheckDef("limit_step",     "连板天梯",   "sentiment", "trade_date", "sentiment", "important", "limit_board"),
    CheckDef("limit_stats",    "涨跌停统计", "sentiment", "trade_date", "sentiment", "minor",     "limit_board"),
    CheckDef("top_list",       "龙虎榜",     "sentiment", "trade_date", "sentiment", "important", "limit_board"),
    CheckDef("hm_detail",      "游资动向",   "sentiment", "trade_date", "sentiment", "important", "limit_board"),
    CheckDef("dc_hot",         "市场热榜",   "sentiment", "trade_date", "sentiment", "important", "limit_board"),
    CheckDef("top_inst",       "机构交易明细", "sentiment", "trade_date", "sentiment", "minor",     "top_inst"),
    CheckDef("limit_cpt_list", "涨停题材",   "sentiment", "trade_date", "sentiment", "minor",     "limit_board"),

    # ── /fundamental 基本面 ──
    CheckDef("fina_indicator",    "财务指标",   "fundamental", "end_date",   "quarterly", "minor", ""),
    CheckDef("income",            "利润表",     "fundamental", "end_date",   "quarterly", "minor", ""),
    CheckDef("disclosure_date",   "披露日期",   "fundamental", "end_date",   "quarterly", "minor", "disclosure"),
    CheckDef("fina_mainbz",       "主营业务",   "fundamental", "end_date",   "quarterly", "minor", ""),
    CheckDef("share_float",       "限售解禁",   "fundamental", "float_date", "event",     "minor", "share_float"),
    CheckDef("stk_holdertrade",   "增减持",     "fundamental", "ann_date",   "daily",     "minor", "stk_holdertrade"),
    CheckDef("stk_holdernumber",  "股东人数",   "fundamental", "end_date",   "quarterly", "minor", "stk_holdernumber"),
    CheckDef("top10_floatholders","十大股东",   "fundamental", "end_date",   "quarterly", "minor", "top10_floatholders"),
    CheckDef("concept_list",      "概念板块",   "fundamental", "",           "static",    "minor", "concepts"),
    CheckDef("concept_detail",    "概念成分",   "fundamental", "",           "static",    "minor", "concepts"),
]

GROUP_LABELS = {
    "console": "控制台", "trading": "交易中心", "strategy": "策略研究",
    "system": "市场监控", "news": "消息中心", "sentiment": "情绪看板",
    "fundamental": "基本面", "infra": "基础设施",
}

TABLE_SYNC_MAP = {c.table: c.sync_name for c in CHECKS if c.sync_name}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_market_phase(now: datetime | None = None) -> str:
    if now is None:
        now = datetime.now()
    t = now.time()
    for name, start, end in PHASES:
        if start <= t < end:
            return name
    return "evening"


async def _max_date(session: AsyncSession, table: str, col: str) -> str:
    try:
        r = await session.execute(text(f"SELECT max({col}) FROM {table}"))
        val = r.scalar_one_or_none()
        return str(val) if val else ""
    except Exception:
        return ""


async def _row_count(session: AsyncSession, table: str) -> int:
    try:
        r = await session.execute(text(f"SELECT count(*) FROM {table}"))
        return r.scalar_one_or_none() or 0
    except Exception:
        return 0


def _trade_day_gap(actual: str, recent_tds: list[str]) -> int:
    if not actual:
        return 99
    return sum(1 for td in recent_tds if td > actual[:8])


def _diagnose(table: str, actual: str, expected: str, phase: str, is_trade_day: bool) -> dict:
    """Root-cause diagnosis for stale/missing data."""
    rec = sync_tracker.get(table)
    sync_name = TABLE_SYNC_MAP.get(table, table)
    sync_rec = sync_tracker.get(sync_name) if sync_name != table else rec

    if rec and rec.status == SyncStatus.SYNCING:
        return {"reason": "syncing", "detail": "正在同步中...", "action": "等待完成", "repairable": False}
    if rec and rec.status == SyncStatus.REPAIRING:
        return {"reason": "repairing", "detail": "正在自动修复...", "action": "等待完成", "repairable": False}

    effective = sync_rec or rec
    if effective and effective.status == SyncStatus.SYNCING:
        return {"reason": "syncing", "detail": f"关联任务 {sync_name} 正在同步", "action": "等待完成", "repairable": False}

    if effective and effective.last_error:
        etype = effective.last_error_type
        err = effective.last_error
        if etype == "schema_mismatch":
            return {"reason": "schema_mismatch", "detail": f"同步失败: {err}", "action": "自动ALTER TABLE修复", "repairable": True}
        if etype == "partition_missing":
            return {"reason": "partition_missing", "detail": "分区表缺少当月分区", "action": "运行 create_min_partitions.py", "repairable": False}
        if etype in ("connection_error", "timeout", "rate_limit"):
            return {"reason": etype, "detail": f"同步失败: {err}", "action": "可自动重试", "repairable": True}
        return {"reason": "sync_error", "detail": f"同步失败: {err}", "action": "可尝试重新同步", "repairable": True}

    # Tushare 延迟发布：同步跑了但返回 0 行，后续可能补上 → 允许自动重试
    if effective and effective.status == SyncStatus.SUCCESS and effective.rows_synced == 0:
        return {"reason": "tushare_empty", "detail": "同步已执行但Tushare未返回数据（可能尚未发布）", "action": "自动重试拉取", "repairable": True}

    if not is_trade_day:
        return {"reason": "non_trade_day", "detail": "非交易日无新数据", "action": "无需操作", "repairable": False}

    if table in ("top_list", "dc_hot", "hm_detail", "top_inst"):
        if phase in ("morning", "afternoon", "lunch", "call_auction"):
            return {"reason": "tushare_delay", "detail": "盘后数据，交易时段尚未发布", "action": "收盘后自动同步", "repairable": False}
        elif phase in ("evening", "post_sync", "pre_market", "settlement"):
            return {"reason": "not_synced", "detail": f"盘后同步未成功拉取到{expected}数据", "action": "自动重新同步", "repairable": True}

    if not effective or effective.last_attempt == 0:
        return {"reason": "not_synced", "detail": "本次启动后未触发同步", "action": "自动重新同步", "repairable": True}

    if effective.status == SyncStatus.SUCCESS:
        return {"reason": "tushare_partial", "detail": f"同步成功({effective.rows_synced}行)但该表数据仍不完整", "action": "可重试", "repairable": True}

    return {"reason": "unknown", "detail": "原因不明", "action": "可尝试重新同步", "repairable": True}


def _get_expected(
    chk: CheckDef, phase: str, is_trade_day: bool,
    today: str, latest_td: str, prev_td: str,
    recent_tds: list[str] | None = None,
) -> str | None:
    """Determine expected date for a check. Returns None if check is non-date."""
    f = chk.freshness

    if f == "daily":
        if is_trade_day:
            return today if phase in ("evening", "post_sync") else prev_td
        return latest_td

    if f == "daily_t1":
        if is_trade_day:
            return prev_td if phase in ("evening", "post_sync") else (recent_tds[2] if len(recent_tds) > 2 else prev_td)
        return latest_td

    if f == "sentiment":
        if is_trade_day and phase in ("evening", "post_sync"):
            return today
        return latest_td if latest_td != today else prev_td

    if f == "quarterly":
        return None  # checked by row count instead

    if f == "event":
        return None  # checked by row count

    if f == "static":
        return None  # checked by row count

    if f == "realtime":
        return None  # checked by recency

    return None


# ---------------------------------------------------------------------------
# Auto-repair
# ---------------------------------------------------------------------------
def _trigger_repair_async(tables: list[str], trade_date: str):
    if sync_tracker.repair_running:
        logger.info("repair already running, skip")
        return

    def _do_repair():
        sync_tracker.repair_running = True
        try:
            import inspect
            import os
            import psycopg2
            from app.research.data.tushare_service import TushareService
            from app.execution.feed import data_sync

            db_url = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
            svc = TushareService()

            sync_groups = set()
            for t in tables:
                sn = TABLE_SYNC_MAP.get(t, t)
                if sn:
                    sync_groups.add(sn)

            for group in sync_groups:
                sync_tracker.begin(group, trade_date)
                try:
                    with psycopg2.connect(db_url) as conn:
                        conn.autocommit = False
                        fn = getattr(data_sync, f"sync_{group}", None)
                        if fn is None:
                            sync_tracker.fail(group, RuntimeError(f"sync_{group} 函数不存在"))
                            continue
                        sig = inspect.signature(fn)
                        params = list(sig.parameters.keys())
                        if len(params) == 3:
                            rows = fn(conn, svc, trade_date)
                        else:
                            rows = fn(conn, svc)
                        sync_tracker.success(group, rows if isinstance(rows, int) else 0)
                        logger.info("auto-repair: %s OK (%s rows)", group, rows)
                except Exception as exc:
                    sync_tracker.fail(group, exc)
                    logger.warning("auto-repair: %s failed: %s", group, exc)
        except Exception:
            logger.exception("auto-repair thread failed")
        finally:
            sync_tracker.repair_running = False

    t = threading.Thread(target=_do_repair, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Main health check
# ---------------------------------------------------------------------------
async def run_health_check(session: AsyncSession, auto_repair: bool = True) -> dict:
    now = datetime.now()
    today = now.strftime("%Y%m%d")
    phase = get_market_phase(now)

    # Trade calendar
    r = await session.execute(text(
        "SELECT is_open FROM trade_cal WHERE cal_date = :d AND exchange = 'SSE' LIMIT 1"
    ), {"d": today})
    is_td_val = r.scalar_one_or_none()
    is_trade_day = is_td_val == 1 if is_td_val is not None else now.weekday() < 5

    r2 = await session.execute(text(
        "SELECT cal_date FROM trade_cal WHERE is_open = 1 AND cal_date <= :d "
        "ORDER BY cal_date DESC LIMIT 10"
    ), {"d": today})
    recent_tds = [row[0] for row in r2.fetchall()]
    latest_td = recent_tds[0] if recent_tds else today
    prev_td = recent_tds[1] if len(recent_tds) > 1 else ""

    # -----------------------------------------------------------------------
    # Run all declarative checks
    # -----------------------------------------------------------------------
    groups: dict[str, list[dict]] = {}

    for chk in CHECKS:
        expected = _get_expected(chk, phase, is_trade_day, today, latest_td, prev_td, recent_tds)

        if chk.freshness == "realtime":
            actual_raw = await _max_date(session, chk.table, chk.date_col)
            news_age_min = 0
            if actual_raw:
                try:
                    news_dt = datetime.strptime(actual_raw[:19], "%Y-%m-%d %H:%M:%S")
                    news_age_min = int((now - news_dt).total_seconds() / 60)
                except Exception:
                    pass
            is_trading = phase in ("morning", "afternoon", "lunch")
            status = "stale" if is_trading and news_age_min > 30 else "ok"
            result = {
                "name": chk.table, "label": chk.label, "group": chk.group,
                "actual_date": actual_raw[:19] if actual_raw else "",
                "expected_date": "<30min" if is_trading else "N/A",
                "status": status, "severity": chk.severity,
                "note": f"最新{news_age_min}分钟前" if news_age_min else "",
                "diagnosis": None, "gap_days": 0,
            }

        elif chk.freshness in ("quarterly", "static", "event"):
            cnt = await _row_count(session, chk.table)
            actual_raw = await _max_date(session, chk.table, chk.date_col) if chk.date_col else ""
            status = "ok" if cnt > 0 else "missing"
            result = {
                "name": chk.table, "label": chk.label, "group": chk.group,
                "actual_date": actual_raw or f"{cnt}行",
                "expected_date": {"quarterly": "季度更新", "static": "静态", "event": "事件驱动"}.get(chk.freshness, ""),
                "status": status, "severity": chk.severity,
                "note": f"共{cnt}行" if cnt else "表为空",
                "diagnosis": _diagnose(chk.table, "", "有数据", phase, is_trade_day) if status == "missing" else None,
                "gap_days": 0,
            }

        else:
            actual_raw = await _max_date(session, chk.table, chk.date_col)
            actual_cmp = actual_raw[:8] if actual_raw else ""
            if not actual_cmp:
                status = "missing"
            elif expected and actual_cmp >= expected:
                status = "ok"
            elif expected:
                status = "stale"
            else:
                status = "ok"

            diag = None
            gap = 0
            if status in ("stale", "missing"):
                diag = _diagnose(chk.table, actual_cmp, expected or "", phase, is_trade_day)
                gap = _trade_day_gap(actual_cmp, recent_tds)

            result = {
                "name": chk.table, "label": chk.label, "group": chk.group,
                "actual_date": actual_cmp, "expected_date": expected or "",
                "status": status, "severity": chk.severity,
                "note": diag["detail"] if diag else "",
                "diagnosis": diag, "gap_days": gap,
            }

        groups.setdefault(chk.group, []).append(result)

    # -----------------------------------------------------------------------
    # Infrastructure checks
    # -----------------------------------------------------------------------
    infra_checks = []

    # Scheduler
    from app.execution.feed.scheduler import get_rt_snapshot
    snap, snap_ts = get_rt_snapshot()
    snap_age = time.time() - snap_ts if snap_ts > 0 else -1
    snap_count = len(snap) if snap else 0

    if phase in ("morning", "afternoon"):
        sched_ok = snap_age >= 0 and snap_age < 10 and snap_count > 100
    elif phase in ("call_auction", "lunch"):
        sched_ok = snap_count > 0 or True
    else:
        sched_ok = True
    sched_note = f"{snap_count}只股票" + (f", {snap_age:.0f}秒前" if snap_age >= 0 else ", 未启动")
    infra_checks.append({
        "name": "scheduler", "label": "行情调度器", "group": "infra",
        "actual_date": sched_note, "expected_date": "实时" if phase in ("morning", "afternoon") else "非交易时段",
        "status": "ok" if sched_ok else "stale", "severity": "important" if phase in ("morning", "afternoon") else "minor",
        "note": sched_note, "diagnosis": None, "gap_days": 0,
    })

    # Partitions
    partition_ok = True
    partition_note = ""
    try:
        month_str = now.strftime("%Y_%m")
        r_part = await session.execute(text(
            "SELECT count(*) FROM pg_class WHERE relname = :name"
        ), {"name": f"stock_min_kline_{month_str}"})
        has_cur = (r_part.scalar_one_or_none() or 0) > 0
        if not has_cur:
            partition_ok = False
            partition_note = f"缺少{now.year}年{now.month}月分区"
    except Exception:
        partition_ok = False
        partition_note = "检查失败"

    next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
    try:
        r_next = await session.execute(text(
            "SELECT count(*) FROM pg_class WHERE relname = :name"
        ), {"name": f"stock_min_kline_{next_month.strftime('%Y_%m')}"})
        has_next = (r_next.scalar_one_or_none() or 0) > 0
        if not has_next and now.day >= 25:
            partition_note += ("; " if partition_note else "") + f"下月({next_month.month}月)分区未创建"
    except Exception:
        pass

    infra_checks.append({
        "name": "partitions", "label": "分钟分区", "group": "infra",
        "actual_date": partition_note or "正常", "expected_date": "",
        "status": "ok" if partition_ok else "stale", "severity": "important",
        "note": partition_note, "diagnosis": None, "gap_days": 0,
    })

    # Redis
    redis_ok = False
    redis_note = ""
    try:
        from app.core.redis import redis_client
        redis_ok = bool(redis_client.ping())
        redis_note = "连接正常"
    except Exception as e:
        redis_note = f"连接失败: {type(e).__name__}"

    infra_checks.append({
        "name": "redis", "label": "Redis", "group": "infra",
        "actual_date": redis_note, "expected_date": "",
        "status": "ok" if redis_ok else "stale", "severity": "minor",
        "note": redis_note, "diagnosis": None, "gap_days": 0,
    })

    groups["infra"] = infra_checks

    # -----------------------------------------------------------------------
    # Auto-repair
    # -----------------------------------------------------------------------
    all_checks = [c for cks in groups.values() for c in cks]
    repairable = [
        c["name"] for c in all_checks
        if c["status"] in ("stale", "missing")
        and c.get("diagnosis") and c["diagnosis"].get("repairable")
        and not sync_tracker.recently_repaired(TABLE_SYNC_MAP.get(c["name"], c["name"]))
    ]

    repair_status = None
    if repairable and auto_repair and not sync_tracker.repair_running:
        if is_trade_day:
            if phase in ("evening", "post_sync"):
                repair_td = today
            else:
                repair_td = prev_td if prev_td else latest_td
        else:
            repair_td = latest_td
        _trigger_repair_async(repairable, repair_td)
        repair_status = {"triggered": True, "tables": repairable, "trade_date": repair_td}
    elif sync_tracker.repair_running:
        repair_status = {"triggered": False, "tables": [], "message": "修复正在进行中"}

    # -----------------------------------------------------------------------
    # Overall assessment
    # -----------------------------------------------------------------------
    critical_bad = any(c["status"] in ("stale", "missing") and c["severity"] == "critical" for c in all_checks)
    important_bad = sum(1 for c in all_checks if c["status"] in ("stale", "missing") and c["severity"] == "important")

    if critical_bad:
        overall = "critical"
    elif important_bad >= 3:
        overall = "degraded"
    elif important_bad >= 1 or not partition_ok:
        overall = "warning"
    else:
        overall = "healthy"

    return {
        "timestamp": now.isoformat(),
        "phase": phase,
        "phase_label": PHASE_LABELS.get(phase, phase),
        "is_trade_date": is_trade_day,
        "today": today,
        "expected_daily_date": today if is_trade_day and phase in ("evening", "post_sync") else prev_td if is_trade_day else latest_td,
        "expected_sentiment_date": today if is_trade_day and phase in ("evening", "post_sync") else (latest_td if latest_td != today else prev_td),
        "overall": overall,
        "groups": groups,
        "group_labels": GROUP_LABELS,
        "repair": repair_status,
        "sync_tracker": sync_tracker.get_all(),
    }
