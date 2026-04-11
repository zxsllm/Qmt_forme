"""Market feature vector construction for daily review and morning plan.

Pure functions — no database access, no async. Takes dict inputs from
DailyReview / DailyPlan fields, outputs fixed-length float vectors for
pgvector storage and cosine-similarity retrieval.
"""

from __future__ import annotations

import json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize(value: float | None, min_val: float, max_val: float) -> float:
    """Normalize a value to [0, 1]. None → 0.5 (neutral). Clamps extremes."""
    if value is None:
        return 0.5
    if max_val == min_val:
        return 0.5
    result = (value - min_val) / (max_val - min_val)
    return max(0.0, min(1.0, result))


_TEMP_MAP: dict[str, float] = {
    "极热": 1.0,
    "偏热": 0.75,
    "中性": 0.5,
    "偏冷": 0.25,
    "冰点": 0.0,
}


def temp_to_float(temperature: str | None) -> float:
    """Convert sentiment temperature label to [0, 1] float."""
    if not temperature:
        return 0.5
    return _TEMP_MAP.get(temperature, 0.5)


_DIRECTION_MAP: dict[str, float] = {
    "看多": 1.0,
    "偏多": 0.75,
    "震荡": 0.5,
    "偏空": 0.25,
    "看空": 0.0,
}


def direction_to_float(direction: str | None) -> float:
    """Convert predicted direction label to [0, 1] float."""
    if not direction:
        return 0.5
    return _DIRECTION_MAP.get(direction, 0.5)


