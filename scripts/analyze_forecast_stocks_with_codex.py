"""Batch-analyze earnings forecast stocks with local DB context + codex exec.

Workflow:
1. Read stock/fundamental/forecast/main-business data from the local PostgreSQL DB.
2. Compute main-business shares locally.
3. Call `codex exec` once for the whole stock list to supplement highlights and format the report.
4. Print a formatted Markdown report and optionally save JSON/Markdown outputs.

Usage:
    python scripts/analyze_forecast_stocks_with_codex.py --codes 605189.SH 002039.SZ
    python scripts/analyze_forecast_stocks_with_codex.py --codes-file codes.txt --out-dir logs/earnings_exec
    python scripts/analyze_forecast_stocks_with_codex.py --codes 605189.SH --mode web
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import psycopg2
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

DB_URL = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
WEB_ALLOWED_DOMAINS = [
    "cninfo.com.cn",
    "static.cninfo.com.cn",
    "sse.com.cn",
    "szse.cn",
    "bse.cn",
]


def resolve_codex_bin() -> str:
    candidates = [
        shutil.which("codex.cmd"),
        shutil.which("codex"),
        str(Path.home() / "AppData" / "Roaming" / "npm" / "codex.cmd"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise FileNotFoundError("Cannot find codex executable. Expected codex.cmd in PATH or %APPDATA%\\npm.")


def _num(v: object) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:  # NaN
        return None
    return x


def _pct(part: float | None, total: float | None) -> float | None:
    if part is None or total is None or total == 0:
        return None
    return round(part / total * 100, 2)


def _short_money(v: float | None) -> str:
    if v is None:
        return "暂无"
    yi = 1e8
    if abs(v) >= yi:
        return f"{v / yi:.2f}亿"
    if abs(v) >= 1e4:
        return f"{v / 1e4:.2f}万"
    return f"{v:.2f}"


def _short_money_wan(v: float | None) -> str:
    """Tushare forecast net_profit_* is commonly in 10k CNY."""
    if v is None:
        return "暂无"
    if abs(v) >= 10000:
        return f"{v / 10000:.2f}亿"
    return f"{v:.0f}万"


def load_codes(args: argparse.Namespace) -> list[str]:
    codes = list(args.codes or [])
    if args.codes_file:
        for line in Path(args.codes_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                codes.append(line)
    seen: set[str] = set()
    uniq: list[str] = []
    for code in codes:
        code = code.strip().upper()
        if code and code not in seen:
            uniq.append(code)
            seen.add(code)
    return uniq


def fetch_context(conn, ts_code: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ts_code, name, industry, area, market, list_date
            FROM stock_basic
            WHERE ts_code = %s
            """,
            (ts_code,),
        )
        basic_row = cur.fetchone()
        if not basic_row:
            raise ValueError(f"stock not found: {ts_code}")

        basic = {
            "ts_code": basic_row[0],
            "name": basic_row[1],
            "industry": basic_row[2],
            "area": basic_row[3],
            "market": basic_row[4],
            "list_date": basic_row[5],
        }

        cur.execute(
            """
            SELECT ann_date, end_date, type, p_change_min, p_change_max,
                   net_profit_min, net_profit_max, summary, change_reason
            FROM forecast
            WHERE ts_code = %s
            ORDER BY ann_date DESC NULLS LAST, end_date DESC
            LIMIT 1
            """,
            (ts_code,),
        )
        forecast_row = cur.fetchone()
        forecast = None
        if forecast_row:
            forecast = {
                "ann_date": forecast_row[0],
                "end_date": forecast_row[1],
                "type": forecast_row[2],
                "p_change_min": _num(forecast_row[3]),
                "p_change_max": _num(forecast_row[4]),
                "net_profit_min": _num(forecast_row[5]),
                "net_profit_max": _num(forecast_row[6]),
                "net_profit_unit": "万元",
                "summary": forecast_row[7],
                "change_reason": forecast_row[8],
            }

        cur.execute(
            """
            SELECT end_date, roe, netprofit_yoy, or_yoy, grossprofit_margin,
                   netprofit_margin, debt_to_assets, ocfps
            FROM fina_indicator
            WHERE ts_code = %s
            ORDER BY end_date DESC
            LIMIT 1
            """,
            (ts_code,),
        )
        fina_row = cur.fetchone()
        fina = None
        if fina_row:
            fina = {
                "end_date": fina_row[0],
                "roe": _num(fina_row[1]),
                "netprofit_yoy": _num(fina_row[2]),
                "or_yoy": _num(fina_row[3]),
                "grossprofit_margin": _num(fina_row[4]),
                "netprofit_margin": _num(fina_row[5]),
                "debt_to_assets": _num(fina_row[6]),
                "ocfps": _num(fina_row[7]),
            }

        cur.execute(
            """
            SELECT trade_date, pe_ttm, pb, total_mv, circ_mv, turnover_rate
            FROM daily_basic
            WHERE ts_code = %s
            ORDER BY trade_date DESC
            LIMIT 1
            """,
            (ts_code,),
        )
        val_row = cur.fetchone()
        valuation = None
        if val_row:
            valuation = {
                "trade_date": val_row[0],
                "pe_ttm": _num(val_row[1]),
                "pb": _num(val_row[2]),
                "total_mv": _num(val_row[3]),
                "circ_mv": _num(val_row[4]),
                "turnover_rate": _num(val_row[5]),
            }

        cur.execute(
            """
            SELECT concept_name
            FROM concept_detail
            WHERE ts_code = %s AND concept_name IS NOT NULL AND concept_name != ''
            ORDER BY concept_name
            LIMIT 12
            """,
            (ts_code,),
        )
        concepts = [r[0] for r in cur.fetchall()]

        cur.execute("SELECT MAX(end_date) FROM fina_mainbz WHERE ts_code = %s", (ts_code,))
        latest_mainbz_end = cur.fetchone()[0]

        main_business: list[dict] = []
        if latest_mainbz_end:
            cur.execute(
                """
                SELECT bz_item, bz_sales, bz_profit, bz_cost, curr_type
                FROM fina_mainbz
                WHERE ts_code = %s AND end_date = %s
                ORDER BY bz_sales DESC NULLS LAST, bz_profit DESC NULLS LAST, bz_item
                """,
                (ts_code, latest_mainbz_end),
            )
            rows = cur.fetchall()
            total_sales = sum(v for _, sales, _, _, _ in rows if (v := _num(sales)) is not None)
            total_profit = sum(v for _, _, profit, _, _ in rows if (v := _num(profit)) is not None)
            for item, sales, profit, cost, curr_type in rows:
                sales_f = _num(sales)
                profit_f = _num(profit)
                main_business.append(
                    {
                        "item": item,
                        "bz_sales": sales_f,
                        "bz_profit": profit_f,
                        "bz_cost": _num(cost),
                        "curr_type": curr_type,
                        "sales_share_pct": _pct(sales_f, total_sales),
                        "profit_share_pct": _pct(profit_f, total_profit) if (total_profit and total_profit > 0) else None,
                    }
                )

        return {
            "basic": basic,
            "forecast": forecast,
            "fina_indicator": fina,
            "valuation": valuation,
            "concepts": concepts,
            "main_business_end_date": latest_mainbz_end,
            "main_business": main_business[:8],
        }


