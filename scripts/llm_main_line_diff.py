"""对照 LLM 主线判定 vs 板块必读 daily 人工标签的命中率。

用法：
    python scripts/llm_main_line_diff.py 20260506

链路文档：docs/sector_main_line_pipeline.md
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core.database import async_session
from sqlalchemy import text


async def load_main_lines(td: str, source: str, scope_filter: bool = False):
    async with async_session() as s:
        if scope_filter:
            r = await s.execute(text(
                "SELECT sector_name, ts_code, stock_name, board_count, sector_rank, sector_size "
                "FROM daily_sector_review "
                "WHERE trade_date=:d AND source=:s "
                "AND raw_meta->>'scope'='daily' "
                "AND sector_name NOT IN ('一季报预增','反弹','公告','其他') "
                "ORDER BY sector_rank, board_count DESC"
            ), {"d": td, "s": source})
        else:
            r = await s.execute(text(
                "SELECT sector_name, ts_code, stock_name, board_count, sector_rank, sector_size "
                "FROM daily_sector_review WHERE trade_date=:d AND source=:s "
                "ORDER BY sector_rank, board_count DESC"
            ), {"d": td, "s": source})
        rows = r.fetchall()
    secs = {}
    for sec, code, name, bc, rank, size in rows:
        secs.setdefault(sec, {"rank": rank, "size": size, "stocks": []})
        secs[sec]["stocks"].append((code, name, bc))
    return secs


def best_match(jy_sec_name, jy_codes_set, llm_secs):
    best = ("(漏标)", 0, set(), set())
    for llm_sec, info in llm_secs.items():
        llm_codes = {c for c, *_ in info["stocks"] if c}
        hit = jy_codes_set & llm_codes
        if len(hit) > best[1]:
            best = (llm_sec, len(hit), hit, llm_codes)
    return best


async def compare(td: str, gt_source: str = "bankuai"):
    bk = await load_main_lines(td, gt_source, scope_filter=(gt_source == "bankuai"))
    v1 = await load_main_lines(td, "llm")
    v2 = await load_main_lines(td, "llm_v2")

    print(f"\n=== {td} ground truth = {gt_source} ===")
    print(f"  人工：{len(bk)} 主线 / LLM v1：{len(v1)} 主线 / LLM v2：{len(v2)} 主线")

    # 主线级对照
    total, hit_v1, hit_v2 = 0, 0, 0
    print(f"\n{'人工主线':<12} {'人工只数':>4}   {'v1 主线 (命中)':<35} {'v2 主线 (命中)':<35}")
    print("-" * 100)
    for bk_sec, info in sorted(bk.items(), key=lambda x: x[1]["rank"] or 999):
        bk_codes = {c for c, *_ in info["stocks"] if c}
        if not bk_codes:
            continue
        bv1 = best_match(bk_sec, bk_codes, v1)
        bv2 = best_match(bk_sec, bk_codes, v2)
        rate_v1 = bv1[1] / len(bk_codes) * 100
        rate_v2 = bv2[1] / len(bk_codes) * 100
        total += len(bk_codes)
        hit_v1 += bv1[1]
        hit_v2 += bv2[1]
        v1_str = f"{bv1[0]} ({bv1[1]}/{len(bk_codes)} {rate_v1:.0f}%)"
        v2_str = f"{bv2[0]} ({bv2[1]}/{len(bk_codes)} {rate_v2:.0f}%)"
        print(f"{bk_sec:<12} {len(bk_codes):>4}   {v1_str:<35} {v2_str:<35}")

    print("-" * 100)
    if total:
        print(f"{'合计':<12} {total:>4}   v1: {hit_v1}/{total} = {hit_v1/total*100:.1f}%       v2: {hit_v2}/{total} = {hit_v2/total*100:.1f}%")

    # v2 自身打印
    print(f"\n--- LLM v2 全部主线 ---")
    for sec, info in sorted(v2.items(), key=lambda x: x[1]["rank"] or 999):
        names = [n for _, n, _ in info["stocks"][:8]]
        print(f"  #{info['rank']} {sec} ({len(info['stocks'])} 只): {names}")


async def main():
    if len(sys.argv) < 2:
        print("usage: python diff_llm_versions.py YYYYMMDD [gt_source]")
        sys.exit(1)
    td = sys.argv[1]
    gt = sys.argv[2] if len(sys.argv) >= 3 else "bankuai"
    await compare(td, gt)


if __name__ == "__main__":
    asyncio.run(main())
