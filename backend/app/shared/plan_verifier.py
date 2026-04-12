"""Plan Verifier — 自动验证当日早盘计划 vs 实际收盘结果。

收盘后调用 auto_verify_plan(trade_date)，对比维度:
  1. 市场方向预测准确性 (30分)
  2. watchlist 个股命中率 (30分)
  3. 风险预警命中率 (20分)
  4. 板块预测准确性 (20分)

结果写入 daily_plan 表的 accuracy_score / actual_result / retrospect_note。
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_json(raw: str | list | dict | None) -> list | dict:
    """Parse a JSON string; if already parsed or None, return as-is."""
    if raw is None:
        return []
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def _classify_result(score: float) -> str:
    """Map numeric score → 正确/部分正确/错误."""
    if score >= 60:
        return "正确"
    elif score >= 30:
        return "部分正确"
    else:
        return "错误"


# ---------------------------------------------------------------------------
# Score: 市场方向 (30 pts)
# ---------------------------------------------------------------------------

async def _score_direction(
    session: AsyncSession,
    predicted_direction: str | None,
    trade_date: str,
) -> tuple[float, str]:
    """Compare predicted_direction (涨/跌/震荡) vs 上证实际涨跌幅.

    Returns (score, detail_text).
    """
    if not predicted_direction:
        return 0, "无方向预判"

    r = await session.execute(text("""
        SELECT pct_chg FROM index_daily
        WHERE ts_code = '000001.SH' AND trade_date = :td
    """), {"td": trade_date})
    row = r.fetchone()
    if not row or row[0] is None:
        return 0, "无上证收盘数据"

    actual_chg = float(row[0])
    pred = predicted_direction.strip()

    # Determine actual direction
    if abs(actual_chg) < 0.3:
        actual_dir = "震荡"
    elif actual_chg > 0:
        actual_dir = "涨"
    else:
        actual_dir = "跌"

    detail = f"预判:{pred} 实际:{actual_dir}(上证{actual_chg:+.2f}%)"

    # Scoring
    if pred == actual_dir:
        return 30, detail
    # 预测震荡且实际涨跌<1% → 给满分
    if pred == "震荡" and abs(actual_chg) < 1.0:
        return 30, detail + " (震荡容差内)"
    # 方向大致一致（预测涨但小涨<0.3%算震荡范围）
    if pred in ("涨", "跌") and actual_dir == "震荡":
        return 15, detail + " (方向模糊)"
    # 方向相反
    return 0, detail


# ---------------------------------------------------------------------------
# Score: watchlist 个股命中 (30 pts)
# ---------------------------------------------------------------------------

async def _score_watchlist(
    session: AsyncSession,
    watch_stocks_json: str | list | None,
    trade_date: str,
) -> tuple[float, str]:
    """Check how many watchlist stocks actually went up.

    Returns (score out of 30, detail_text).
    """
    stocks = _safe_json(watch_stocks_json)
    if not stocks or not isinstance(stocks, list):
        return 0, "无 watchlist"

    # Extract ts_codes
    codes: list[str] = []
    for item in stocks:
        if isinstance(item, dict):
            code = item.get("ts_code") or item.get("code", "")
        elif isinstance(item, str):
            code = item
        else:
            continue
        if code:
            codes.append(code)

    if not codes:
        return 0, "watchlist 为空"

    # Query actual results
    placeholders = ", ".join(f":c{i}" for i in range(len(codes)))
    params = {f"c{i}": c for i, c in enumerate(codes)}
    params["td"] = trade_date

    r = await session.execute(text(f"""
        SELECT ts_code, pct_chg FROM stock_daily
        WHERE ts_code IN ({placeholders}) AND trade_date = :td
    """), params)
    rows = r.fetchall()

    if not rows:
        return 0, f"watchlist {len(codes)}只无当日数据"

    up_count = sum(1 for _, chg in rows if chg is not None and chg > 0)
    total = len(rows)
    ratio = up_count / total if total > 0 else 0
    score = round(ratio * 30, 1)
    detail = f"watchlist {total}只: {up_count}涨 {total - up_count}平/跌 命中率{ratio:.0%}"
    return score, detail


# ---------------------------------------------------------------------------
# Score: 风险预警命中 (20 pts)
# ---------------------------------------------------------------------------

async def _score_risk_alerts(
    session: AsyncSession,
    plan_risk_notes: str | None,
    trade_date: str,
) -> tuple[float, str]:
    """Evaluate whether risk warnings materialized.

    Simple heuristic: if risk_notes mentions specific risks,
    check if market actually had a bad day (significant drops).
    """
    if not plan_risk_notes or not plan_risk_notes.strip():
        return 10, "无风险预警(给基础分10)"

    # Get market stats for the day
    r = await session.execute(text("""
        SELECT pct_chg FROM index_daily
        WHERE ts_code = '000001.SH' AND trade_date = :td
    """), {"td": trade_date})
    row = r.fetchone()
    if not row:
        return 0, "无上证数据"

    actual_chg = float(row[0]) if row[0] is not None else 0

    # Check breadth: down stocks ratio
    breadth_r = await session.execute(text("""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE pct_chg < -3) AS big_drop
        FROM stock_daily WHERE trade_date = :td
    """), {"td": trade_date})
    breadth = breadth_r.fetchone()
    total_stocks = breadth[0] if breadth else 0
    big_drop_count = breadth[1] if breadth else 0

    # Risk occurred if: market dropped >1% or >10% stocks dropped >3%
    risk_occurred = (
        actual_chg < -1.0
        or (total_stocks > 0 and big_drop_count / total_stocks > 0.1)
    )

    has_warning = len(plan_risk_notes.strip()) > 10  # meaningful warning

    if has_warning and risk_occurred:
        return 20, f"预警命中: 市场{actual_chg:+.2f}% 大跌股{big_drop_count}只"
    elif has_warning and not risk_occurred:
        return 10, f"预警未触发: 市场{actual_chg:+.2f}% (给基础分)"
    elif not has_warning and risk_occurred:
        return 0, f"未预警但风险发生: 市场{actual_chg:+.2f}%"
    else:
        return 10, "无预警且无风险"


# ---------------------------------------------------------------------------
# Score: 板块预测 (20 pts)
# ---------------------------------------------------------------------------

async def _score_sectors(
    session: AsyncSession,
    watch_sectors_json: str | list | None,
    trade_date: str,
) -> tuple[float, str]:
    """Compare predicted hot sectors vs actual TOP5 sectors.

    Returns (score out of 20, detail_text).
    """
    predicted = _safe_json(watch_sectors_json)
    if not predicted or not isinstance(predicted, list):
        return 0, "无板块预判"

    # Extract sector names from predictions
    pred_names: list[str] = []
    for item in predicted:
        if isinstance(item, dict):
            name = item.get("name") or item.get("industry") or ""
        elif isinstance(item, str):
            name = item
        else:
            continue
        if name:
            pred_names.append(name.strip())

    if not pred_names:
        return 0, "板块预判为空"

    # Get actual top 5 sectors from sw_daily
    r = await session.execute(text("""
        SELECT name FROM sw_daily
        WHERE trade_date = :td AND pct_change IS NOT NULL
        ORDER BY pct_change DESC
        LIMIT 5
    """), {"td": trade_date})
    actual_top5 = [row[0] for row in r.fetchall() if row[0]]

    if not actual_top5:
        return 0, "无当日板块数据"

    # Count overlaps (fuzzy: check if predicted name is contained in actual or vice versa)
    overlap = 0
    matched_sectors = []
    for pred in pred_names:
        for actual in actual_top5:
            if pred in actual or actual in pred:
                overlap += 1
                matched_sectors.append(pred)
                break

    score = round(overlap / 5 * 20, 1)
    detail = (
        f"预判板块{len(pred_names)}个 实际TOP5: {', '.join(actual_top5[:5])} "
        f"重叠{overlap}个"
    )
    if matched_sectors:
        detail += f" (命中: {', '.join(matched_sectors)})"
    return score, detail


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def auto_verify_plan(trade_date: str) -> dict | None:
    """收盘后自动验证当日早盘计划 vs 实际结果。

    Steps:
      1. 查询 daily_plan 当日计划
      2. 逐维度评分
      3. 汇总并写入 accuracy_score + actual_result
      4. 容错: 计划不存在或数据不全时返回 None

    Returns: {accuracy_score, actual_result, details} or None
    """
    async with async_session() as session:
        # 1. Fetch the plan
        r = await session.execute(text("""
            SELECT predicted_direction, watch_stocks_json, watch_sectors_json,
                   risk_notes, accuracy_score
            FROM daily_plan
            WHERE trade_date = :td
        """), {"td": trade_date})
        plan_row = r.fetchone()

        if not plan_row:
            logger.info("auto_verify: no plan found for %s, skip", trade_date)
            return None

        predicted_direction = plan_row[0]
        watch_stocks_json = plan_row[1]
        watch_sectors_json = plan_row[2]
        risk_notes = plan_row[3]
        existing_score = plan_row[4]

        # If already verified, skip
        if existing_score is not None:
            logger.info("auto_verify: plan %s already verified (score=%.1f), skip",
                        trade_date, existing_score)
            return None

        # 2. Score each dimension
        dir_score, dir_detail = await _score_direction(
            session, predicted_direction, trade_date
        )
        wl_score, wl_detail = await _score_watchlist(
            session, watch_stocks_json, trade_date
        )
        risk_score, risk_detail = await _score_risk_alerts(
            session, risk_notes, trade_date
        )
        sector_score, sector_detail = await _score_sectors(
            session, watch_sectors_json, trade_date
        )

        # 3. Aggregate
        total_score = round(dir_score + wl_score + risk_score + sector_score, 1)
        actual_result = _classify_result(total_score)

        details = {
            "direction": {"score": dir_score, "max": 30, "detail": dir_detail},
            "watchlist": {"score": wl_score, "max": 30, "detail": wl_detail},
            "risk_alerts": {"score": risk_score, "max": 20, "detail": risk_detail},
            "sectors": {"score": sector_score, "max": 20, "detail": sector_detail},
        }

        retrospect_note = (
            f"[自动验证] 总分{total_score}/100 "
            f"| 方向{dir_score}/30 | 选股{wl_score}/30 "
            f"| 风险{risk_score}/20 | 板块{sector_score}/20\n"
            f"方向: {dir_detail}\n"
            f"选股: {wl_detail}\n"
            f"风险: {risk_detail}\n"
            f"板块: {sector_detail}"
        )

        # 4. Write back
        await session.execute(text("""
            UPDATE daily_plan
            SET accuracy_score = :score,
                actual_result = :result,
                retrospect_note = CASE
                    WHEN retrospect_note IS NULL OR retrospect_note = ''
                    THEN :note
                    ELSE retrospect_note || E'\n---\n' || :note
                END
            WHERE trade_date = :td
        """), {
            "score": total_score,
            "result": actual_result,
            "note": retrospect_note,
            "td": trade_date,
        })
        await session.commit()

        logger.info(
            "auto_verify: %s → score=%.1f result=%s",
            trade_date, total_score, actual_result,
        )

        return {
            "trade_date": trade_date,
            "accuracy_score": total_score,
            "actual_result": actual_result,
            "details": details,
            "retrospect_note": retrospect_note,
        }
