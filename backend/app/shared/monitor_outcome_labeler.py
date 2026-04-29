"""Path label engine — classify signal outcomes by objective price behavior.

Labels (mutually exclusive, priority ordered):
  follow_through  — sustained move in signal direction
  spike_fade      — initial spike then reversal
  dip_recover     — initial dip then recovery
  trend_down      — sustained decline
  flat_noise      — no significant movement

Called by backfill after outcome returns are computed.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)

# ── Label definitions ────────────────────────────────────────────
# Each label function takes outcome dict → bool.
# Evaluation order matters: first match wins.

def _is_follow_through(o: dict) -> bool:
    """Sustained move: ret_30m > 1.5% AND max_down_30m > -0.8%."""
    r30 = o.get("ret_30m")
    md30 = o.get("max_down_30m")
    if r30 is None:
        return False
    return r30 > 1.5 and (md30 is None or md30 > -0.8)


def _is_spike_fade(o: dict) -> bool:
    """Initial spike then reversal: max_up_30m > 1.0% AND ret_30m < 0."""
    mu30 = o.get("max_up_30m")
    r30 = o.get("ret_30m")
    if mu30 is None or r30 is None:
        return False
    return mu30 > 1.0 and r30 < 0


def _is_dip_recover(o: dict) -> bool:
    """Initial dip then recovery: max_down_30m < -1.0% AND ret_60m > 1.5%."""
    md30 = o.get("max_down_30m")
    r60 = o.get("ret_60m")
    if md30 is None:
        return False
    # If no 60m data, fall back to 30m
    r = r60 if r60 is not None else o.get("ret_30m")
    if r is None:
        return False
    return md30 < -1.0 and r > 1.5


def _is_trend_down(o: dict) -> bool:
    """Sustained decline: ret_30m < -1.0% AND max_up_30m < 0.5%."""
    r30 = o.get("ret_30m")
    mu30 = o.get("max_up_30m")
    if r30 is None:
        return False
    return r30 < -1.0 and (mu30 is None or mu30 < 0.5)


def _classify(o: dict) -> str:
    """Classify outcome into a path label.  Priority order matters."""
    if _is_follow_through(o):
        return "follow_through"
    if _is_spike_fade(o):
        return "spike_fade"
    if _is_dip_recover(o):
        return "dip_recover"
    if _is_trend_down(o):
        return "trend_down"
    return "flat_noise"


# ── Semantic mapping (for display) ───────────────────────────────

LABEL_DISPLAY = {
    "follow_through": {"cn": "持续走强", "hint": "可能是真买入"},
    "spike_fade":     {"cn": "冲高回落", "hint": "可能是诱多/出货"},
    "dip_recover":    {"cn": "先杀后拉", "hint": "可能是洗盘"},
    "flat_noise":     {"cn": "无效噪声", "hint": "信号无明显方向"},
    "trend_down":     {"cn": "持续走弱", "hint": "弱信号/出货倾向"},
}


# ── Batch labeling ───────────────────────────────────────────────

def label_outcomes(conn: Connection, event_date: str) -> dict:
    """Label all backfilled rows for event_date that don't have a label yet.

    Works on both monitor_events and monitor_largecap_alerts.
    Expects a connection with an active transaction — caller commits.
    """
    events_labeled = 0
    alerts_labeled = 0

    # ── Largecap alerts (have full minute-level outcome data) ──
    rows = conn.execute(text("""
        SELECT id, ret_5m, ret_15m, ret_30m, ret_60m,
               max_up_30m, max_down_30m, max_up_60m, max_down_60m,
               close_pos_30m, close_pos_60m
        FROM monitor_largecap_alerts
        WHERE event_date = :ed AND ret_5m IS NOT NULL AND path_label IS NULL
    """), {"ed": event_date}).fetchall()

    for row in rows:
        o = {
            "ret_5m": row[1], "ret_15m": row[2], "ret_30m": row[3],
            "ret_60m": row[4], "max_up_30m": row[5], "max_down_30m": row[6],
            "max_up_60m": row[7], "max_down_60m": row[8],
            "close_pos_30m": row[9], "close_pos_60m": row[10],
        }
        label = _classify(o)
        conn.execute(text("""
            UPDATE monitor_largecap_alerts SET path_label = :lbl WHERE id = :id
        """), {"lbl": label, "id": row[0]})
        alerts_labeled += 1

    # ── Index events (only have ret_eod, so limited labeling) ──
    # For index events with ret_eod only, we use a simplified rule:
    # ret_eod > 0.5% → follow_through, ret_eod < -0.5% → trend_down, else flat_noise
    idx_rows = conn.execute(text("""
        SELECT id, ret_eod, max_move_30m, min_move_30m
        FROM monitor_events
        WHERE event_date = :ed AND ret_eod IS NOT NULL AND path_label IS NULL
    """), {"ed": event_date}).fetchall()

    for row in idx_rows:
        r_eod = row[1]
        # Index events lack minute granularity — use simplified classification
        if r_eod is not None and r_eod > 0.5:
            label = "follow_through"
        elif r_eod is not None and r_eod < -0.5:
            label = "trend_down"
        else:
            label = "flat_noise"
        conn.execute(text("""
            UPDATE monitor_events SET path_label = :lbl WHERE id = :id
        """), {"lbl": label, "id": row[0]})
        events_labeled += 1

    conn.commit()

    return {"events_labeled": events_labeled, "alerts_labeled": alerts_labeled}
