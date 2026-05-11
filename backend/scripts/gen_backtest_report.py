"""龙头隔夜模式回测 HTML 报告生成器。

用法:
    python backend/scripts/gen_backtest_report.py 20260430 20260506 20260507 20260508
    输出到 reports/backtest_YYYYMMDD_pattern1.html

复用 test_pattern_backtest.py 的 execute_signal + fetch_sector_followers + Pattern01。
HTML 含：汇总卡片 / 已成交表（含买入理由 + 板块跟风明细折叠）/ 未成交 SKIP 表。
"""
import argparse
import asyncio
import html
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.database import async_session  # noqa: E402
from app.research.signals.long_head_detector import fetch_minute_quotes  # noqa: E402
from app.research.strategies.base_pattern import PatternSignal, PatternTrade, load_sectors  # noqa: E402
from app.research.strategies.pattern_01_long1_natural import Pattern01  # noqa: E402
from sqlalchemy import text  # noqa: E402

from test_pattern_backtest import (  # noqa: E402
    execute_signal, fetch_sector_followers, role_label,
)


def _h(s) -> str:
    """HTML escape（None 转空串）。"""
    return html.escape(str(s)) if s is not None else ""


def _hhmm(anchor: str, anchor_time: str | None) -> str:
    if anchor == "today_close":
        return "14:55"
    if anchor in ("today_open", "next_open"):
        return "09:30"
    if anchor == "intraday_at" and anchor_time:
        return f"{anchor_time[:2]}:{anchor_time[2:4]}"
    return "?"


def build_trigger_reason(sig: PatternSignal, sec_info: dict) -> str:
    """触发（买入）理由：主线 / 角色 / 龙 1 / 板块强度 / 买入锚点 / 策略 reason。"""
    role = role_label(sig.pick_role)
    parts = [f"<b>主线</b>: {_h(sig.sector)} ／ <b>角色</b>: {_h(role)}"]

    if sig.pick_kind == "cb":
        parts.append(f"<b>正股</b>: {_h(sig.underlying_code or '?')}")

    parts.append(
        f"<b>龙 1</b>: {_h(sig.long1_name)}({_h(sig.long1_tag)}) "
        f"首封 {_h(sig.long1_first_time)}，当日炸板 {sig.long1_open_times} 次"
    )

    if sec_info:
        max_stock = sec_info.get("max_stock")
        if max_stock:
            parts.append(f"<b>板块最高</b>: {_h(max_stock[0])}({_h(max_stock[1])})")
        followers = sec_info.get("followers", [])
        at_long1 = sec_info.get("at_long1_count", 0)
        parts.append(
            f"<b>板块涨停</b>: 龙 1 封板时刻已封 {at_long1} 只 ／ 全天 {len(followers)} 只"
        )
    else:
        parts.append("<b>板块</b>: 萌芽板块 / 成员未识别")

    buy_t = _hhmm(sig.buy_anchor, sig.buy_anchor_time)
    parts.append(f"<b>买入锚点</b>: {sig.buy_anchor} ({buy_t})")

    if sig.reason:
        parts.append(f"<b>策略 reason</b>: {_h(sig.reason)}")

    return "<br>".join(parts)


