"""补入：4/29 韭研全天复盘 + 4/28 板块必读连板天梯。

注：4/28 月度主线 / 最强转债与 4/29 那两张图完全相同（板块必读月度数据周更/不日更），
不重复入库。
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import async_session
from sqlalchemy import text


# =====================================================================
# 4/29 韭研全天复盘简图（图 16）
# =====================================================================
JIUYAN_4_29_SECTORS = [
    ("电池产业链", 10, 1),
    ("算力", 7, 2),
    ("PCB板", 4, 3),
    ("稀土", 3, 4),
    ("钨", 3, 5),
    ("洁净室", 2, 6),
    ("氢气", 2, 7),
    ("业绩", 2, 8),
    ("公告", 60, 9),
    ("其他", 7, 10),
]

# board, days_to_board, sector, ts_code, name, time, float_mv_yi, amount_yi, keywords
JIUYAN_4_29 = [
    # 电池产业链*10
    (3, 4, "电池产业链", "600338.SH", "西藏珠峰",   "13:40:39", 252.4, 36.4, "锂矿+一季报扭亏+拟出售部分盐湖资产+铅锌铜银矿山"),
    (2, 4, "电池产业链", "002756.SZ", "永兴材料",   "11:03:27", 324.5, 16.3, "锂矿+一季报增长+碳酸锂+特钢新材料"),
    (2, 4, "电池产业链", "002192.SZ", "融捷股份",   "9:38",      257.3, 37.6, "锂矿+一季报增长+电池负极材料项目+锂电正极材料"),
    (2, 4, "电池产业链", "002176.SZ", "江特电机",   "14:52:48",  74.1, 57.8, "锂矿+机器人+无人机"),
    (1, 1, "电池产业链", "603906.SH", "龙磁科技",   "11:14:27",  184.4, 19.6, "收购理士+一季度预增+磷酸铁锂+储能+固态电池前驱体+数据中心"),
    (1, 1, "电池产业链", "600367.SH", "红星发展",   "13:18",      74.8,  9.3, "锂电池+磷酸锰铁锂+电解锰金属+硫酸锰新工艺"),
    (1, 1, "电池产业链", "002497.SZ", "雅化集团",   "13:32",     320.8, 23.8, "锂矿+年报增长+固态电池(硫化锂新工艺)+民爆+四川"),
    (1, 1, "电池产业链", "002709.SZ", "天赐材料",   "13:40:09",  895.3,  103, "六氟磷酸锂+一季报大增+签订电解液供货协议+固态电池电解质"),
    (1, 1, "电池产业链", "001203.SZ", "大中矿业",   "11:01:42",  670.0, 15.9, "锂矿+拟建设年产20万吨锂盐项目+获采矿许可证+风电"),
    (1, 1, "电池产业链", "002136.SZ", "安纳达",     "14:38:21",   38.0,  3.8, "磷酸铁+钛白粉+烟台国资"),
    # 算力*7
    (8, 15, "算力", "603773.SH", "沃格光电",   "11:05:16", 156.7,   14, "玻璃基板(CPO)+6G+太空光伏+先进封装"),
    (2, 2, "算力", "605168.SH", "三人行",     "14:36:11", 102.2,  9.9, "算力+年报增长+股权转让+AI营销+数据要素"),
    (2, 5, "算力", "600186.SH", "莲花控股",   "9:59:38",  193.6, 24.2, "算力租赁+OpenClaw+调味品"),
    (1, 1, "算力", "920125.BJ", "鸿仕达",     "13:42:53",   11.1,  4.6, "服务器散热贴装设备+光模块+消费电子+苹果供应链+半导体"),
    (1, 1, "算力", "605139.SH", "康惠股份",   "13:56:45",   36.7,  2.3, "算力资产注入猜想+一季度报亏+AI减肥药+儿童用药+NMN"),
    (1, 1, "算力", "602348.SZ", "高乐股份",   "14:39:54",   95.5,  5.3, "布局算力+IP化身+拟募资8.54亿+PCIe接口芯片+机器人"),
    (1, 1, "算力", "603738.SH", "泰晶科技",   "14:41:12",  153.7, 25.4, "晶振对日替代+光模块+商业航天"),
    # PCB板*4
    (3, 3, "PCB板", "603095.SH", "越剑智能",   "13:16:53",   59.6,  5.1, "AI智能验布机+机器人+合作华为+人工智能"),
    (3, 3, "PCB板", "301217.SZ", "山东玻纤",   "9:37",        72.8,  4.9, "玻纤纱(电子级玻纤布上游)+科创板IPO上市+山东国资"),
    (1, 5, "PCB板", "501217.SZ", "铜冠铜箔",   "14:12:48",  588.4,   50, "PCB铜箔+一季报扭亏+HVLP4铜箔+锂电池铜箔"),
    (1, 1, "PCB板", "603256.SH", "宏和科技",   "9:43:06",  1061.1, 18.4, "玻璃纤维布+海峡两岸+供货苹果"),
    # 稀土*3
    (1, 1, "稀土", "002645.SZ", "华宏科技",   "10:21:09",   131.0,  6.2, "稀土磁材+年报扭亏+工业机器人电机+固废处理"),
    (1, 1, "稀土", "000831.SZ", "中国稀土",   "11:00:00",   573.0, 31.5, "稀土永磁+一季报扭亏+小金属+央企"),
    (1, 1, "稀土", "600392.SH", "盛和资源",   "13:30:18",   459.1, 28.3, "稀土+业绩预增+持股MP公司+小金属"),
    # 钨*3
    (1, 1, "钨", "600397.SH", "江钨装备",   "11:18:14",  143.7,  6.9, "定增收购钨钼资产+磁选装备+钨矿"),
    (1, 1, "钨", "000657.SZ", "中钨高新",   "13:03:45",  832.7,  9.5, "钨矿+一季报大增+PCB钻针"),
    (1, 1, "钨", "002378.SZ", "章源钨业",   "14:20:06",  393.4, 35.5, "钨矿+一季报增长+一带一路+军工"),
    # 洁净室*2
    (7, 9, "洁净室", "002081.SZ", "金螳螂",     "9:48:09",  141.7, 16.3, "半导体洁净室+商业航天+传闻签订大单"),
    (2, 2, "洁净室", "002652.SZ", "扬子新材",   "9:32:42",   45.0,  2.1, "半导体洁净室+航空航天+医疗器械+无人机+环保建材"),
    # 氢气*2
    (3, 5, "氢气", "600379.SH", "宝光股份",   "13:58:58",   50.4,  9.9, "氢气+半导体+储能调频+真空集热管+氢能源"),
    (1, 1, "氢气", "000039.SZ", "中集集团",   "13:47:55",  286.1,  6.9, "氢气储气瓶+数据中心+商业航天+储能+氢能"),
    # 业绩*2
    (1, 1, "业绩", "605299.SH", "舒华体育",   "10:07:53",   96.7,  7.6, "一季报增长+足球+体育产业+AI健身助手+华为合作+跨境电商"),
    (1, 1, "业绩", "001396.SZ", "誉帆科技",   "14:16:48",   10.6,  2.7, "一季报增长+排水管网检测+机器人+地下管网运维服务"),
    # 公告*60 仅入高板代表
    (2, 3, "公告", "002210.SZ", "飞马国际",   "9:31:00",    87.9,  6.1, "一季报增长+物流(深圳)+马字辈+控股股东拟变更+环保"),
    (2, 2, "公告", "001266.SZ", "宏英智能",   "9:25:00",    23.0,  1.2, "一季报增长+商业航天+机器人+液冷储能"),
    # 其他*7
    (4, 8, "其他", "603017.SH", "中衡设计",   "10:00:31",   42.2,  4.3, "商业航天(苏州)+建筑设计+低空经济"),
]


# =====================================================================
# 4/28 板块必读 - 连板天梯（仅 daily）
# =====================================================================
BANKUAI_4_28_HEADER = [
    ("国产芯片", 7, 1),
    ("算力", 6, 2),
    ("氢气", 4, 3),
    ("电池产业链", 2, 4),
]

BANKUAI_4_28_LADDER = [
    # 5板
    (5, "氢气", "水发燃气", "13:06", False),
    # 4板
    (4, "公告", "华电能源", "14:11", False),
    # 3板
    (3, "电池产业链", "维科技术", "9:41", False),
    # 2板
    (2, "国产芯片", "格林达", "9:52", False),
    (2, "算力", "越剑智能", "9:33", False),
    (2, "算力", "铭普光磁", "9:36", False),
    (2, "公告", "飞马国际", "9:43", False),
    (2, "公告", "东方智造", "9:55", False),
    (2, "公告", "罗曼股份", "10:36", False),
    (2, "公告", "德龙汇能", "11:21", False),
    (2, "反弹", "德才股份", "11:02", False),
    # 首板（48）
    (1, "国产芯片", "综艺股份", "9:58", False),
    (1, "国产芯片", "中晶科技", "10:01", False),
    (1, "国产芯片", "仁东控股", "10:06", False),
    (1, "国产芯片", "扬子新材", "13:04", False),
    (1, "国产芯片", "中天精装", "14:44", False),
    (1, "国产芯片", "金螳螂",   "14:49", False),
    (1, "算力", "三人行",   "13:14", False),
    (1, "算力", "群兴玩具", "13:21", False),
    (1, "算力", "中嘉博创", "13:50", False),
    (1, "算力", "雄韬股份", "14:39", True),
    (1, "氢气", "宝光股份", "13:14", False),
    (1, "氢气", "蜀道装备", None,    False),
    (1, "氢气", "陕建股份", None,    False),
    (1, "电池产业链", "宝丽迪", None, False),
    (1, "公告", "宏英智能", "9:30",  True),
    (1, "公告", "利通电子", "9:35",  True),
    (1, "公告", "恒工精密", "9:30",  False),
    (1, "公告", "美凯龙",   "9:34",  False),
    (1, "公告", "宁波建工", "9:34",  False),
    (1, "公告", "润都股份", "9:35",  False),
    (1, "公告", "药明康德", "9:35",  False),
    (1, "公告", "汉森制药", "9:36",  False),
    (1, "公告", "凯莱英",   "9:39",  False),
    (1, "公告", "永杉锂业", "9:40",  False),
    (1, "公告", "浙江鼎力", "9:41",  False),
    (1, "公告", "赤天化",   "9:45",  False),
    (1, "公告", "赛腾股份", "9:50",  False),
    (1, "公告", "日海智能", "9:50",  False),
    (1, "公告", "好上好",   "9:55",  False),
    (1, "公告", "天味食品", "10:21", False),
    (1, "公告", "宏辉果蔬", "10:27", False),
    (1, "公告", "盈峰环境", "10:38", False),
    (1, "公告", "杭齿前进", "11:12", False),
    (1, "公告", "华谊集团", "11:18", False),
    (1, "公告", "永清环保", "13:03", False),
    (1, "公告", "博云新材", "13:38", False),
    (1, "公告", "振华重工", "13:54", False),
    (1, "公告", "兴欣新材", "14:39", False),
    (1, "公告", "美邦科技", "14:54", False),
    (1, "反弹", "拓日新能", "9:38",  False),
    (1, "反弹", "津药药业", "9:41",  False),
    (1, "反弹", "登云股份", "10:43", False),
    (1, "反弹", "威龙股份", "13:15", False),
    (1, "反弹", "华银电力", "13:22", False),
    (1, "反弹", "比依股份", "13:42", False),
    (1, "反弹", "精工钢构", "13:52", False),
    (1, "反弹", "昊华能源", "14:16", False),
]


async def resolve_ts_code(session, name: str) -> str | None:
    name_clean = name.replace(" ", "").replace("XD", "")
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
        # 4/29 韭研
        await s.execute(text(
            "DELETE FROM daily_sector_review WHERE trade_date='20260429' AND source='jiuyan'"
        ))
        size_map_29 = {sec: (size, rank) for sec, size, rank in JIUYAN_4_29_SECTORS}
        n_jy = 0
        unr = []
        for board, dtb, sector, ts_code_known, name, ftime, mv_yi, amt_yi, kw in JIUYAN_4_29:
            ts_code = ts_code_known or await resolve_ts_code(s, name)
            if not ts_code:
                unr.append(("jy_4_29", name))
            size, rank = size_map_29.get(sector, (None, None))
            await s.execute(text(
                "INSERT INTO daily_sector_review "
                "(trade_date, source, sector_name, sector_rank, sector_size, "
                " ts_code, stock_name, board_count, days_to_board, limit_time, "
                " float_mv, amount, keywords, is_main_line, raw_meta) VALUES "
                "('20260429','jiuyan',:sec,:rank,:size,:tc,:nm,:bc,:dtb,:lt,:fmv,:amt,:kw,true,:rm)"
            ), {
                "sec": sector, "rank": rank, "size": size, "tc": ts_code, "nm": name,
                "bc": board, "dtb": dtb, "lt": ftime,
                "fmv": mv_yi * 1e8 if mv_yi else None,
                "amt": amt_yi * 1e8 if amt_yi else None,
                "kw": kw,
                "rm": json.dumps({"scope": "daily"}, ensure_ascii=False),
            })
            n_jy += 1

        # 4/28 板块必读 daily
        await s.execute(text(
            "DELETE FROM daily_sector_review WHERE trade_date='20260428' AND source='bankuai'"
        ))
        size_map_28 = {sec: (size, rank) for sec, size, rank in BANKUAI_4_28_HEADER}
        n_bk = 0
        for board, sector, name, ftime, one_word in BANKUAI_4_28_LADDER:
            ts_code = await resolve_ts_code(s, name)
            if not ts_code:
                unr.append(("bk_4_28_daily", name))
            size, rank = size_map_28.get(sector, (None, None))
            await s.execute(text(
                "INSERT INTO daily_sector_review "
                "(trade_date, source, sector_name, sector_rank, sector_size, "
                " ts_code, stock_name, board_count, days_to_board, limit_time, "
                " is_main_line, raw_meta) VALUES "
                "('20260428','bankuai',:sec,:rank,:size,:tc,:nm,:bc,:dtb,:lt,true,:rm)"
            ), {
                "sec": sector, "rank": rank, "size": size, "tc": ts_code, "nm": name,
                "bc": board, "dtb": board, "lt": ftime,
                "rm": json.dumps({"scope": "daily", "one_word": one_word}, ensure_ascii=False),
            })
            n_bk += 1

        await s.commit()

    print(f"4/29 韭研: {n_jy} 行")
    print(f"4/28 板块必读 daily: {n_bk} 行")
    if unr:
        print(f"\n未匹配 ts_code {len(unr)} 条:")
        for src, nm in unr:
            print(f"  [{src}] {nm}")


if __name__ == "__main__":
    asyncio.run(main())
