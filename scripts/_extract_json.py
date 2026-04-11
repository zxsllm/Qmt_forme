#!/usr/bin/env python3
"""从 Claude CLI 原始输出中提取 JSON，自动修复常见格式问题。

用法: python3 _extract_json.py input_file output_file
退出码: 0=成功 1=失败
"""

import json
import re
import sys


def _fix_inner_quotes(text: str) -> str:
    """修复 JSON 字符串值内部的未转义双引号 → 中文引号「」"""
    result = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == '"':
            result.append('"')
            i += 1
            while i < n:
                if text[i] == '\\':
                    result.append(text[i : i + 2])
                    i += 2
                elif text[i] == '"':
                    rest = text[i + 1 :].lstrip()
                    if not rest or rest[0] in ',:}]':
                        result.append('"')
                        i += 1
                        break
                    else:
                        # 内嵌双引号对 "xxx" → 「xxx」
                        result.append('「')
                        i += 1
                        close_pos = text.find('"', i)
                        if close_pos != -1:
                            result.append(text[i:close_pos])
                            result.append('」')
                            after = text[close_pos + 1 :].lstrip()
                            if after and after[0] not in ',:}]':
                                i = close_pos + 1
                            else:
                                i = close_pos
                        # 找不到闭合引号则跳过
                else:
                    result.append(text[i])
                    i += 1
        else:
            result.append(text[i])
            i += 1
    return ''.join(result)


def try_parse(text: str) -> dict | None:
    """尝试解析 JSON，失败则修复后重试"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fixed = _fix_inner_quotes(text)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        return None


def _find_balanced_braces(text: str) -> str | None:
    """从文本中提取第一个括号平衡的 {...} 块（避免贪婪正则误匹配）"""
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def extract(raw: str) -> dict | None:
    """从原始文本提取 JSON 对象"""
    obj = try_parse(raw)
    if obj is not None:
        return obj

    # ```json ... ```
    m = re.search(r'```json\s*\n(.*?)\n```', raw, re.DOTALL)
    if m:
        obj = try_parse(m.group(1))
        if obj is not None:
            return obj

    # ``` ... ```
    m = re.search(r'```\s*\n(.*?)\n```', raw, re.DOTALL)
    if m:
        obj = try_parse(m.group(1))
        if obj is not None:
            return obj

    # 括号平衡匹配 {...}（替代贪婪正则，避免匹配到多余内容）
    balanced = _find_balanced_braces(raw)
    if balanced:
        obj = try_parse(balanced)
        if obj is not None:
            return obj

    return None


def main():
    if len(sys.argv) < 3:
        print(f"用法: {sys.argv[0]} input_file output_file", file=sys.stderr)
        sys.exit(1)

    infile, outfile = sys.argv[1], sys.argv[2]
    raw = open(infile, encoding="utf-8").read().strip()

    obj = extract(raw)
    if obj is not None:
        json.dump(obj, open(outfile, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        sys.exit(0)
    else:
        print(f"JSON 提取失败: {infile}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