def build_prompt(contexts: list[dict], mode: str) -> str:
    if mode == "web":
        mode_rules = (
            "你可以在本地JSON上下文之外联网补充信息，但只能优先参考巨潮资讯、交易所披露页面，以及能明确确认是公司官网的页面。\n"
            "不要使用证券时报、财联社、东方财富等媒体站作为来源。\n"
            "联网补充得到的内容只能写入 web_findings 字段，不要混入 company_highlights。\n"
            "web_findings 写 2 到 4 条，每条必须用 Markdown 粗体包裹，例如 **公司某产品进入放量期**。\n"
            "web_sources 写你实际参考的来源链接列表；没有可靠来源时返回空数组。\n"
            "如果联网信息和本地数据库信息冲突，优先采用更近期且来源更可靠的信息，并在 web_findings 中保守表述。\n"
        )
    else:
        mode_rules = (
            "仅根据我提供的JSON上下文输出，不要联网，不要补充未给出的事实。\n"
            "web_findings 和 web_sources 必须返回空数组。\n"
        )

    return (
        "你是A股财报分析助手。\n"
        f"{mode_rules}"
        "你会收到多只股票的本地结构化数据。\n"
        "主营业务及占比已经由本地数据库计算完成，你不要改写这些数字，只负责补充亮点、风险和摘要表达。\n"
        "目标：为每只股票生成摘要、亮点、风险和可选的联网补充。\n"
        "要求：\n"
        "1. 对每只股票输出一条分析，必须保留原 ts_code 和 name。\n"
        "2. company_highlights 写3到5条，必须尽量基于本地主营构成、业绩预告、行业/概念、财务特征。\n"
        "3. risks 写2到3条；如果数据不足，要直接写“数据不足”。\n"
        "4. latest_forecast 用一句话概括本次业绩预告。\n"
        "5. one_line_summary 控制在25字内。\n"
        "6. 不要输出任何 schema 之外的字段。\n\n"
        "股票上下文JSON如下：\n"
        f"{json.dumps(contexts, ensure_ascii=False, indent=2)}\n"
    )


