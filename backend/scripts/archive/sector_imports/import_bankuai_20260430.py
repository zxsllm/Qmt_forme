"""一次性导入板块必读 4/30 三张图（连板天梯 / 月度主线 / 最强转债）→ daily_sector_review。

数据全部由对话内 Claude 多模态 OCR 后手工编码，作为后续算法 B 训练 / 校准的人工标签。

source='bankuai'  | scope ∈ {'daily','monthly','cb_strongest'}
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from sqlalchemy import text


TRADE_DATE = "20260430"

# ---- 图 1：连板天梯（当日 daily 主线） ----
# 顶部摘要：板块名 -> 当日涨停只数（sector_size）
DAILY_SECTOR_HEADER = [
    ("一季报预增", 35, 1),
    ("国产芯片", 9, 2),
    ("电池产业链", 7, 3),
    ("机器人", 6, 4),
    ("算力", 5, 5),
    ("商业航天", 5, 6),
    ("体育产业", 4, 7),
]

# 图 1 主体——每只票 (股票名, 主标签, 连板信息, 涨停时间, 是否一字)
# 板数：4板 / 3板 / 2板 / 首板
# 主标签 = 票下方的彩色字
DAILY_LADDER = [
    # board, sector, name, time, one_word
    (4, "算力",       "越剑智能", "13:35", True),
    (3, "国产芯片",    "金螳螂",   None,    False),
    (3, "电池产业链",  "永杉锂业", "9:34",  True),
    (3, "反弹",       "宝光股份", "9:54",  False),
    (2, "一季报预增",  "光莆股份", "9:30",  False),
    (2, "一季报预增",  "金融街",   "13:14", False),
    (2, "一季报预增",  "华宏科技", "10:05", False),
    (2, "一季报预增",  "众泰汽车", "10:07", False),
    (2, "一季报预增",  "丽岛新材", "13:08", False),
    (2, "一季报预增",  "金瑞矿业", "13:14", False),
    (2, "一季报预增",  "翔鹭钨业", "14:02", False),
    (2, "一季报预增",  "日联科技", "14:29", False),
    (2, "一季报预增",  "海德股份", "14:31", False),
    (2, "电池产业链",  "丰元股份", "9:30",  False),
    (2, "电池产业链",  "融捷股份", "10:50", False),
    (2, "体育产业",    "舒华体育", "9:40",  False),
    (2, "体育产业",    "共创草坪", "9:51",  False),
    # 首板 61 只（按图从左到右、上到下）
    (1, "一季报预增", "安道麦A",  "9:30",  True),
    (1, "一季报预增", "丽臣实业", "9:34",  True),
    (1, "一季报预增", "福达合金", "9:35",  True),
    (1, "一季报预增", "跨境通",   "9:38",  False),
    (1, "一季报预增", "全筑股份", "9:32",  False),
    (1, "一季报预增", "润贝航科", "9:34",  False),
    (1, "一季报预增", "华软科技", "9:34",  False),
    (1, "一季报预增", "中体产业", "9:45",  False),
    (1, "一季报预增", "明微电子", "9:48",  False),
    (1, "一季报预增", "先惠技术", "9:39",  False),
    (1, "一季报预增", "香飘飘",   "9:50",  False),
    (1, "一季报预增", "新赛股份", "9:51",  False),
    (1, "一季报预增", "国芳集团", "9:54",  False),
    (1, "一季报预增", "朗迪集团", "10:01", False),
    (1, "一季报预增", "衢州发展", "10:10", False),
    (1, "一季报预增", "华神科技", "10:23", False),
    (1, "一季报预增", "亚通精工", "10:24", False),
    (1, "一季报预增", "汇洁股份", "10:37", False),
    (1, "一季报预增", "派克新材", "10:58", False),
    (1, "一季报预增", "北辰实业", "13:08", False),
    (1, "一季报预增", "冠豪高新", "13:11", False),
    (1, "一季报预增", "长江证券", "10:17", False),
    (1, "一季报预增", "中国一重", "10:52", False),
    (1, "一季报预增", "浙江荣泰", "13:13", False),
    (1, "一季报预增", "恒大高新", "13:28", False),
    (1, "一季报预增", "津投城开", "13:33", False),
    (1, "国产芯片",   "中国长城", "13:45", False),
    (1, "国产芯片",   "高新发展", "14:16", False),
    (1, "国产芯片",   "万通发展", "14:26", False),
    (1, "国产芯片",   "中天精装", "9:55",  False),
    (1, "国产芯片",   "汉钟精机", "13:42", False),
    (1, "国产芯片",   "寒武纪",   "14:31", False),
    (1, "国产芯片",   "华东重机", "14:43", False),
    (1, "国产芯片",   "大胜达",   "10:03", False),
    (1, "电池产业链", "东望时代", "10:36", False),
    (1, "电池产业链", "粤桂股份", "13:13", False),
    (1, "电池产业链", "盛新锂能", "13:19", False),
    (1, "电池产业链", "万里石",   "13:21", False),
    (1, "电池产业链", "圣龙股份", "14:35", False),
    (1, "电池产业链", "海昌新材", "9:43",  False),
    (1, "机器人",     "凌云光",   "11:10", False),
    (1, "机器人",     "香山股份", "13:50", False),
    (1, "机器人",     "长城科技", "14:41", False),
    (1, "机器人",     "红豆股份", "10:30", False),
    (1, "算力",       "盛视科技", "10:58", False),
    (1, "算力",       "芯原股份", "13:26", False),
    (1, "算力",       "博迁新材", "13:42", False),
    (1, "算力",       "润建股份", "13:51", False),
    (1, "商业航天",   "航天工程", "13:03", False),
    (1, "商业航天",   "起帆电缆", "14:57", False),
    (1, "商业航天",   "联合精密", "13:20", False),
    (1, "商业航天",   "上海沪工", "9:53",  False),
    (1, "商业航天",   "西部材料", "13:26", False),
    (1, "体育产业",   "粤传媒",   "13:33", False),
    (1, "体育产业",   "安妮股份", "13:51", False),
    (1, "公告",       "百傲化学", "14:23", False),
    (1, "公告",       "创世纪",   None,    False),
    (1, "反弹",       "天域生物", None,    False),
    (1, "反弹",       "全新好",   None,    False),
    (1, "反弹",       "盛景微",   None,    False),
    (1, "反弹",       "千味央厨", None,    False),
]


# ---- 图 2：月度主线（小盘 / 大盘） ----
# (sector, is_core, name, monthly_chg, today_chg, market_cap_tier)
MONTHLY_MAIN_LINE = [
    # ---- 小盘主线（4 月）----
    ("算力", False, "利通电子",  125, 10, "small"),
    ("算力", False, "博云新材",  124,  6, "small"),
    ("算力", False, "沃格光电",  112, -1, "small"),
    ("算力", False, "华盛昌",    90, -2, "small"),
    ("算力", False, "金富科技",  83, -3, "small"),
    ("算力", False, "东山精密",  81,  1, "small"),
    ("算力", False, "天通股份",  78,  9, "small"),
    ("算力", False, "剑桥科技",  72,  3, "small"),
    ("算力", False, "光迅科技",  71,  9, "small"),
    ("算力", False, "宏和科技",  70, -1, "small"),
    ("算力", True,  "铜冠铜箔", 109, 10, "small"),
    ("算力", True,  "宏景科技", 107, -3, "small"),
    ("算力", True,  "行云科技",  75,  3, "small"),
    ("算力", True,  "奥尼电子",  74,  0, "small"),
    ("算力", True,  "长芯博创",  68,  4, "small"),
    ("算力", False, "品高股份", 136,  6, "small"),
    ("算力", False, "优利德",   129, -1, "small"),
    ("算力", False, "海泰新光", 101, -1, "small"),
    ("算力", False, "盛科通信-U", 93, -2, "small"),
    ("算力", False, "杰华特",    81, 17, "small"),
    ("算力", False, "鼎通科技",  75,  0, "small"),
    ("算力", False, "长光华芯",  71,  0, "small"),
    ("算力", False, "优迅股份",  70, -2, "small"),
    ("芯片", False, "盛视科技",  84, 10, "small"),
    ("芯片", True,  "凌玮科技",  77,  4, "small"),
    ("芯片", True,  "斯迪克",    76,  1, "small"),
    ("芯片", True,  "唯特偶",    74,  2, "small"),
    ("芯片", True,  "蜀道装备",  69, -2, "small"),
    ("芯片", False, "九州一轨", 123,  2, "small"),
    ("芯片", False, "华特气体", 107, -1, "small"),
    ("芯片", False, "迅捷兴",    96, 19, "small"),
    ("芯片", False, "锴威特",    93,  8, "small"),
    ("芯片", False, "中船特气",  89,  6, "small"),
    ("芯片", False, "欧莱新材",  84,  7, "small"),
    ("芯片", False, "华兴源创",  75, -4, "small"),
    ("芯片", False, "寒武纪",    73, 20, "small"),
    ("锂电", False, "永杉锂业",  72, 10, "small"),
    ("锂电", True,  "天华新能",  89,  0, "small"),
    # ---- 大盘主线 ----
    ("算力", False, "工业富联", 186, -5, "large"),
    ("算力", False, "东山精密", 153,  1, "large"),
    ("算力", False, "光迅科技", 113,  9, "large"),
    ("算力", False, "华工科技", 109,  0, "large"),
    ("算力", False, "亨通光电", 106, -2, "large"),
    ("算力", False, "立讯精密", 105, -2, "large"),
    ("算力", False, "浪潮信息",  82, -4, "large"),
    ("算力", False, "天通股份",  80,  9, "large"),
    ("算力", False, "云南锗业",  73,  1, "large"),
    ("算力", False, "长飞光纤",  72, -4, "large"),
    ("算力", False, "烽火通信",  72, -9, "large"),
    ("算力", False, "中天科技",  70, -3, "large"),
    ("算力", False, "剑桥科技",  69,  3, "large"),
    ("算力", False, "紫光股份",  67, -1, "large"),
    ("算力", True,  "中际旭创", 183,  1, "large"),
    ("算力", True,  "新易盛",  160, -2, "large"),
    ("算力", True,  "胜宏科技", 107, -2, "large"),
    ("算力", True,  "协创数据",  76, -4, "large"),
    ("算力", True,  "天孚通信",  73, -1, "large"),
    ("芯片", False, "兆易创新", 185,  1, "large"),
    ("芯片", False, "德明利",   101,  0, "large"),
    ("芯片", False, "北方华创",  88,  5, "large"),
    ("芯片", False, "中国长城",  83, 10, "large"),
    ("芯片", False, "通富微电",  68,  5, "large"),
    ("芯片", True,  "江波龙",    76, -3, "large"),
    ("芯片", True,  "香农芯创",  68,  0, "large"),
    ("芯片", False, "寒武纪",   285, 20, "large"),
    ("芯片", False, "海光信息", 144,  6, "large"),
    ("芯片", False, "中芯国际", 119,  6, "large"),
    ("芯片", False, "芯原股份", 111, 20, "large"),
    ("芯片", False, "澜起科技", 102,  2, "large"),
    ("芯片", False, "中微公司",  71,  5, "large"),
    ("芯片", False, "佰维存储",  68, -1, "large"),
    ("锂电", False, "天赐材料", 109,  2, "large"),
    ("锂电", False, "天齐锂业", 103,  6, "large"),
    ("锂电", False, "赣锋锂业",  96,  2, "large"),
    ("锂电", True,  "宁德时代", 131, -1, "large"),
    ("锂电", True,  "天华新能",  77,  0, "large"),
]


# ---- 图 3：板块最强转债 ----
# (concept, cb_name, pct_chg, amount_yi)
CB_STRONGEST = [
    ("氢气",    "华特转债", -1, 63),
    ("锂电",    "万顺转2",   0, 30),
    ("锂电",    "大中转债",  0, 23),
    ("液冷",    "欧通转债",  6, 23),
    ("电力",    "晶科转债",  0, 17),
    ("算力租赁","盈峰转债", -6, 14),
]


async def resolve_ts_code(session, name: str, prefer_cb: bool = False) -> str | None:
    """股票名 → ts_code。优先级：完全匹配 > LIKE。"""
    name_clean = name.replace(" ", "")
    if prefer_cb:
        r = await session.execute(text(
            "SELECT ts_code FROM cb_basic "
            "WHERE bond_short_name=:n OR bond_short_name LIKE :nl "
            "LIMIT 1"
        ), {"n": name_clean, "nl": f"%{name_clean}%"})
        row = r.fetchone()
        if row:
            return row[0]
    r = await session.execute(text(
        "SELECT ts_code FROM stock_basic "
        "WHERE REPLACE(name,' ','')=:n AND list_status='L' LIMIT 1"
    ), {"n": name_clean})
    row = r.fetchone()
    if row:
        return row[0]
    # fallback like
    r = await session.execute(text(
        "SELECT ts_code FROM stock_basic "
        "WHERE REPLACE(name,' ','') LIKE :nl AND list_status='L' LIMIT 1"
    ), {"nl": f"%{name_clean}%"})
    row = r.fetchone()
    return row[0] if row else None


async def main():
    async with async_session() as s:
        # 清旧
        await s.execute(text(
            "DELETE FROM daily_sector_review WHERE trade_date=:d AND source='bankuai'"
        ), {"d": TRADE_DATE})

        n_daily = 0
        n_monthly = 0
        n_cb = 0
        unresolved = []

        # 先建 sector → rank/size 字典
        size_map = {sec: (size, rank) for sec, size, rank in DAILY_SECTOR_HEADER}

        # ---- 图 1 daily ----
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
                "(:td, 'bankuai', :sec, :rank, :size, :tc, :nm, :bc, :dtb, :lt, :main, :rm)"
            ), {
                "td": TRADE_DATE, "sec": sector, "rank": rank, "size": size,
                "tc": ts_code, "nm": name, "bc": board, "dtb": board,
                "lt": ftime, "main": True,
                "rm": json.dumps({"scope": "daily", "one_word": one_word}, ensure_ascii=False),
            })
            n_daily += 1

        # ---- 图 2 monthly ----
        for sector, is_core, name, mchg, tchg, tier in MONTHLY_MAIN_LINE:
            ts_code = await resolve_ts_code(s, name)
            if not ts_code:
                unresolved.append(("monthly", name))
            await s.execute(text(
                "INSERT INTO daily_sector_review "
                "(trade_date, source, sector_name, ts_code, stock_name, "
                " is_main_line, market_cap_tier, keywords, raw_meta) VALUES "
                "(:td, 'bankuai', :sec, :tc, :nm, true, :tier, :kw, :rm)"
            ), {
                "td": TRADE_DATE, "sec": sector, "tc": ts_code, "nm": name, "tier": tier,
                "kw": "核心" if is_core else None,
                "rm": json.dumps(
                    {"scope": "monthly", "month": "202604",
                     "monthly_chg_pct": mchg, "today_chg_pct": tchg, "is_core": is_core},
                    ensure_ascii=False),
            })
            n_monthly += 1

        # ---- 图 3 cb_strongest ----
        for concept, cb_name, chg, amt in CB_STRONGEST:
            ts_code = await resolve_ts_code(s, cb_name, prefer_cb=True)
            if not ts_code:
                unresolved.append(("cb", cb_name))
            await s.execute(text(
                "INSERT INTO daily_sector_review "
                "(trade_date, source, sector_name, ts_code, stock_name, amount, "
                " is_main_line, raw_meta) VALUES "
                "(:td, 'bankuai', :sec, :tc, :nm, :amt, true, :rm)"
            ), {
                "td": TRADE_DATE, "sec": concept, "tc": ts_code, "nm": cb_name, "amt": amt,
                "rm": json.dumps({"scope": "cb_strongest", "pct_chg": chg}, ensure_ascii=False),
            })
            n_cb += 1

        await s.commit()

    print(f"daily 入库: {n_daily} 行")
    print(f"monthly 入库: {n_monthly} 行")
    print(f"cb_strongest 入库: {n_cb} 行")
    if unresolved:
        print(f"\n未匹配 ts_code 的 {len(unresolved)} 条:")
        for scope, nm in unresolved:
            print(f"  [{scope}] {nm}")


if __name__ == "__main__":
    asyncio.run(main())