def build_sell_reason(sig: PatternSignal) -> str:
    """卖出理由：优先用 sig.sell_reason（真实分支），fallback 到 sell_anchor 推断。"""
    sell_hhmm = ""
    if sig.sell_anchor_time:
        sell_hhmm = f"{sig.sell_anchor_time[:2]}:{sig.sell_anchor_time[2:4]}"
    diff_label = ""
    if sig.buy_anchor_time and sig.sell_anchor_time:
        try:
            buy_min = int(sig.buy_anchor_time[:2]) * 60 + int(sig.buy_anchor_time[2:4])
            sell_min = int(sig.sell_anchor_time[:2]) * 60 + int(sig.sell_anchor_time[2:4])
            diff_label = f"（持仓 {sell_min - buy_min} 分钟）"
        except Exception:
            pass

    # 优先用 sell_reason 字段（pattern_01 直接写入的真实分支）
    reason = getattr(sig, "sell_reason", "") or ""
    if reason == "C_vwap":
        return (
            f"<b>L_CB C 分支（VWAP 止损）</b>: underlying close 跌破当日 VWAP（开盘累计均价）"
            f"→ {sell_hhmm} 盘中止损卖出{diff_label}"
        )
    if reason == "C_rebuy_fixed_stop":
        return (
            f"<b>L_CB 买回固定止损</b>: CB 价跌破买回价 × 0.99（仅对买回 hold 生效，不走 VWAP）"
            f"→ {sell_hhmm} 卖出{diff_label}"
        )
    if reason == "B_window_timeout":
        return (
            f"<b>L_CB B 分支（T+0 立卖 / 评估窗超时）</b>: underlying 首次封板后给 10min 评估窗，"
            f"窗口内板块共识始终未达标（≥3 涨停 + 炸板 ≤1）→ {sell_hhmm} 窗口超时立卖{diff_label}"
        )
    if reason == "A_overnight":
        return (
            "<b>L_CB A 分支（升级隔夜）</b>: 板块共识达标（≥3 涨停 + 炸板 ≤1）→ "
            "CB 升级为隔夜持有，T+1 09:30 开盘卖出"
        )
    if reason == "A_then_recheck_fallback":
        return (
            f"<b>L_CB A→T+0 回退（题材崩）</b>: 升级隔夜后板块累计炸板 ≥3 → "
            f"{sell_hhmm} 盘中回退止损{diff_label}"
        )
    if reason == "D_today_close":
        return (
            "<b>L_CB D 分支（fallback）</b>: 盘中 underlying 既未封板共识达标也未触跌破止损 → "
            "T 日 14:55 尾盘 fallback 卖出"
        )

    # Fallback：sell_reason 为空（旧数据 / 正股 L1/L2 信号）
    if sig.sell_anchor == "next_open":
        if sig.pick_kind == "cb":
            return "<b>L_CB A 分支（升级隔夜）</b>: T+1 09:30 开盘卖出"
        return (
            "<b>L1 / L2 正股标准隔夜</b>: T+1 09:30 开盘卖出，"
            "博次日高开溢价（自然涨停启动 + 板块共识强 → 次日资金延续概率高）"
        )
    if sig.sell_anchor == "today_close":
        return "<b>D 分支 fallback</b>: T 日 14:55 尾盘卖出"
    if sig.sell_anchor == "intraday_at" and sell_hhmm:
        return f"<b>盘中卖出</b>: {sell_hhmm}{diff_label}"
    return f"<b>未知卖出锚点</b>: {sig.sell_anchor}"


# ---------------------------------------------------------------------------
# 板块共识股票（trigger 时点 ≥6%/≥8% 的板块成员，含未涨停的 ）
# ---------------------------------------------------------------------------

async def fetch_consensus_stocks(
    s, sector: str, trade_date: str, anchor_hhmmss: str,
    threshold: float, exclude_codes: set[str] | None = None,
) -> list[dict]:
    """拉指定时刻板块内涨幅 ≥threshold% 的所有股票（含未涨停）。"""
    from app.research.signals.theme_taxonomy import ALIAS_TO_CANONICAL

    if not sector or sector.startswith("("):
        return []

    aliases = [alias for alias, canon in ALIAS_TO_CANONICAL.items() if canon == sector]
    sub_names = list({sector, *aliases})

    cal_rows = (await s.execute(text(
        "SELECT cal_date FROM trade_cal WHERE cal_date < :td AND is_open=1 "
        "ORDER BY cal_date DESC LIMIT 5"
    ), {"td": trade_date})).fetchall()
    if not cal_rows:
        return []
    dates = [r[0] for r in cal_rows]

    code_rows = (await s.execute(text(
        "SELECT DISTINCT ts_code FROM daily_sector_review "
        "WHERE trade_date = ANY(:dates) AND sector_name = ANY(:names) "
        "AND source IN ('bankuai','jiuyan','llm_v2') "
        "AND ts_code IS NOT NULL AND ts_code <> ''"
    ), {"dates": dates, "names": sub_names})).fetchall()
    codes = [r[0] for r in code_rows]
    if not codes:
        return []

    quotes = await fetch_minute_quotes(s, trade_date, codes)
    minute_dt = datetime.strptime(trade_date, "%Y%m%d").replace(
        hour=int(anchor_hhmmss[:2]), minute=int(anchor_hhmmss[2:4])
    )

    excludes = exclude_codes or set()
    consensus = []
    for code in codes:
        if code in excludes:
            continue
        q = quotes.get((code, minute_dt))
        if q and q.pct >= threshold:
            consensus.append({"code": code, "pct": q.pct, "is_limit": q.is_limit})

    if consensus:
        name_rows = (await s.execute(text(
            "SELECT ts_code, name FROM stock_basic WHERE ts_code = ANY(:codes)"
        ), {"codes": [c["code"] for c in consensus]})).fetchall()
        name_map = {r[0]: (r[1] or "").replace(" ", "") for r in name_rows}
        for c in consensus:
            c["name"] = name_map.get(c["code"], c["code"])

    consensus.sort(key=lambda x: (-int(x["is_limit"]), -x["pct"]))
    return consensus