def build_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "analyses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ts_code": {"type": "string"},
                        "name": {"type": "string"},
                        "one_line_summary": {"type": "string"},
                        "latest_forecast": {"type": "string"},
                        "company_highlights": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "risks": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "web_findings": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "web_sources": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": [
                        "ts_code",
                        "name",
                        "one_line_summary",
                        "latest_forecast",
                        "company_highlights",
                        "risks",
                        "web_findings",
                        "web_sources",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["analyses"],
        "additionalProperties": False,
    }


def run_codex_exec(contexts: list[dict], model: str | None, mode: str) -> dict[str, dict]:
    with tempfile.TemporaryDirectory(prefix="codex_exec_stock_") as tmp_dir:
        tmp = Path(tmp_dir)
        schema_path = tmp / "schema.json"
        output_path = tmp / "result.json"
        schema_path.write_text(json.dumps(build_schema(), ensure_ascii=False, indent=2), encoding="utf-8")
        codex_bin = resolve_codex_bin()

        cmd = [
            codex_bin,
            "exec",
            "--ephemeral",
            "-C",
            str(PROJECT_ROOT),
            "--output-schema",
            str(schema_path),
            "-o",
            str(output_path),
            "-",
        ]
        if mode == "web":
            cmd[2:2] = [
                "-c",
                'web_search="live"',
                "-c",
                f'tools.web_search={{context_size="medium",allowed_domains={json.dumps(WEB_ALLOWED_DOMAINS, ensure_ascii=False)}}}',
            ]
        if model:
            cmd[2:2] = ["-m", model]

        prompt = build_prompt(contexts, mode)
        proc = subprocess.run(
            cmd,
            input=prompt.encode("utf-8"),
            cwd=PROJECT_ROOT,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"codex exec failed: {proc.stderr.decode('utf-8', errors='ignore').strip() or proc.stdout.decode('utf-8', errors='ignore').strip()}"
            )
        if not output_path.exists():
            raise RuntimeError("codex exec produced no output file")
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        results: dict[str, dict] = {}
        for item in payload.get("analyses", []):
            item.setdefault("web_findings", [])
            item.setdefault("web_sources", [])
            results[item["ts_code"]] = item
        return results


