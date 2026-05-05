"""模式 7 ｜ 盘中一字跌停被打开 → 抢反弹（CB 主品种 T+0）。

模式手册原文：盘中观察到正股一字跌停被打开 → 第一时间买**这只正股的可转债**。
完全依赖分钟级数据，必须分钟级触发。

A 股合规口径：只发 CB 信号
    A 股 T+1 → 当日买正股当日不能卖 → 这种盘中博反弹必须用 CB（T+0）

严格触发条件（日级初筛 + 分钟级精确）：
    日级初筛：
        - T 日 open == high（开盘即最高价 = 一字跌停特征）
        - open / pre_close ≤ 0.905（开盘价是跌停价）
        - close > open（盘中被打开 + 收盘高于开盘 = 反弹有效）
    分钟级触发（在分钟线里找）：
        - 找第一根 high > open 的分钟 = 被打开的瞬间
        - 买入价 = 该分钟 CB close
        - 卖出价 = T 日 14:55 CB close（尾盘锁定）

风险：
    - 打开是假动作，再次封死 → 承认开板瞬间买入价 = 反弹起点
    - 该正股没 CB → 跳过（因为正股 T+1 不能玩）
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.research.data.cb_resolver import find_cb_for_stock
from app.research.strategies.base_pattern import (
    BasePattern,
    PatternSignal,
)

logger = logging.getLogger(__name__)


YIZI_DOWN_TOLERANCE = 0.005  # open/pre_close 接近 0.9（容许 0.5% 误差）


class Pattern07(BasePattern):
    pattern_id = "pattern_07"
    description = "盘中一字跌停被打开 → 买 CB（分钟级）"

    async def _find_yizi_down_open_candidates(
        self, session: AsyncSession, trade_date: str
    ) -> list[dict]:
        """日级初筛：开盘一字跌停 + 盘中被打开（close > open）。"""
        rows = (await session.execute(text(
            "SELECT d.ts_code, sb.name, d.open, d.high, d.low, d.close, d.pre_close "
            "FROM stock_daily d "
            "JOIN stock_basic sb ON sb.ts_code=d.ts_code "
            "WHERE d.trade_date=:td AND sb.list_status='L' "
            "  AND d.pre_close > 0 "
            "  AND ABS(d.open / d.pre_close - 0.9) < :tol "  # 开盘 = 跌停价
            "  AND d.open = d.high "                            # 开盘即最高 = 一字开盘
            "  AND d.close > d.open"                            # 盘中被打开
        ), {"td": trade_date, "tol": YIZI_DOWN_TOLERANCE})).fetchall()
        return [
            {"ts_code": r[0], "name": (r[1] or "").replace(" ", ""),
             "open": r[2], "high": r[3], "low": r[4], "close": r[5], "pre_close": r[6]}
            for r in rows
        ]

    async def _find_break_minute(
        self, session: AsyncSession, ts_code: str, trade_date: str, open_price: float
    ) -> str | None:
        """分钟级扫描：找第一根 high > open（=跌停被打开）的分钟。返回 HHMMSS。"""
        td_start = datetime.strptime(trade_date, "%Y%m%d").replace(hour=9, minute=30)
        td_end = datetime.strptime(trade_date, "%Y%m%d").replace(hour=15, minute=0)
        # 容差：跌停价之上才算"打开"，避免微小波动误触
        threshold = open_price * 1.001
        r = await session.execute(text(
            "SELECT trade_time FROM stock_min_kline "
            "WHERE ts_code=:c AND freq='1min' "
            "AND trade_time >= :s AND trade_time <= :e "
            "AND high > :th "
            "ORDER BY trade_time ASC LIMIT 1"
        ), {"c": ts_code, "s": td_start, "e": td_end, "th": threshold})
        row = r.fetchone()
        if not row:
            return None
        ts: datetime = row[0]
        return f"{ts.hour:02d}{ts.minute:02d}{ts.second:02d}"

    async def find_signals(
        self, session: AsyncSession, trade_date: str, source: str = "bankuai"
    ) -> list[PatternSignal]:
        candidates = await self._find_yizi_down_open_candidates(session, trade_date)
        if not candidates:
            return []
        logger.info("pattern_07 %s: %d 一字跌停打开候选", trade_date, len(candidates))

        signals: list[PatternSignal] = []
        for c in candidates:
            break_time = await self._find_break_minute(
                session, c["ts_code"], trade_date, c["open"]
            )
            if not break_time:
                continue  # 没找到分钟级打开点 → 数据缺失 / 实际未打开
            # A 股 T+1 → 必须有 CB 才发；正股不发
            cb_code = await find_cb_for_stock(session, c["ts_code"], trade_date)
            if not cb_code:
                continue
            base = dict(
                trade_date=trade_date,
                pattern=self.pattern_id,
                sector="(盘中一字跌停打开)",
                long1_code=c["ts_code"],
                long1_name=c["name"],
                long1_tag=f"开板@{break_time[:4]}",
                long1_first_time="",
                long1_open_times=1,
                sector_size=1,
                pick_role="long1_cb",
                pick_tag="一字跌停打开",
                holding="intraday",
                buy_anchor="intraday_at",
                buy_anchor_time=break_time,
                sell_anchor="intraday_at",
                sell_anchor_time="145500",
            )
            signals.append(PatternSignal(
                **base,
                pick_code=cb_code,
                pick_name=f"{c['name']}转债",
                reason=f"正股开盘一字跌停{(c['open']/c['pre_close']-1)*100:.1f}% "
                       f"分钟开板@{break_time[:4]} 收{(c['close']/c['pre_close']-1)*100:.1f}% [CB]",
                pick_kind="cb",
                underlying_code=c["ts_code"],
            ))
        return signals

    async def _check(self, lh, sector_size, ohlc_map, trade_date, prediction=None):
        return None
