#!/usr/bin/env python3
"""查看复盘/早盘报告 — 从后端 API 拉取并格式化输出

用法:
    python3 scripts/view_report.py review [日期]          # 终端查看复盘
    python3 scripts/view_report.py plan [日期]            # 终端查看早盘
    python3 scripts/view_report.py latest                 # 查看最新（复盘+早盘）
    python3 scripts/view_report.py review 20260410 --md   # 导出为 Markdown 文件
    python3 scripts/view_report.py plan 20260411 --md     # 导出为 Markdown 文件

日期格式: YYYYMMDD，省略则显示最新一条
--md 将报告导出到 reports/ 目录下的 .md 文件
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _detect_api_base() -> str:
    """WSL2 自动检测 Windows 宿主 IP"""
    try:
        with open("/proc/version") as f:
            if "microsoft" in f.read().lower():
                result = subprocess.run(
                    ["ip", "route", "show", "default"],
                    capture_output=True, text=True,
                )
                parts = result.stdout.split()
                if len(parts) >= 3:
                    return f"http://{parts[2]}:8000"
    except FileNotFoundError:
        pass
    return "http://localhost:8000"


API_BASE = _detect_api_base()


def _fetch(path: str) -> dict | list | None:
    """curl 获取 API 数据"""
    try:
        result = subprocess.run(
            ["curl", "--noproxy", "*", "-sf", f"{API_BASE}{path}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return None


def _line(char="─", width=60):
    print(char * width)


def _section(title: str, text: str, max_len: int = 0):
    if not text:
        return
    print(f"\n\033[1m【{title}】\033[0m")
    print(text[:max_len] + "..." if max_len and len(text) > max_len else text)


def _json_section(title: str, data, indent: int = 2):
    if not data:
        return
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            print(f"\n\033[1m【{title}】\033[0m")
            print(data)
            return
    if not data:
        return
    print(f"\n\033[1m【{title}】\033[0m")
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                parts = []
                for k in ("name", "ts_code", "strategy", "trigger", "reason", "action"):
                    if k in item:
                        parts.append(f"{item[k]}")
                print(f"  - {' | '.join(parts)}")
                for k in ("target_price", "stop_loss", "position"):
                    if k in item:
                        print(f"    {k}: {item[k]}")
            else:
                print(f"  - {item}")
    elif isinstance(data, dict):
        for k, v in data.items():
            print(f"  {k}: {v}")


def show_review(date: str | None = None):
    """显示复盘报告"""
    if date:
        resp = _fetch(f"/api/v1/review/history?limit=1&start_date={date}&end_date={date}")
    else:
        resp = _fetch("/api/v1/review/history?limit=1")

    if not resp or not resp.get("data"):
        print(f"未找到复盘报告" + (f" ({date})" if date else ""))
        return

    d = resp["data"][0]
    td = d.get("trade_date", "?")

    # 解析 strategy_conclusion
    sc = d.get("strategy_conclusion", "")
    if isinstance(sc, str):
        try:
            sc = json.loads(sc)
        except json.JSONDecodeError:
            sc = {}

    print()
    _line("═")
    print(f"\033[1;36m  {td} 收盘复盘报告\033[0m")
    _line("═")

    if isinstance(sc, dict) and sc:
        print(f"\n  \033[1m方向:\033[0m {sc.get('direction', '?')}  "
              f"\033[1m信心:\033[0m {sc.get('confidence', '?')}  "
              f"\033[1m策略:\033[0m {d.get('dominant_strategy', '?')}")
        fs = sc.get("focus_sectors", [])
        if fs:
            print(f"  \033[1m重点:\033[0m {', '.join(fs)}")
        rw = sc.get("risk_warnings", [])
        if rw:
            print(f"  \033[1m警示:\033[0m {'; '.join(rw)}")

    # 情绪数值摘要
    temp = d.get("temperature")
    lu = d.get("limit_up_count")
    ld = d.get("limit_down_count")
    br = d.get("broken_count")
    sr = d.get("seal_rate")
    mb = d.get("max_board")
    if any(v is not None for v in (temp, lu, ld)):
        print(f"\n  温度:{temp or '?'} 涨停:{lu or '?'} 跌停:{ld or '?'} "
              f"炸板:{br or '?'} 封板率:{sr or '?'}% 最高板:{mb or '?'}")

    _section("大盘综述", d.get("market_summary", ""))
    _section("板块分析", d.get("sector_analysis", ""))
    _section("情绪面", d.get("sentiment_narrative", ""))
    _section("短线打板", d.get("board_play_summary", ""))
    _section("波段趋势", d.get("swing_trade_summary", ""))
    _section("价值投资", d.get("value_invest_summary", ""))
    _section("风险提示", d.get("risk_summary", ""))
    _section("切换信号", d.get("strategy_switch_signal", ""))

    _json_section("风险预警", d.get("risk_alerts_json"))

    print()
    _line("═")
    ts = d.get("created_at", "")
    if ts:
        print(f"  生成时间: {ts}")


def show_plan(date: str | None = None):
    """显示早盘计划"""
    if date:
        resp = _fetch(f"/api/v1/plan/history?limit=1&start_date={date}&end_date={date}")
    else:
        resp = _fetch("/api/v1/plan/history?limit=1")

    if not resp or not resp.get("data"):
        print(f"未找到早盘计划" + (f" ({date})" if date else ""))
        return

    d = resp["data"][0]
    td = d.get("trade_date", "?")

    print()
    _line("═")
    print(f"\033[1;33m  {td} 早盘计划\033[0m")
    _line("═")

    print(f"\n  \033[1m方向:\033[0m {d.get('predicted_direction', '?')}  "
          f"\033[1m温度:\033[0m {d.get('predicted_temperature', '?')}  "
          f"\033[1m信心:\033[0m {d.get('confidence_score', '?')}")

    _json_section("仓位计划", d.get("position_plan_json"))
    _json_section("策略权重", d.get("strategy_weights_json"))

    _section("核心逻辑", d.get("key_logic", ""))
    _section("隔夜环境", d.get("overnight_summary", ""))
    _section("打板计划", d.get("board_play_plan", ""))
    _section("波段计划", d.get("swing_trade_plan", ""))
    _section("价值计划", d.get("value_invest_plan", ""))
    _section("风险提示", d.get("risk_notes", ""))

    _json_section("关注板块", d.get("watch_sectors_json"))
    _json_section("回避板块", d.get("avoid_sectors_json"))
    _json_section("关注个股", d.get("watch_stocks_json"))
    _json_section("进场计划", d.get("entry_plan_json"))
    _json_section("退出计划", d.get("exit_plan_json"))

    # 回溯验证
    ar = d.get("actual_result")
    acs = d.get("accuracy_score")
    rn = d.get("retrospect_note", "")
    if ar or acs is not None:
        print(f"\n\033[1m【回溯验证】\033[0m")
        print(f"  结果: {ar or '待验证'}  准确度: {acs or '待评分'}")
        if rn:
            print(f"  备注: {rn}")

    print()
    _line("═")
    ts = d.get("created_at", "")
    if ts:
        print(f"  生成时间: {ts}")


def _reports_dir() -> Path:
    """Find project root and return reports/ directory."""
    p = Path(__file__).resolve().parent.parent / "reports"
    p.mkdir(exist_ok=True)
    return p


def export_review_md(date: str | None = None) -> str | None:
    """Export review to markdown file, return file path."""
    if date:
        resp = _fetch(f"/api/v1/review/history?limit=1&start={date}&end={date}")
    else:
        resp = _fetch("/api/v1/review/history?limit=1")
    if not resp or not resp.get("data"):
        print(f"未找到复盘报告" + (f" ({date})" if date else ""))
        return None

    d = resp["data"][0]
    td = d.get("trade_date", "unknown")
    date_fmt = f"{td[:4]}-{td[4:6]}-{td[6:]}"

    sc = d.get("strategy_conclusion", "")
    if isinstance(sc, str):
        try:
            sc = json.loads(sc)
        except json.JSONDecodeError:
            sc = {}

    lines = [f"# {date_fmt} 收盘复盘报告\n"]
    if isinstance(sc, dict) and sc:
        lines.append(f"> 方向: **{sc.get('direction','?')}** | "
                     f"信心: **{sc.get('confidence','?')}** | "
                     f"策略: **{d.get('dominant_strategy','?')}**")
        fs = sc.get("focus_sectors", [])
        if fs:
            lines.append(f">\n> 重点板块: {', '.join(fs)}")
        rw = sc.get("risk_warnings", [])
        if rw:
            lines.append(f">\n> 风险警示: {'; '.join(rw)}")
    lines.append("")

    for key, title in [
        ("market_summary", "大盘综述"), ("sector_analysis", "板块分析"),
        ("sentiment_narrative", "情绪面"), ("board_play_summary", "短线打板"),
        ("swing_trade_summary", "波段趋势"), ("value_invest_summary", "价值投资"),
        ("risk_summary", "风险提示"), ("strategy_switch_signal", "策略切换信号"),
    ]:
        text = d.get(key, "")
        if text:
            lines.append(f"## {title}\n\n{text}\n")

    md_path = _reports_dir() / f"review_{td}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return str(md_path)


def export_plan_md(date: str | None = None) -> str | None:
    """Export plan to markdown file, return file path."""
    if date:
        resp = _fetch(f"/api/v1/plan/history?limit=1&start={date}&end={date}")
    else:
        resp = _fetch("/api/v1/plan/history?limit=1")
    if not resp or not resp.get("data"):
        print(f"未找到早盘计划" + (f" ({date})" if date else ""))
        return None

    d = resp["data"][0]
    td = d.get("trade_date", "unknown")
    date_fmt = f"{td[:4]}-{td[4:6]}-{td[6:]}"

    lines = [f"# {date_fmt} 早盘计划\n"]
    lines.append(f"> 方向: **{d.get('predicted_direction','?')}** | "
                 f"温度: **{d.get('predicted_temperature','?')}** | "
                 f"信心: **{d.get('confidence_score','?')}**")

    pp = d.get("position_plan_json", {})
    if isinstance(pp, str):
        try:
            pp = json.loads(pp)
        except json.JSONDecodeError:
            pp = {}
    if isinstance(pp, dict) and pp:
        lines.append(f">\n> 仓位: {pp.get('total_position','?')} "
                     f"(打板 {pp.get('board_play','?')} / 波段 {pp.get('swing','?')} / 价值 {pp.get('value','?')})")
    lines.append("")

    for key, title in [
        ("key_logic", "核心逻辑"), ("overnight_summary", "隔夜环境"),
        ("board_play_plan", "打板计划"), ("swing_trade_plan", "波段计划"),
        ("value_invest_plan", "价值计划"), ("risk_notes", "风险提示"),
    ]:
        text = d.get(key, "")
        if text:
            lines.append(f"## {title}\n\n{text}\n")

    # 关注个股
    stocks = d.get("watch_stocks_json", [])
    if isinstance(stocks, str):
        try:
            stocks = json.loads(stocks)
        except json.JSONDecodeError:
            stocks = []
    if stocks:
        lines.append("## 关注个股\n")
        lines.append("| 代码 | 名称 | 理由 |")
        lines.append("|------|------|------|")
        for s in stocks:
            if isinstance(s, dict):
                lines.append(f"| {s.get('ts_code','')} | {s.get('name','')} | {s.get('reason','')} |")
        lines.append("")

    # 进场/退出
    for key, title, cols in [
        ("entry_plan_json", "进场计划", ["name", "strategy", "trigger", "target_price", "stop_loss", "position"]),
        ("exit_plan_json", "退出计划", ["name", "strategy", "trigger", "action"]),
    ]:
        items = d.get(key, [])
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except json.JSONDecodeError:
                items = []
        if items:
            lines.append(f"## {title}\n")
            lines.append("| " + " | ".join(cols) + " |")
            lines.append("|" + "|".join(["------"] * len(cols)) + "|")
            for it in items:
                if isinstance(it, dict):
                    lines.append("| " + " | ".join(str(it.get(c, "")) for c in cols) + " |")
            lines.append("")

    md_path = _reports_dir() / f"plan_{td}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return str(md_path)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1].lower()
    date = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("-") else None
    to_md = "--md" in sys.argv

    # 检查后端
    health = _fetch("/health")
    if not health:
        print(f"❌ 后端不可用: {API_BASE}")
        print("   请确认后端已启动")
        sys.exit(1)

    if cmd == "review":
        if to_md:
            path = export_review_md(date)
            if path:
                print(f"✓ 已导出: {path}")
        else:
            show_review(date)
    elif cmd == "plan":
        if to_md:
            path = export_plan_md(date)
            if path:
                print(f"✓ 已导出: {path}")
        else:
            show_plan(date)
    elif cmd == "latest":
        if to_md:
            p1 = export_review_md()
            p2 = export_plan_md()
            if p1:
                print(f"✓ 复盘: {p1}")
            if p2:
                print(f"✓ 早盘: {p2}")
        else:
            show_review()
            print("\n")
            show_plan()
    else:
        print(f"未知命令: {cmd}")
        print("用法: view_report.py [review|plan|latest] [日期] [--md]")
        sys.exit(1)


if __name__ == "__main__":
    main()
