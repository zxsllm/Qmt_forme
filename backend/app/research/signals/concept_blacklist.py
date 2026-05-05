"""概念黑名单——Tushare concept_detail 里的资金属性 / 宽基 / 跨品种标签。

这些标签出现在 top 频次里只是"涨停股票本身就属于这些类别"的副作用，
并不代表当日真正的题材主线。算法 B 在聚合主线时应跳过这些。

可在使用过程中持续扩充。
"""

# 完全跳过：资金属性 / 宽基指数 / 北向 / 大盘类
EXACT_BLACKLIST: set[str] = {
    "融资融券",
    "转融券标的",
    "新股与次新股",
    "次新股",
    "新股",
    "富时罗素概念股",
    "富时罗素",
    "富时罗素A股",
    "中证红利股",
    "中证红利",
    "深股通",
    "沪股通",
    "陆股通",
    "标普道琼斯A股",
    "MSCI概念",
    "MSCI中国",
    "QFII持股",
    "QFII重仓股",
    "社保重仓",
    "社保基金重仓",
    "证金持股",
    "汇金持股",
    "破净股",
    "高送转",
    "预盈预增",
    "预亏预减",
    "员工持股",
    "举牌概念",
    "壳资源",
    "AH股",
    "B股",
    "ST股",
    "国资改革",
    "央企改革",
    "地方国资改革",
    "国企改革",
    "中字头",
    "QFII持股",
    "深证100",
    "上证50",
    "沪深300",
    "中证500",
    "中证1000",
}

# 包含子串则跳过：兜底通配
SUBSTR_BLACKLIST: tuple[str, ...] = (
    "MSCI",
    "QFII",
    "RQFII",
    "陆股通",
    "深股通",
    "沪股通",
    "富时罗素",
    "标普道琼斯",
    "证金持股",
    "汇金持股",
    "社保",
    "员工持股",
    "增减持",
    "破净",
    "次新股",
    "重组",
)


def is_blacklisted(concept_name: str) -> bool:
    if not concept_name:
        return True
    if concept_name in EXACT_BLACKLIST:
        return True
    for sub in SUBSTR_BLACKLIST:
        if sub in concept_name:
            return True
    return False