def consensus_threshold_for(sig: PatternSignal) -> float:
    """根据 reason / pick_role 推断该信号触发时用的共识阈值（6% 或 8%）。"""
    if sig.reason and "≥8%" in sig.reason:
        return 8.0
    if sig.pick_role in ("shadow", "long2", "shadow_cb", "long2_cb"):
        return 8.0
    return 6.0


def render_consensus(consensus: list[dict], threshold: float) -> str:
    if not consensus:
        return f"<span class='gray' style='font-size:12px'>触发时点板块内 ≥{threshold:.0f}% 共识股 0 只（去重 龙 1 / 标的）</span>"
    items = []
    for c in consensus:
        cls = "red" if c.get("is_limit") else ""
        flag = " 🔥" if c.get("is_limit") else ""
        pct_str = f"+{c['pct']:.2f}%"
        items.append(
            f"<li><span class='{cls}'>{_h(c['name'])}</span> "
            f"<span class='gray' style='font-size:11px'>({_h(c['code'])})</span> "
            f"<span class='{cls}'>{pct_str}</span>{flag}</li>"
        )
    return (
        f"<details open><summary style='cursor:pointer;color:#1890ff;font-size:12px;'>"
        f"🎯 触发时点板块共识股 {len(consensus)} 只 ≥{threshold:.0f}%（🔥 = 当时已涨停）</summary>"
        f"<ul style='margin:4px 0 0 20px;padding:0;font-size:12px;line-height:1.7;"
        f"columns:2;column-gap:24px;'>{''.join(items)}</ul></details>"
    )


def render_followers(sec_info: dict) -> str:
    if not sec_info:
        return '<span style="color:#999">—</span>'
    followers = sec_info.get("followers", [])
    if not followers:
        return '<span style="color:#999">板块无跟风</span>'
    items = []
    for f in followers:
        ft = f.get("first_time", "?")
        ft_fmt = f"{ft[:2]}:{ft[2:4]}" if len(ft) >= 4 and ft[:6].isdigit() else ft
        opens = f.get("open_times", 0)
        opens_str = f" 炸{opens}" if opens else ""
        items.append(
            f"<li>{_h(f.get('name', '?'))} "
            f"<span style='color:#666'>({_h(f.get('tag', '?'))}, {ft_fmt}{opens_str})</span></li>"
        )
    return (
        f"<details><summary style='cursor:pointer;color:#1890ff;font-size:12px;'>"
        f"📋 跟风明细 {len(followers)} 只（封板时刻已封 {sec_info.get('at_long1_count', 0)} 只）</summary>"
        f"<ul style='margin:4px 0 0 20px;padding:0;font-size:12px;line-height:1.6;'>"
        f"{''.join(items)}</ul></details>"
    )


