#!/usr/bin/env python3
"""报告内容校验：检测占位符/测试文本，校验字段最小长度。

用法: python3 _validate_report.py <json_file> <report_type>
  report_type: "review_core" | "review_detail" | "plan_core" | "plan_detail"

退出码: 0=通过 1=校验失败（错误信息输出到 stderr）
"""

import json
import sys

# 黑名单关键词（大写匹配）
BLACKLIST = ["TEST", "TODO", "PLACEHOLDER", "FIXME", "待填写", "暂无数据"]

# 各报告类型的必填字段及最小字符数
REQUIRED_FIELDS = {
    "review_core": {
        "strategy_conclusion": 20,
        "dominant_strategy": 4,
        "risk_summary": 50,
    },
    "review_detail": {
        "market_summary": 50,
        "sector_analysis": 50,
        "sentiment_narrative": 50,
    },
    "plan_core": {
        "predicted_direction": 2,
        "key_logic": 30,
        "risk_notes": 50,
    },
    "plan_detail": {
        "overnight_summary": 30,
        "board_play_plan": 30,
        "swing_trade_plan": 30,
    },
}


def validate(json_data: dict, report_type: str) -> list[str]:
    """校验 JSON 数据，返回错误列表（空列表=通过）"""
    errors = []
    fields = REQUIRED_FIELDS.get(report_type, {})

    for field, min_len in fields.items():
        value = json_data.get(field, "")
        text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)

        # 长度检查
        if len(text) < min_len:
            errors.append(f"{field}: 内容过短 ({len(text)} 字符 < 最少 {min_len})")

        # 黑名单检查
        upper = text.upper()
        for word in BLACKLIST:
            if word.upper() in upper:
                errors.append(f"{field}: 包含禁止词 '{word}'")

    return errors


def main():
    if len(sys.argv) < 3:
        print(f"用法: {sys.argv[0]} <json_file> <report_type>", file=sys.stderr)
        print(f"  report_type: {', '.join(REQUIRED_FIELDS.keys())}", file=sys.stderr)
        sys.exit(1)

    json_file = sys.argv[1]
    report_type = sys.argv[2]

    if report_type not in REQUIRED_FIELDS:
        print(f"未知报告类型: {report_type}", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.load(open(json_file, encoding="utf-8"))
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"读取失败: {e}", file=sys.stderr)
        sys.exit(1)

    errors = validate(data, report_type)
    if errors:
        print(f"校验失败 ({report_type}):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
