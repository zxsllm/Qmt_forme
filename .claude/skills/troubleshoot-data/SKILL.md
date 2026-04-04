---
name: troubleshoot-data
description: 数据问题排查——当用户反馈数据缺失、不更新、前端空白、数据不对时使用
---

# 数据问题排查流程

当用户报告数据缺失、不更新、前端显示空白或异常时，按以下分层排查。

## 第 1 层: 前端

- 打开浏览器 DevTools → Network，检查 API 请求是否发出、返回状态码
- 检查 `useQuery` 的 `queryKey` 是否正确、`refetchInterval` 是否设置
- 检查 `api.ts` 中对应方法是否存在

## 第 2 层: API 端点

- 直接访问 `http://localhost:8000/api/v1/xxx` 看返回
- 检查 `main.py` 中端点是否注册
- 检查 DataLoader 方法是否有对应查询

## 第 3 层: 数据库

```sql
SELECT MAX(trade_date) FROM xxx;
SELECT COUNT(*) FROM xxx WHERE trade_date = 'YYYYMMDD';
```

- 如果表为空: 需要执行 pull 脚本或触发同步
- 如果数据旧: 检查 scheduler 是否在运行

## 第 4 层: 数据同步 (scheduler + data_sync)

- 检查 `/api/v1/feed/status` — scheduler 是否运行
- 检查后端日志中 `sync:` 前缀的行
- 检查 `sync_tracker` 状态 (通过 `/api/v1/system/data-health` 端点)
- 常见问题:
  - `schema_mismatch`: 表结构与代码不一致 → 跑 Alembic 迁移
  - `partition_missing`: 分钟线分区不存在 → `python scripts/create_min_partitions.py`
  - `rate_limit`: Tushare API 限流 → 等待或降低频率
  - `connection_error`: DB 连接失败 → 检查 PostgreSQL 服务

## 第 5 层: Tushare 数据源

- 确认接口权限 (满积分满权限)
- 确认参数格式: 日期 `YYYYMMDD`，代码 `000001.SZ`
- 部分数据有延迟: top_list/dc_hot 仅盘后可用，forecast 日频更新

## 健康面板快速判断

前端左下角健康面板 (MainLayout 抽屉) 提供实时状态:
- 绿色 ok = 正常
- 橙色 stale = 数据滞后 (查看 gap_days)
- 红色 missing = 数据缺失
- 蓝色 syncing = 正在同步中

点击展开可看到:
- 每个检查项的实际日期 vs 期望日期
- 诊断原因 (reason) + 推荐操作 (action)
- 是否可自动修复 (repairable)

## 常见故障速查

| 现象 | 原因 | 解决 |
|------|------|------|
| 全部数据空 | 后端未启动或 scheduler 未运行 | 启动后端 `uvicorn app.main:app --port 8000` |
| 单表数据旧 | 该表的 sync 函数报错 | 查日志 + 手动跑 pull 脚本 |
| 分钟线缺失 | 分区不存在 | `python scripts/create_min_partitions.py` |
| WS 推送不工作 | Memurai (Redis) 未运行 | `Get-Service memurai` 检查 + 启动 |
| 健康面板显示 critical | 关键表 (stock_daily/daily_basic) 缺数据 | 手动 `python scripts/daily_sync.py` |