CSS = """
* { box-sizing: border-box; }
body { font: 14px/1.55 "Microsoft YaHei", -apple-system, sans-serif;
       max-width: 1480px; margin: 0 auto; padding: 20px; background: #f6f7f9; color: #2c2c2c; }
h1 { margin: 0 0 6px; font-size: 22px; }
h2 { margin: 24px 0 10px; font-size: 17px; padding-left: 8px;
     border-left: 4px solid #1890ff; }
.meta { color: #666; font-size: 13px; }
.summary { display: flex; flex-wrap: wrap; gap: 14px; margin: 14px 0;
           padding: 14px 18px; background: #fff; border: 1px solid #e6e9ed;
           border-left: 4px solid #f5a623; }
.summary > div { font-weight: 700; font-size: 15px; min-width: 90px; }
.red { color: #d4380d; }
.green { color: #389e0d; }
.gray { color: #8c8c8c; }
table { border-collapse: collapse; width: 100%; background: #fff; font-size: 13px; }
th, td { border: 1px solid #e6e9ed; padding: 7px 9px; text-align: left;
         vertical-align: top; }
th { background: #fafbfc; font-weight: 700; color: #444; }
tr.win { background: #fff7f5; }
tr.loss { background: #f5fbf3; }
tr.skip td { color: #999; background: #fafafa; }
tr:hover td { background-color: #f0f6ff; }
.code { font-family: Consolas, Menlo, monospace; }
.tag { display: inline-block; padding: 1px 6px; background: #e6f4ff; color: #1890ff;
       border-radius: 3px; font-size: 11px; }
.role-龙1, .role-龙1债 { background: #fff1f0; color: #d4380d; }
.role-龙2, .role-龙2债 { background: #fff7e6; color: #d46b08; }
.role-影子龙, .role-影子龙债 { background: #f9f0ff; color: #722ed1; }
.role-跟风, .role-跟风债 { background: #f0f5ff; color: #1d39c4; }
.role-跟风债-买回 { background: #fff7e6; color: #fa8c16; font-weight: 700; }
.reason { font-size: 12px; line-height: 1.7; color: #444; }
.footer { margin-top: 30px; color: #999; font-size: 12px; text-align: center; }
"""


