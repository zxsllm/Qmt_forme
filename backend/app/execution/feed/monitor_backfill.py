"""Post-market backfill: compute outcome returns for monitor events.

Called by scheduler at ~16:10 on trade dates.

Methodology (largecap alerts):
  1. Entry price = open of the NEXT whole-minute bar after signal trigger.
     e.g. signal at 09:31:04 → entry = 09:32:00 bar's open.
     This simulates "see signal → place order → fill at next bar open."
  2. All horizon windows (5/15/30/60m) are counted from entry time.
     All targets are whole minutes → exact match in stock_min_kline.
  3. Returns are computed vs entry_price, not vs trigger snapshot price.
  4. entry_price and entry_time are stored for audit.

Index anomaly events:
  - Only ret_eod (index close vs trigger price). No minute klines for indexes.

Trading clock: 09:30-11:30 / 13:00-15:00, lunch break skipped.
Path labels: assigned after backfill via monitor_outcome_labeler.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time as dt_time, timedelta

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)

# ── Trading clock helpers ────────────────────────────────────────

_MORNING_OPEN = dt_time(9, 30)
_MORNING_CLOSE = dt_time(11, 30)
_AFTERNOON_OPEN = dt_time(13, 0)
_AFTERNOON_CLOSE = dt_time(15, 0)


def _advance_trading_minutes(base: datetime, minutes: int) -> datetime | None:
    """Advance *minutes* of trading time from *base*, skipping lunch break.

    Returns None if the target falls after 15:00 (incomplete window).
    Assumes base has second=0.
    """
    remaining = minutes
    cursor = base

    while remaining > 0:
        t = cursor.time()
        if t < _MORNING_OPEN:
            cursor = cursor.replace(hour=9, minute=30, second=0)
            t = cursor.time()
        if _MORNING_OPEN <= t < _MORNING_CLOSE:
            mins_to_lunch = int((_as_dt(cursor, _MORNING_CLOSE) - cursor).total_seconds() / 60)
            if remaining <= mins_to_lunch:
                cursor += timedelta(minutes=remaining)
                remaining = 0
            else:
                remaining -= mins_to_lunch
                cursor = cursor.replace(hour=13, minute=0, second=0)
        elif _MORNING_CLOSE <= t < _AFTERNOON_OPEN:
            cursor = cursor.replace(hour=13, minute=0, second=0)
        elif _AFTERNOON_OPEN <= t < _AFTERNOON_CLOSE:
            mins_to_close = int((_as_dt(cursor, _AFTERNOON_CLOSE) - cursor).total_seconds() / 60)
            if remaining <= mins_to_close:
                cursor += timedelta(minutes=remaining)
                remaining = 0
            else:
                return None  # Window extends past close — incomplete
        else:
            return None  # After close

    if cursor.time() > _AFTERNOON_CLOSE:
        return None
    return cursor


def _as_dt(ref: datetime, t: dt_time) -> datetime:
    return ref.replace(hour=t.hour, minute=t.minute, second=t.second, microsecond=0)


# ── Price helpers (exact minute match only) ──────────────────────

def _ret_exact(price_map: dict[str, float], target_dt: datetime | None,
               entry_price: float) -> float | None:
    """Return % at target_dt — exact minute match only, no forward tolerance."""
    if target_dt is None or entry_price <= 0:
        return None
    target_str = target_dt.strftime("%H:%M:%S")
    p = price_map.get(target_str)
    if p is None:
        return None
    return round((p - entry_price) / entry_price * 100, 3)


def _max_up_down_in_window(
    price_series: list[tuple[str, float]],
    start_str: str,
    end_dt: datetime | None,
    entry_price: float,
) -> tuple[float | None, float | None]:
    """Max upward and max downward move (%) within [start, end] window."""
    if end_dt is None or entry_price <= 0:
        return None, None
    end_str = end_dt.strftime("%H:%M:%S")
    max_up = 0.0
    max_down = 0.0
    found = False
    for ts, close in price_series:
        if ts < start_str or ts > end_str:
            continue
        ret = (close - entry_price) / entry_price * 100
        if ret > max_up:
            max_up = ret
        if ret < max_down:
            max_down = ret
        found = True
    if not found:
        return None, None
    return round(max_up, 3), round(max_down, 3)


def _close_pos_in_window(
    price_series: list[tuple[str, float]],
    start_str: str,
    end_dt: datetime | None,
    close_price: float | None,
) -> float | None:
    """Position of close price within [low, high] of window.  0=low, 1=high."""
    if end_dt is None or close_price is None:
        return None
    end_str = end_dt.strftime("%H:%M:%S")
    prices_in_window = [close for ts, close in price_series
                        if start_str <= ts <= end_str]
    if not prices_in_window:
        return None
    hi = max(prices_in_window)
    lo = min(prices_in_window)
    if hi == lo:
        return 0.5  # flat
    return round((close_price - lo) / (hi - lo), 3)


# ── Main backfill ────────────────────────────────────────────────

def backfill_monitor_returns(trade_date: str | None = None) -> dict:
    """Backfill outcome returns for today's monitor events and largecap alerts.

    Largecap: entry = next-minute-bar open, all returns vs entry_price.
    Index: ret_eod only (trigger price vs index close).
    """
    from app.core.config import settings

    if not trade_date:
        trade_date = date.today().strftime("%Y%m%d")

    event_date_iso = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    trade_date_dash = event_date_iso
    sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg")
    eng = create_engine(sync_url, echo=False)

    events_updated = 0
    alerts_updated = 0

    try:
        with eng.connect() as conn:
            # ── 1. Index anomaly events ──
            # No index minute klines → only ret_eod.  All other fields stay NULL.
            events = conn.execute(text("""
                SELECT id, index_code, event_ts, event_time, price_now
                FROM monitor_events
                WHERE event_date = :ed AND ret_eod IS NULL
            """), {"ed": event_date_iso}).fetchall()

            index_closes: dict[str, float] = {}
            if events:
                ic = conn.execute(text("""
                    SELECT ts_code, close FROM index_daily
                    WHERE trade_date = :td
                """), {"td": trade_date}).fetchall()
                index_closes = {r[0]: float(r[1]) for r in ic if r[1]}

            for row in events:
                ev_id, index_code, ev_ts, ev_time, price_now = row
                if not price_now or price_now <= 0:
                    continue
                close = index_closes.get(index_code)
                if not close:
                    continue
                eod_ret = round((close - float(price_now)) / float(price_now) * 100, 3)
                conn.execute(text("""
                    UPDATE monitor_events SET ret_eod = :eod WHERE id = :id
                """), {"eod": eod_ret, "id": ev_id})
                events_updated += 1

            # ── 2. Largecap alerts ──
            # Entry = next whole minute bar's open.  We also pull alerts whose
            # ret_5m is already filled but ret_eod is still NULL, so adding a
            # new window retroactively rehydrates history without rescanning
            # minute klines.
            alerts = conn.execute(text("""
                SELECT id, ts_code, event_ts, event_time, entry_price
                FROM monitor_largecap_alerts
                WHERE event_date = :ed
                  AND (ret_5m IS NULL OR ret_eod IS NULL)
            """), {"ed": event_date_iso}).fetchall()

            # Preload daily closes for all involved tickers (one query).
            lc_codes = sorted({str(a[1]) for a in alerts})
            daily_closes: dict[str, float] = {}
            if lc_codes:
                dc = conn.execute(text("""
                    SELECT ts_code, close FROM stock_daily
                    WHERE trade_date = :td AND ts_code = ANY(:codes)
                """), {"td": trade_date, "codes": lc_codes}).fetchall()
                daily_closes = {r[0]: float(r[1]) for r in dc if r[1]}

            for row in alerts:
                alert_id, ts_code, ev_ts, ev_time, existing_entry = row

                # ── Fast path: ret_5m already filled, just backfill ret_eod ──
                if existing_entry is not None and existing_entry > 0:
                    close = daily_closes.get(ts_code)
                    if close:
                        eod = round(
                            (close - float(existing_entry)) / float(existing_entry) * 100,
                            3,
                        )
                        conn.execute(text("""
                            UPDATE monitor_largecap_alerts SET ret_eod = :eod
                            WHERE id = :id AND ret_eod IS NULL
                        """), {"eod": eod, "id": alert_id})
                        alerts_updated += 1
                    continue

                try:
                    event_dt = datetime.strptime(
                        f"{trade_date_dash} {ev_time}", "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue

                # ── Entry: truncate to current minute, advance +1 trading min ──
                truncated_dt = event_dt.replace(second=0, microsecond=0)
                entry_dt = _advance_trading_minutes(truncated_dt, 1)
                if entry_dt is None:
                    continue  # Event too close to close — no executable entry

                entry_time_str = entry_dt.strftime("%H:%M:%S")

                # ── Windows from entry (all whole minutes → exact match) ──
                t5_dt = _advance_trading_minutes(entry_dt, 5)
                t15_dt = _advance_trading_minutes(entry_dt, 15)
                t30_dt = _advance_trading_minutes(entry_dt, 30)
                t60_dt = _advance_trading_minutes(entry_dt, 60)

                end_dt = t60_dt or t30_dt or t15_dt or t5_dt
                if not end_dt:
                    continue

                # ── Fetch minute klines: need open (for entry) + close (for exits) ──
                prices = conn.execute(text("""
                    SELECT trade_time, open, close
                    FROM stock_min_kline
                    WHERE ts_code = :code
                      AND trade_time >= :t0 AND trade_time <= :t1
                      AND freq = '1min'
                    ORDER BY trade_time
                """), {
                    "code": ts_code,
                    "t0": f"{trade_date_dash} {entry_time_str}",
                    "t1": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                }).fetchall()

                if not prices:
                    continue

                # ── Verify entry bar exists at expected time ──
                first_bar_time = (prices[0][0].strftime("%H:%M:%S")
                                  if hasattr(prices[0][0], 'strftime')
                                  else str(prices[0][0]))
                if first_bar_time != entry_time_str:
                    logger.debug("skip %s: entry bar %s != expected %s",
                                 ts_code, first_bar_time, entry_time_str)
                    continue

                entry_price = float(prices[0][1])  # open of entry bar
                if entry_price <= 0:
                    continue

                # ── Build close price map (HH:MM:00 → close) ──
                price_series: list[tuple[str, float]] = []
                price_map: dict[str, float] = {}
                for p in prices:
                    ts_str = (p[0].strftime("%H:%M:%S")
                              if hasattr(p[0], 'strftime') else str(p[0]))
                    close_val = float(p[2])
                    price_series.append((ts_str, close_val))
                    price_map[ts_str] = close_val

                # ── Returns at each horizon (exact match) ──
                r5 = _ret_exact(price_map, t5_dt, entry_price)
                r15 = _ret_exact(price_map, t15_dt, entry_price)
                r30 = _ret_exact(price_map, t30_dt, entry_price)
                r60 = _ret_exact(price_map, t60_dt, entry_price)

                # ── Max up / down in 30m and 60m windows ──
                mu30, md30 = _max_up_down_in_window(
                    price_series, entry_time_str, t30_dt, entry_price)
                mu60, md60 = _max_up_down_in_window(
                    price_series, entry_time_str, t60_dt, entry_price)

                # ── Close position ──
                close_at_30 = price_map.get(t30_dt.strftime("%H:%M:%S")) if t30_dt else None
                close_at_60 = price_map.get(t60_dt.strftime("%H:%M:%S")) if t60_dt else None

                cp30 = _close_pos_in_window(
                    price_series, entry_time_str, t30_dt, close_at_30)
                cp60 = _close_pos_in_window(
                    price_series, entry_time_str, t60_dt, close_at_60)

                # ── Close-of-day return vs entry_price ──
                close_price = daily_closes.get(ts_code)
                reod = (round((close_price - entry_price) / entry_price * 100, 3)
                        if close_price else None)

                conn.execute(text("""
                    UPDATE monitor_largecap_alerts
                    SET entry_price = :ep, entry_time = :et,
                        ret_5m = :r5, ret_15m = :r15, ret_30m = :r30,
                        ret_60m = :r60, ret_eod = :reod,
                        max_up_30m = :mu30, max_down_30m = :md30,
                        max_up_60m = :mu60, max_down_60m = :md60,
                        close_pos_30m = :cp30, close_pos_60m = :cp60
                    WHERE id = :id
                """), {
                    "ep": entry_price, "et": entry_time_str,
                    "r5": r5, "r15": r15, "r30": r30, "r60": r60,
                    "reod": reod,
                    "mu30": mu30, "md30": md30,
                    "mu60": mu60, "md60": md60,
                    "cp30": cp30, "cp60": cp60,
                    "id": alert_id,
                })
                alerts_updated += 1

            conn.commit()

            # ── 3. Run path labeler on freshly backfilled rows ──
            try:
                from app.shared.monitor_outcome_labeler import label_outcomes
                label_result = label_outcomes(conn, event_date_iso)
                logger.info("path labeler: %s", label_result)
            except Exception:
                logger.exception("path labeler failed for %s", trade_date)

    except Exception:
        logger.exception("monitor backfill failed for %s", trade_date)
    finally:
        eng.dispose()

    logger.info("monitor backfill %s: events=%d, alerts=%d",
                trade_date, events_updated, alerts_updated)
    return {"events_updated": events_updated, "alerts_updated": alerts_updated}
