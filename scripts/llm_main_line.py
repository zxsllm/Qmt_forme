"""LLM 题材主线判定（每日盘后跑一次，结果入 daily_sector_review 表）。

输入：当日涨停池（limit_stats）+ 概念归属（concept_detail）+ 主线-细分概念地图（theme_taxonomy）
输出：daily_sector_review (source='llm_v2')，每行一只股票 → 主线归属

用法：
    python scripts/llm_main_line.py 20260506

链路文档：docs/sector_main_line_pipeline.md
"""
import asyncio
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core.database import async_session
from app.research.signals.theme_taxonomy import render_taxonomy_for_prompt
from sqlalchemy import text


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


PROMPT_V2 = """你是 A 股短线题材分析助手。请按"市场当日的真实题材主线"对 {trade_date} 当日所有涨停股进行分组。

# 重要指引（按优先级）

## 1. 主线归类原则
- 优先按"游资当下炒作的题材"归类，**不要按"行业分类"**机械拆分
- 不同行业但题材相同，必须**合并**为一个主线（例：算力主线 = 光模块 + 服务器 + 数据中心电源 + 液冷 + 算力租赁，是一个主线，不是多个）
- 一只股票可同时属于多个主线，全部列出

## 2. 主线-细分概念地图（必须遵守，避免拆得过细）
{taxonomy}

## 3. 壳股蹭题材识别（关键！）
- **高板妖股（≥4 连板）即使主营业务与题材无关**，但市场公认其炒的就是该题材，**必须**归入该题材主线
- 反例：4/30 金螳螂（建筑装饰主营）10 天 8 板，市场公认炒"国产芯片"（半导体洁净室+传闻签订大单），应归"国产芯片"，**不要**归"装修装饰"
- 判别方法：连板高度 ≥ 4 板的票，看其涨停关键词/涨停时间/同板块跟风票，反推它在炒什么主线
- 普通首板/2 板的非主营题材沾边股，按主营行业即可

## 4. 主线 vs 补涨/杂毛
- 题材主线候选标准：当日 ≥ 3 只同题材涨停，**或** 至少有 1 只 ≥ 2 连板的高标
- 涨停股零散（< 3 只）且全是 1 板首板 = 补涨/杂毛，**不应**列入主线
- **跳过基本面属性标签**："一季报预增"、"年报增长"、"业绩扭亏"、"净利润增长"等都不是题材主线
- 仅同板块涨停 1-2 只的"地产"、"造纸"、"汽车配件"这种纯行业标签，多半是补涨，慎入主线

# Few-Shot 参考案例（板块必读 4/30 权威标签）

| 真实主线 | 涨停 | 包含股票（关键的几只） |
|---|---|---|
| 国产芯片 | 9 | **金螳螂(10天8板)** ← 壳股蹭题材 / 寒武纪 / 中国长城 / 万通发展 / 高新发展 / 华东重机 / 中天精装 / 汉钟精机 / 大胜达 |
| 电池产业链 | 7 | 永杉锂业(3板) / 融捷股份 / 丰元股份 / 盛新锂能 / 圣龙股份 / 海昌新材 / 万里石 |
| 机器人 | 6 | 凌云光 / 红豆股份 / 长城科技 / 香山股份 |
| 算力 | 5 | 越剑智能(4板) / 盛视科技 / 芯原股份 / 博迁新材 / 润建股份 |
| 商业航天 | 5 | 上海沪工 / 联合精密 / 西部材料 / 航天工程 / 起帆电缆 |
| 体育产业 | 4 | 共创草坪 / 舒华体育 / 粤传媒 / 安妮股份 |

# 输出要求

**只回复 JSON，不要任何解释文字**。格式：

{{
  "trade_date": "{trade_date}",
  "main_lines": [
    {{
      "sector": "国产芯片",
      "rank": 1,
      "stocks": [
        {{"ts_code": "688256.SH", "name": "寒武纪", "board_count": 1, "days_to_board": 1, "first_time": "13:44:38"}}
      ]
    }}
  ],
  "summary": {{"total_limit_up": N, "main_line_count": M}}
}}

排序规则：
- 主线之间按"涨停只数 + 高板权重"排序，强的在前
- 每个主线下按"连板高度倒序、首封时间正序"排
- 跳过纯资金属性标签 / 基本面标签 / 仅 1 只孤立票的窄标签

# 当日涨停清单

{stock_list}
"""


