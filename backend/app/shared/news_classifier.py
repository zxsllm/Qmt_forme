"""Rule-based news & announcement classifier.

Classifies news by:
  - scope:     macro / industry / stock / mixed
  - time_slot: pre_open / intraday / after_hours
  - sentiment: positive / negative / neutral
  - related stock codes and industry names

Uses keyword matching against stock_basic names and index_classify industries.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, time as dtime

# ── Trading session boundaries ──────────────────────────────────────────

_PRE_OPEN_START = dtime(7, 0)
_MORNING_OPEN = dtime(9, 30)
_MORNING_CLOSE = dtime(11, 30)
_AFTERNOON_OPEN = dtime(13, 0)
_AFTERNOON_CLOSE = dtime(15, 0)
_AFTER_HOURS_END = dtime(23, 59, 59)

# ── Macro keywords ──────────────────────────────────────────────────────

MACRO_KEYWORDS: list[str] = [
    "央行", "国务院", "证监会", "银保监", "财政部", "发改委", "商务部",
    "工信部", "科技部", "国资委", "外汇局", "统计局",
    "利率", "降息", "加息", "降准", "MLF", "LPR", "逆回购", "公开市场",
    "GDP", "CPI", "PPI", "PMI", "社融", "M2", "货币供应",
    "美联储", "美元", "人民币", "汇率", "关税", "贸易战",
    "A股", "沪指", "深成指", "创业板指", "北证", "大盘",
    "IPO", "注册制", "退市", "印花税", "两融", "转融通",
    "北向资金", "外资", "QFII", "沪港通", "深港通",
    "国债", "地方债", "专项债",
]

# ── Sentiment keywords ──────────────────────────────────────────────────

POSITIVE_KEYWORDS: list[str] = [
    "涨停", "大涨", "暴涨", "创新高", "突破", "利好", "超预期", "景气",
    "高增长", "翻倍", "爆发", "井喷", "强势", "放量上涨",
    "签约", "中标", "获批", "通过", "战略合作", "增持", "回购",
    "扭亏", "预增", "业绩大增", "净利润增长", "营收增长",
    "产品涨价", "供不应求", "满产满销", "订单饱满",
    "技术突破", "国产替代", "自主可控",
    "降准", "降息", "减税", "补贴", "扶持",
]

NEGATIVE_KEYWORDS: list[str] = [
    "跌停", "大跌", "暴跌", "崩盘", "闪崩", "利空", "不及预期",
    "爆雷", "暴雷", "违规", "处罚", "罚款", "立案", "调查",
    "退市", "st", "ST", "*ST", "风险警示",
    "减持", "清仓", "质押", "爆仓", "强平",
    "预减", "预亏", "业绩下滑", "净利润下降", "亏损",
    "产品降价", "需求下滑", "库存积压", "停产",
    "破发", "破净", "腰斩",
    "加息", "加税", "制裁", "禁令",
]

# ── Announcement type keywords ──────────────────────────────────────────

ANN_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("earnings_forecast", ["业绩预告", "业绩预增", "业绩预减", "业绩预亏", "业绩预盈"]),
    ("earnings_express", ["业绩快报"]),
    ("earnings_report", ["年度报告", "半年度报告", "季度报告", "年报", "半年报", "季报"]),
    ("dividend", ["分红", "送股", "转增", "派息", "利润分配"]),
    ("buyback", ["回购", "股份回购"]),
    ("holder_change", ["增持", "减持", "权益变动", "举牌"]),
    ("equity", ["定增", "增发", "配股", "可转债发行", "股权激励"]),
    ("restructure", ["重组", "并购", "收购", "资产重组", "借壳"]),
    ("violation", ["处罚", "违规", "立案", "警示函", "监管函", "问询函"]),
    ("suspend", ["停牌", "复牌"]),
    ("contract", ["中标", "签约", "合同", "订单"]),
    ("other", []),
]


@dataclass
class NewsClassResult:
    news_scope: str = "mixed"
    time_slot: str = "after_hours"
    sentiment: str = "neutral"
    related_codes: list[str] = field(default_factory=list)
    related_industries: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    def to_db_dict(self, news_id: int) -> dict:
        return {
            "news_id": news_id,
            "news_scope": self.news_scope,
            "time_slot": self.time_slot,
            "sentiment": self.sentiment,
            "related_codes": self.related_codes or None,
            "related_industries": self.related_industries or None,
            "keywords": self.keywords or None,
        }


@dataclass
class AnnsClassResult:
    ann_type: str = "other"
    sentiment: str = "neutral"
    keywords: list[str] = field(default_factory=list)

    def to_db_dict(self, anns_id: int) -> dict:
        return {
            "anns_id": anns_id,
            "ann_type": self.ann_type,
            "sentiment": self.sentiment,
            "keywords": self.keywords or None,
        }


class NewsClassifier:
    """Stateful classifier that loads stock names and industry keywords from DB."""

    def __init__(self):
        self._stock_map: dict[str, str] = {}       # name -> ts_code
        self._stock_code_map: dict[str, str] = {}   # "000001" -> "000001.SZ"
        self._industry_keywords: list[str] = []
        self._loaded = False

    def load_reference_data(
        self,
        stock_rows: list[tuple[str, str]],
        industry_names: list[str],
    ):
        """Load from DB query results.

        stock_rows: [(ts_code, name), ...]
        industry_names: [industry_name, ...]
        """
        for ts_code, name in stock_rows:
            if name and len(name) >= 2:
                self._stock_map[name] = ts_code
            if ts_code:
                short = ts_code.split(".")[0]
                self._stock_code_map[short] = ts_code

        self._industry_keywords = [n for n in industry_names if n and len(n) >= 2]
        self._loaded = True

    # ── News classification ─────────────────────────────────────────────

    def classify_news(self, news_id: int, content: str, dt_str: str) -> NewsClassResult:
        result = NewsClassResult()

        # Time slot
        result.time_slot = self._classify_time_slot(dt_str)

        # Scope + related entities
        is_macro = self._match_macro(content)
        matched_codes = self._extract_stock_codes(content)
        matched_industries = self._extract_industries(content)

        if matched_codes:
            result.related_codes = matched_codes
        if matched_industries:
            result.related_industries = matched_industries

        has_stock = len(matched_codes) > 0
        has_industry = len(matched_industries) > 0

        if is_macro and not has_stock:
            result.news_scope = "macro"
        elif has_stock and not is_macro:
            result.news_scope = "stock"
        elif has_industry and not has_stock and not is_macro:
            result.news_scope = "industry"
        elif is_macro and has_stock:
            result.news_scope = "mixed"
        elif has_industry:
            result.news_scope = "industry"
        else:
            result.news_scope = "macro" if is_macro else "mixed"

        # Sentiment
        result.sentiment = self._classify_sentiment(content)

        # Keywords (collect matched terms)
        kw = []
        for w in MACRO_KEYWORDS:
            if w in content:
                kw.append(w)
        for w in POSITIVE_KEYWORDS + NEGATIVE_KEYWORDS:
            if w in content:
                kw.append(w)
        result.keywords = list(dict.fromkeys(kw))[:20]

        return result

    # ── Announcement classification ─────────────────────────────────────

    def classify_anns(self, anns_id: int, title: str) -> AnnsClassResult:
        result = AnnsClassResult()

        for ann_type, keywords in ANN_TYPE_RULES:
            if any(kw in title for kw in keywords):
                result.ann_type = ann_type
                result.keywords = [kw for kw in keywords if kw in title]
                break

        result.sentiment = self._classify_sentiment(title)
        return result

    # ── Internal helpers ────────────────────────────────────────────────

    def _classify_time_slot(self, dt_str: str) -> str:
        """Determine time slot from datetime string like '2026-03-24 14:30:00'."""
        try:
            if len(dt_str) >= 16:
                dt = datetime.strptime(dt_str[:19], "%Y-%m-%d %H:%M:%S")
            elif len(dt_str) >= 10:
                dt = datetime.strptime(dt_str[:10], "%Y-%m-%d")
                return "after_hours"
            else:
                return "after_hours"

            t = dt.time()
            weekday = dt.weekday()

            if weekday >= 5:
                return "after_hours"

            if _PRE_OPEN_START <= t < _MORNING_OPEN:
                return "pre_open"
            elif (_MORNING_OPEN <= t <= _MORNING_CLOSE) or (_AFTERNOON_OPEN <= t <= _AFTERNOON_CLOSE):
                return "intraday"
            else:
                return "after_hours"
        except (ValueError, TypeError):
            return "after_hours"

    def _match_macro(self, text: str) -> bool:
        return any(kw in text for kw in MACRO_KEYWORDS)

    def _extract_stock_codes(self, text: str) -> list[str]:
        """Extract stock codes from news content via name and code matching."""
        found: list[str] = []

        # Match by stock name (min 2 chars, avoid common words)
        for name, ts_code in self._stock_map.items():
            if len(name) < 2:
                continue
            if name in text and ts_code not in found:
                found.append(ts_code)
                if len(found) >= 10:
                    break

        # Match 6-digit code patterns like (000001) or 600519
        code_pattern = re.findall(r'(?<!\d)([036]\d{5})(?!\d)', text)
        for code in code_pattern:
            ts = self._stock_code_map.get(code)
            if ts and ts not in found:
                found.append(ts)
                if len(found) >= 10:
                    break

        return found

    def _extract_industries(self, text: str) -> list[str]:
        found = []
        for ind in self._industry_keywords:
            if ind in text and ind not in found:
                found.append(ind)
                if len(found) >= 5:
                    break
        return found

    def _classify_sentiment(self, text: str) -> str:
        pos_count = sum(1 for kw in POSITIVE_KEYWORDS if kw in text)
        neg_count = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text)

        if pos_count > neg_count and pos_count >= 1:
            return "positive"
        elif neg_count > pos_count and neg_count >= 1:
            return "negative"
        return "neutral"