def render_html(trade_date: str, results: list, summary: dict, pattern_desc: str) -> str:
    """results: list of (idx, trade, sec_info, consensus_stocks)"""
    win_count = summary["wins"]
    lose_count = summary["losses"]
    total = summary["total"]
    win_rate = summary["win_rate"]
    avg_ret = summary["avg_ret"]
    pl_ratio = summary["pl_ratio"]
    pnl = summary["pnl"]
    skipped = summary["skipped"]
    cost = summary["cost"]
    revenue = summary["revenue"]
    fees = summary["fees"]
    avg_cost = summary["avg_cost"]
    avg_win = summary["avg_win"]
    avg_loss = summary["avg_loss"]

    # A 股配色：净盈亏 + = 红（盈利）／ - = 绿（亏损）
    pnl_cls = "red" if pnl > 0 else ("green" if pnl < 0 else "gray")
    avg_cls = "red" if avg_ret > 0 else ("green" if avg_ret < 0 else "gray")

    # 已成交表行
    traded_rows = []
    skip_rows = []
    for idx, trade, sec_info, consensus in results:
        sig = trade.signal
        role = role_label(sig.pick_role)
        kind_tag = "CB" if sig.pick_kind == "cb" else "股"
        target_html = (
            f"<div class='code'><span class='tag'>{kind_tag}</span> "
            f"{_h(sig.pick_code)}</div>"
            f"<div><b>{_h(sig.pick_name)}</b> "
            f"<span class='gray'>({_h(sig.pick_tag)})</span></div>"
        )
        if sig.pick_kind == "cb" and sig.underlying_code:
            target_html += f"<div class='gray' style='font-size:11px'>正股 {_h(sig.underlying_code)}</div>"

        sector_html = (
            f"<b>{_h(sig.sector)}</b>"
            f"<div><span class='tag role-{role}'>{_h(role)}</span></div>"
        )

        if trade.skip_reason:
            skip_rows.append(f"""
<tr class='skip'>
  <td>{idx}</td>
  <td>{sector_html}</td>
  <td>{target_html}</td>
  <td>{_h(trade.skip_reason)}</td>
</tr>""")
            continue

        buy_t = _hhmm(sig.buy_anchor, sig.buy_anchor_time)
        sell_t = _hhmm(sig.sell_anchor, sig.sell_anchor_time)
        sell_date = trade.next_date if sig.sell_anchor == "next_open" else sig.trade_date

        ret_cls = "red" if trade.ret_pct > 0 else ("green" if trade.ret_pct < 0 else "gray")
        # A 股配色：红涨绿跌（PnL 正=红，负=绿）
        pnl_row_cls = "win" if trade.pnl > 0 else "loss"
        sign_pct = "+" if trade.ret_pct > 0 else ""
        sign_pnl = "+" if trade.pnl > 0 else ""

        trigger_html = build_trigger_reason(sig, sec_info)
        sell_html = build_sell_reason(sig)
        followers_html = render_followers(sec_info)
        consensus_threshold = consensus_threshold_for(sig)
        consensus_html = render_consensus(consensus, consensus_threshold)

        # 每笔占用 + 回收（不计手续费，让用户看清"实际下单时打了多少钱进去"）
        trade_cost = (trade.buy_price or 0) * trade.qty
        trade_revenue = (trade.sell_price or 0) * trade.qty
        qty_label = f"{trade.qty} {'张' if sig.pick_kind == 'cb' else '股'}"
        traded_rows.append(f"""
<tr class='{pnl_row_cls}'>
  <td>{idx}</td>
  <td>{sector_html}</td>
  <td>{target_html}</td>
  <td><div class='code'>{sig.trade_date} {buy_t}</div><div class='code'>¥{trade.buy_price} × {qty_label}</div><div class='code' style='color:#666;font-size:11px'>占用 ¥{trade_cost:,.2f}</div></td>
  <td><div class='code'>{sell_date} {sell_t}</div><div class='code'>¥{trade.sell_price} × {qty_label}</div><div class='code' style='color:#666;font-size:11px'>回收 ¥{trade_revenue:,.2f}</div></td>
  <td class='{ret_cls}'>{sign_pct}{trade.ret_pct}%</td>
  <td class='{ret_cls}'>{sign_pnl}¥{trade.pnl:,.2f}<div style='color:#999;font-size:11px;font-weight:normal'>手续费 ¥{trade.fee:.2f}</div></td>
  <td>
    <div class='reason' style='border-left:3px solid #fa8c16;padding-left:8px;margin-bottom:8px'>
      <div style='color:#fa8c16;font-weight:700;margin-bottom:4px'>📥 触发理由（买入）</div>
      {trigger_html}
    </div>
    <div class='reason' style='border-left:3px solid #1890ff;padding-left:8px;margin-bottom:8px'>
      <div style='color:#1890ff;font-weight:700;margin-bottom:4px'>📤 卖出策略</div>
      {sell_html}
    </div>
    <div style='margin-top:6px'>{consensus_html}</div>
    <div style='margin-top:4px'>{followers_html}</div>
  </td>
</tr>""")

    # 组装最终 HTML
    return f"""<!doctype html>
<html lang='zh-CN'>
<head>
<meta charset='utf-8'>
<title>{trade_date} 龙头隔夜回测报告 — 模式 1</title>
<style>{CSS}</style>
</head>
<body>
  <h1>{trade_date} 龙头隔夜回测报告 — 模式 1</h1>
  <div class='meta'>
    策略：{_h(pattern_desc)}<br>
    板块来源：bankuai + jiuyan + llm_v2 三源并集（细分主线粒度），ALIAS_TO_CANONICAL 同义词归一<br>
    撮合口径：分钟线，涨停封单容差 0.005，A 股 100 股 / CB 10 张，含手续费
  </div>

  <div style='background:#fff;border:1px solid #e6e9ed;padding:12px 16px;margin:14px 0;font-size:13px;line-height:1.7;'>
    <b style='color:#1890ff'>📖 指标说明</b><br>
    · <b>净盈亏</b>: 单位元（¥）。每笔 = 卖出金额 - 买入金额 - 手续费（双向佣金 + 印花税 + 沪市过户费）。当日合计 = 所有成交净盈亏之和<br>
    · <b>占用资金</b>: 单位元（¥）。每笔 = 买入价 × 数量（A 股 100 股 / CB 10 张）。当日合计 = 所有成交独立累加（策略不复用资金，每个信号都假定独立下单）<br>
    · <b>胜率</b>: 净盈亏 &gt; 0 的笔数 / 成交总笔数<br>
    · <b>盈亏比</b>: 平均盈利 ÷ 平均亏损（=平均赚一笔的金额是平均亏一笔金额的 N 倍）。盈亏比 &gt; 1 即使胜率低也能赚；&lt; 1 时即便胜率高也容易亏（典型如"小赚多次，一次大亏吃掉所有利润"）<br>
    · <b>SKIP</b>: 信号被丢弃。原因可能是 unfillable_limit（涨停封单买不到）/ missing price（分钟数据缺失，常见于次日数据未拉）/ already_traded（同一标的当日已被前序 sector 信号买入，去重）
  </div>

  <div class='summary'>
    <div>📊 {total} 笔成交</div>
    <div class='red'>✅ 胜 {win_count}</div>
    <div class='green'>❌ 负 {lose_count}</div>
    <div>胜率 <b>{win_rate:.1f}%</b></div>
    <div class='{avg_cls}'>均收益 {'+' if avg_ret>0 else ''}{avg_ret:.2f}%</div>
    <div>盈亏比 <b>{pl_ratio:.2f}</b></div>
    <div class='{pnl_cls}' style='font-size:17px'>净盈亏 {'+' if pnl>0 else ''}¥{pnl:,.2f}</div>
    <div class='gray'>⏭ SKIP {skipped} 个信号</div>
  </div>

  <div class='summary' style='border-left-color:#52c41a;background:#f6ffed'>
    <div>💰 当日占用资金 <b>¥{cost:,.2f}</b></div>
    <div>📥 卖出回收 <b>¥{revenue:,.2f}</b></div>
    <div>💸 手续费合计 <b>¥{fees:,.2f}</b></div>
    <div>📊 平均单笔投入 <b>¥{avg_cost:,.2f}</b></div>
    <div class='gray' style='font-size:12px;font-weight:normal'>(每笔独立下单，不考虑资金复用)</div>
    <div>🟢 平均盈利单 <b>¥{avg_win:,.2f}</b></div>
    <div>🔴 平均亏损单 <b>¥{avg_loss:,.2f}</b></div>
  </div>

  <h2>已成交（{total} 笔）</h2>
  <table>
    <thead>
      <tr>
        <th style='width:40px'>#</th>
        <th style='width:130px'>主线 / 角色</th>
        <th style='width:160px'>标的</th>
        <th style='width:140px'>买入<br><span style='color:#999;font-weight:normal;font-size:11px'>时间 / 价 / 占用 ¥</span></th>
        <th style='width:140px'>卖出<br><span style='color:#999;font-weight:normal;font-size:11px'>时间 / 价 / 回收 ¥</span></th>
        <th style='width:80px'>收益</th>
        <th style='width:100px'>净盈亏 (¥)</th>
        <th>买入理由 + 板块跟风</th>
      </tr>
    </thead>
    <tbody>{''.join(traded_rows) if traded_rows else "<tr><td colspan='8' class='gray' style='text-align:center'>无成交</td></tr>"}</tbody>
  </table>

  <h2>未成交 SKIP（{skipped} 个信号）</h2>
  <table>
    <thead>
      <tr>
        <th style='width:40px'>#</th>
        <th style='width:130px'>主线 / 角色</th>
        <th style='width:160px'>标的</th>
        <th>SKIP 原因</th>
      </tr>
    </thead>
    <tbody>{''.join(skip_rows) if skip_rows else "<tr><td colspan='4' class='gray' style='text-align:center'>所有信号都成交了</td></tr>"}</tbody>
  </table>

  <div class='footer'>
    生成时间 {_h(__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"))} CST
    · pattern_01_long1_natural · ALIAS_TO_CANONICAL 细分粒度
  </div>
</body>
</html>"""


