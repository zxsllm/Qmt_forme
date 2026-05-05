"""补入第三轮：
- 4/28 板块必读月度主线（图 21）
- 4/28 板块必读最强转债（图 22）
- 4/30 韭研全天复盘简图（图 23）
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from sqlalchemy import text


# =====================================================================
# 4/28 月度主线（图 21）
# =====================================================================
# (sector, is_core, name, monthly_chg, today_chg, market_cap_tier)
BANKUAI_4_28_MONTHLY = [
    # 小盘
    ("算力", False, "博云新材",  107, 10, "small"),
    ("算力", False, "华盛昌",    102,  5, "small"),
    ("算力", False, "沃格光电",   94, -1, "small"),
    ("算力", False, "金富科技",   90, -1, "small"),
    ("算力", False, "利通电子",   86, 10, "small"),
    ("算力", False, "东山精密",   78, -2, "small"),
    ("算力", False, "大族激光",   72,  1, "small"),
    ("算力", False, "中瓷电子",   70,  0, "small"),
    ("算力", False, "天通股份",   69, -4, "small"),
    ("算力", False, "圣阳股份",   68,  2, "small"),
    ("算力", False, "盈峰环境",   67, 10, "small"),
    ("算力", False, "罗曼股份",   65, 10, "small"),
    ("算力", False, "博杰股份",   63, -2, "small"),
    ("算力", False, "光迅科技",   63,  2, "small"),
    ("算力", False, "永鼎股份",   62, -8, "small"),
    ("算力", True,  "宏景科技",  119,  7, "small"),
    ("算力", True,  "奥尼电子",   67, -1, "small"),
    ("算力", False, "优利德",    139, -4, "small"),
    ("算力", False, "海泰新光",  124,  3, "small"),
    ("算力", False, "品高股份",  111,  5, "small"),
    ("算力", False, "优迅股份",   80, -1, "small"),
    ("算力", False, "鼎通科技",   77, -5, "small"),
    ("算力", False, "长光华芯",   77, -4, "small"),
    ("算力", False, "盛科通信-U", 71, -4, "small"),
    ("算力", False, "仕佳光子",   61, -8, "small"),
    ("芯片", False, "盛视科技",   68,  1, "small"),
    ("芯片", False, "科瑞技术",   66, -3, "small"),
    ("芯片", True,  "蜀道装备",   83, 20, "small"),
    ("芯片", True,  "凌玮科技",   74, -2, "small"),
    ("芯片", True,  "斯迪克",     71,  2, "small"),
    ("芯片", True,  "唯特偶",     64, -12, "small"),
    ("芯片", False, "华特气体",  129, 14, "small"),
    ("芯片", False, "九州一轨",   96,  1, "small"),
    ("芯片", False, "华兴源创",   94, -3, "small"),
    ("芯片", False, "欧莱新材",   88, 18, "small"),
    ("芯片", False, "锴威特",     86, -4, "small"),
    ("芯片", False, "中船特气",   74,  4, "small"),
    ("芯片", False, "和林微纳",   62,  4, "small"),
    # 大盘
    ("算力", False, "工业富联",  161,  1, "large"),
    ("算力", False, "立讯精密",  152, -3, "large"),
    ("算力", False, "东山精密",  146, -2, "large"),
    ("算力", False, "亨通光电",  121, -4, "large"),
    ("算力", False, "中天科技",   93, -2, "large"),
    ("算力", False, "永鼎股份",   91, -8, "large"),
    ("算力", False, "光迅科技",   87,  2, "large"),
    ("算力", False, "华工科技",   76, -3, "large"),
    ("算力", False, "拓维信息",   72, -9, "large"),
    ("算力", False, "天通股份",   67, -4, "large"),
    ("算力", False, "剑桥科技",   65,  1, "large"),
    ("算力", False, "烽火通信",   63,  1, "large"),
    ("算力", False, "云南锗业",   62, -4, "large"),
    ("算力", False, "大族激光",   61,  1, "large"),
    ("算力", False, "中科曙光",   58, -4, "large"),
    ("算力", True,  "中际旭创", 245, -4, "large"),
    ("算力", True,  "新易盛",   190,  0, "large"),
    ("算力", True,  "天孚通信", 108, -4, "large"),
    ("算力", True,  "协创数据", 104,  1, "large"),
    ("算力", True,  "胜宏科技",  89, -1, "large"),
    ("算力", False, "源杰科技",   64,  2, "large"),
    ("算力", False, "仕佳光子",   63, -8, "large"),
    ("算力", False, "长光华芯",   60, -5, "large"),
    ("芯片", False, "兆易创新", 114,  1, "large"),
    ("芯片", False, "中国长城",   76,  6, "large"),
    ("芯片", False, "北方华创",   72,  0, "large"),
    ("芯片", False, "德明利",     66,  2, "large"),
    ("芯片", False, "通富微电",   59, -2, "large"),
    ("芯片", True,  "江波龙",   104, -3, "large"),
    ("芯片", True,  "香农芯创",   92,  0, "large"),
    ("芯片", True,  "长川科技",   71,  2, "large"),
    ("芯片", False, "澜起科技", 121, -3, "large"),
    ("芯片", False, "寒武纪",   104,  1, "large"),
    ("芯片", False, "海光信息",   93, -2, "large"),
    ("芯片", False, "中微公司",   78,  3, "large"),
    ("芯片", False, "佰维存储",   75, -1, "large"),
    ("芯片", False, "中芯国际",   72, -3, "large"),
    ("锂电", False, "天赐材料",   89,  0, "large"),
]

# =====================================================================
# 4/28 板块最强转债（图 22）
# =====================================================================
# (concept, cb_name, pct_chg, amount_yi)
BANKUAI_4_28_CB = [
    ("氢气",      "华特转债",   16, 106),
    ("鑫多多",    "美诺转债",    6,  77),
    ("算力租赁",  "盈峰转债",   13,  48),
    ("电池",      "瑞丰转债",    7,  34),
    ("电力",      "晶科转债",   -2,  28),
    ("光模块设备","华兴转债",    1,  20),
]

# =====================================================================
# 4/30 韭研全天复盘（图 23）
# =====================================================================
JIUYAN_4_30_SECTORS = [
    ("国产芯片",   9, 1),
    ("电池产业链", 7, 2),
    ("机器人",     6, 3),
    ("算力",       5, 4),
    ("商业航天",   5, 5),
    ("体育产业",   4, 6),
    ("公告",      36, 7),
    ("其他",       7, 8),
]

# board, days_to_board, sector, ts_code, name, time, float_mv_yi, amount_yi, keywords
JIUYAN_4_30 = [
    # 国产芯片*9
    (8, 10, "国产芯片", "002081.SZ", "金螳螂",   "13:34:42",  156.0, 32.2, "半导体洁净室(苏州)+建筑装饰+商业航天+传闻签订大单"),
    (3, 3,  "国产芯片", "002989.SZ", "中天精装", "13:27:15",   53.6,  2.6, "芯片ABF载板+芯片封测+精装修+并购重组猜想"),
    (2, 4,  "国产芯片", "600246.SH", "万通发展", "13:12:26",  213.2, 18.1, "PCIe5.0交换芯片+合作阿里+一季报大涨+房地产"),
    (1, 1,  "国产芯片", "000066.SZ", "中国长城", "10:16:27",  639.3, 83.2, "国产CPU+OpenClaw+商业航天+AI服务器+液冷"),
    (1, 1,  "国产芯片", "000628.SZ", "高新发展", "10:51:45",  127.2, 11.7, "华擎振宇收购预期+数字半导体+华为CANN+成都国资"),
    (1, 1,  "国产芯片", "002158.SZ", "汉钟精机", "13:32:36",  147.3,  4.5, "半导体真空产品+数据中心备电+光伏+压缩机"),
    (1, 1,  "国产芯片", "688256.SH", "寒武纪",   "13:44:38", 7168.5, 284.7, "国产算力芯片(支持FP8精度)+一季报大增+大模型"),
    (1, 1,  "国产芯片", "002685.SZ", "华东重机", "14:15:03",   92.2, 12.2, "控股国产GPU公司+一季报增长+机器人+TOPCon电池片"),
    (1, 1,  "国产芯片", "603687.SH", "大胜达",   "14:25:33",   94.5, 11.5, "5.5亿投资GPU公司+AI芯片+AI应用+卡游"),
    # 电池产业链*7
    (3, 3, "电池产业链", "603399.SH", "永杉锂业", "9:25:00",    99.3,  1.7, "锂矿+一季度业绩扭亏"),
    (3, 5, "电池产业链", "002192.SZ", "融捷股份", "10:49:18",  283.0, 36.5, "锂矿+一季报增长+拟投建锂电池负极材料项目+锂电正极材料"),
    (2, 2, "电池产业链", "002805.SZ", "丰元股份", "9:30:09",    45.0,  1.1, "磷酸铁锂+一季报扭亏+固态电池+储能+草酸"),
    (2, 4, "电池产业链", "002785.SZ", "万里石",   "14:42:45",   45.0,  1.8, "电池级碳酸锂+核电+铟铅多金属矿+合作中国铀业+资产注入预期"),
    (1, 5, "电池产业链", "002240.SZ", "盛新锂能", "14:30:09",  548.6, 52.4, "锂矿+固态电池+拟定增+林木"),
    (1, 1, "电池产业链", "600052.SH", "东望时代", "9:54:29",    37.5,  2.7, "锂电池+收购调整+文化传媒+节能服务"),
    (1, 1, "电池产业链", "000833.SZ", "粤桂股份", "13:41:42",  143.9, 19.7, "固态电池上游+一季报增长+硫铁矿+磷肥"),
    # 机器人*6
    (2, 4, "机器人", "600400.SH", "红豆股份", "14:34:54",   63.2,  5.1, "投资养老机器人+被动减持完毕+固态电池(已转出)+服饰+低价股"),
    (1, 1, "机器人", "603178.SH", "圣龙股份", "10:02:05",   46.0,  4.6, "机器人+一季报扭亏+供货赛力斯+制动真空泵+5G汽车"),
    (1, 1, "机器人", "300885.SZ", "海昌新材", "10:35:54",   47.8,  7.5, "人形机器人+一季报增长+卫星通信+粉末冶金齿轮箱(灵巧手)"),
    (1, 1, "机器人", "688400.SH", "凌云光",   "13:12:08",  273.5,  2.7, "合作宇树+一季报大增+智谱AI+AI视觉"),
    (1, 1, "机器人", "002870.SZ", "香山股份", "13:18:21",   50.6,  4.1, "定增获批+人形机器人+比亚迪+智能座舱"),
    (1, 1, "机器人", "603897.SH", "长城科技", "13:20:00",  108.1,  5.5, "人形机器人(线束)+电磁线+比亚迪+新能源车用扁线"),
    # 算力*5
    (4, 4, "算力", "603095.SH", "越剑智能", "9:25:00",    65.5,  1.0, "AI智能验布机+机器人+合作华为+人工智能"),
    (3, 5, "算力", "002990.SZ", "盛视科技", "9:42:06",    74.3,  6.2, "拟采购IT设备及零部件+算力一体芯片+一季报增长+智慧口岸"),
    (1, 1, "算力", "688521.SH", "芯原股份", "11:09:04", 1477.2, 111.2, "AI算力+一季度营收增长+芯片IP+RISC-V+先进封装"),
    (1, 1, "算力", "605376.SH", "博迁新材", "13:49:51",  344.2, 21.3, "AI服务器(MLCC)+一季报增长+光伏替银+固态电池+硅碳负极上游"),
    (1, 1, "算力", "002929.SZ", "润建股份", "14:40:15",  126.5, 17.6, "数据中心(阿里)+机器人+AI智能体"),
    # 商业航天*5
    (1, 1, "商业航天", "603131.SH", "上海沪工", "10:29:26",   75.9,  3.2, "商业卫星+一季报增长+航天军工+机器人成套设备"),
    (1, 1, "商业航天", "002149.SZ", "西部材料", "10:57:27",  310.0, 46.8, "商业航天+网传SpaceX铅合金供应商+钛合金+核电"),
    (1, 1, "商业航天", "603698.SH", "航天工程", "13:25:33",  235.7, 20.8, "航天一院+一季报增长+航天粉煤+氢能+军工"),
    (1, 1, "商业航天", "605222.SH", "起帆电缆", "13:41:13",  256.0,  7.3, "航空电缆+商业航天+风电(海缆)+电力网设备+特种电缆"),
    (1, 1, "商业航天", "001268.SZ", "联合精密", "13:50:00",   25.9,  1.8, "收购迈特航空+猜测引接供货英伟达+军工+美的机器人"),
    # 体育产业*4
    (2, 2, "体育产业", "605299.SH", "舒华体育", "9:39:23",   106.3,  5.9, "足球+一季报增长+体育产业+AI健身助手+华为合作+跨境电商"),
    (2, 2, "体育产业", "605099.SH", "共创草坪", "9:50:54",   194.4,  6.2, "足球草坪+一季报增长+人造草坪龙头+外销"),
    (4, 5, "体育产业", "002181.SZ", "粤传媒",   "9:52:45",   187.1,   12, "足球媒体+AI营销+短剧+广州国资"),
    (1, 1, "体育产业", "002235.SZ", "安妮股份", "13:25:18",   62.0, 11.7, "体育+彩票+AI版权+控制权变更获深交所确认+文化传媒"),
    # 公告*36 仅入高板代表
    (3, 5, "公告", "603937.SH", "丽岛新材", "13:07:42",   31.9,  3.6, "一季报扭亏+电池铝箔+功能型铝材(建筑)+电池集流体"),
    (2, 2, "公告", "300632.SZ", "光莆股份", "9:30:00",    54.1,    9, "拟开发光引擎产品+复合集流体+Mini LED+整形美容"),
    # 其他*7 高板
    (3, 3, "其他", "600379.SH", "宝光股份", "9:53:56",    55.4,  7.3, "氢气+半导体+储能调频+真空集热管+氢能源"),
    (2, 3, "其他", "600714.SH", "金瑞矿业", "13:13:15",   63.7, 10.2, "碳酸锂+天青石+一季报落地+钛酸锂(量子材料)+实控人变更"),
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


async def main():
    async with async_session() as s:
        unr = []

        # ---- 4/28 月度主线 ----
        await s.execute(text(
            "DELETE FROM daily_sector_review "
            "WHERE trade_date='20260428' AND source='bankuai' "
            "AND raw_meta->>'scope'='monthly'"
        ))
        n_m = 0
        for sector, is_core, name, mchg, tchg, tier in BANKUAI_4_28_MONTHLY:
            ts_code = await resolve_ts_code(s, name)
            if not ts_code:
                unr.append(("bk_4_28_monthly", name))
            await s.execute(text(
                "INSERT INTO daily_sector_review "
                "(trade_date, source, sector_name, ts_code, stock_name, "
                " is_main_line, market_cap_tier, keywords, raw_meta) VALUES "
                "('20260428','bankuai',:sec,:tc,:nm,true,:tier,:kw,:rm)"
            ), {
                "sec": sector, "tc": ts_code, "nm": name, "tier": tier,
                "kw": "核心" if is_core else None,
                "rm": json.dumps({
                    "scope": "monthly", "month": "202604",
                    "monthly_chg_pct": mchg, "today_chg_pct": tchg, "is_core": is_core,
                }, ensure_ascii=False),
            })
            n_m += 1

        # ---- 4/28 最强转债 ----
        await s.execute(text(
            "DELETE FROM daily_sector_review "
            "WHERE trade_date='20260428' AND source='bankuai' "
            "AND raw_meta->>'scope'='cb_strongest'"
        ))
        n_c = 0
        for concept, cb_name, chg, amt in BANKUAI_4_28_CB:
            ts_code = await resolve_ts_code(s, cb_name, prefer_cb=True)
            if not ts_code:
                unr.append(("bk_4_28_cb", cb_name))
            await s.execute(text(
                "INSERT INTO daily_sector_review "
                "(trade_date, source, sector_name, ts_code, stock_name, amount, "
                " is_main_line, raw_meta) VALUES "
                "('20260428','bankuai',:sec,:tc,:nm,:amt,true,:rm)"
            ), {
                "sec": concept, "tc": ts_code, "nm": cb_name, "amt": amt,
                "rm": json.dumps({"scope": "cb_strongest", "pct_chg": chg}, ensure_ascii=False),
            })
            n_c += 1

        # ---- 4/30 韭研全天复盘 ----
        await s.execute(text(
            "DELETE FROM daily_sector_review WHERE trade_date='20260430' AND source='jiuyan'"
        ))
        size_map = {sec: (size, rank) for sec, size, rank in JIUYAN_4_30_SECTORS}
        n_j = 0
        for board, dtb, sector, ts_code_known, name, ftime, mv_yi, amt_yi, kw in JIUYAN_4_30:
            ts_code = ts_code_known or await resolve_ts_code(s, name)
            if not ts_code:
                unr.append(("jy_4_30", name))
            size, rank = size_map.get(sector, (None, None))
            await s.execute(text(
                "INSERT INTO daily_sector_review "
                "(trade_date, source, sector_name, sector_rank, sector_size, "
                " ts_code, stock_name, board_count, days_to_board, limit_time, "
                " float_mv, amount, keywords, is_main_line, raw_meta) VALUES "
                "('20260430','jiuyan',:sec,:rank,:size,:tc,:nm,:bc,:dtb,:lt,:fmv,:amt,:kw,true,:rm)"
            ), {
                "sec": sector, "rank": rank, "size": size, "tc": ts_code, "nm": name,
                "bc": board, "dtb": dtb, "lt": ftime,
                "fmv": mv_yi * 1e8 if mv_yi else None,
                "amt": amt_yi * 1e8 if amt_yi else None,
                "kw": kw,
                "rm": json.dumps({"scope": "daily"}, ensure_ascii=False),
            })
            n_j += 1

        await s.commit()

    print(f"4/28 月度主线: {n_m} 行")
    print(f"4/28 最强转债: {n_c} 行")
    print(f"4/30 韭研: {n_j} 行")
    if unr:
        print(f"\n未匹配 {len(unr)} 条:")
        for s_, n_ in unr:
            print(f"  [{s_}] {n_}")


if __name__ == "__main__":
    asyncio.run(main())
