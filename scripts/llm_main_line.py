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


PROMPT_V2 = """你是 A 股短线题材分析助手。请按"市场当日资金真正抱团的细分主线"对 {trade_date} 当日所有涨停股进行分组。

# 重要指引（按优先级）

## 1. 主线归类原则 — 细分粒度优先（关键！）

**资金每天抱团的是细分主线，不是大筐**。同样属于"算力大类"，但 5/7 的光通信、PCB、算力租赁、液冷是 4 个独立主线 — 因为不同细分有不同的启动股 / 跟风逻辑 / 资金来源。**禁止把它们合并到一个"算力"大主线**。

判定细分粒度的方法：
- 看启动股是不是**同一批人在炒**（光通信龙 1 杭电股份的资金 ≠ 算力租赁龙 1 航锦科技的资金）
- 看涨停关键词 / 同板块跟风票 / 主流游资讨论的细分名（如"光通信""PCB""液冷"是当日板块必读 / 韭研公社 / 东方财富热度榜各自独立的主线名）
- 同一只股票可同时归入多个细分主线（业务横跨），全部列出，去重交给下游

## 2. 已知细分主线参考粒度（仅参考，遇新细分允许新建）

{taxonomy}

注意：上面的列表只是已知细分**示例**，不是全集。当日如出现新的强势细分（如"Kimi概念""快手概念"等突发题材），按当日实际抱团情况自己取名建新主线。

## 3. 壳股蹭题材识别（关键！）

- **高板妖股（≥4 连板）即使主营业务与题材无关**，但市场公认其炒的就是该题材，**必须**归入该题材主线
- 历史案例：4/30 金螳螂（建筑装饰主营）10 天 8 板炒"半导体洁净室"（传闻签订大单），应归"半导体洁净室"细分（不是"装修装饰"也不是"国产芯片"大筐）
- 判别方法：连板高度 ≥ 4 板的票，看其涨停关键词 / 涨停时间 / 同板块跟风票，反推它在炒什么细分
- 普通首板 / 2 板的非主营题材沾边股，按主营行业即可

## 4. 主线 vs 补涨 / 杂毛

- 细分主线候选标准：当日 ≥ 2 只同细分涨停，**或** 至少有 1 只 ≥ 2 连板的高标
- 涨停股孤立（同细分仅 1 只 1 板首板）且无高标 = 补涨 / 杂毛，**不应**列入主线
- **跳过基本面属性标签**："一季报预增" / "年报增长" / "业绩扭亏" / "净利润增长" 都不是题材主线
- 仅同板块涨停 1 只的"地产" / "造纸" / "汽车配件"这种纯行业大标签，按补涨处理

## 5. sector 命名硬约束（关键！）

- **sector 字段必须是单一细分主线名**，禁止用斜杠 / 顿号 / 加号 / 括号合并多个主线
- ❌ 错误示例："算力租赁/数据中心"、"光通信/通信设备"、"国产芯片/存储"、"机器人/精密制造"、"锂电（锂矿/锂电材料）"
- ✅ 正确做法：如果你认为两个细分是同一波抱团，挑**最贴切的那个**做 sector 名（其他细分如果有独立成员也单独成主线）
- ✅ 正确示例："算力租赁"（最贴切就用算力租赁）、"光通信"、"存储芯片"、"机器人"
- 原因：下游归一表 ALIAS_TO_CANONICAL 不识别带斜杠的复合名，会让"算力租赁/数据中心"独立成主线 → 跟纯"算力租赁"、纯"数据中心"重复，污染回测信号

# Few-Shot 参考案例（5/7 真实细分主线）

5/7 当日资金抱团的细分主线（按 jiuyan + 板块必读人工共识，仅列代表股）：

| 细分主线 | 涨停只数 | 代表股（含连板） |
|---|---|---|
| 光通信 | 14 | 杭电股份(2板) / 炬光科技 / 中天科技 / 通鼎互联 / 特发信息 |
| 算力租赁 | 12 | 航锦科技(2板) / 东阳光(2板) / 中嘉博创(2板) / 合力泰(2板) |
| PCB | 11 | 宏和科技(2板) / 协和电子 / 红板科技 / 聚杰微纤 / 超声电子 |
| 机器人 | 10 | 宇环数控(2板) / 大业股份(2板) / 巨轮智能 / 模塑科技 |
| 数据中心 | 8 | 腾龙股份(2板) / 科华数据 / 诚邦股份(2板) |
| 电力 | 7 | 大唐发电(2板) / 大连热电(2板) / 华电辽能(2板) / 中国能建 |
| 国产芯片细分 | 6 | 超声电子 / 大族激光 / 格林达 / 泰晶科技 / 三孚股份 |
| 商业航天 | 5 | **金螳螂(5连板)** ← 壳股蹭题材 / 上海港湾 / 巨力索具 |
| 液冷 | 2 | 大中转债 / 欧通转债（液冷服务器细分） |

**关键观察**：
- 上面 9 个细分主线里，光通信 / PCB / 算力租赁 / 数据中心 / 液冷 都属于"算力大筐"，但它们是 5 个独立主线（不同启动股、不同跟风逻辑），**不要合并**
- 同样道理，国产芯片细分（存储芯片 / 半导体材料 / 光刻胶 / CPU / 半导体洁净室）若当日有抱团，应各自独立成主线
- 模塑科技 / 巨轮智能 既是机器人也是汽车产业链 — 都列出，去重交给下游

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