def render_markdown(results: dict[str, dict], contexts: dict[str, dict], codes: list[str], mode: str) -> str:
    lines = ["# 业绩预告个股分析", ""]
    for code in codes:
        ctx = contexts[code]
        item = results[code]
        basic = ctx["basic"]
        forecast = ctx.get("forecast") or {}
        lines.append(f"## {code} {basic['name']}")
        lines.append("")
        lines.append(f"- 一句话：{item['one_line_summary']}")
        lines.append(f"- 行业：{basic.get('industry') or '暂无'}")
        if forecast:
            lines.append(
                f"- 业绩预告：{forecast.get('ann_date') or '暂无'}，"
                f"{forecast.get('end_date') or '暂无'}，"
                f"变动区间 {forecast.get('p_change_min') or '暂无'}% ~ {forecast.get('p_change_max') or '暂无'}%，"
                f"净利润 {_short_money_wan(forecast.get('net_profit_min'))} ~ {_short_money_wan(forecast.get('net_profit_max'))}"
            )
        lines.append(f"- Codex结论：{item['latest_forecast']}")
        lines.append("")
        lines.append("### 核心业务")
        if ctx["main_business"]:
            for biz in ctx["main_business"][:4]:
                rs = "暂无" if biz["sales_share_pct"] is None else f"{biz['sales_share_pct']}%"
                ps = "暂无" if biz["profit_share_pct"] is None else f"{biz['profit_share_pct']}%"
                note = "本地数据库计算"
                if biz["sales_share_pct"] is not None and biz["profit_share_pct"] is not None:
                    if biz["profit_share_pct"] > biz["sales_share_pct"]:
                        note = "利润贡献高于收入贡献"
                    elif biz["profit_share_pct"] < biz["sales_share_pct"]:
                        note = "收入贡献高于利润贡献"
                lines.append(f"- {biz['item']}：收入占比 {rs}，利润占比 {ps}；{note}")
        else:
            lines.append("- 数据不足")
        lines.append("")
        lines.append("### 公司亮点")
        for x in item["company_highlights"] or ["数据不足"]:
            lines.append(f"- {x}")
        lines.append("")
        if mode == "web":
            lines.append("### 联网补充")
            for x in item.get("web_findings") or ["**暂无可靠联网补充**"]:
                lines.append(f"- {x}")
            if item.get("web_sources"):
                lines.append("")
                lines.append("来源：")
                for src in item["web_sources"]:
                    lines.append(f"- {src}")
            lines.append("")
        lines.append("### 风险提示")
        for x in item["risks"] or ["数据不足"]:
            lines.append(f"- {x}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", nargs="*", default=[], help="Stock codes, e.g. 605189.SH 002039.SZ")
    parser.add_argument("--codes-file", help="Text file with one ts_code per line")
    parser.add_argument("--out-dir", help="Directory to save JSON and Markdown outputs")
    parser.add_argument("--model", help="Optional codex model override")
    parser.add_argument("--mode", choices=["local", "web"], default="local", help="Analysis mode")
    args = parser.parse_args()

    codes = load_codes(args)
    if not codes:
        print("Please provide --codes or --codes-file", file=sys.stderr)
        return 2
    if not DB_URL:
        print("DATABASE_URL is missing in environment/.env", file=sys.stderr)
        return 2

    contexts: dict[str, dict] = {}

    with psycopg2.connect(DB_URL) as conn:
        for code in codes:
            context = fetch_context(conn, code)
            contexts[code] = context
            print(f"[CTX] {code} {context['basic']['name']}", file=sys.stderr)

    batch_contexts = [contexts[code] for code in codes]
    results = run_codex_exec(batch_contexts, args.model, args.mode)
    missing = [code for code in codes if code not in results]
    if missing:
        raise RuntimeError(f"codex exec missing analyses for: {', '.join(missing)}")
    for code in codes:
        print(f"[OK] {code} {contexts[code]['basic']['name']}", file=sys.stderr)

    markdown = render_markdown(results, contexts, codes, args.mode)
    print(markdown)

    if args.out_dir:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = out_dir / f"forecast_analysis_{stamp}.json"
        md_path = out_dir / f"forecast_analysis_{stamp}.md"
        json_path.write_text(
            json.dumps(
                {"generated_at": stamp, "mode": args.mode, "results": results, "contexts": contexts, "codes": codes},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        md_path.write_text(markdown, encoding="utf-8")
        print(f"Saved JSON: {json_path}", file=sys.stderr)
        print(f"Saved MD: {md_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