def _parse_json(raw: str | list | None) -> list:
    """Safely parse a JSON string or pass through a list."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _sector_features(top_sectors_json: str | list | None, n: int = 5) -> list[float]:
    """Extract 2*n features from top sector data: pct_change + net_amount.

    Returns exactly 2*n floats (zero-padded if fewer sectors).
    """
    sectors = _parse_json(top_sectors_json)
    features: list[float] = []
    for i in range(n):
        if i < len(sectors):
            s = sectors[i]
            features.append(normalize(s.get("pct_change"), -5, 8))
            features.append(normalize(s.get("net_amount"), -20, 30))
        else:
            features.append(0.5)
            features.append(0.5)
    return features


def _strategy_weight_bias(weights_json: str | dict | None) -> float:
    """Encode strategy weights into a single [0, 1] bias value.

    0.0 = pure value, 0.5 = balanced, 1.0 = pure board-play.
    """
    if weights_json is None:
        return 0.5
    if isinstance(weights_json, str):
        try:
            weights = json.loads(weights_json)
        except (json.JSONDecodeError, TypeError):
            return 0.5
    else:
        weights = weights_json
    if not isinstance(weights, dict):
        return 0.5
    bp = weights.get("board_play", 0)
    vi = weights.get("value_invest", 0)
    # board_play pulls toward 1.0, value_invest pulls toward 0.0
    total = bp + vi
    if total == 0:
        return 0.5
    return bp / total


# ---------------------------------------------------------------------------
# 36-dim market feature vector (DailyReview)
# ---------------------------------------------------------------------------

def build_market_feature_vector(review_data: dict) -> list[float]:
    """Build a 36-dimensional market feature vector from review data.

    Every dimension is normalized to [0, 1] via min-max scaling with
    domain-appropriate ranges. The vector is designed for cosine similarity
    comparison across trading days.

    Dimensions
    ----------
    [0-4]   大盘涨跌 + 量能 (5)
    [5-11]  情绪指标 (7)
    [12-21] 板块轮动 — Top5 涨幅+资金流 (10)
    [22-25] 资金面 (4)
    [26-29] 技术面 — 预留 (4)
    [30-35] 策略适配 — 预留 (6)
    """
    g = review_data.get

    vec: list[float] = [
        # ── [0-4] 大盘涨跌 + 量能 ──
        normalize(g("sh_pct_chg"),      -5,    5),      # 0  上证涨跌%
        normalize(g("sz_pct_chg"),      -5,    5),      # 1  深证涨跌%
        normalize(g("cy_pct_chg"),      -8,    8),      # 2  创业板涨跌%
        normalize(g("total_amount"),    5000,  20000),   # 3  两市成交额(亿)
        normalize(g("amount_chg_pct"),  -30,   30),      # 4  成交额环比%

        # ── [5-11] 情绪指标 ──
        normalize(g("limit_up_count"),   0,    150),     # 5  涨停数
        normalize(g("limit_down_count"), 0,    80),      # 6  跌停数
        normalize(g("broken_count"),     0,    60),      # 7  炸板数
        normalize(g("seal_rate"),        0,    100),     # 8  封板率%
        normalize(g("max_board"),        1,    12),      # 9  最高连板
        normalize(g("up_down_ratio"),    0.2,  5.0),     # 10 涨跌比
        temp_to_float(g("temperature")),                 # 11 情绪温度

        # ── [12-21] 板块轮动 — Top5板块×(涨幅+资金流) ──
        *_sector_features(g("top_sectors_json"), n=5),

        # ── [22-25] 资金面 ──
        normalize(g("margin_balance"),  15000, 20000),   # 22 两融余额(亿)
        normalize(g("margin_net_buy"),  -200,  200),     # 23 融资净买入(亿)
        normalize(g("hot_money_net"),   -50,   50),      # 24 游资净买入(亿)
        normalize(g("inst_net_buy"),    -100,  100),     # 25 机构净买入(亿)

        # ── [26-29] 技术面 — 预留，后续接入指数MA位置+波动率 ──
        0.5,                                             # 26 指数vs MA5
        0.5,                                             # 27 指数vs MA20
        0.5,                                             # 28 指数vs MA60
        0.5,                                             # 29 波动率

        # ── [30-35] 策略适配 — 预留，后续接入首板成功率等 ──
        0.5,                                             # 30 首板成功率
        0.5,                                             # 31 连板晋级率
        0.5,                                             # 32 MA20之上占比
        0.5,                                             # 33 板块轮动速度
        0.5,                                             # 34 全市场PB分位
        0.5,                                             # 35 Top50股息率
    ]

    assert len(vec) == 36, f"Expected 36 dims, got {len(vec)}"
    return vec


# ---------------------------------------------------------------------------
# 16-dim environment feature vector (DailyPlan)
# ---------------------------------------------------------------------------

def build_env_feature_vector(plan_data: dict) -> list[float]:
    """Build a 16-dimensional environment feature vector from morning plan data.

    Dimensions
    ----------
    [0-3]   外盘隔夜涨跌 (4)
    [4-7]   昨日情绪 (4)
    [8-11]  策略预判 (4)
    [12-15] 预留 (4)
    """
    g = plan_data.get

    vec: list[float] = [
        # ── [0-3] 外盘隔夜 ──
        normalize(g("us_sp500_pct"),   -3,   3),         # 0  标普500%
        normalize(g("us_nasdaq_pct"),  -4,   4),         # 1  纳指%
        normalize(g("a50_night_pct"),  -3,   3),         # 2  A50夜盘%
        normalize(g("hk_hsi_pct"),     -3,   3),         # 3  恒指%

        # ── [4-7] 昨日情绪（从昨日复盘数据填充） ──
        temp_to_float(g("prev_temperature")),            # 4  昨日温度
        normalize(g("prev_limit_up_count"),  0,  150),   # 5  昨日涨停数
        normalize(g("prev_seal_rate"),       0,  100),   # 6  昨日封板率%
        normalize(g("prev_up_down_ratio"),   0.2, 5.0),  # 7  昨日涨跌比

        # ── [8-11] 策略预判 ──
        temp_to_float(g("predicted_temperature")),       # 8  预判温度
        direction_to_float(g("predicted_direction")),    # 9  预判方向
        normalize(g("confidence_score"),     0,  100),   # 10 信心分
        _strategy_weight_bias(g("strategy_weights_json")),  # 11 策略倾向

        # ── [12-15] 预留 ──
        0.5,                                             # 12
        0.5,                                             # 13
        0.5,                                             # 14
        0.5,                                             # 15
    ]

    assert len(vec) == 16, f"Expected 16 dims, got {len(vec)}"
    return vec
