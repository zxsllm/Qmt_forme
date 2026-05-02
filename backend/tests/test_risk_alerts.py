from app.shared.risk_alerts import (
    _extract_effective_date,
    _financial_st_reason,
    _mentions_st_warning_for_stock,
)


def test_extract_st_effective_date_prefers_warning_context():
    content = (
        "利源股份公告称，公司股票于2026年4月29日开市起停牌一天，"
        "并于4月30日开市起复牌。自4月30日起，公司股票被实施退市风险警示。"
    )

    assert _extract_effective_date(content, "2026") == "20260430"


def test_extract_st_effective_date_reads_full_date():
    content = "公司股票自2026年5月6日起被实施退市风险警示。"

    assert _extract_effective_date(content) == "20260506"


def test_extract_st_effective_date_prefers_resume_date():
    content = (
        "公司股票将于2026年4月30日停牌一天，"
        "于2026年5月6日起复牌并被实施退市风险警示。"
    )

    assert _extract_effective_date(content, "2026") == "20260506"


def test_extract_st_effective_date_reads_resume_date_before_st_name():
    content = (
        "公司股票自2026年4月30日开市起停牌1天，"
        "将于2026年5月6日开市起复牌，实施后A股简称为ST际华。"
    )

    assert _extract_effective_date(content, "2026") == "20260506"


def test_news_st_match_requires_nearby_stock_context():
    content = (
        "晚间重要公告汇总|中远海控：签订造船协议。"
        "ST华鹏：公司股票将于5月6日被实施退市风险警示。"
        "工商银行：一季度净利润同比增长。"
    )

    assert not _mentions_st_warning_for_stock(content, "工商银行", "601398.SH")
    assert _mentions_st_warning_for_stock(content, "ST华鹏", "603021.SH")


def test_news_st_match_handles_compact_summary_items():
    content = (
        "晚间重要公告汇总|【品大事】中远海控：签订造船协议总价22.2亿美元"
        "ST华鹏：公司股票将于5月6日被实施退市风险警示"
        "山西高速：选举董事长【观业绩】工商银行：一季度净利润同比增长"
    )

    assert not _mentions_st_warning_for_stock(content, "中远海控", "601919.SH")
    assert not _mentions_st_warning_for_stock(content, "工商银行", "601398.SH")
    assert _mentions_st_warning_for_stock(content, "ST华鹏", "603021.SH")


def test_news_st_match_handles_company_body_text():
    content = (
        "利源股份(002501.SZ)公告称，公司股票于2026年4月29日开市起停牌一天，"
        "并于4月30日开市起复牌。自4月30日起，公司股票被实施退市风险警示，"
        "股票简称变更为“*ST利源”。"
    )

    assert _mentions_st_warning_for_stock(content, "利源股份", "002501.SZ")


def test_news_st_match_handles_quoted_warning_after_long_body_text():
    content = (
        "东方智造公告，公司2025年度经审计的合并报表中利润总额为-3162.8万元，"
        "归属于上市公司股东的净利润为-3272.91万元、扣除非经常性损益后的净利润为-3304万元，"
        "且营业收入扣除后金额为2.99亿元。根据《深圳证券交易所股票上市规则》第9.3.1条，"
        "公司触及被实施“退市风险警示”的情形。公司股票将于2026年4月29日停牌一天，"
        "于2026年4月30日开市起复牌，并自2026年4月30日开市起被实施退市风险警示，"
        "股票简称变更为“*ST东智”。"
    )

    assert _mentions_st_warning_for_stock(content, "东方智造", "002175.SZ")
    assert _extract_effective_date(content, "2026") == "20260430"


def test_news_st_match_handles_other_risk_warning():
    content = (
        "华谊兄弟公告，公司股票自4月29日开市起停牌1天，"
        "将于2026年4月30日开市起复牌。公司股票自4月30日起被实施其他风险警示，"
        "股票简称由“华谊兄弟”变更为“ST华谊”。"
    )

    assert _mentions_st_warning_for_stock(content, "华谊兄弟", "300027.SZ")
    assert _extract_effective_date(content, "2026") == "20260430"


def test_news_st_match_rejects_possible_warning():
    content = "美芝股份公告，若2025年审计报告确认净资产为负，公司股票可能被实施退市风险警示。"

    assert not _mentions_st_warning_for_stock(content, "美芝股份", "002856.SZ")


def test_news_st_match_stops_at_news_section_boundary():
    content = (
        "【市场动态】当天机构净买入前三的股票分别是铜冠铜箔、江特电机、固德威；"
        "【公司新闻】①寒武纪：第一季度净利润同比增长185%；"
        "⑤闻泰科技：公司股票被实施退市风险警示并叠加其他风险警示。"
    )

    assert not _mentions_st_warning_for_stock(content, "江特电机", "002176.SZ")
    assert not _mentions_st_warning_for_stock(content, "固德威", "688390.SH")
    assert not _mentions_st_warning_for_stock(content, "铜冠铜箔", "301217.SZ")
    assert _mentions_st_warning_for_stock(content, "闻泰科技", "600745.SH")


def test_news_st_match_stops_at_next_summary_item_colon():
    content = (
        "晚间重要公告汇总|【品大事】矽电股份：与兆驰股份子公司签署合同"
        "科华数据：拟出售控股子公司"
        "ST西发：法院裁定受理重整，股票将被实施退市风险警示"
    )

    assert not _mentions_st_warning_for_stock(content, "兆驰股份", "002429.SZ")
    assert _mentions_st_warning_for_stock(content, "ST西发", "000752.SZ")


def test_financial_st_reason_only_accepts_hard_triggers():
    assert _financial_st_reason(3_525_619_493.4, -213_632_973.91, -265_423_507.43, -0.3877)
    assert _financial_st_reason(223_592_402.92, -178_475_046.18, -181_870_557.33, 0.0488)
    assert not _financial_st_reason(3_096_712_785.3, 12_000_000, -20_000_000, 1.2)
