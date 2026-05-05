"""龙1 次日一字预测器（T 日盘后判定，**严格无未来**）。

核心逻辑（来自股桃老师课程，见 12模式策略详解.md 7.5）：
    "市场买不到龙1 才去买跟风。有 ≥2 个跟风涨停 = 龙1 真有溢价 = 次日大概率一字。
     没有跟风涨停的孤龙 = 假封单 = 次日必开板。"

主信号 + 辅助信号给出 0-100 评分。

输入：
    - long_head_detector 的 LongHeadResult
    - 板块成员（用于查跟风涨停数 + 板块整体情绪）

输出：
    - YiziPrediction 数据类，含 score / decision / 各信号明细
    - decision: "yizi" / "uncertain" / "break"
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.research.signals.long_head_detector import LongHeadResult, LimitUpStock

logger = logging.getLogger(__name__)


@dataclass
class YiziPrediction:
    long1_code: str
    long1_name: str
    sector: str
    # 主信号
    follower_limit_count: int        # 跟风涨停数（不含龙1 本身）
    has_shadow: bool                 # 是否有影子龙
    # 辅助信号
    long1_open_times: int            # 龙1 当日炸板次数
    long1_board_height: int          # 龙1 累计板数
    long1_seal_ratio_pct: float | None   # 封单比 (limit_amount / float_mv * 100)，None=数据缺失
    sector_amount_ratio: float | None    # 板块今日成交额 / 5日均，None=数据不足
    # 评分 + 判定
    score: float                     # 0-100
    decision: str                    # "yizi" / "uncertain" / "break"
    breakdown: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 评分配置
# ---------------------------------------------------------------------------

# 主信号权重最大
W_FOLLOWER = 50.0          # 跟风涨停数 ≥2 → 满分
W_SHADOW = 10.0            # 有影子龙
W_NO_BREAK = 10.0          # 龙1 当日未炸板
W_BOARD = 10.0             # 连板高度
W_SEAL = 10.0              # 封单比
W_SECTOR_AMT = 10.0        # 板块成交放大

# 判定阈值
SCORE_YIZI = 65            # ≥65 判定次日一字
SCORE_BREAK = 35           # <35 判定次日开板（孤龙）


def _score_followers(n: int) -> float:
    """跟风涨停数评分。0=孤龙, 1=弱跟随, 2+=真溢价"""
    if n >= 4: return W_FOLLOWER
    if n >= 2: return W_FOLLOWER * 0.85
    if n == 1: return W_FOLLOWER * 0.30
    return 0.0  # 孤龙 = 0 分（直接判失败）


def _score_board(h: int) -> float:
    if h >= 5: return W_BOARD
    if h >= 3: return W_BOARD * 0.7
    if h >= 2: return W_BOARD * 0.5
    return W_BOARD * 0.2  # 首板


def _score_seal_ratio(r: float | None) -> float:
    if r is None: return W_SEAL * 0.5  # 缺失给中性分
    if r >= 3.0: return W_SEAL
    if r >= 2.0: return W_SEAL * 0.8
    if r >= 1.0: return W_SEAL * 0.5
    return W_SEAL * 0.2  # <1% = 假封单嫌疑


def _score_sector_amt(r: float | None) -> float:
    if r is None: return W_SECTOR_AMT * 0.5
    if r >= 2.0: return W_SECTOR_AMT
    if r >= 1.5: return W_SECTOR_AMT * 0.8
    if r >= 1.0: return W_SECTOR_AMT * 0.5
    return W_SECTOR_AMT * 0.2


# ---------------------------------------------------------------------------
# 主预测函数
# ---------------------------------------------------------------------------

async def _sector_amount_ratio(
    session: AsyncSession, trade_date: str, ts_codes: list[str]
) -> float | None:
    """板块今日总成交额 / 前5日均成交额。"""
    if not ts_codes:
        return None
    rows = (await session.execute(text(
        "SELECT trade_date, SUM(amount) AS amt FROM stock_daily "
        "WHERE ts_code = ANY(:codes) AND trade_date <= :td "
        "GROUP BY trade_date ORDER BY trade_date DESC LIMIT 6"
    ), {"codes": ts_codes, "td": trade_date})).fetchall()
    if len(rows) < 6:
        return None
    today_amt = float(rows[0][1] or 0)
    prev = [float(r[1] or 0) for r in rows[1:]]
    avg5 = sum(prev) / 5
    if avg5 <= 0:
        return None
    return today_amt / avg5


def _seal_ratio_pct(stock: LimitUpStock) -> float | None:
    """封单比 = limit_amount / float_mv * 100（百分比形式）。"""
    if not stock.limit_amount or not stock.float_mv:
        return None
    if stock.float_mv <= 0:
        return None
    return stock.limit_amount / stock.float_mv * 100


async def _cross_sector_member_codes(
    session: AsyncSession, trade_date: str, long1_code: str
) -> list[str]:
    """同主线跨板块成员并集（双源汇总）：
    1. 板块必读 daily（source='bankuai'）：所有包含龙1 的板块成员
    2. LLM v2（source='llm_v2'）：所有包含龙1 的主线成员
    取并集去重 → 更接近真实主线（防止板块必读单一归类的偏差）

    例：金螳螂 4/29 板块必读只挂"洁净室"，但 LLM v2 归到"国产芯片"
    → 跨主线并集会包含国产芯片下的所有票（金螳螂+寒武纪+中天精装等）。
    """
    rows = (await session.execute(text(
        # 板块必读
        "SELECT DISTINCT dsr.ts_code FROM daily_sector_review dsr "
        "WHERE dsr.trade_date=:td AND dsr.source='bankuai' "
        "AND dsr.raw_meta->>'scope'='daily' "
        "AND dsr.sector_name IN ("
        "    SELECT sector_name FROM daily_sector_review "
        "    WHERE trade_date=:td AND source='bankuai' "
        "    AND raw_meta->>'scope'='daily' AND ts_code=:c"
        ") AND dsr.ts_code IS NOT NULL "
        "UNION "
        # LLM v2
        "SELECT DISTINCT dsr.ts_code FROM daily_sector_review dsr "
        "WHERE dsr.trade_date=:td AND dsr.source='llm_v2' "
        "AND dsr.sector_name IN ("
        "    SELECT sector_name FROM daily_sector_review "
        "    WHERE trade_date=:td AND source='llm_v2' AND ts_code=:c"
        ") AND dsr.ts_code IS NOT NULL"
    ), {"td": trade_date, "c": long1_code})).fetchall()
    return [r[0] for r in rows]


async def _count_limit_up_in(
    session: AsyncSession, trade_date: str, codes: list[str], exclude_code: str
) -> int:
    """codes 里当日涨停股数（去掉 exclude_code）。"""
    if not codes:
        return 0
    r = await session.execute(text(
        "SELECT COUNT(DISTINCT ts_code) FROM limit_stats "
        "WHERE trade_date=:td AND \"limit\"='U' "
        "AND ts_code = ANY(:codes) AND ts_code != :ex"
    ), {"td": trade_date, "codes": codes, "ex": exclude_code})
    return int(r.scalar() or 0)


async def predict_long1_yizi(
    session: AsyncSession,
    trade_date: str,
    sector_codes: list[str],
    lh: LongHeadResult,
) -> YiziPrediction | None:
    """龙1 次日一字预测（跨主线跟风汇总版）。

    Args:
        session: DB 会话
        trade_date: T 日（YYYYMMDD）
        sector_codes: 当前板块成员（用于算板块成交放大）
        lh: 龙头识别结果

    跟风涨停数算法：
        1. 查询"包含龙1 的所有板块成员并集" = 同主线代理
        2. 在并集里数当日涨停股（去龙1）
        3. 与"单板块跟风数"取较大值（防止板块归属偏差）

    Returns:
        YiziPrediction，或 None（无龙1 时）
    """
    if not lh.long1:
        return None
    long1 = lh.long1

    # 单板块跟风数（多龙1 群组 + 龙2 + 影子龙 + 跟风），剔除主龙1 自身
    in_sector_codes = set()
    for s in lh.long1_group:
        in_sector_codes.add(s.ts_code)  # 多龙1 时其他一字龙1 互相算"封板共识"
    if lh.long2:
        in_sector_codes.add(lh.long2.ts_code)
    if lh.shadow:
        in_sector_codes.add(lh.shadow.ts_code)
    for f in lh.followers:
        in_sector_codes.add(f.ts_code)
    in_sector_codes.discard(long1.ts_code)
    in_sector_count = len(in_sector_codes)

    # 跨主线跟风数（跨板块并集去重去龙1）
    cross_codes = await _cross_sector_member_codes(session, trade_date, long1.ts_code)
    cross_count = await _count_limit_up_in(session, trade_date, cross_codes, long1.ts_code)

    # 取较大值作为主信号
    follower_count = max(in_sector_count, cross_count)

    has_shadow = bool(lh.shadow)

    # 辅助信号
    seal_ratio = _seal_ratio_pct(long1)
    sector_amt_ratio = await _sector_amount_ratio(session, trade_date, sector_codes)

    # 评分
    s_follower = _score_followers(follower_count)
    s_shadow = W_SHADOW if has_shadow else 0.0
    s_nobreak = W_NO_BREAK if long1.open_times == 0 else (W_NO_BREAK * 0.3 if long1.open_times == 1 else 0.0)
    s_board = _score_board(long1.limit_times)
    s_seal = _score_seal_ratio(seal_ratio)
    s_amt = _score_sector_amt(sector_amt_ratio)
    score = s_follower + s_shadow + s_nobreak + s_board + s_seal + s_amt

    # 主信号 ≤1 → 强制下调（孤龙必败）
    if follower_count <= 1:
        score = min(score, SCORE_BREAK)  # 顶到 BREAK 阈值

    # 判定
    if score >= SCORE_YIZI:
        decision = "yizi"
    elif score < SCORE_BREAK:
        decision = "break"
    else:
        decision = "uncertain"

    breakdown = {
        "follower_count": (follower_count, round(s_follower, 1)),
        "  in_sector": in_sector_count,
        "  cross_main_line": cross_count,
        "has_shadow": (has_shadow, round(s_shadow, 1)),
        "no_break": (long1.open_times, round(s_nobreak, 1)),
        "board_height": (long1.limit_times, round(s_board, 1)),
        "seal_ratio_pct": (round(seal_ratio, 2) if seal_ratio else None, round(s_seal, 1)),
        "sector_amt_ratio": (round(sector_amt_ratio, 2) if sector_amt_ratio else None, round(s_amt, 1)),
    }

    return YiziPrediction(
        long1_code=long1.ts_code,
        long1_name=long1.name,
        sector=lh.sector,
        follower_limit_count=follower_count,
        has_shadow=has_shadow,
        long1_open_times=long1.open_times,
        long1_board_height=long1.limit_times,
        long1_seal_ratio_pct=seal_ratio,
        sector_amount_ratio=sector_amt_ratio,
        score=round(score, 1),
        decision=decision,
        breakdown=breakdown,
    )


def format_prediction(p: YiziPrediction) -> str:
    decision_marker = {"yizi": "✓ 一字", "uncertain": "? 不确定", "break": "✗ 开板"}[p.decision]
    lines = [
        f"=== {p.sector} 龙1 {p.long1_code} {p.long1_name} ===",
        f"  预测: {decision_marker}  评分 {p.score}/100",
        f"  跟风涨停数={p.follower_limit_count}  影子龙={'有' if p.has_shadow else '无'}  "
        f"炸板={p.long1_open_times}次  连板={p.long1_board_height}",
    ]
    if p.long1_seal_ratio_pct is not None:
        lines.append(f"  封单比={p.long1_seal_ratio_pct:.2f}%  板块量比={p.sector_amount_ratio or '-'}")
    return "\n".join(lines)
