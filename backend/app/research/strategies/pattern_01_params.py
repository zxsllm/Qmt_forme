"""Pattern01 龙头隔夜策略 — 可调参数预设。

通过环境变量切换:
    STRATEGY_PRESET=moderate  # 默认，等于当前回测使用的"适中"参数
    STRATEGY_PRESET=strict    # 行情差时收紧（亏损缩小）
    STRATEGY_PRESET=loose     # 行情好时放宽（收益放大）

行情判定由用户人工把控（不在策略层自动识别）。

设计原则:
- moderate = 当前所有常量原值，回测数字必须完全一致
- strict / loose 只调"阈值/数量/仓位"，不改大逻辑（L1/L2/L_CB 三层框架）
"""
from __future__ import annotations

import os

# ─────────────────────────────────────────────────────────────────────────────
# 适中（默认 = 当前回测参数）
# ─────────────────────────────────────────────────────────────────────────────
MODERATE: dict = dict(
    # ── 共识阈值 ──
    INTRADAY_CONSENSUS_MIN_L1=2,
    INTRADAY_CONSENSUS_MIN_L1_EMERGING=3,
    INTRADAY_CONSENSUS_MIN_L2=3,
    INTRADAY_CONSENSUS_PCT_L1=6.0,
    INTRADAY_CONSENSUS_PCT_L2=8.0,
    SELF_TRIGGER_RATIO=0.9,
    # ── L_CB 升级隔夜 ──
    L_CB_OVERNIGHT_LIMIT_MIN=3,
    L_CB_OVERNIGHT_OPEN_MAX=1,
    L_CB_RECHECK_BROKEN_MAX=3,
    L_CB_EVAL_WINDOW_MIN=10,
    # ── L_CB 买回 ──
    L_CB_REBUY_MAX_TIMES=1,
    L_CB_REBUY_NEW_LIMITS_MIN=3,
    L_CB_REBUY_PRICE_RATIO=1.02,
    L_CB_REBUY_MIN_GAP_MIN=5,
    L_CB_REBUY_DEADLINE="143000",
    L_CB_REBUY_FIXED_STOP_RATIO=0.99,
    # ── 偏离度过滤 ──
    L1_MA5_DEVIATION_MAX=0.28,
    L1_MA5_DEVIATION_LARGE_MV=0.20,
    L1_LARGE_MV_THRESHOLD_YI=800,
    L2_MA5_DEVIATION_MAX=0.20,
    # ── 萌芽主线 ──
    EMERGING_CUTOFF="113000",
    EMERGING_MIN_COUNT=3,
    # ── 撮合层（单笔目标仓位）──
    TARGET_NOTIONAL=10_000,
)


# ─────────────────────────────────────────────────────────────────────────────
# 严格（行情差时用 — 减少触发、严共识、小仓位）
# ─────────────────────────────────────────────────────────────────────────────
STRICT: dict = {**MODERATE, **dict(
    # 共识门槛抬高：板块要更宽的"普涨"才算共识
    INTRADAY_CONSENSUS_MIN_L1=3,           # 2 → 3
    INTRADAY_CONSENSUS_PCT_L1=8.0,         # 6.0 → 8.0
    INTRADAY_CONSENSUS_MIN_L2=4,           # 3 → 4
    # L_CB 升级隔夜门槛抬高：板块更强才允许过夜
    L_CB_OVERNIGHT_LIMIT_MIN=5,            # 3 → 5
    L_CB_OVERNIGHT_OPEN_MAX=0,             # 1 → 0（任何炸板都不升级）
    L_CB_REBUY_NEW_LIMITS_MIN=5,           # 3 → 5（板块要再涨 5 只才允许买回）
    # 偏离度收紧：防追高
    L1_MA5_DEVIATION_MAX=0.20,             # 0.28 → 0.20
    L1_MA5_DEVIATION_LARGE_MV=0.15,        # 0.20 → 0.15
    L2_MA5_DEVIATION_MAX=0.15,             # 0.20 → 0.15
    # 萌芽监控提前结束（行情差时午后情绪退潮，不发新 L_CB）
    EMERGING_CUTOFF="103000",              # 11:30 → 10:30
    # 仓位保持 moderate（不动）：让"行情判定"和"仓位决策"分离
)}


# ─────────────────────────────────────────────────────────────────────────────
# 宽松（行情好时用 — L_CB 易升级 + 萌芽延后 + 买回延后 + 仓位放大；偏离度不动）
# ─────────────────────────────────────────────────────────────────────────────
# 探索过程（4/28-5/12 8 天回测验证）的关键发现:
# - 偏离度放宽是负向 -¥6,253（金螳螂/德明利等大票偏离度天然高，放宽=放进追高陷阱）
# - 仓位放大 10k→15k 是核心正向价值 +¥5,899（纯杠杆 ×1.5）
# - L_CB 升级条件 ≥2 vs ≥3 略负 -¥1,486（升级太松引入假突破）— 但保留 ≥2 仍接受
# - 萌芽延后 + 买回延后 +¥1,438（5/7 单笔贡献占大头，证据较弱但保留）
# - 综合: +¥17,808 / 110 笔，比 moderate +¥11,957 多 +¥5,851
LOOSE: dict = {**MODERATE, **dict(
    # L_CB 升级隔夜门槛降低：板块稍强就过夜吃 T+1 溢价
    L_CB_OVERNIGHT_LIMIT_MIN=2,            # 3 → 2
    L_CB_REBUY_NEW_LIMITS_MIN=2,           # 3 → 2
    # 萌芽监控延后（行情好时午后题材轮动仍活跃）
    EMERGING_CUTOFF="133000",              # 11:30 → 13:30
    # 买回截止时间延后
    L_CB_REBUY_DEADLINE="145000",          # 14:30 → 14:50
    # 仓位保持 moderate（不动）：让"行情判定"和"仓位决策"分离
    # 偏离度保持 moderate（放宽是负向）:
    #   L1_MA5_DEVIATION_MAX=0.28 / L1_MA5_DEVIATION_LARGE_MV=0.20 / L2_MA5_DEVIATION_MAX=0.20
)}


PRESETS: dict[str, dict] = {
    "moderate": MODERATE,
    "strict": STRICT,
    "loose": LOOSE,
}


def _resolve_preset() -> tuple[str, dict]:
    name = os.environ.get("STRATEGY_PRESET", "moderate").lower()
    if name not in PRESETS:
        raise ValueError(
            f"STRATEGY_PRESET={name!r} 不存在，可选: {list(PRESETS)}"
        )
    return name, PRESETS[name]


PRESET_NAME, ACTIVE = _resolve_preset()
