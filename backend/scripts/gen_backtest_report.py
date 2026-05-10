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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.database import async_session  # noqa: E402
from app.research.strategies.base_pattern import PatternSignal, PatternTrade  # noqa: E402
from app.research.strategies.pattern_01_long1_natural import Pattern01  # noqa: E402

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


def build_buy_reason(sig: PatternSignal, sec_info: dict) -> str:
    """根据信号字段拼一段中文买入理由。"""
    role = role_label(sig.pick_role)
    parts = []

    # 主线 + 标的
    parts.append(f"<b>主线</b>: {_h(sig.sector)}")
    parts.append(f"<b>角色</b>: {_h(role)}")

    # CB 关联
    if sig.pick_kind == "cb":
        und = sig.underlying_code or "?"
        parts.append(f"<b>正股</b>: {_h(und)}")

    # 龙 1
    parts.append(
        f"<b>龙 1</b>: {_h(sig.long1_name)}({_h(sig.long1_tag)}) "
        f"首封 {_h(sig.long1_first_time)}，当日炸板 {sig.long1_open_times} 次"
    )

    # 板块强度
    if sec_info:
        max_stock = sec_info.get("max_stock")
        if max_stock:
            parts.append(f"<b>板块最高</b>: {_h(max_stock[0])}({_h(max_stock[1])})")
        followers = sec_info.get("followers", [])
        at_long1 = sec_info.get("at_long1_count", 0)
        parts.append(
            f"<b>跟风</b>: 龙 1 封板时刻已封 {at_long1} 只 / 全天 {len(followers)} 只"
        )
    else:
        parts.append("<b>跟风</b>: 萌芽板块 / 板块成员未识别")

    # 买入策略
    buy_t = _hhmm(sig.buy_anchor, sig.buy_anchor_time)
    sell_t = _hhmm(sig.sell_anchor, sig.sell_anchor_time)
    parts.append(
        f"<b>买入</b>: {sig.buy_anchor} ({buy_t}) → "
        f"<b>卖出</b>: {sig.sell_anchor} ({sell_t})"
    )

    # 持有方式
    parts.append(f"<b>持有</b>: {_h(sig.holding)}")

    # 信号原始 reason
    if sig.reason:
        parts.append(f"<b>策略 reason</b>: {_h(sig.reason)}")

    return "<br>".join(parts)


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
.reason { font-size: 12px; line-height: 1.7; color: #444; }
.footer { margin-top: 30px; color: #999; font-size: 12px; text-align: center; }
"""


def render_html(trade_date: str, results: list, summary: dict, pattern_desc: str) -> str:
    """results: list of (idx, trade, sec_info, is_skip)"""
    win_count = summary["wins"]
    lose_count = summary["losses"]
    total = summary["total"]
    win_rate = summary["win_rate"]
    avg_ret = summary["avg_ret"]
    pl_ratio = summary["pl_ratio"]
    pnl = summary["pnl"]
    skipped = summary["skipped"]

    pnl_cls = "green" if pnl > 0 else ("red" if pnl < 0 else "gray")
    avg_cls = "green" if avg_ret > 0 else ("red" if avg_ret < 0 else "gray")

    # 已成交表行
    traded_rows = []
    skip_rows = []
    for idx, trade, sec_info in results:
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

        reason_html = build_buy_reason(sig, sec_info)
        followers_html = render_followers(sec_info)

        traded_rows.append(f"""
<tr class='{pnl_row_cls}'>
  <td>{idx}</td>
  <td>{sector_html}</td>
  <td>{target_html}</td>
  <td><div class='code'>{sig.trade_date} {buy_t}</div><div class='code'>¥{trade.buy_price}</div></td>
  <td><div class='code'>{sell_date} {sell_t}</div><div class='code'>¥{trade.sell_price}</div></td>
  <td class='{ret_cls}'>{sign_pct}{trade.ret_pct}%</td>
  <td class='{ret_cls}'>{sign_pnl}{trade.pnl}</td>
  <td>
    <div class='reason'>{reason_html}</div>
    <div style='margin-top:6px'>{followers_html}</div>
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
  <div class='summary'>
    <div>📊 {total} 笔成交</div>
    <div class='red'>✅ 胜 {win_count}</div>
    <div class='green'>❌ 负 {lose_count}</div>
    <div>胜率 <b>{win_rate:.1f}%</b></div>
    <div class='{avg_cls}'>均收益 {'+' if avg_ret>0 else ''}{avg_ret:.2f}%</div>
    <div>盈亏比 <b>{pl_ratio:.2f}</b></div>
    <div class='{pnl_cls}' style='font-size:17px'>PnL {'+' if pnl>0 else ''}{pnl:.2f}</div>
    <div class='gray'>⏭ SKIP {skipped} 个信号</div>
  </div>

  <h2>已成交（{total} 笔）</h2>
  <table>
    <thead>
      <tr>
        <th style='width:40px'>#</th>
        <th style='width:130px'>主线 / 角色</th>
        <th style='width:160px'>标的</th>
        <th style='width:130px'>买入</th>
        <th style='width:130px'>卖出</th>
        <th style='width:80px'>收益</th>
        <th style='width:90px'>PnL</th>
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

    results = []  # (idx, trade, sec_info)
    traded_today: set[tuple[str, str]] = set()
    wins: list[float] = []
    losses: list[float] = []
    skipped = 0
    for i, sig in enumerate(sigs, 1):
        key = (sig.trade_date, sig.pick_code)
        if key in traded_today:
            from app.research.strategies.base_pattern import PatternTrade as PT
            trade = PT(
                signal=sig, next_date="", buy_price=None, sell_price=None,
                skip_reason=f"already_traded（同日 {sig.pick_code} 已被前序 sector 信号买入，本信号 sector={sig.sector} 跳过）"
            )
            results.append((i, trade, None))
            skipped += 1
            continue

        trade = await execute_signal(sig)
        if trade.skip_reason:
            results.append((i, trade, None))
            skipped += 1
            continue
        traded_today.add(key)

        sec_info = await fetch_sector_followers(
            sig.sector, sig.trade_date,
            exclude_codes={sig.long1_code, sig.pick_code},
            long1_first_time=sig.long1_first_time,
        )
        results.append((i, trade, sec_info))
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

    summary = {
        "total": valid_count, "wins": len(wins), "losses": len(losses),
        "win_rate": win_rate, "avg_ret": avg_ret, "pl_ratio": pl_ratio, "pnl": pnl,
        "skipped": skipped,
    }
    print(f"  成交 {valid_count} 笔 / 胜 {len(wins)} / 负 {len(losses)} / "
          f"胜率 {win_rate:.1f}% / 均 {avg_ret:+.2f}% / PnL {pnl:+.2f} / SKIP {skipped}")

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