async def fetch_limit_pool(trade_date: str) -> list[dict]:
    async with async_session() as s:
        rows = (await s.execute(text(
            "SELECT ls.ts_code, ls.name, COALESCE(ls.limit_times, 1) AS bc, "
            "       ls.first_time, ls.float_mv, ls.amount, "
            "       lt.tag, sb.industry "
            "FROM limit_stats ls "
            "LEFT JOIN limit_list_ths lt "
            "       ON lt.trade_date=ls.trade_date AND lt.ts_code=ls.ts_code AND lt.limit_type='涨停池' "
            "LEFT JOIN stock_basic sb ON sb.ts_code=ls.ts_code "
            "WHERE ls.trade_date=:d AND ls.\"limit\"='U' "
            "ORDER BY ls.first_time"
        ), {"d": trade_date})).fetchall()
    pool = []
    for r in rows:
        ts_code, name, bc, ft, mv, amt, tag, industry = r
        days, board = bc, bc
        if tag:
            m = re.match(r"(\d+)天(\d+)板", tag)
            if m:
                days, board = int(m.group(1)), int(m.group(2))
            elif tag == "首板":
                days, board = 1, 1
        pool.append({
            "ts_code": ts_code,
            "name": (name or "").replace(" ", ""),
            "board_count": board,
            "days_to_board": days,
            "first_time": (ft or "")[:8] if ft and len(ft) >= 6 else (ft or ""),
            "float_mv_yi": round((mv or 0) / 1e8, 1),
            "amount_yi": round((amt or 0) / 1e8, 1),
            "industry": industry or "",
        })
    return pool


def build_prompt(trade_date: str, pool: list[dict]) -> str:
    lines = []
    for p in pool:
        lines.append(
            f"{p['ts_code']}|{p['name']}|{p['days_to_board']}天{p['board_count']}板|"
            f"{p['first_time']}|流通{p['float_mv_yi']}亿|成交{p['amount_yi']}亿|{p['industry']}"
        )
    return PROMPT_V2.format(
        trade_date=trade_date,
        taxonomy=render_taxonomy_for_prompt(),
        stock_list="\n".join(lines),
    )


def call_claude_sg(prompt: str, timeout: int = 1500) -> str:
    log.info("calling claude-sg --print, prompt=%d chars", len(prompt))
    proc = subprocess.run(
        ["claude-sg.cmd", "--print"],
        input=prompt, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude-sg failed (code={proc.returncode})\nstderr={proc.stderr[-2000:]}")
    return proc.stdout


def parse_llm_response(raw: str) -> dict:
    txt = raw.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", txt, re.DOTALL)
    if m:
        txt = m.group(1)
    if not txt.startswith("{"):
        m = re.search(r"(\{.*\})", txt, re.DOTALL)
        if m:
            txt = m.group(1)
    return json.loads(txt)


async def save_to_db(trade_date: str, llm_data: dict, source_label: str = "llm_v2") -> int:
    n = 0
    async with async_session() as s:
        await s.execute(text(
            "DELETE FROM daily_sector_review WHERE trade_date=:d AND source=:src"
        ), {"d": trade_date, "src": source_label})
        for sec in llm_data.get("main_lines", []):
            sector_name = sec.get("sector", "")
            rank = sec.get("rank", 0)
            stocks = sec.get("stocks", [])
            sector_size = len(stocks)
            for stk in stocks:
                await s.execute(text(
                    "INSERT INTO daily_sector_review "
                    "(trade_date, source, sector_name, sector_rank, sector_size, "
                    " ts_code, stock_name, board_count, days_to_board, limit_time, "
                    " is_main_line, raw_meta) VALUES "
                    "(:trade_date, :src, :sector_name, :sector_rank, :sector_size, "
                    " :ts_code, :stock_name, :board_count, :days_to_board, :limit_time, "
                    " true, :raw_meta)"
                ), {
                    "trade_date": trade_date, "src": source_label,
                    "sector_name": sector_name, "sector_rank": rank, "sector_size": sector_size,
                    "ts_code": stk.get("ts_code"), "stock_name": stk.get("name"),
                    "board_count": stk.get("board_count"), "days_to_board": stk.get("days_to_board"),
                    "limit_time": stk.get("first_time"),
                    "raw_meta": json.dumps(llm_data.get("summary", {}), ensure_ascii=False),
                })
                n += 1
        await s.commit()
    return n


async def main(trade_date: str):
    pool = await fetch_limit_pool(trade_date)
    log.info("trade_date=%s 涨停 %d 只", trade_date, len(pool))
    if not pool:
        return

    prompt = build_prompt(trade_date, pool)
    cache_dir = Path(__file__).resolve().parent / "_cache"
    cache_dir.mkdir(exist_ok=True)
    (cache_dir / f"prompt_{trade_date}.txt").write_text(prompt, encoding="utf-8")

    raw = call_claude_sg(prompt)
    (cache_dir / f"llm_raw_{trade_date}.txt").write_text(raw, encoding="utf-8")

    try:
        data = parse_llm_response(raw)
    except json.JSONDecodeError as e:
        log.error("LLM 返回非 JSON: %s\n%s", e, raw[:500])
        sys.exit(1)

    log.info("LLM v2 识别 %d 个主线", len(data.get("main_lines", [])))
    for sec in data.get("main_lines", []):
        log.info("  #%s %s (%d 只)", sec.get("rank"), sec.get("sector"), len(sec.get("stocks", [])))

    n = await save_to_db(trade_date, data, source_label="llm_v2")
    log.info("入库 %d 行 (source='llm_v2')", n)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python llm_main_line_v2.py YYYYMMDD")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
