"""Risk alert engine — generates warnings for ST, earnings forecast, CB forced
redemption, share unlock, and shareholder increase/decrease.

Called by GET /api/v1/risk/alerts. All queries are async via SQLAlchemy session.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _clean(rows: list[dict]) -> list[dict]:
    """Replace NaN/None with JSON-safe values."""
    for row in rows:
        for k, v in row.items():
            if v is None or (isinstance(v, float) and str(v) == "nan"):
                row[k] = None
    return rows


def _format_yyyymmdd(value: str) -> str:
    return f"{value[:4]}-{value[4:6]}-{value[6:]}" if value and len(value) == 8 else value


def _st_warning_pattern() -> str:
    return r"(?:退市风险警示|其他风险警示|风险警示)"


def _has_confirmed_st_warning(text_value: str) -> bool:
    if not text_value or "可能被实施" in text_value:
        return False

    warning = _st_warning_pattern()
    patterns = [
        rf"(?:被实施|实施|将被实施)[^。；，、]*{warning}",
        rf"{warning}[^。；，、]*(?:被实施|实施|将被实施)",
        r"股票简称[^。；，、]*(?:变更为|更名为)[^。；，、]*[“\"]?\*?ST",
    ]
    return any(re.search(pattern, text_value) for pattern in patterns)


def _extract_effective_date(text_value: str, default_year: str = "") -> str:
    """Extract an ST effective date from announcement/news text when present."""
    if not text_value:
        return ""

    year = default_year or str(datetime.now().year)
    warning = _st_warning_pattern()

    resume_patterns = [
        rf"于(\d{{4}})年(\d{{1,2}})月(\d{{1,2}})日(?:开市)?起复牌[^。；]*(?:被实施|实施|将被实施)[^。；，、]{{0,12}}{warning}",
        rf"于(\d{{1,2}})月(\d{{1,2}})日(?:开市)?起复牌[^。；]*(?:被实施|实施|将被实施)[^。；，、]{{0,12}}{warning}",
        r"于(\d{4})年(\d{1,2})月(\d{1,2})日(?:开市)?起复牌[^。；]*(?:简称|股票简称)[^。；]*[“\"]?\*?ST",
        r"于(\d{1,2})月(\d{1,2})日(?:开市)?起复牌[^。；]*(?:简称|股票简称)[^。；]*[“\"]?\*?ST",
        rf"将于(\d{{4}})年(\d{{1,2}})月(\d{{1,2}})日(?:开市)?(?:起)?[^。；]*(?:被实施|实施|将被实施)[^。；，、]{{0,12}}{warning}",
        rf"将于(\d{{1,2}})月(\d{{1,2}})日(?:开市)?(?:起)?[^。；]*(?:被实施|实施|将被实施)[^。；，、]{{0,12}}{warning}",
    ]
    for pattern in resume_patterns:
        match = re.search(pattern, text_value)
        if match and len(match.groups()) == 3:
            y, m, d = match.groups()
            return f"{int(y):04d}{int(m):02d}{int(d):02d}"
        if match:
            m, d = match.groups()
            return f"{int(year):04d}{int(m):02d}{int(d):02d}"

    contextual_patterns = [
        rf"自(\d{{4}})年(\d{{1,2}})月(\d{{1,2}})日(?:开市)?起[^。；]*(?:被实施|实施|将被实施)[^。；，、]{{0,12}}{warning}",
        rf"于(\d{{4}})年(\d{{1,2}})月(\d{{1,2}})日(?:开市)?起[^。；]*(?:被实施|实施|将被实施)[^。；，、]{{0,12}}{warning}",
        rf"(\d{{4}})年(\d{{1,2}})月(\d{{1,2}})日(?:开市)?起[^。；]*(?:被实施|实施|将被实施)[^。；，、]{{0,12}}{warning}",
    ]
    for pattern in contextual_patterns:
        match = re.search(pattern, text_value)
        if match:
            y, m, d = match.groups()
            return f"{int(y):04d}{int(m):02d}{int(d):02d}"

    month_day_patterns = [
        rf"自(\d{{1,2}})月(\d{{1,2}})日(?:开市)?起[^。；]*(?:被实施|实施|将被实施)[^。；，、]{{0,12}}{warning}",
        rf"于(\d{{1,2}})月(\d{{1,2}})日(?:开市)?起[^。；]*(?:被实施|实施|将被实施)[^。；，、]{{0,12}}{warning}",
        rf"(\d{{1,2}})月(\d{{1,2}})日(?:开市)?起[^。；]*(?:被实施|实施|将被实施)[^。；，、]{{0,12}}{warning}",
    ]
    for pattern in month_day_patterns:
        match = re.search(pattern, text_value)
        if match:
            m, d = match.groups()
            return f"{int(year):04d}{int(m):02d}{int(d):02d}"

    generic_patterns = [
        r"自(\d{4})年(\d{1,2})月(\d{1,2})日(?:开市)?起",
        r"于(\d{4})年(\d{1,2})月(\d{1,2})日(?:开市)?起",
        r"(\d{4})年(\d{1,2})月(\d{1,2})日(?:开市)?起",
        r"(\d{4})(\d{2})(\d{2})起",
    ]
    for pattern in generic_patterns:
        match = re.search(pattern, text_value)
        if match:
            y, m, d = match.groups()
            return f"{int(y):04d}{int(m):02d}{int(d):02d}"
    return ""


def _mentions_st_warning_for_stock(content: str, name: str, code: str, window: int = 80) -> bool:
    """Return True only when ST warning terms appear near a stock mention."""
    if not content:
        return False

    code_plain = code.replace(".", "") if code else ""
    mentions = [m for m in [name, code, code_plain] if m]

    for mention in mentions:
        start = content.find(mention)
        while start >= 0:
            colon_pos = content.find("：", start, start + len(mention) + 5)
            if colon_pos >= 0:
                segment = content[colon_pos + 1:colon_pos + 1 + window * 2]
                term_pos = re.search(_st_warning_pattern() + r"|股票简称", segment)
                next_colon = segment.find("：")
                if term_pos and (next_colon < 0 or term_pos.start() < next_colon) and _has_confirmed_st_warning(segment):
                    return True
                start = content.find(mention, start + len(mention))
                continue

            raw = content[start:min(len(content), start + len(mention) + window * 4)]
            boundary_positions = [
                pos for pos in [
                    raw.find("【", len(mention)),
                    raw.find("】", len(mention)),
                    raw.find("：", len(mention)),
                    *[raw.find(mark, len(mention)) for mark in "①②③④⑤⑥⑦⑧⑨⑩"],
                ] if pos >= 0
            ]
            snippet = raw[:min(boundary_positions)] if boundary_positions else raw
            if _has_confirmed_st_warning(snippet):
                return True
            start = content.find(mention, start + len(mention))
    return False


def _financial_st_reason(
    revenue: float | None,
    net_profit: float | None,
    profit_dedt: float | None,
    bps: float | None,
) -> str:
    if bps is not None and bps < 0:
        return f"2025年报每股净资产为负（bps={bps:.4f}）"
    if (
        net_profit is not None
        and profit_dedt is not None
        and revenue is not None
        and net_profit < 0
        and profit_dedt < 0
        and revenue < 300_000_000
    ):
        return "2025年报归母净利润、扣非净利润为负，且营业收入低于3亿元"
    if (
        net_profit is not None
        and profit_dedt is not None
        and bps is not None
        and net_profit < 0
        and profit_dedt < 0
        and 0 <= bps < 0.05
    ):
        return f"2025年报归母净利润、扣非净利润为负，且每股净资产接近零（bps={bps:.4f}）"
    return ""


async def _st_alerts(session: AsyncSession) -> list[dict]:
    """A. ST warnings: newly ST-listed stocks + forecast-based consecutive-loss risk."""
    alerts: list[dict] = []

    current_r = await session.execute(text("""
        SELECT DISTINCT ts_code FROM stock_st
        WHERE trade_date = (SELECT MAX(trade_date) FROM stock_st)
    """))
    current_st_codes = {row[0] for row in current_r.fetchall()}

    # 1) 近期新增ST：对比最早可用日期 vs 最新日期，找出期间新增的ST股票
    diff_r = await session.execute(text("""
        WITH earliest AS (
            SELECT DISTINCT ts_code FROM stock_st
            WHERE trade_date = (SELECT MIN(trade_date) FROM stock_st)
        ),
        latest AS (
            SELECT DISTINCT ON (ts_code) ts_code, name, type_name
            FROM stock_st
            WHERE trade_date = (SELECT MAX(trade_date) FROM stock_st)
        ),
        first_seen AS (
            SELECT ts_code, MIN(trade_date) AS since_date
            FROM stock_st GROUP BY ts_code
        )
        SELECT l.ts_code, l.name, l.type_name, f.since_date
        FROM latest l
        JOIN first_seen f ON l.ts_code = f.ts_code
        WHERE l.ts_code NOT IN (SELECT ts_code FROM earliest)
        ORDER BY f.since_date DESC
    """))
    for row in diff_r.fetchall():
        since = row[3] or ""
        alerts.append({
            "type": "ST预警",
            "level": "high",
            "ts_code": row[0],
            "name": row[1],
            "detail": f"新增风险警示: {row[2] or 'ST'}（{since}起）",
            "time": _format_yyyymmdd(since),
            "effective_date": since,
            "source": "stock_st",
        })

    alerted_codes = {a["ts_code"] for a in alerts}

    # 2) 已公告实施退市风险警示，但 stock_st 次日才更新的股票。
    #    一旦 stock_st 最新名单包含该股票，上面的官方口径自然覆盖这里。
    cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y%m%d")
    ann_r = await session.execute(text("""
        SELECT a.ts_code, b.name, a.ann_date, a.title, a.url
        FROM stock_anns a
        JOIN stock_basic b ON a.ts_code = b.ts_code
        WHERE a.ann_date >= :cutoff
          AND (
              a.title LIKE '%%被实施退市风险警示%%'
              OR a.title LIKE '%%实施退市风险警示%%'
              OR a.title LIKE '%%将被实施退市风险警示%%'
              OR a.title LIKE '%%被实施其他风险警示%%'
              OR a.title LIKE '%%实施其他风险警示%%'
              OR a.title LIKE '%%将被实施其他风险警示%%'
              OR a.title LIKE '%%股票简称变更为%%ST%%'
          )
          AND a.title NOT LIKE '%%可能被实施%%'
        ORDER BY a.ann_date DESC
        LIMIT 100
    """), {"cutoff": cutoff})
    for row in ann_r.fetchall():
        ts_code, name, ann_date, title, url = row[0], row[1], row[2] or "", row[3] or "", row[4]
        if ts_code in current_st_codes or ts_code in alerted_codes:
            continue
        effective = _extract_effective_date(title, ann_date[:4] if len(ann_date) >= 4 else "")
        effective_text = _format_yyyymmdd(effective or ann_date)
        warning_label = "风险警示" if "其他风险警示" in title else "退市风险警示"
        alerts.append({
            "type": "ST预警",
            "level": "high",
            "ts_code": ts_code,
            "name": name,
            "detail": f"公告实施{warning_label}: {title}（{effective_text}起）",
            "time": _format_yyyymmdd(ann_date),
            "effective_date": effective or ann_date,
            "ann_url": url,
            "source": "announcement",
        })
        alerted_codes.add(ts_code)

    news_cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")
    news_r = await session.execute(text("""
        WITH recent_news AS (
            SELECT id, datetime, content
            FROM stock_news
            WHERE datetime >= :cutoff
              AND (
                  content LIKE '%%被实施退市风险警示%%'
                  OR content LIKE '%%实施退市风险警示%%'
                  OR content LIKE '%%将被实施退市风险警示%%'
                  OR content LIKE '%%被实施其他风险警示%%'
                  OR content LIKE '%%实施其他风险警示%%'
                  OR content LIKE '%%将被实施其他风险警示%%'
                  OR content LIKE '%%其他风险警示%%'
                  OR content LIKE '%%股票简称变更为%%ST%%'
              )
              AND content NOT LIKE '%%可能被实施%%'
            ORDER BY datetime DESC
            LIMIT 200
        )
        SELECT b.ts_code, b.name, n.datetime, n.content
        FROM recent_news n
        JOIN stock_basic b
          ON n.content LIKE '%%' || b.name || '%%'
          OR n.content LIKE '%%' || replace(b.ts_code, '.', '') || '%%'
          OR n.content LIKE '%%' || b.ts_code || '%%'
        ORDER BY n.datetime DESC
        LIMIT 500
    """), {"cutoff": news_cutoff})
    for row in news_r.fetchall():
        ts_code, name, news_time, content = row[0], row[1], row[2] or "", row[3] or ""
        if ts_code in current_st_codes or ts_code in alerted_codes:
            continue
        if not _mentions_st_warning_for_stock(content, name, ts_code):
            continue
        default_year = str(news_time)[:4] if news_time else ""
        effective = _extract_effective_date(content, default_year)
        effective_text = _format_yyyymmdd(effective) if effective else str(news_time)[:10]
        warning_label = "风险警示" if "其他风险警示" in content else "退市风险警示"
        alerts.append({
            "type": "ST预警",
            "level": "high",
            "ts_code": ts_code,
            "name": name,
            "detail": f"新闻确认{warning_label}: {effective_text}起，按已实施ST处理",
            "time": str(news_time)[:10],
            "effective_date": effective or str(news_time)[:10].replace("-", ""),
            "source": "news",
        })
        alerted_codes.add(ts_code)

    # 4) 财务硬触发兜底：用于 stock_st/公告/新闻尚未更新，但年报数据已经入库的情况。
    #    必须同时满足年报已披露和披露日停牌，避免把普通亏损年报误报为已戴帽。
    annual_end = f"{datetime.now().year - 1}1231"
    financial_r = await session.execute(text("""
        SELECT b.ts_code, b.name, i.ann_date, i.revenue, i.n_income_attr_p,
               fi.profit_dedt, fi.bps
        FROM stock_basic b
        JOIN income i ON i.ts_code = b.ts_code AND i.end_date = :annual_end
        JOIN fina_indicator fi ON fi.ts_code = b.ts_code AND fi.end_date = i.end_date
        JOIN suspend_d s ON s.ts_code = b.ts_code
                        AND s.trade_date = i.ann_date
                        AND s.suspend_type = 'S'
        LEFT JOIN suspend_d s_next ON s_next.ts_code = b.ts_code
                                  AND s_next.trade_date = TO_CHAR(
                                      TO_DATE(i.ann_date, 'YYYYMMDD') + INTERVAL '1 day',
                                      'YYYYMMDD'
                                  )
                                  AND s_next.suspend_type = 'S'
        WHERE i.ann_date >= :cutoff
          AND b.name NOT ILIKE '%%ST%%'
          AND s_next.ts_code IS NULL
          AND (
              fi.bps < 0
              OR (i.n_income_attr_p < 0 AND fi.profit_dedt < 0 AND i.revenue < 300000000)
              OR (i.n_income_attr_p < 0 AND fi.profit_dedt < 0 AND fi.bps >= 0 AND fi.bps < 0.05)
          )
        ORDER BY i.ann_date DESC
        LIMIT 100
    """), {"annual_end": annual_end, "cutoff": cutoff})
    for row in financial_r.fetchall():
        ts_code, name, ann_date = row[0], row[1], row[2] or ""
        if ts_code in current_st_codes or ts_code in alerted_codes:
            continue
        reason = _financial_st_reason(row[3], row[4], row[5], row[6])
        if not reason:
            continue
        alerts.append({
            "type": "ST预警",
            "level": "high",
            "ts_code": ts_code,
            "name": name,
            "detail": f"年报财务触发风险警示: {reason}，且年报披露日停牌，按疑似已实施ST处理",
            "time": _format_yyyymmdd(ann_date),
            "effective_date": ann_date,
            "source": "annual_financial",
        })
        alerted_codes.add(ts_code)

    alerts.sort(key=lambda x: (x.get("effective_date") or "", x.get("time") or ""), reverse=True)
    return alerts


async def _forecast_alerts(session: AsyncSession) -> list[dict]:
    """B. Earnings forecast alerts: recent announcements within last 30 days."""
    alerts: list[dict] = []
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")

    r = await session.execute(text("""
        WITH forecast_url AS (
            SELECT f.ts_code, f.ann_date, f.end_date,
                   (SELECT sa.url FROM stock_anns sa
                    WHERE sa.ts_code = f.ts_code
                      AND ABS(sa.ann_date::bigint - f.ann_date::bigint) <= 3
                      AND (sa.title LIKE '%%业绩预告%%' OR sa.title LIKE '%%业绩快报%%'
                           OR sa.title LIKE '%%预增%%' OR sa.title LIKE '%%预减%%'
                           OR sa.title LIKE '%%扭亏%%' OR sa.title LIKE '%%首亏%%'
                           OR sa.title LIKE '%%续亏%%' OR sa.title LIKE '%%续盈%%'
                           OR sa.title LIKE '%%略增%%' OR sa.title LIKE '%%略减%%')
                    ORDER BY ABS(sa.ann_date::bigint - f.ann_date::bigint) ASC,
                             sa.ann_date DESC
                    LIMIT 1) AS forecast_url,
                   (SELECT sa.url FROM stock_anns sa
                    WHERE sa.ts_code = f.ts_code
                      AND ABS(sa.ann_date::bigint - f.ann_date::bigint) <= 1
                      AND (sa.title LIKE '%%年度报告%%' OR sa.title LIKE '%%季度报告%%'
                           OR sa.title LIKE '%%半年度报告%%' OR sa.title LIKE '%%一季报%%'
                           OR sa.title LIKE '%%三季报%%' OR sa.title LIKE '%%中报%%'
                           OR sa.title LIKE '%%年报%%')
                      AND sa.title NOT LIKE '%%摘要%%'
                      AND sa.title NOT LIKE '%%审计%%'
                      AND sa.title NOT LIKE '%%审核%%'
                      AND sa.title NOT LIKE '%%专项说明%%'
                    ORDER BY ABS(sa.ann_date::bigint - f.ann_date::bigint) ASC,
                             sa.ann_date DESC
                    LIMIT 1) AS report_url
            FROM forecast f
            WHERE f.ann_date >= :cutoff
        )
        SELECT f.ts_code, b.name, f.type, f.ann_date, f.end_date,
               f.p_change_min, f.p_change_max, f.net_profit_min, f.net_profit_max,
               f.source,
               COALESCE(
                   fu.forecast_url,
                   fu.report_url,
                   'http://www.cninfo.com.cn/new/disclosure/stock?stockCode='
                       || split_part(f.ts_code, '.', 1) || '&orgId='
               ) AS ann_url,
               CASE
                   WHEN fu.forecast_url IS NOT NULL THEN 'forecast'
                   WHEN fu.report_url IS NOT NULL THEN 'report'
                   ELSE 'fallback'
               END AS link_type
        FROM forecast f
        JOIN stock_basic b ON f.ts_code = b.ts_code
        JOIN forecast_url fu ON fu.ts_code = f.ts_code
                            AND fu.ann_date = f.ann_date
                            AND fu.end_date = f.end_date
        WHERE f.ann_date >= :cutoff
          AND NOT (f.source = 'anns_parsed'
                   AND EXISTS (SELECT 1 FROM forecast f2
                               WHERE f2.ts_code = f.ts_code
                                 AND f2.source = 'tushare'
                                 AND f2.ann_date >= :cutoff))
        ORDER BY f.ann_date DESC
        LIMIT 300
    """), {"cutoff": cutoff})

    level_map = {
        "预增": "info", "略增": "info", "扭亏": "info", "续盈": "info",
        "预减": "warning", "略减": "warning", "首亏": "warning", "续亏": "warning",
    }

    for row in r.fetchall():
        ts_code, name, ftype, ann_date, end_date = row[0], row[1], row[2], row[3], row[4]
        p_min, p_max = row[5], row[6]
        np_min, np_max = row[7], row[8]
        source, ann_url, link_type = row[9], row[10], row[11]

        pct_range = ""
        if p_min is not None and p_max is not None:
            pct_range = f"{p_min:.0f}%~{p_max:.0f}%"

        profit_str = ""
        if np_min is not None and np_max is not None:
            profit_str = f"净利润 {np_min / 10000:.2f}~{np_max / 10000:.2f} 亿"

        detail_parts = [f"{ftype} — 报告期{end_date}"]
        if pct_range:
            detail_parts.append(f"同比{pct_range}")
        if profit_str:
            detail_parts.append(profit_str)
        if source == "anns_parsed" and not pct_range:
            detail_parts.append("数据待更新")

        alerts.append({
            "type": "业绩预告",
            "level": level_map.get(ftype, "info"),
            "ts_code": ts_code,
            "name": name,
            "forecast_type": ftype,
            "pct_range": pct_range,
            "detail": ", ".join(detail_parts),
            "time": f"{ann_date[:4]}-{ann_date[4:6]}-{ann_date[6:]}" if ann_date and len(ann_date) == 8 else ann_date,
            "ann_url": ann_url,
            "link_type": link_type,
        })

    return alerts


async def _cb_call_alerts(session: AsyncSession) -> list[dict]:
    """C. Convertible bond forced redemption alerts."""
    alerts: list[dict] = []

    r = await session.execute(text("""
        SELECT c.ts_code, b.bond_short_name, b.stk_code, b.stk_short_name,
               c.call_type, c.is_call, c.ann_date, c.call_date, c.call_price
        FROM cb_call c
        JOIN cb_basic b ON c.ts_code = b.ts_code
        WHERE c.is_call LIKE '%满足强赎%'
           OR c.is_call LIKE '%公告提示强赎%'
           OR c.is_call LIKE '%公告实施强赎%'
        ORDER BY c.ann_date DESC NULLS LAST
        LIMIT 50
    """))

    for row in r.fetchall():
        bond_code, bond_name = row[0], row[1]
        stk_code, stk_name = row[2], row[3]
        call_type, is_call = row[4], row[5]
        ann_date, call_date, call_price = row[6], row[7], row[8]

        detail_parts = [f"{bond_name}({bond_code})"]
        if stk_name:
            detail_parts.append(f"正股 {stk_name}({stk_code})")
        detail_parts.append(f"状态: {is_call}")
        if call_date:
            detail_parts.append(f"赎回日 {call_date}")
        if call_price:
            detail_parts.append(f"赎回价 {call_price}")

        alerts.append({
            "type": "可转债强赎",
            "level": "warning",
            "ts_code": stk_code or bond_code,
            "bond_code": bond_code,
            "bond_name": bond_name,
            "stk_code": stk_code,
            "is_call": is_call,
            "call_date": call_date,
            "detail": " | ".join(detail_parts),
            "time": f"{ann_date[:4]}-{ann_date[4:6]}-{ann_date[6:]}" if ann_date and len(ann_date) == 8 else ann_date,
        })

    return alerts


async def _unlock_alerts(session: AsyncSession, trade_date: str = "",
                         days: int = 5) -> list[dict]:
    """D. 限售解禁预警：未来N天内有大额解禁的个股。

    Args:
        trade_date: 起始日期(YYYYMMDD)，默认今天
        days: 向前看N天
    """
    alerts: list[dict] = []
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")
    horizon = (datetime.strptime(trade_date, "%Y%m%d") + timedelta(days=days)).strftime("%Y%m%d")

    r = await session.execute(text("""
        SELECT f.ts_code, b.name, f.float_date, f.float_share, f.float_ratio,
               f.holder_name, f.share_type,
               d.close, d.total_mv
        FROM share_float f
        JOIN stock_basic b ON f.ts_code = b.ts_code
        LEFT JOIN daily_basic d ON f.ts_code = d.ts_code
             AND d.trade_date = (
                 SELECT MAX(trade_date) FROM daily_basic
                 WHERE ts_code = f.ts_code AND trade_date <= :td
             )
        WHERE f.float_date BETWEEN :td AND :horizon
          AND f.float_share IS NOT NULL
        ORDER BY COALESCE(f.float_ratio, 0) DESC, f.float_date ASC
        LIMIT 100
    """), {"td": trade_date, "horizon": horizon})

    for row in r.fetchall():
        ts_code, name = row[0], row[1]
        float_date, float_share, float_ratio = row[2], row[3], row[4]
        holder_name, share_type = row[5], row[6]
        close_price, total_mv = row[7], row[8]

        ratio = float_ratio or 0
        if ratio >= 10:
            risk_level = "高"
            level = "high"
        elif ratio >= 5:
            risk_level = "中"
            level = "warning"
        else:
            risk_level = "低"
            level = "info"

        # 估算解禁市值(亿)
        unlock_value = None
        if float_share and close_price:
            unlock_value = float_share * close_price / 1e8  # float_share单位万股→亿元

        fd = float_date or ""
        fd_fmt = f"{fd[:4]}-{fd[4:6]}-{fd[6:]}" if len(fd) == 8 else fd

        msg_parts = [f"{fd_fmt}解禁{ratio:.1f}%"]
        if unlock_value is not None:
            msg_parts.append(f"约{unlock_value:.1f}亿元")
        if share_type:
            msg_parts.append(share_type)
        message = "，".join(msg_parts)

        alerts.append({
            "type": "解禁预警",
            "level": level,
            "ts_code": ts_code,
            "name": name,
            "float_date": float_date,
            "float_share": float_share,
            "float_ratio": float_ratio,
            "risk_level": risk_level,
            "message": message,
            "detail": message,
            "time": fd_fmt,
        })

    return alerts


async def _holdertrade_alerts(session: AsyncSession, trade_date: str = "",
                              days: int = 7) -> list[dict]:
    """E. 股东增减持预警：近N天大额减持/增持。

    Args:
        trade_date: 截止日期(YYYYMMDD)，默认今天
        days: 向前回溯N天
    """
    alerts: list[dict] = []
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")
    cutoff = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=days)).strftime("%Y%m%d")

    r = await session.execute(text("""
        SELECT h.ts_code, b.name, h.ann_date, h.holder_name, h.holder_type,
               h.in_de, h.change_vol, h.change_ratio, h.avg_price, h.after_ratio
        FROM stk_holdertrade h
        JOIN stock_basic b ON h.ts_code = b.ts_code
        WHERE h.ann_date BETWEEN :cutoff AND :td
        ORDER BY h.ann_date DESC, ABS(COALESCE(h.change_ratio, 0)) DESC
        LIMIT 100
    """), {"cutoff": cutoff, "td": trade_date})

    for row in r.fetchall():
        ts_code, name, ann_date = row[0], row[1], row[2]
        holder_name, holder_type = row[3], row[4]
        in_de, change_vol, change_ratio = row[5], row[6], row[7]
        avg_price, after_ratio = row[8], row[9]

        is_decrease = in_de and "减" in in_de
        abs_ratio = abs(change_ratio) if change_ratio else 0

        if is_decrease:
            alert_type = "股东减持"
            if abs_ratio >= 5:
                risk_level, level = "高", "high"
            elif abs_ratio >= 1:
                risk_level, level = "中", "warning"
            else:
                risk_level, level = "低", "info"
        else:
            alert_type = "股东增持"
            risk_level, level = "利好", "info"

        holder_short = (holder_name[:10] + "…") if holder_name and len(holder_name) > 10 else (holder_name or "未知")
        direction = "减持" if is_decrease else "增持"
        msg_parts = [f"股东{holder_short}近{days}日{direction}{abs_ratio:.2f}%"]
        if change_vol:
            msg_parts.append(f"{abs(change_vol) / 10000:.2f}万股")
        if avg_price:
            msg_parts.append(f"均价{avg_price:.2f}")
        message = "，".join(msg_parts)

        ad = ann_date or ""
        alerts.append({
            "type": alert_type,
            "level": level,
            "ts_code": ts_code,
            "name": name,
            "holder_name": holder_name,
            "in_de": in_de,
            "change_vol": -abs(change_vol) if is_decrease and change_vol else change_vol,
            "change_ratio": -abs_ratio if is_decrease else abs_ratio,
            "ann_date": ann_date,
            "risk_level": risk_level,
            "message": message,
            "detail": message,
            "time": f"{ad[:4]}-{ad[4:6]}-{ad[6:]}" if len(ad) == 8 else ad,
        })

    return alerts


async def generate_risk_alerts(session: AsyncSession, trade_date: str = "") -> dict:
    """Main entry: generate all risk alerts.

    Args:
        trade_date: 基准日期(YYYYMMDD)，默认今天。传递给需要日期的子函数。
    """
    st = await _st_alerts(session)
    fc = await _forecast_alerts(session)
    cb = await _cb_call_alerts(session)
    unlock = await _unlock_alerts(session, trade_date=trade_date, days=5)
    holder = await _holdertrade_alerts(session, trade_date=trade_date, days=7)
    all_alerts = st + fc + cb + unlock + holder
    return {
        "count": len(all_alerts),
        "data": _clean(all_alerts),
        "summary": {
            "st": len(st),
            "forecast": len(fc),
            "cb_call": len(cb),
            "unlock": len(unlock),
            "holdertrade": len(holder),
        },
    }
