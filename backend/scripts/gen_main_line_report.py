"""每日主线 + 股票池 HTML 报告生成器。

数据来源 daily_sector_review（三源 bankuai + jiuyan + llm_v2）：
  - 三源各识别的主线（原始 raw alias） + 票数
  - 按 ALIAS_TO_CANONICAL 归一后的细分主线 + 票池（三源合并去重）
  - 每只票标注来源（B/J/L 三源各自命中标记）

用法：
    python backend/scripts/gen_main_line_report.py 20260428 20260429 ... 20260512
    输出到 reports/main_line/main_line_YYYYMMDD.html
"""
import argparse
import asyncio
import html
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from app.research.signals.theme_taxonomy import ALIAS_TO_CANONICAL, SUBSECTOR_TO_PARENT
from sqlalchemy import text


def _h(s) -> str:
    return html.escape(str(s)) if s is not None else ""


SOURCE_LABEL = {"bankuai": "B 板块必读", "jiuyan": "J 韭研", "llm_v2": "L LLM v2"}
SOURCE_COLOR = {"bankuai": "#f5222d", "jiuyan": "#fa8c16", "llm_v2": "#722ed1"}


CSS = """
body { font-family: -apple-system,Segoe UI,Microsoft YaHei,sans-serif; padding:18px; background:#f5f5f7; color:#222; max-width:1400px; margin:0 auto; }
h1 { color:#1890ff; border-bottom:2px solid #1890ff; padding-bottom:8px; margin-top:0; }
h2 { color:#262626; border-left:4px solid #1890ff; padding-left:10px; margin-top:24px; }
h3 { color:#595959; margin-top:18px; margin-bottom:6px; }
.meta { background:#fff; border:1px solid #e6e9ed; padding:10px 14px; border-radius:6px; font-size:13px; line-height:1.7; margin-bottom:14px; }
.sources { display:flex; gap:14px; flex-wrap:wrap; margin-bottom:14px; }
.src-card { flex:1; min-width:280px; background:#fff; border:1px solid #e6e9ed; border-radius:6px; padding:10px 14px; }
.src-card h3 { margin:0 0 8px 0; font-size:14px; }
.src-list { font-size:13px; line-height:1.9; }
.src-tag { display:inline-block; padding:2px 6px; margin:2px 4px 2px 0; background:#f0f5ff; color:#1890ff; border-radius:3px; font-size:12px; }
.parent-block { background:#fff; border:1px solid #e6e9ed; border-radius:6px; padding:12px 16px; margin-bottom:14px; }
.parent-block h2 { margin:0 0 8px 0; padding-left:8px; }
table { border-collapse:collapse; width:100%; font-size:13px; }
th { background:#fafafa; padding:6px 8px; text-align:left; border-bottom:2px solid #e6e9ed; font-weight:600; color:#595959; }
td { padding:6px 8px; border-bottom:1px solid #f0f0f0; vertical-align:top; }
tr:hover { background:#fafafa; }
.src-dot { display:inline-block; width:18px; height:18px; line-height:18px; text-align:center; font-size:11px; font-weight:600; border-radius:3px; color:#fff; margin-right:3px; }
.board-tag { display:inline-block; padding:1px 6px; background:#fff2e8; color:#fa541c; border-radius:3px; font-size:11px; font-weight:600; }
.board-high { background:#fff1f0; color:#cf1322; }
.kw { color:#888; font-size:12px; }
.summary { background:linear-gradient(135deg,#e6f7ff,#fff); border:1px solid #91d5ff; padding:10px 14px; border-radius:6px; margin-bottom:14px; font-size:13px; line-height:1.8; }
.big-num { font-size:20px; font-weight:700; color:#1890ff; }
"""


def parent_of(canonical: str) -> str:
    """canonical 细分 → 父大类（用于 UI 分组），未命中则用 '其他'"""
    return SUBSECTOR_TO_PARENT.get(canonical, "其他")


def normalize(sector_name: str) -> str:
    """raw alias → canonical 细分"""
    return ALIAS_TO_CANONICAL.get(sector_name, sector_name)


async def fetch_day(trade_date: str) -> dict:
    """拉某日三源全部 sector_review 行，返回结构化数据。"""
    async with async_session() as s:
        rows = (await s.execute(text("""
            SELECT source, sector_name, sector_size, ts_code, stock_name,
                   board_count, days_to_board, limit_time, float_mv, amount, keywords,
                   is_main_line, raw_meta
            FROM daily_sector_review
            WHERE trade_date = :d
              AND source IN ('bankuai','jiuyan','llm_v2')
              AND ts_code IS NOT NULL AND ts_code <> ''
            ORDER BY source, sector_name, COALESCE(board_count, 0) DESC, limit_time
        """), {"d": trade_date})).fetchall()
    return rows