async def gen_one(trade_date: str) -> str:
    """生成一日报告，返回 HTML 路径。"""
    pattern = Pattern01()
    print(f"\n=== 生成 {trade_date} 报告 ===")
    async with async_session() as s:
        sigs = await pattern.find_signals(s, trade_date)
    print(f"  信号数: {len(sigs)}")

    results = []  # (idx, trade, sec_info, consensus)
    traded_today: set[tuple[str, str, str | None]] = set()
    wins: list[float] = []
    losses: list[float] = []
    skipped = 0
    async with async_session() as s_conn:
        for i, sig in enumerate(sigs, 1):
            key = (sig.trade_date, sig.pick_code, sig.buy_anchor_time)
            if key in traded_today:
                from app.research.strategies.base_pattern import PatternTrade as PT
                trade = PT(
                    signal=sig, next_date="", buy_price=None, sell_price=None,
                    skip_reason=f"already_traded（同日 {sig.pick_code} 已被前序 sector 信号买入，本信号 sector={sig.sector} 跳过）"
                )
                results.append((i, trade, None, []))
                skipped += 1
                continue

            trade = await execute_signal(sig)
            if trade.skip_reason:
                results.append((i, trade, None, []))
                skipped += 1
                continue
            traded_today.add(key)

            sec_info = await fetch_sector_followers(
                sig.sector, sig.trade_date,
                exclude_codes={sig.long1_code, sig.pick_code},
                long1_first_time=sig.long1_first_time,
            )

            # 板块共识股票（trigger 时点全板块成员中 ≥6%/≥8% 的）
            anchor_hhmmss = sig.buy_anchor_time
            if not anchor_hhmmss:
                # 兜底：从 buy_anchor 推
                anchor_hhmmss = {"today_close": "145500", "today_open": "093000"}.get(
                    sig.buy_anchor, "093000"
                )
            threshold = consensus_threshold_for(sig)
            consensus = await fetch_consensus_stocks(
                s_conn, sig.sector, sig.trade_date, anchor_hhmmss, threshold,
                exclude_codes={sig.long1_code, sig.pick_code},
            )
            results.append((i, trade, sec_info, consensus))
            if trade.pnl > 0:
                wins.append(trade.pnl)
            elif trade.pnl < 0:
                losses.append(abs(trade.pnl))

    valid_count = len([r for r in results if not r[1].skip_reason])
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    win_rate = len(wins) / valid_count * 100 if valid_count else 0
    pl_ratio = avg_win / max(avg_loss, 0.01)
    valid_trades = [r[1] for r in results if not r[1].skip_reason]
    avg_ret = sum(t.ret_pct for t in valid_trades) / len(valid_trades) if valid_trades else 0
    pnl = sum(t.pnl for t in valid_trades)

    # 资金统计（不考虑分时复用，每笔独立计算占用 — 与策略无资金限制的口径一致）
    cost = sum((t.buy_price or 0) * t.qty for t in valid_trades)
    revenue = sum((t.sell_price or 0) * t.qty for t in valid_trades)
    fees = sum(t.fee for t in valid_trades)
    avg_cost = cost / valid_count if valid_count else 0

    summary = {
        "total": valid_count, "wins": len(wins), "losses": len(losses),
        "win_rate": win_rate, "avg_ret": avg_ret, "pl_ratio": pl_ratio, "pnl": pnl,
        "skipped": skipped,
        "cost": cost, "revenue": revenue, "fees": fees, "avg_cost": avg_cost,
        "avg_win": avg_win, "avg_loss": avg_loss,
    }
    print(f"  成交 {valid_count} 笔 / 胜 {len(wins)} / 负 {len(losses)} / "
          f"胜率 {win_rate:.1f}% / 均 {avg_ret:+.2f}% / 净盈亏 {pnl:+.2f} / "
          f"投入 ¥{cost:.0f} / SKIP {skipped}")

    # render_html 内部按"已成交 / SKIP"自动分两表，传完整 results
    html_str = render_html(trade_date, results, summary, pattern.description)

    out_dir = Path(__file__).resolve().parents[2] / "reports"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"backtest_{trade_date}_pattern1.html"
    out_path.write_text(html_str, encoding="utf-8")
    print(f"  → {out_path}")
    return str(out_path)


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("dates", nargs="+", help="trade dates YYYYMMDD ...")
    args = p.parse_args()

    paths = []
    for td in args.dates:
        paths.append(await gen_one(td))

    print("\n=== 生成完成 ===")
    for p in paths:
        print(f"  file:///{p.replace(chr(92), '/')}")


if __name__ == "__main__":
    asyncio.run(main())
