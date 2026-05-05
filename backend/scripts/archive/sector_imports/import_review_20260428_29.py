"""一次性导入：4/28 韭研全天复盘 + 4/29 板块必读连板天梯/月度主线/最强转债。

数据由对话内 Claude 多模态 OCR 后手工编码。
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from sqlalchemy import text


# =====================================================================
# 4/28 韭研公社全天复盘简图
# =====================================================================
JIUYAN_4_28_SECTORS = [
    ("国产芯片", 7, 1),
    ("算力", 6, 2),
    ("氢气", 4, 3),
    ("电池产业链", 2, 4),
    ("公告", 31, 5),  # 一季报相关，非游资题材
    ("其他", 9, 6),
]

# board, days_to_board, sector, ts_code, name, time, float_mv_yi, amount_yi, keywords
JIUYAN_4_28 = [
    # 国产芯片*7
    (6, 8, "国产芯片", "002081.SZ", "金螳螂",   "14:48:36", 128.8, 22.2, "半导体洁净室(苏州)+建筑装饰+商业航天+传闻签订大单"),
    (3, 4, "国产芯片", "600770.SH", "综艺股份", "9:57:27",   99.6, 13.7, "参股CPU+一季报业绩扭亏+半导体+集成电路"),
    (2, 2, "国产芯片", "603931.SH", "格林达",   "9:51:31",   75.7,  6.9, "光刻胶用显影液/剥离液+OLED"),
    (1, 1, "国产芯片", "003026.SZ", "中晶科技", "10:00:06",  43.3,  6.6, "半导体硅片+半导体功率芯片"),
    (1, 1, "国产芯片", "002647.SZ", "仁东控股", "10:05:51", 130.8, 10.9, "参股江原科技+摘帽+第三方支付+重整完毕+跨境支付"),
    (1, 1, "国产芯片", "002652.SZ", "扬子新材", "13:03:30",  28.8,  2.2, "半导体洁净室+航空航天+医疗器械+无人机+环保建材"),
    (1, 1, "国产芯片", "002989.SZ", "中天精装", "14:43:15",  48.2,  2.2, "芯片ABF载板+精装修+并购重组猜想"),
    # 算力*6
    (2, 2, "算力", "603095.SH", "越剑智能", "9:32:46",   54.1,  1.7, "AI智能验布机+机器人+合作华为+人工智能"),
    (2, 2, "算力", "002902.SZ", "铭普光磁", "9:35:42",   55.9,  9.9, "AI算力+光模块+业绩显著改善+合作英诺赛科+英伟达"),
    (2, 3, "算力", "000889.SZ", "中嘉博创", "14:24:30",  42.7, 11.8, "算力+借壳传闻+AI应用+字节+移动通信"),
    (1, 1, "算力", "605168.SH", "三人行",   "10:58:35",  92.9,  6.1, "算力+年报增长+股权转让+AI营销+数据要素"),
    (1, 1, "算力", "002575.SZ", "群兴玩具", "11:00:24",  39.7,  5.9, "算力+OpenClaw(微信)+合作中昊芯英+探索合作机器人+玩具"),
    (1, 1, "算力", "002733.SZ", "雄韬股份", "14:39:00", 118.6, 13.7, "数据中心备电+固态电池+氢燃料电池+空气电池"),
    # 氢气*4
    (6, 7, "氢气", "603318.SH", "水发燃气", "13:05:00",  63.3, 18.8, "氢气涨价+燃气轮机+天然气+LNG业务+城镇燃气"),
    (1, 1, "氢气", "600379.SH", "宝光股份", "13:13:43",  45.8,  3.2, "氢气+半导体+储能调频+真空集热管+氢能源"),
    (1, 1, "氢气", "300540.SZ", "蜀道装备", "13:20:48",  74.7, 12.8, "高纯氢气+商业航天(四川)+氢能产业+天然气液化"),
    (1, 1, "氢气", "600248.SH", "陕建股份", "13:49:04", 137.1,  3.5, "氢气+建筑工程+一带一路+石油化工"),
    # 电池产业链*2
    (3, 3, "电池产业链", "600152.SH", "维科技术", "9:40:37", 83.0, 11.5, "钠电池+投资电池项目+储能+定增+华为"),
    (1, 1, "电池产业链", "300905.SZ", "宝丽迪",   "9:30:00", 93.6,  5.2, "COFs材料+固态电池+一季报增长+光刻胶"),
    # 公告*31（业绩相关，非游资题材，部分入库）
    (4, 4, "公告", "600726.SH", "华电能源", "14:10:47", 524.8, 36.8, "一季报增长+绿色电力+央企+煤炭"),
    (3, 4, "公告", "000593.SZ", "德龙汇能", "11:20:51",  91.2, 13.2, "净利润增长+实控人变更+科恩斯半导体+天然气+集成电路"),
    (2, 2, "公告", "002210.SZ", "飞马国际", "9:42:33",   79.9,  4.9, "一季报增长+物流(深圳)+马字辈+控股股东拟变更+环保"),
    (2, 2, "公告", "002175.SZ", "东方智造", "9:54:45",   36.9,  3.5, "退市博弈+广西国资委入主+数显量具量仪+智能快递分拣设备+芯片"),
    (2, 2, "公告", "605289.SH", "罗曼股份", "10:35:55", 169.6, 13.7, "一季报增长+AI算力+液冷+入股东方天算"),
    (2, 3, "公告", "002313.SZ", "日海智能", "9:49:57",   37.9,  3.5, "业绩增长+高算力AI模组+eSIM模组+RWA"),
    # 其他*9 + 其他公告首板（部分跳过，仅入库高板和重要票）
    (4, 4, "其他", "601101.SH", "昊华能源", "14:15:29", 156.7,  7.0, "业绩增长+煤炭+北京国资+甲醇"),
    (2, 2, "其他", "605287.SH", "德才股份", "11:01:50",  75.9,  8.4, "AI漫剧+智算+城市更新+VR"),
]


# =====================================================================
# 4/29 板块必读 - 连板天梯（daily 主线）
# =====================================================================
BANKUAI_4_29_HEADER = [
    ("一季报预增", 62, 1),
    ("电池产业链", 10, 2),
    ("算力", 7, 3),
    ("PCB板", 4, 4),
    ("稀土", 3, 5),
    ("钨", 3, 6),
    ("洁净室", 2, 7),
    ("氢气", 2, 8),
    ("机器人", 1, 9),
]

# board, sector, name, time, one_word
BANKUAI_4_29_LADDER = [
    # 3板
    (3, "一季报预增", "飞马国际", "9:32",  False),
    (3, "PCB板",     "越剑智能", "13:17", False),
    # 2板
    (2, "一季报预增", "宏英智能", "9:33",  True),
    (2, "一季报预增", "利通电子", "9:33",  False),
    (2, "一季报预增", "华升股份", "9:34",  False),
    (2, "一季报预增", "天味食品", "9:50",  False),
    (2, "一季报预增", "永杉锂业", "9:59",  False),
    (2, "算力",       "三人行",   "14:37", False),
    (2, "洁净室",     "扬子新材", "9:33",  False),
    (2, "洁净室",     "金螳螂",   "9:49",  False),
    (2, "氢气",       "宝光股份", "13:59", False),
    # 首板 (89) - 分行入库主要的
    (1, "一季报预增", "金融街",   "9:30",  True),
    (1, "一季报预增", "光莆股份", "9:32",  True),
    (1, "一季报预增", "日联科技", "9:33",  True),
    (1, "一季报预增", "天娱数科", "9:30",  False),
    (1, "一季报预增", "瑞斯康达", "9:32",  False),
    (1, "一季报预增", "游族网络", "9:33",  False),
    (1, "一季报预增", "创元科技", "9:33",  False),
    (1, "一季报预增", "惠天热电", "9:34",  False),
    (1, "一季报预增", "绿地控股", "9:34",  False),
    (1, "一季报预增", "睿能科技", "9:35",  False),
    (1, "一季报预增", "威海广泰", "9:35",  False),
    (1, "一季报预增", "日发精机", "9:35",  False),
    (1, "一季报预增", "众泰汽车", "9:36",  False),
    (1, "一季报预增", "周大生",   "9:37",  False),
    (1, "一季报预增", "百润股份", "9:38",  False),
    (1, "一季报预增", "苏州固锝", "9:38",  False),
    (1, "一季报预增", "海德股份", "9:40",  False),
    (1, "一季报预增", "淳中科技", "9:40",  False),
    (1, "一季报预增", "亚普股份", "9:40",  False),
    (1, "一季报预增", "丽岛新材", "9:43",  False),
    (1, "一季报预增", "中安科",   "9:44",  False),
    (1, "一季报预增", "共创草坪", "9:43",  False),
    (1, "一季报预增", "金瑞矿业", "9:45",  False),
    (1, "一季报预增", "银宝山新", "9:45",  False),
    (1, "一季报预增", "盐津铺子", "9:52",  False),
    (1, "一季报预增", "金新农",   "9:57",  False),
    (1, "一季报预增", "富森美",   "9:59",  False),
    (1, "一季报预增", "丰元股份", "9:59",  False),
    (1, "一季报预增", "航天科技", "10:05", False),
    (1, "一季报预增", "黑芝麻",   "10:05", False),
    (1, "一季报预增", "XD舒华体", "10:08", False),
    (1, "一季报预增", "卓郎智能", "10:09", False),
    (1, "一季报预增", "北方稀土", "10:16", False),
    (1, "一季报预增", "汉缆股份", "10:20", False),
    (1, "一季报预增", "嘉美包装", "10:20", False),
    (1, "一季报预增", "麦格米特", "10:21", False),
    (1, "一季报预增", "亚泰集团", "10:29", False),
    (1, "一季报预增", "乐凯胶片", "10:31", False),
    (1, "一季报预增", "航锦科技", "10:36", False),
    (1, "一季报预增", "翔鹭钨业", "10:48", False),
    (1, "一季报预增", "德方纳米", "10:52", False),
    (1, "一季报预增", "八方股份", "10:58", False),
    (1, "一季报预增", "剑桥科技", "11:02", False),
    (1, "一季报预增", "浙江众成", "13:02", False),
    (1, "一季报预增", "鹏辉能源", "13:10", False),
    (1, "一季报预增", "西麦食品", "13:17", False),
    (1, "一季报预增", "佛塑科技", "13:28", False),
    (1, "一季报预增", "比音勒芬", "13:31", False),
    (1, "一季报预增", "安井食品", "13:39", False),
    (1, "一季报预增", "楚环科技", "13:40", False),
    (1, "一季报预增", "石大胜华", "13:41", False),
    (1, "一季报预增", "桐昆股份", "13:53", False),
    (1, "一季报预增", "思维列控", "14:02", False),
    (1, "一季报预增", "安奈儿",   "14:12", False),
    (1, "一季报预增", "誉帆科技", "14:17", False),
    (1, "一季报预增", "共达电声", "13:13", False),
    (1, "电池产业链", "永兴材料", "13:39", False),
    (1, "电池产业链", "龙蟠科技", "13:41", False),
    (1, "电池产业链", "红星发展", "13:51", False),
    (1, "电池产业链", "雅化集团", "14:02", False),
    (1, "电池产业链", "天赐材料", "14:51", False),
    (1, "电池产业链", "西藏珠峰", "13:41", False),
    (1, "电池产业链", "融捷股份", "9:59",  False),
    (1, "电池产业链", "大中矿业", "11:06", False),
    (1, "电池产业链", "安纳达",   "13:43", False),
    (1, "电池产业链", "江特电机", "13:57", False),
    (1, "算力", "莲花控股", "14:53", False),
    (1, "算力", "沃格光电", "14:40", False),
    (1, "算力", "鸿仕达",   "9:38",  False),
    (1, "算力", "康惠股份", "9:44",  False),
    (1, "算力", "高乐股份", "14:13", False),
    (1, "算力", "泰晶科技", "10:22", False),
    (1, "PCB板", "山东玻纤", "11:01", False),
    (1, "PCB板", "宏和科技", "13:31", False),
    (1, "PCB板", "铜冠铜箔", "11:19", False),
    (1, "稀土", "华宏科技", "13:04", False),
    (1, "稀土", "中国稀土", "10:40", False),
    (1, "稀土", "盛和资源", "14:21", False),
    (1, "钨",   "江钨装备", "13:48", False),
    (1, "钨",   "中钨高新", "11:28", False),
    (1, "钨",   "章源钨业", "10:01", False),
    (1, "氢气", "中集集团", "10:22", False),
    (1, "机器人", "宇环数控", "13:05", False),
    (1, "反弹",   "中衡设计", "13:06", False),
    (1, "反弹",   "三峡旅游", "13:35", False),
    (1, "反弹",   "苏文电能", "14:43", False),
    (1, "反弹",   "光明地产", "13:13", False),
    (1, "反弹",   "和顺石油", "13:06", False),
    (1, "反弹",   "华达新材", "13:35", False),
]


# =====================================================================
# 4/29 板块必读 - 月度主线（小盘 / 大盘）
# =====================================================================
# (sector, is_core, name, monthly_chg, today_chg, market_cap_tier)
BANKUAI_4_29_MONTHLY = [
    # ---- 小盘 ----
    ("算力", False, "沃格光电", 113, 10, "small"),
    ("算力", False, "博云新材", 112,  3, "small"),
    ("算力", False, "利通电子", 104, 10, "small"),
    ("算力", False, "华盛昌",    93, -4, "small"),
    ("算力", False, "金富科技",  89,  0, "small"),
    ("算力", False, "东山精密",  78,  0, "small"),
    ("算力", False, "宏和科技",  72, 10, "small"),
    ("算力", False, "大族激光",  69, -2, "small"),
    ("算力", False, "剑桥科技",  68, 10, "small"),
    ("算力", False, "盈峰环境",  66,  0, "small"),
    ("算力", False, "中瓷电子",  65, -3, "small"),
    ("算力", False, "天通股份",  64, -3, "small"),
    ("算力", True,  "宏景科技", 114, -3, "small"),
    ("算力", True,  "铜冠铜箔",  89, 20, "small"),
    ("算力", True,  "奥尼电子",  74,  4, "small"),
    ("算力", True,  "行云科技",  70, 20, "small"),
    ("算力", False, "优利德",   132, -3, "small"),
    ("算力", False, "品高股份", 122,  5, "small"),
    ("算力", False, "海泰新光", 103, -10, "small"),
    ("算力", False, "盛科通信-U", 97, 15, "small"),
    ("算力", False, "鼎通科技",  74, -2, "small"),
    ("算力", False, "优迅股份",  74, -3, "small"),
    ("算力", False, "长光华芯",  70, -4, "small"),
    ("芯片", False, "盛视科技",  67,  0, "small"),
    ("芯片", False, "科瑞技术",  66, -1, "small"),
    ("芯片", True,  "斯迪克",    75,  2, "small"),
    ("芯片", True,  "蜀道装备",  72, -6, "small"),
    ("芯片", True,  "凌玮科技",  70, -2, "small"),
    ("芯片", True,  "唯特偶",    70,  4, "small"),
    ("芯片", False, "九州一轨", 119, 12, "small"),
    ("芯片", False, "华特气体", 109, -9, "small"),
    ("芯片", False, "华兴源创",  82, -7, "small"),
    ("芯片", False, "锴威特",    80, -3, "small"),
    ("芯片", False, "中船特气",  79,  3, "small"),
    ("芯片", False, "欧莱新材",  72, -9, "small"),
    # ---- 大盘 ----
    ("算力", False, "工业富联", 185, -3, "large"),
    ("算力", False, "东山精密", 167,  0, "large"),
    ("算力", False, "立讯精密", 143, -2, "large"),
    ("算力", False, "华工科技",  99,  3, "large"),
    ("算力", False, "紫光股份",  83,  3, "large"),
    ("算力", False, "亨通光电",  83, -1, "large"),
    ("算力", False, "光迅科技",  75, -3, "large"),
    ("算力", False, "永鼎股份",  73, -3, "large"),
    ("算力", False, "中国巨石",  63,  3, "large"),
    ("算力", False, "中天科技",  61, -2, "large"),
    ("算力", False, "生益科技",  58,  2, "large"),
    ("算力", True,  "中际旭创", 212,  3, "large"),
    ("算力", True,  "胜宏科技", 205,  7, "large"),
    ("算力", True,  "新易盛",   148,  0, "large"),
    ("算力", True,  "协创数据",  95,  4, "large"),
    ("算力", True,  "天孚通信",  79,  0, "large"),
    ("算力", False, "源杰科技",  58,  5, "large"),
    ("算力", False, "长光华芯",  56, -4, "large"),
    ("芯片", False, "兆易创新", 128,  0, "large"),
    ("芯片", False, "德明利",    89,  5, "large"),
    ("芯片", False, "中国长城",  62,  1, "large"),
    ("芯片", True,  "江波龙",    92,  9, "large"),
    ("芯片", True,  "香农芯创",  85,  2, "large"),
    ("芯片", False, "寒武纪",   127,  3, "large"),
    ("芯片", False, "海光信息",  99, -4, "large"),
    ("芯片", False, "澜起科技",  87, -2, "large"),
    ("芯片", False, "佰维存储",  80,  3, "large"),
    ("芯片", False, "中芯国际",  58, -1, "large"),
    ("锂电", False, "比亚迪",   110,  4, "large"),
    ("锂电", False, "天赐材料", 103, 10, "large"),
    ("锂电", False, "天齐锂业",  87,  4, "large"),
    ("锂电", False, "赣锋锂业",  72,  6, "large"),
    ("锂电", True,  "宁德时代", 165,  4, "large"),
    ("锂电", True,  "天华新能",  99, 19, "large"),
    ("锂电", True,  "亿纬锂能",  69,  5, "large"),
]


# =====================================================================
# 4/29 板块必读 - 板块最强转债
# =====================================================================
# (concept, cb_name, pct_chg, amount_yi, premium_rate)
BANKUAI_4_29_CB = [
    ("鑫多多",     "Z美诺转",   7,   59, None),
    ("氢气",       "华特转债",  -9,  45, None),
    ("锂矿",       "大中转债",  8,   43, None),
    ("算力租赁",   "盈峰转债",  -3,  33, None),
]


async def resolve_ts_code(session, name: str, prefer_cb: bool = False) -> str | None:
    name_clean = name.replace(" ", "").replace("XD", "")
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


async def import_jiuyan_4_28(session) -> tuple[int, list]:
    await session.execute(text(
        "DELETE FROM daily_sector_review WHERE trade_date='20260428' AND source='jiuyan'"
    ))
    size_map = {sec: (size, rank) for sec, size, rank in JIUYAN_4_28_SECTORS}
    n = 0
    unresolved = []
    for board, dtb, sector, ts_code_known, name, ftime, mv_yi, amt_yi, kw in JIUYAN_4_28:
        ts_code = ts_code_known
        if not ts_code:
            ts_code = await resolve_ts_code(session, name)
        if not ts_code:
            unresolved.append(("jiuyan_4_28", name))
        size, rank = size_map.get(sector, (None, None))
        await session.execute(text(
            "INSERT INTO daily_sector_review "
            "(trade_date, source, sector_name, sector_rank, sector_size, "
            " ts_code, stock_name, board_count, days_to_board, limit_time, "
            " float_mv, amount, keywords, is_main_line, raw_meta) VALUES "
            "('20260428','jiuyan',:sec,:rank,:size,:tc,:nm,:bc,:dtb,:lt,:fmv,:amt,:kw,true,:rm)"
        ), {
            "sec": sector, "rank": rank, "size": size,
            "tc": ts_code, "nm": name, "bc": board, "dtb": dtb, "lt": ftime,
            "fmv": mv_yi * 1e8 if mv_yi else None,
            "amt": amt_yi * 1e8 if amt_yi else None,
            "kw": kw,
            "rm": json.dumps({"scope": "daily"}, ensure_ascii=False),
        })
        n += 1
    return n, unresolved


async def import_bankuai_4_29(session) -> tuple[int, int, int, list]:
    await session.execute(text(
        "DELETE FROM daily_sector_review WHERE trade_date='20260429' AND source='bankuai'"
    ))
    size_map = {sec: (size, rank) for sec, size, rank in BANKUAI_4_29_HEADER}
    unresolved = []

    n_d = 0
    for board, sector, name, ftime, one_word in BANKUAI_4_29_LADDER:
        ts_code = await resolve_ts_code(session, name)
        if not ts_code:
            unresolved.append(("bk_4_29_daily", name))
        size, rank = size_map.get(sector, (None, None))
        await session.execute(text(
            "INSERT INTO daily_sector_review "
            "(trade_date, source, sector_name, sector_rank, sector_size, "
            " ts_code, stock_name, board_count, days_to_board, limit_time, "
            " is_main_line, raw_meta) VALUES "
            "('20260429','bankuai',:sec,:rank,:size,:tc,:nm,:bc,:dtb,:lt,true,:rm)"
        ), {
            "sec": sector, "rank": rank, "size": size,
            "tc": ts_code, "nm": name, "bc": board, "dtb": board, "lt": ftime,
            "rm": json.dumps({"scope": "daily", "one_word": one_word}, ensure_ascii=False),
        })
        n_d += 1

    n_m = 0
    for sector, is_core, name, mchg, tchg, tier in BANKUAI_4_29_MONTHLY:
        ts_code = await resolve_ts_code(session, name)
        if not ts_code:
            unresolved.append(("bk_4_29_monthly", name))
        await session.execute(text(
            "INSERT INTO daily_sector_review "
            "(trade_date, source, sector_name, ts_code, stock_name, "
            " is_main_line, market_cap_tier, keywords, raw_meta) VALUES "
            "('20260429','bankuai',:sec,:tc,:nm,true,:tier,:kw,:rm)"
        ), {
            "sec": sector, "tc": ts_code, "nm": name, "tier": tier,
            "kw": "核心" if is_core else None,
            "rm": json.dumps({
                "scope": "monthly", "month": "202604",
                "monthly_chg_pct": mchg, "today_chg_pct": tchg, "is_core": is_core,
            }, ensure_ascii=False),
        })
        n_m += 1

    n_c = 0
    for concept, cb_name, chg, amt, prem in BANKUAI_4_29_CB:
        ts_code = await resolve_ts_code(session, cb_name, prefer_cb=True)
        if not ts_code:
            unresolved.append(("bk_4_29_cb", cb_name))
        await session.execute(text(
            "INSERT INTO daily_sector_review "
            "(trade_date, source, sector_name, ts_code, stock_name, amount, "
            " is_main_line, raw_meta) VALUES "
            "('20260429','bankuai',:sec,:tc,:nm,:amt,true,:rm)"
        ), {
            "sec": concept, "tc": ts_code, "nm": cb_name, "amt": amt,
            "rm": json.dumps({"scope": "cb_strongest", "pct_chg": chg, "premium": prem}, ensure_ascii=False),
        })
        n_c += 1

    return n_d, n_m, n_c, unresolved


async def main():
    async with async_session() as s:
        n_jy, unr_jy = await import_jiuyan_4_28(s)
        n_d, n_m, n_c, unr_bk = await import_bankuai_4_29(s)
        await s.commit()

    print(f"4/28 韭研: {n_jy} 行")
    print(f"4/29 板块必读 daily: {n_d} 行 / monthly: {n_m} 行 / cb: {n_c} 行")
    all_unr = unr_jy + unr_bk
    if all_unr:
        print(f"\n未匹配 ts_code {len(all_unr)} 条:")
        for src, nm in all_unr:
            print(f"  [{src}] {nm}")


if __name__ == "__main__":
    asyncio.run(main())
