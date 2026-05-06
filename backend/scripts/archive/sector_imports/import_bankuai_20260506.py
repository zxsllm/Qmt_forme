"""一次性导入：5/6 板块必读连板天梯（图 #33）+ 板块最强转债（图 #34）→ daily_sector_review。

source='bankuai'  scope ∈ {'daily','cb_strongest'}

图 #35（板块涨幅监测格子图）不入库，非 sector_review_workflow.md 标准的图 A/B/D 三类。
本日板块必读未发布"小盘/大盘月度主线柱状图"（图 B），故无 monthly scope。
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.core.database import async_session
from sqlalchemy import text


TRADE_DATE = "20260506"

# ---- 图 #33 顶部摘要：板块名 → (size, rank) ----
DAILY_SECTOR_HEADER = [
    ("国产芯片",    22,  1),
    ("算力租赁",    12,  2),
    ("数据中心",    11,  3),
    ("电力",         8,  4),
    ("大消费",       5,  5),
    ("光通信",       5,  6),
    ("电池产业链",   4,  7),
    ("PCB",          4,  8),
    ("商业航天",     3,  9),
    ("燃气轮机",     3, 10),
    ("大金融",       2, 11),
    ("机器人",       2, 12),
]

# ---- 图 #33 连板天梯 ----
# (board, sector, name, time, one_word)
DAILY_LADDER = [
    # 4 板
    (4, "国产芯片",    "金螳螂",   "9:42", False),
    (4, "电池产业链",  "永杉锂业", "9:30", True),    # 一字
    (4, "反弹",        "宝光股份", "9:30", False),
    # 3 板
    (3, "电池产业链",  "丰元股份", "11:26", False),
    (3, "公告",        "丽岛新材", "9:33",  False),
    (3, "公告",        "金融街",   "9:52",  False),
    # 2 板
    (2, "国产芯片",    "中国长城", "10:04", False),
    (2, "国产芯片",    "中天精装", "9:36",  False),
    (2, "大金融",      "长江证券", "11:27", False),
    (2, "公告",        "华软科技", "9:30",  True),    # 一字
    (2, "公告",        "福达合金", None,    False),
    (2, "公告",        "跨境通",   None,    False),
    (2, "公告",        "润贝航科", "9:39",  False),
    (2, "公告",        "安道麦A",  "10:36", False),
    (2, "数据中心",    "汉钟精机", "10:58", False),
    (2, "大消费",      "粤传媒",   "14:57", False),
    (2, "商业航天",    "西部材料", "14:10", False),
    # 首板：每板块 top 5（按图最早封板的）
    # 国产芯片首板 (含存储/CPU 子板)
    (1, "国产芯片", "盈新发展", "9:30", True),    # 一字
    (1, "国产芯片", "通富微电", "9:30", False),
    (1, "国产芯片", "德明利",   "9:37", False),
    (1, "国产芯片", "禾盛新材", "9:40", False),
    (1, "国产芯片", "诚邦股份", "9:41", False),
    (1, "国产芯片", "园林股份", "9:46", False),
    (1, "国产芯片", "综艺股份", "9:52", False),
    (1, "国产芯片", "川润股份", "9:57", False),
    (1, "国产芯片", "深圳新星", "10:11", False),
    (1, "国产芯片", "养元饮品", "10:12", False),
    (1, "国产芯片", "华源控股", "10:12", False),
    (1, "国产芯片", "朗科科技", "10:12", False),
    (1, "国产芯片", "兆易创新", "9:38",  False),
    (1, "国产芯片", "中电港",   "10:43", False),
    (1, "国产芯片", "上海合晶", "10:48", False),
    (1, "国产芯片", "和顺石油", "14:33", False),
    (1, "国产芯片", "广合科技", "14:46", False),
    (1, "国产芯片", "江波龙",   "14:47", False),
    (1, "国产芯片", "赛英电子", "15:01", False),
    # 算力租赁
    (1, "算力租赁", "中嘉博创", "9:34",  True),    # 一字 (韭研口径 6天3板 → 板块必读列首板)
    (1, "算力租赁", "合力泰",   "9:37",  False),
    (1, "算力租赁", "美利云",   "10:42", False),
    (1, "算力租赁", "兴民智通", "10:47", False),
    (1, "算力租赁", "直真科技", "11:02", False),
    (1, "算力租赁", "大位科技", "11:14", False),
    (1, "算力租赁", "鸿博股份", "13:00", False),
    (1, "算力租赁", "恒润股份", "14:05", False),
    (1, "算力租赁", "东方国信", "14:20", False),
    (1, "算力租赁", "利通电子", "14:51", False),
    (1, "算力租赁", "航锦科技", "10:51", False),
    (1, "算力租赁", "奥瑞德",   "13:14", False),
    # 数据中心
    (1, "数据中心", "景津装备", "9:32",  False),
    (1, "数据中心", "海鸥股份", "9:55",  False),
    (1, "数据中心", "中恒电气", "13:49", False),
    (1, "数据中心", "腾龙股份", "14:09", False),
    (1, "数据中心", "海亮股份", "14:25", False),
    (1, "数据中心", "禾望电气", "14:36", False),
    (1, "数据中心", "海星股份", "14:41", False),
    (1, "数据中心", "同洲电子", "14:44", False),
    (1, "数据中心", "伟隆股份", "14:56", False),
    (1, "数据中心", "瑞可达",   "14:56", False),
    # 电力
    (1, "电力", "华电辽能",   "14:53", False),
    (1, "电力", "大唐发电",   "9:36",  False),
    (1, "电力", "杭电股份",   "9:49",  False),
    (1, "电力", "诺普信",     "10:12", False),
    (1, "电力", "大连热电",   "10:42", False),
    (1, "电力", "节能风电",   "10:45", False),
    (1, "电力", "晶科科技",   "11:13", False),
    (1, "电力", "金开新能",   "14:23", False),
    # 光通信
    (1, "光通信", "博敏电子", "9:30", False),
    (1, "光通信", "杭电股份", "9:36", False),
    (1, "光通信", "中金岭南", "13:05", False),
    (1, "光通信", "雷迪克",   "14:23", False),
    (1, "光通信", "云南锗业", "14:41", False),
    # PCB
    (1, "PCB", "宏和科技", "14:09", False),
    (1, "PCB", "泰金新能", "10:21", False),
    (1, "PCB", "德福科技", "14:14", False),
    (1, "PCB", "中材科技", "14:28", False),
    # 大消费
    (1, "大消费", "浙江东日", "9:47",  False),
    (1, "大消费", "奥康国际", "10:00", False),
    (1, "大消费", "轻纺城",   "10:16", False),
    (1, "大消费", "北京文化", "14:55", False),
    # 电池产业链
    (1, "电池产业链", "蔚蓝锂芯", "14:22", False),
    (1, "电池产业链", "海南矿业", "14:53", False),
    # 商业航天
    (1, "商业航天", "瑞华泰",   "10:51", False),
    (1, "商业航天", "通宇通讯", "14:10", False),
    # 燃气轮机
    (1, "燃气轮机", "潍柴动力", "10:19", False),
    (1, "燃气轮机", "联德股份", "13:00", False),
    (1, "燃气轮机", "天润工业", "14:27", False),
    # 大金融
    (1, "大金融", "汇金股份", "13:15", False),
    # 机器人
    (1, "机器人", "宇环数控", "13:32", False),
    (1, "机器人", "大业股份", "14:25", False),
]


# ---- 图 #34 板块最强转债 ----
# (concept, cb_name, pct_chg, amount_yi)
CB_STRONGEST = [
    ("算力租赁", "盈峰转债", 12, 41),
    ("电力",     "晶科转债", 17, 36),
    ("氢气",     "华特转债",  1, 36),
    ("锂电",     "万顺转2",   3, 16),
    ("锂电",     "大中转债",  4, 14),
    ("液冷",     "欧通转债",  2, 14),
]


async def resolve_ts_code(session, name: str, prefer_cb: bool = False):
    name_clean = (name or "").replace(" ", "").replace("XD", "")
    if not name_clean:
        return None
    if prefer_cb:
        r = await session.execute(text(
            "SELECT ts_code FROM cb_basic WHERE bond_short_name=:n OR bond_short_name LIKE :nl LIMIT 1"
        ), {"n": name_clean, "nl": f"%{name_clean}%"})
        row = r.fetchone()
        if row:
            return row[0]
    r = await session.execute(text(
        "SELECT ts_code FROM stock_basic WHERE REPLACE(name,' ','')=:n AND list_status='L' LIMIT 1"
    ), {"n": name_clean})
    row = r.fetchone()
    if row:
        return row[0]
    r = await session.execute(text(
        "SELECT ts_code FROM stock_basic WHERE REPLACE(name,' ','') LIKE :nl AND list_status='L' LIMIT 1"
    ), {"nl": f"%{name_clean}%"})
    row = r.fetchone()
    return row[0] if row else None


async def main():
    async with async_session() as s:
        await s.execute(text(
            "DELETE FROM daily_sector_review WHERE trade_date=:d AND source='bankuai'"
        ), {"d": TRADE_DATE})

        size_map = {sec: (size, rank) for sec, size, rank in DAILY_SECTOR_HEADER}
        n_d = 0
        n_c = 0
        unresolved = []

        # ---- daily ladder ----
        for board, sector, name, ftime, one_word in DAILY_LADDER:
            ts_code = await resolve_ts_code(s, name)
            if not ts_code:
                unresolved.append(("daily", name))
            size, rank = size_map.get(sector, (None, None))
            await s.execute(text(
                "INSERT INTO daily_sector_review "
                "(trade_date, source, sector_name, sector_rank, sector_size, "
                " ts_code, stock_name, board_count, days_to_board, limit_time, "
                " is_main_line, raw_meta) VALUES "
                "(:td,'bankuai',:sec,:rank,:size,:tc,:nm,:bc,:dtb,:lt,true,:rm)"
            ), {
                "td": TRADE_DATE, "sec": sector, "rank": rank, "size": size,
                "tc": ts_code, "nm": name, "bc": board, "dtb": board, "lt": ftime,
                "rm": json.dumps({"scope": "daily", "one_word": one_word}, ensure_ascii=False),
            })
            n_d += 1

        # ---- cb_strongest ----
        for concept, cb_name, chg, amt in CB_STRONGEST:
            ts_code = await resolve_ts_code(s, cb_name, prefer_cb=True)
            if not ts_code:
                unresolved.append(("cb", cb_name))
            await s.execute(text(
                "INSERT INTO daily_sector_review "
                "(trade_date, source, sector_name, ts_code, stock_name, amount, "
                " is_main_line, raw_meta) VALUES "
                "(:td,'bankuai',:sec,:tc,:nm,:amt,true,:rm)"
            ), {
                "td": TRADE_DATE, "sec": concept, "tc": ts_code, "nm": cb_name, "amt": amt,
                "rm": json.dumps({"scope": "cb_strongest", "pct_chg": chg}, ensure_ascii=False),
            })
            n_c += 1

        await s.commit()

    print(f"bankuai {TRADE_DATE} daily: {n_d} 行 / cb: {n_c} 行")
    if unresolved:
        print(f"\n未匹配 ts_code {len(unresolved)} 条:")
        for src, nm in unresolved:
            print(f"  [{src}] {nm}")


if __name__ == "__main__":
    asyncio.run(main())