def build_html(trade_date: str, rows) -> str:
    if not rows:
        return f"<html><body><h1>{trade_date}</h1><p>无数据</p></body></html>"

    # 1. 按 source 分组（保留原始 raw sector_name）
    by_src: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    # 2. 按 canonical 归一聚合（票池：dict[canonical -> dict[ts_code -> {name, sources_set, ...}]]）
    pool: dict[str, dict] = defaultdict(dict)

    for r in rows:
        src, raw_sec, sec_size, ts_code, name, board, days, lt, fmv, amount, kw, is_main, raw_meta = r
        canonical = normalize(raw_sec)
        # 跳过 CB（scope='cb_strongest'）—— 不进股票池，单独展示
        scope = (raw_meta or {}).get("scope") if isinstance(raw_meta, dict) else None
        if scope == "cb_strongest":
            by_src[src][f"{raw_sec} [CB]"].append({
                "ts_code": ts_code, "name": name, "amount": amount,
                "raw_meta": raw_meta,
            })
            continue
        by_src[src][raw_sec].append({
            "ts_code": ts_code, "name": name, "board": board, "days": days,
            "limit_time": lt, "float_mv": fmv, "amount": amount, "keywords": kw,
        })
        # 票池：相同 ts_code 合并三源
        if ts_code not in pool[canonical]:
            pool[canonical][ts_code] = {
                "name": name, "sources": set(),
                "board": board, "days": days, "limit_time": lt,
                "float_mv": fmv, "amount": amount, "keywords": kw,
                "raw_secs": set(),
            }
        pool[canonical][ts_code]["sources"].add(src)
        pool[canonical][ts_code]["raw_secs"].add(raw_sec)
        # 用最先看到的非空字段填充
        for k in ("board", "days", "limit_time", "float_mv", "amount", "keywords"):
            v = locals().get(k.replace("limit_time", "lt"))
            cur = pool[canonical][ts_code][k]
            if (cur is None or cur == "") and r[r._fields.index({
                "board": "board_count", "days": "days_to_board",
                "limit_time": "limit_time", "float_mv": "float_mv",
                "amount": "amount", "keywords": "keywords",
            }[k])] if False else False:
                pass

    # 3. canonical 按 parent 分组（UI 显示）
    by_parent: dict[str, list] = defaultdict(list)
    for canon, codes in pool.items():
        by_parent[parent_of(canon)].append((canon, codes))
    # 排序：按本主线票数倒序
    for parent in by_parent:
        by_parent[parent].sort(key=lambda x: -len(x[1]))

    # —— 渲染 ——
    total_stocks = len({c for codes in pool.values() for c in codes})
    canonical_count = len(pool)
    src_counts = {s: sum(len(v) for v in by_src[s].values()) for s in by_src}
    src_secs = {s: len(by_src[s]) for s in by_src}

    # 三源原始板块卡
    src_cards = []
    for src in ("bankuai", "jiuyan", "llm_v2"):
        if src not in by_src:
            continue
        items = sorted(by_src[src].items(), key=lambda x: -len(x[1]))
        tags = "".join(
            f"<span class='src-tag'>{_h(sec)} ({len(stocks)})</span>"
            for sec, stocks in items
        )
        src_cards.append(f"""
        <div class='src-card'>
          <h3 style='color:{SOURCE_COLOR[src]}'>{SOURCE_LABEL[src]} — {src_secs[src]} 个原始板块 / {src_counts[src]} 行</h3>
          <div class='src-list'>{tags}</div>
        </div>
        """)

    # 归一后的票池
    parent_blocks = []
    for parent, items in sorted(by_parent.items(), key=lambda x: -sum(len(c) for _, c in x[1])):
        canon_blocks = []
        for canon, codes in items:
            n = len(codes)
            rows_html = []
            # 票池按 board 倒序、limit_time 升序
            sorted_codes = sorted(
                codes.items(),
                key=lambda x: (-(x[1]["board"] or 1), x[1]["limit_time"] or "999999"),
            )
            for ts_code, info in sorted_codes:
                src_dots = "".join(
                    f"<span class='src-dot' style='background:{SOURCE_COLOR[s]}'>"
                    f"{SOURCE_LABEL[s][0]}</span>"
                    for s in ("bankuai", "jiuyan", "llm_v2") if s in info["sources"]
                )
                board_tag = ""
                if info["board"] and info["board"] >= 2:
                    cls = "board-tag board-high" if info["board"] >= 4 else "board-tag"
                    board_tag = f"<span class='{cls}'>{info['days']}天{info['board']}板</span>"
                elif info["board"] == 1:
                    board_tag = "<span class='board-tag' style='background:#f0f0f0;color:#888'>首板</span>"
                lt = info["limit_time"] or ""
                if lt and len(lt) >= 5:
                    lt = lt[:5]  # HH:MM
                fmv = f"{info['float_mv']:.0f}亿" if info["float_mv"] else ""
                kw = info["keywords"] or ""
                if len(kw) > 50:
                    kw = kw[:50] + "…"
                raw_secs_str = " / ".join(sorted(info["raw_secs"]))
                rows_html.append(f"""
                <tr>
                  <td>{src_dots}</td>
                  <td>{_h(ts_code)}</td>
                  <td><b>{_h(info['name'])}</b></td>
                  <td>{board_tag}</td>
                  <td>{_h(lt)}</td>
                  <td>{fmv}</td>
                  <td class='kw' title='{_h(raw_secs_str)}'>{_h(kw)}</td>
                </tr>
                """)
            canon_blocks.append(f"""
            <h3>{_h(canon)} — {n} 只</h3>
            <table>
              <thead>
                <tr>
                  <th style='width:80px'>来源</th>
                  <th style='width:100px'>代码</th>
                  <th style='width:110px'>名称</th>
                  <th style='width:80px'>板数</th>
                  <th style='width:60px'>涨停</th>
                  <th style='width:70px'>流通市值</th>
                  <th>关键词（hover 看 raw 板块名）</th>
                </tr>
              </thead>
              <tbody>{''.join(rows_html)}</tbody>
            </table>
            """)
        parent_total = sum(len(c) for _, c in items)
        parent_blocks.append(f"""
        <div class='parent-block'>
          <h2>{_h(parent)} — {len(items)} 个细分主线 / {parent_total} 只票</h2>
          {''.join(canon_blocks)}
        </div>
        """)

    return f"""<!doctype html>
<html lang='zh-CN'>
<head>
<meta charset='utf-8'>
<title>{trade_date} 主线板块 + 股票池</title>
<style>{CSS}</style>
</head>
<body>
  <h1>{trade_date} 主线板块 + 股票池</h1>
  <div class='meta'>
    数据源：<code>daily_sector_review</code>（B 板块必读 + J 韭研公社 + L LLM v2）<br>
    归一规则：raw sector_name → ALIAS_TO_CANONICAL 同义词归一 → 细分主线 → SUBSECTOR_TO_PARENT 父大类<br>
    票池：三源合并去重，每只票标注来源命中（B/J/L）；hover 关键词列看 raw 原始板块名
  </div>

  <div class='summary'>
    📊 <span class='big-num'>{total_stocks}</span> 只票 ／
    <span class='big-num'>{canonical_count}</span> 个细分主线 ／
    <span class='big-num'>{len(by_parent)}</span> 个父大类
    &nbsp;&nbsp;|&nbsp;&nbsp;
    {' / '.join(f'<b style="color:{SOURCE_COLOR[s]}">{SOURCE_LABEL[s]}</b> {src_secs.get(s,0)}主线/{src_counts.get(s,0)}行' for s in ('bankuai','jiuyan','llm_v2') if s in by_src)}
  </div>

  <div class='sources'>{''.join(src_cards)}</div>

  {''.join(parent_blocks)}
</body>
</html>"""


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("dates", nargs="+", help="trade dates YYYYMMDD ...")
    args = p.parse_args()

    out_dir = Path(__file__).resolve().parents[2] / "reports" / "main_line"
    out_dir.mkdir(parents=True, exist_ok=True)

    for td in args.dates:
        rows = await fetch_day(td)
        if not rows:
            print(f"  {td}: 无数据，跳过")
            continue
        html_str = build_html(td, rows)
        out_path = out_dir / f"main_line_{td}.html"
        out_path.write_text(html_str, encoding="utf-8")
        print(f"  → {out_path}")

    print("\n=== 生成完成 ===")
    for td in args.dates:
        fp = out_dir / f"main_line_{td}.html"
        if fp.exists():
            print(f"  file:///{str(fp).replace(chr(92), '/')}")


if __name__ == "__main__":
    asyncio.run(main())
