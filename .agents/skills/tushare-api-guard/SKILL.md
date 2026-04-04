---
name: tushare-api-guard
description: Use when the task touches tushare_service.py, pull_*.py, sync_*.py, init_data.py, daily_sync.py, or data_sync.py, or when the user asks to add or fix Tushare-backed data syncing.
---

# Tushare API 调用规范

## 调用规则

- 所有调用必须通过 `TushareService`，禁止直接 `pro.query()`
- 账户满积分+满接口权限，无需考虑积分限制
- TushareService 内置速率限制 (200 RPM) + 指数退避重试

## 接口名称

以 `.cursor/skills/skill-tushare-data/references/` 文档中**接口名称**字段为准。
例: 新闻快讯=`news`，公告=`anns_d`。

> 新增数据源的完整流程见 `add-data-source` skill

## 常见陷阱

- `fields` 参数只包含**输出字段**，不要混入输入参数 (如 `src`)
- 写入 PostgreSQL 前，pandas Series 转 Python 原生类型，避免 `can't adapt type 'Series'`
- 日期格式: `YYYYMMDD` (字符串)
- 股票代码: `ts_code` 格式 (`000001.SZ`, `600000.SH`)
