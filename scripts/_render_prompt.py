#!/usr/bin/env python3
"""模板渲染：用数据文件内容替换 prompt 模板中的占位符。

用法: python3 _render_prompt.py template_file placeholder1 data_file1 [placeholder2 data_file2 ...]

占位符格式示例: {data}  {similar}  {core}
渲染结果输出到 stdout。

退出码: 0=成功 1=失败
"""

import os
import sys


def main():
    # Windows 下强制 stdout 使用 UTF-8，避免 GBK 编码错误
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 4 or (len(sys.argv) - 2) % 2 != 0:
        print(
            f"用法: {sys.argv[0]} template_file placeholder1 data_file1 [placeholder2 data_file2 ...]",
            file=sys.stderr,
        )
        sys.exit(1)

    template_file = sys.argv[1]
    try:
        template = open(template_file, encoding="utf-8").read()
    except FileNotFoundError:
        print(f"模板文件不存在: {template_file}", file=sys.stderr)
        sys.exit(1)

    # 成对读取占位符和数据文件
    for i in range(2, len(sys.argv), 2):
        placeholder = sys.argv[i]
        data_file = sys.argv[i + 1]
        try:
            data = open(data_file, encoding="utf-8").read()
        except FileNotFoundError:
            print(f"数据文件不存在: {data_file}", file=sys.stderr)
            sys.exit(1)
        template = template.replace(placeholder, data)

    print(template)


if __name__ == "__main__":
    main()
