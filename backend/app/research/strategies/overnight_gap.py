"""Overnight Gap V2 — minute-level factors, zero look-ahead bias.

Two modes:
  - "fixed":  Score at a fixed minute (e.g. 14:50), pick TOP N.
              Equivalent to V8 but with no look-ahead in scoring.
  - "signal": Scan 14:30-14:55, buy when absolute score crosses threshold.
              May buy 0-N stocks per day.

Architecture:
  1. Pre-filter: MA20/ST/avg_amount from prior daily data (shift(1), no look-ahead)
  2. Load full-day minute bars (batched IN clause, per-day)
  3. Pre-compute running aggregates per stock (running high/low/cum_vol)
  4. Score using factors from minute data at evaluation time T (no future data)
  5. Execute buy at daily close (simulating closing auction participation)
  6. Sell at next day's open
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime as _dt

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 244
RISK_FREE_RATE = 0.03
COMMISSION_RATE = 0.00025
MIN_COMMISSION = 5.0
STAMP_TAX_RATE = 0.0005
TRANSFER_FEE_RATE = 0.00001

TRADING_MINUTES_PER_DAY = 240
MAX_BUY_PER_DAY = 3
LOT_SIZE = 100
SCAN_START = 1430
SCAN_END = 1455
AMOUNT_THRESHOLD = 10_000_000.0


def _minutes_elapsed(hhmm) -> int | np.ndarray:
    """Convert HHMM to trading minutes elapsed since 09:30. Handles scalar or array."""
    hhmm = np.asarray(hhmm)
    h, m = np.divmod(hhmm, 100)
    result = np.where(h < 12, (h - 9) * 60 + (m - 30), 120 + (h - 13) * 60 + m)
    if result.ndim == 0:
        return int(result)
    return result


def calc_fee(price: float, qty: int, side: str, ts_code: str) -> float:
    amount = price * qty
    commission = max(amount * COMMISSION_RATE, MIN_COMMISSION)
    stamp = amount * STAMP_TAX_RATE if side == "SELL" else 0
    transfer = amount * TRANSFER_FEE_RATE if ts_code.endswith(".SH") else 0
    return round(commission + stamp + transfer, 2)


# ---------------------------------------------------------------------------
# Pre-filter
# ---------------------------------------------------------------------------

def _build_candidate_meta(
    all_daily_sorted: pd.DataFrame,
    trade_dates: list[str],
    st_by_date: dict[str, set[str]],
) -> dict[str, pd.DataFrame]:
    ds = all_daily_sorted.copy()
    ds["_ma20"] = ds.groupby("ts_code")["close"].transform(
        lambda x: x.rolling(20, min_periods=15).mean()
    )
    ds["_avg_vol_20"] = ds.groupby("ts_code")["vol"].transform(
        lambda x: x.rolling(20, min_periods=15).mean()
    )
    ds["_avg_amt_20"] = ds.groupby("ts_code")["amount"].transform(
        lambda x: x.rolling(20, min_periods=10).mean()
    )
    ds["ma20"] = ds.groupby("ts_code")["_ma20"].shift(1)
    ds["avg_vol_20"] = ds.groupby("ts_code")["_avg_vol_20"].shift(1)
    ds["avg_amt_20"] = ds.groupby("ts_code")["_avg_amt_20"].shift(1)

    date_set = set(trade_dates)
    bt = ds[ds["trade_date"].isin(date_set)].copy()

    meta_by_date: dict[str, pd.DataFrame] = {}
    for d, g in bt.groupby("trade_date"):
        sub = g[["ts_code", "ma20", "avg_vol_20", "avg_amt_20", "name"]].copy()
        sub = sub.dropna(subset=["ma20", "avg_vol_20"])
        sub = sub[(sub["ma20"] > 0) & (sub["avg_vol_20"] > 0)]
        sub = sub[sub["avg_amt_20"] >= 5_000_000]
        st = st_by_date.get(d, set())
        if st:
            sub = sub[~sub["ts_code"].isin(st)]
        meta_by_date[d] = sub.reset_index(drop=True)
    return meta_by_date


# ---------------------------------------------------------------------------
# Running stats (with tail-session baselines)
# ---------------------------------------------------------------------------

TAIL_BASELINE_HHMM = 1400  # afternoon session baseline for tail factors

def _build_running_stats(day_bars: pd.DataFrame) -> pd.DataFrame:
    if day_bars.empty:
        return pd.DataFrame()
    df = day_bars.sort_values(["ts_code", "hhmm"]).copy()

    grp = df.groupby("ts_code")
    open_prices = grp["open"].first().rename("open_price")

    df["running_high"] = grp["high"].cummax()
    df["running_low"] = grp["low"].cummin()
    df["cum_vol"] = grp["vol"].cumsum()
    df["cum_amount"] = grp["amount"].cumsum()
    df = df.merge(open_prices, on="ts_code")

    # Tail baseline: capture state at 14:00 for each stock
    baseline = df[df["hhmm"] == TAIL_BASELINE_HHMM][
        ["ts_code", "close", "cum_vol", "cum_amount"]
    ].rename(columns={
        "close": "close_1400",
        "cum_vol": "cum_vol_1400",
        "cum_amount": "cum_amt_1400",
    })
    if baseline.empty:
        nearest = df[df["hhmm"] >= 1300].groupby("ts_code").first().reset_index()
        baseline = nearest[["ts_code", "close", "cum_vol", "cum_amount"]].rename(
            columns={
                "close": "close_1400",
                "cum_vol": "cum_vol_1400",
                "cum_amount": "cum_amt_1400",
            }
        )

    df = df.merge(baseline, on="ts_code", how="left")

    return df[["ts_code", "hhmm", "close", "open_price",
               "running_high", "running_low", "cum_vol", "cum_amount",
               "close_1400", "cum_vol_1400", "cum_amt_1400"]]


# ---------------------------------------------------------------------------
# Scoring — tail-momentum-focused factors
# ---------------------------------------------------------------------------

def _filter_and_score(
    snapshot: pd.DataFrame,
    meta: pd.DataFrame,
    limit_map: dict[str, tuple[float, float]],
    time_frac: float,
    mode: str = "fixed",
) -> pd.DataFrame:
    """Filter and score candidates at a given minute.

    Factors (all computed from data available at evaluation minute T):
      1. tail_ret:      return from 14:00 to T (tail momentum)
      2. tail_vol_spike: tail volume vs morning volume (accumulation signal)
      3. price_position: (close - low) / (high - low) (reversal strength)
      4. vol_ratio:      cum_vol / expected vol (overall activity)
      5. ma_proximity:   distance to MA20 (technical support)
    """
    if snapshot.empty:
        return pd.DataFrame()

    df = snapshot.merge(meta, on="ts_code", how="inner")
    if df.empty:
        return pd.DataFrame()

    # Tradability: exclude limit-up/down
    if limit_map:
        df["_up"] = df["ts_code"].map(lambda c: limit_map.get(c, (None, None))[0])
        df["_dn"] = df["ts_code"].map(lambda c: limit_map.get(c, (None, None))[1])
        df = df[df["_up"].isna() | (df["close"] < df["_up"] * 0.999)]
        df = df[df["_dn"].isna() | (df["close"] > df["_dn"] * 1.001)]

    # Liquidity: cumulative amount must exceed scaled threshold
    scaled_amt = AMOUNT_THRESHOLD * time_frac
    df = df[df["cum_amount"] >= scaled_amt]

    if df.empty:
        return pd.DataFrame()

    # --- Compute factors ---
    rng = df["running_high"] - df["running_low"]

    # F1: Tail momentum — return from 14:00 to current
    df["tail_ret"] = np.where(
        df["close_1400"] > 0,
        (df["close"] - df["close_1400"]) / df["close_1400"] * 100,
        0.0,
    )

    # F2: Tail volume spike — per-minute volume in tail vs morning
    tail_vol = (df["cum_vol"] - df["cum_vol_1400"]).clip(lower=0)
    morning_vol = df["cum_vol_1400"]
    tail_minutes = np.maximum(
        _minutes_elapsed(df["hhmm"].values) - _minutes_elapsed(TAIL_BASELINE_HHMM), 1
    )
    morning_minutes = _minutes_elapsed(TAIL_BASELINE_HHMM)
    df["tail_vol_spike"] = np.where(
        morning_vol > 0,
        (tail_vol / tail_minutes) / (morning_vol / morning_minutes),
        1.0,
    )

    # F3: Price position in day's range
    df["price_position"] = np.where(
        rng > 0.001,
        (df["close"] - df["running_low"]) / rng,
        0.5,
    )

    # F4: Volume ratio vs 20-day average
    expected_vol = df["avg_vol_20"] * time_frac
    df["vol_ratio"] = np.where(expected_vol > 0, df["cum_vol"] / expected_vol, 1.0)

    # F5: MA20 proximity
    df["ma_proximity"] = (df["close"] / df["ma20"] - 1) * 100

    # F6: Intraday return from open
    df["intraday_ret"] = np.where(
        df["open_price"] > 0,
        (df["close"] - df["open_price"]) / df["open_price"] * 100,
        0.0,
    )

    # Clip
    df["tail_ret"] = df["tail_ret"].clip(-5, 5)
    df["tail_vol_spike"] = df["tail_vol_spike"].clip(0.2, 5.0)
    df["vol_ratio"] = df["vol_ratio"].clip(0.3, 5.0)
    df["ma_proximity"] = df["ma_proximity"].clip(-10, 10)
    df["intraday_ret"] = df["intraday_ret"].clip(-8, 8)

    # Volume-price divergence: high volume + slight price decline = stealth accumulation
    df["vol_price_div"] = df["tail_vol_spike"] * np.where(
        df["tail_ret"] < 0,
        (-df["tail_ret"]).clip(0, 3),   # reward negative tail (accumulation)
        0.1,                             # small weight for positive tail
    )

    # Hard filters: significant tail volume, near MA20, not extreme moves
    df = df[
        (df["tail_vol_spike"] > 1.3)     # significantly above-average tail volume
        & (df["intraday_ret"] > -3)       # not crashing
        & (df["intraday_ret"] < 3)        # not limit-up territory
        & (df["ma_proximity"] > -5)       # within 5% of MA20
    ]

    if df.empty:
        return pd.DataFrame()

    if mode == "fixed":
        if len(df) < 2:
            return df.assign(score=0.5)
        # Rank: highest volume spike + volume-price divergence
        for col in ("tail_vol_spike", "vol_price_div", "vol_ratio"):
            df[f"_{col}_r"] = df[col].rank(pct=True, method="average")
        df["_ma_r"] = df["ma_proximity"].rank(pct=True, method="average")
        df["score"] = (
            0.35 * df["_tail_vol_spike_r"]
            + 0.30 * df["_vol_price_div_r"]
            + 0.20 * df["_vol_ratio_r"]
            + 0.15 * df["_ma_r"]
        )
    else:
        df = df.assign(
            s1=(df["tail_vol_spike"].clip(0.5, 4.0) - 0.5) / 3.5,
            s2=df["vol_price_div"].clip(0, 5) / 5.0,
            s3=(df["vol_ratio"].clip(0.5, 3.0) - 0.5) / 2.5,
            s4=(df["ma_proximity"].clip(-5, 5) + 5) / 10.0,
        )
        df["score"] = (
            0.35 * df["s1"] + 0.30 * df["s2"]
            + 0.20 * df["s3"] + 0.15 * df["s4"]
        )

    return df.sort_values("score", ascending=False)


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class DailyRecord:
    trade_date: str
    next_date: str
    ts_code: str
    name: str
    buy_minute: int
    buy_price: float
    buy_score: float
    sell_price: float
    qty: int
    buy_fee: float
    sell_fee: float
    pnl: float
    ret: float


@dataclass
class BacktestSummary:
    start_date: str
    end_date: str
    trading_days: int
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    avg_daily_pnl: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    daily_pnl_list: list[float] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    trade_log: list[DailyRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main backtest
# ---------------------------------------------------------------------------

async def run_backtest(
    start_date: str = "20251001",
    end_date: str = "20260327",
    initial_capital: float = 100_000.0,
    max_buy: int = MAX_BUY_PER_DAY,
    lot_size: int = LOT_SIZE,
    mode: str = "signal",
    entry_minute: int = 1450,
    buy_threshold: float = 0.45,
) -> BacktestSummary:
    """Run the overnight gap backtest.

    Parameters
    ----------
    mode : "fixed" or "signal"
        "fixed" = score at entry_minute, buy top max_buy (no threshold).
        "signal" = scan 14:30-14:55, buy when score > buy_threshold.
    entry_minute : int
        HHMM for fixed mode (default 1450).
    buy_threshold : float
        Score threshold for signal mode (default 0.45).
    """
    from app.shared.data.data_loader import DataLoader

    loader = DataLoader()

    all_cal = await loader.trade_calendar("20250801", end_date)
    trade_dates = [d for d in all_cal if start_date <= d <= end_date]
    if len(trade_dates) < 2:
        raise ValueError("Not enough trading days")

    pre_start_idx = max(0, next(i for i, d in enumerate(all_cal) if d >= start_date) - 25)
    pre_start = all_cal[pre_start_idx]

    logger.info("OvernightGap V2 [%s]: %s~%s, %d days",
                mode, start_date, end_date, len(trade_dates))

    all_daily = await loader._query(
        "SELECT d.ts_code, d.trade_date, d.open, d.high, d.low, d.close, "
        "d.pct_chg, d.vol, d.amount, s.name "
        "FROM stock_daily d "
        "JOIN stock_basic s ON d.ts_code = s.ts_code "
        "WHERE d.trade_date >= :sd AND d.trade_date <= :ed "
        "AND s.list_status = 'L' AND d.vol > 0 "
        "ORDER BY d.ts_code, d.trade_date",
        {"sd": pre_start, "ed": end_date},
    )
    limit_df = await loader._query(
        "SELECT ts_code, trade_date, up_limit, down_limit "
        "FROM stock_limit WHERE trade_date >= :sd AND trade_date <= :ed",
        {"sd": start_date, "ed": end_date},
    )
    st_df = await loader._query(
        "SELECT ts_code, trade_date FROM stock_st "
        "WHERE trade_date >= :sd AND trade_date <= :ed",
        {"sd": start_date, "ed": end_date},
    )

    limit_by_date: dict[str, dict] = {}
    if not limit_df.empty:
        for d, g in limit_df.groupby("trade_date"):
            limit_by_date[d] = dict(zip(g["ts_code"], zip(g["up_limit"], g["down_limit"])))

    st_by_date: dict[str, set[str]] = {}
    if not st_df.empty:
        for d, g in st_df.groupby("trade_date"):
            st_by_date[d] = set(g["ts_code"])

    tomorrow_open_by_date: dict[str, dict[str, float]] = {}
    today_close_by_date: dict[str, dict[str, float]] = {}
    daily_by_date = {d: g for d, g in all_daily[all_daily["trade_date"] >= start_date].groupby("trade_date")}
    for d, g in daily_by_date.items():
        tomorrow_open_by_date[d] = dict(zip(g["ts_code"], g["open"]))
        today_close_by_date[d] = dict(zip(g["ts_code"], g["close"]))

    logger.info("Building candidate metadata ...")
    meta_by_date = _build_candidate_meta(all_daily, trade_dates[:-1], st_by_date)

    equity = initial_capital
    equity_curve: list[float] = [equity]
    daily_pnl_list: list[float] = []
    all_records: list[DailyRecord] = []
    no_min_days = 0

    for i in range(len(trade_dates) - 1):
        t_date = trade_dates[i]
        t1_date = trade_dates[i + 1]

        meta = meta_by_date.get(t_date)
        if meta is None or meta.empty:
            daily_pnl_list.append(0); equity_curve.append(equity); continue

        t1_opens = tomorrow_open_by_date.get(t1_date, {})
        if not t1_opens:
            daily_pnl_list.append(0); equity_curve.append(equity); continue

        # Load minute data
        cand_codes = list(meta["ts_code"])
        td_start = _dt.strptime(t_date, "%Y%m%d").replace(hour=9, minute=30)
        td_end = _dt.strptime(t_date, "%Y%m%d").replace(hour=15, minute=0)

        day_min = pd.DataFrame()
        for b in range(0, len(cand_codes), 500):
            chunk = cand_codes[b:b + 500]
            codes_sql = ",".join(f"'{c}'" for c in chunk)
            part = await loader._query(
                f"SELECT ts_code, trade_time, open, high, low, close, vol, amount "
                f"FROM stock_min_kline "
                f"WHERE freq = '1min' AND trade_time >= :sd AND trade_time <= :ed "
                f"AND ts_code IN ({codes_sql})",
                {"sd": td_start, "ed": td_end},
            )
            if not part.empty:
                day_min = pd.concat([day_min, part], ignore_index=True)

        if day_min.empty:
            no_min_days += 1
            daily_pnl_list.append(0); equity_curve.append(equity); continue

        day_min["hhmm"] = day_min["trade_time"].dt.hour * 100 + day_min["trade_time"].dt.minute
        running = _build_running_stats(day_min)
        if running.empty:
            daily_pnl_list.append(0); equity_curve.append(equity); continue

        limits = limit_by_date.get(t_date, {})

        bought_today: list[DailyRecord] = []
        bought_codes: set[str] = set()

        t_close_map = today_close_by_date.get(t_date, {})

        if mode == "fixed":
            # Score at fixed minute, buy top N, execute at daily close
            hm = entry_minute
            avail = sorted(running["hhmm"].unique())
            if hm not in avail:
                candidates = [m for m in avail if abs(m - hm) <= 5]
                hm = max(candidates) if candidates else (avail[-1] if avail else 0)
            if hm == 0:
                daily_pnl_list.append(0); equity_curve.append(equity); continue

            time_frac = _minutes_elapsed(hm) / TRADING_MINUTES_PER_DAY
            snapshot = running[running["hhmm"] == hm].copy()
            scored = _filter_and_score(snapshot, meta, limits, time_frac, mode="fixed")

            if not scored.empty:
                picks = scored.head(max_buy)
                for _, row in picks.iterrows():
                    code = row["ts_code"]
                    buy_price = t_close_map.get(code)
                    sell_price = t1_opens.get(code)
                    if buy_price is None or sell_price is None or sell_price <= 0 or buy_price <= 0:
                        continue
                    qty = lot_size
                    bf = calc_fee(buy_price, qty, "BUY", code)
                    sf = calc_fee(sell_price, qty, "SELL", code)
                    pnl = (sell_price - buy_price) * qty - bf - sf
                    ret = (sell_price - buy_price) / buy_price * 100
                    bought_today.append(DailyRecord(
                        trade_date=t_date, next_date=t1_date, ts_code=code,
                        name=str(row.get("name", "")), buy_minute=hm,
                        buy_price=round(buy_price, 2),
                        buy_score=round(float(row["score"]), 4),
                        sell_price=round(sell_price, 2),
                        qty=qty, buy_fee=bf, sell_fee=sf,
                        pnl=round(pnl, 2), ret=round(ret, 2),
                    ))

        else:
            # Signal-trigger scanning, execute at daily close
            scan_minutes = [hm for hm in sorted(running["hhmm"].unique())
                           if SCAN_START <= hm <= SCAN_END]

            for hm in scan_minutes:
                if len(bought_today) >= max_buy:
                    break
                time_frac = _minutes_elapsed(hm) / TRADING_MINUTES_PER_DAY
                snapshot = running[running["hhmm"] == hm].copy()
                snapshot = snapshot[~snapshot["ts_code"].isin(bought_codes)]
                scored = _filter_and_score(snapshot, meta, limits, time_frac, mode="signal")
                if scored.empty:
                    continue
                best = scored.iloc[0]
                if best["score"] < buy_threshold:
                    continue
                code = best["ts_code"]
                buy_price = t_close_map.get(code)
                sell_price = t1_opens.get(code)
                if buy_price is None or sell_price is None or sell_price <= 0 or buy_price <= 0:
                    continue
                qty = lot_size
                bf = calc_fee(buy_price, qty, "BUY", code)
                sf = calc_fee(sell_price, qty, "SELL", code)
                pnl = (sell_price - buy_price) * qty - bf - sf
                ret = (sell_price - buy_price) / buy_price * 100
                bought_today.append(DailyRecord(
                    trade_date=t_date, next_date=t1_date, ts_code=code,
                    name=str(best.get("name", "")), buy_minute=hm,
                    buy_price=round(buy_price, 2),
                    buy_score=round(float(best["score"]), 4),
                    sell_price=round(sell_price, 2),
                    qty=qty, buy_fee=bf, sell_fee=sf,
                    pnl=round(pnl, 2), ret=round(ret, 2),
                ))
                bought_codes.add(code)

        all_records.extend(bought_today)
        day_pnl = sum(r.pnl for r in bought_today)
        daily_pnl_list.append(round(day_pnl, 2))
        equity += day_pnl
        equity_curve.append(round(equity, 2))

        if (i + 1) % 20 == 0:
            logger.info("  ... %d/%d days, equity=%.0f", i + 1, len(trade_dates) - 1, equity)

    if no_min_days:
        logger.warning("%d days without minute data", no_min_days)

    total_trades = len(all_records)
    wins = [r for r in all_records if r.pnl > 0]
    losses = [r for r in all_records if r.pnl <= 0]
    total_pnl = sum(r.pnl for r in all_records)
    total_return = total_pnl / initial_capital * 100

    n_days = len(daily_pnl_list)
    annual_factor = TRADING_DAYS_PER_YEAR / max(n_days, 1)
    annual_return = ((1 + total_pnl / initial_capital) ** annual_factor - 1) * 100

    eq_arr = np.array(equity_curve)
    peak = np.maximum.accumulate(eq_arr)
    dd = (peak - eq_arr) / np.where(peak > 0, peak, 1.0)
    max_drawdown = float(dd.max()) * 100

    daily_ret_arr = np.array(daily_pnl_list) / initial_capital
    if len(daily_ret_arr) > 1 and np.std(daily_ret_arr, ddof=1) > 1e-12:
        excess = daily_ret_arr - RISK_FREE_RATE / TRADING_DAYS_PER_YEAR
        sharpe = float(np.mean(excess) / np.std(excess, ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR))
    else:
        sharpe = 0.0

    gross_profit = sum(r.pnl for r in wins)
    gross_loss = abs(sum(r.pnl for r in losses))
    profit_factor = gross_profit / max(gross_loss, 0.01)

    summary = BacktestSummary(
        start_date=trade_dates[0], end_date=trade_dates[-1],
        trading_days=n_days, total_trades=total_trades,
        winning_trades=len(wins), losing_trades=len(losses),
        win_rate=round(len(wins) / max(total_trades, 1) * 100, 2),
        total_pnl=round(total_pnl, 2),
        total_return=round(total_return, 2),
        annual_return=round(annual_return, 2),
        max_drawdown=round(max_drawdown, 2),
        sharpe_ratio=round(sharpe, 4),
        avg_daily_pnl=round(total_pnl / max(n_days, 1), 2),
        avg_win=round(gross_profit / max(len(wins), 1), 2),
        avg_loss=round(-gross_loss / max(len(losses), 1), 2),
        profit_factor=round(profit_factor, 4),
        daily_pnl_list=daily_pnl_list,
        equity_curve=equity_curve,
        trade_log=all_records,
    )
    logger.info(
        "Result [%s]: trades=%d win=%.1f%% ret=%.2f%% sharpe=%.2f dd=%.2f%%",
        mode, total_trades, summary.win_rate, total_return, sharpe, max_drawdown,
    )
    return summary


def run_backtest_sync(**kwargs) -> BacktestSummary:
    return asyncio.run(run_backtest(**kwargs))


from app.shared.interfaces.models import BacktestContext, BarData, Signal
from app.shared.interfaces.strategy import IStrategy


class OvernightGapStrategy(IStrategy):
    name = "overnight_gap"
    description = "尾盘隔夜策略V2: 分钟级因子, 无未来函数, 双模式(固定/信号触发)"
    default_params = {
        "max_buy": 3,
        "lot_size": 100,
        "mode": "signal",
        "entry_minute": 1450,
        "buy_threshold": 0.45,
    }

    def on_init(self, ctx: BacktestContext) -> None:
        self._ctx = ctx

    def on_bar(self, bar_date: str, bars: dict[str, BarData]) -> list[Signal]:
        return []
