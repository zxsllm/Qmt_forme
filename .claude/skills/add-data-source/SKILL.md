---
name: add-data-source
description: 从 Tushare 新增数据源的完整流程——当用户要求拉取新数据、新增数据表、新增同步任务时使用
---

# 新增 Tushare 数据源 — 8 步标准流程

当用户要求拉取新的 Tushare 数据、新建数据表、接入新的数据源时，按以下步骤完成。

## Step 1: 查阅 API 文档

在 `.cursor/skills/skill-tushare-data/references/` 下找到目标 API 的详细文档。
确认: 接口名称、输入参数、输出字段、频率限制。

## Step 2: TushareService 添加方法

文件: `backend/app/research/data/tushare_service.py`

```python
def new_api(self, **kwargs) -> pd.DataFrame:
    return self.query("api_name", fields="field1,field2,...", **kwargs)
```

注意: `fields` 只写输出字段，不混入输入参数。

## Step 3: ORM 模型

文件: `backend/app/shared/models/stock.py`

使用 SQLAlchemy 2.0 `Mapped[]` 风格，复合主键用于时序数据。

## Step 4: Alembic 迁移

```bash
cd backend && alembic revision --autogenerate -m "add xxx table"
```

**必须检查**: 删除生成的 `op.drop_table("stock_min_kline_*")` 误删语句。

## Step 5: data_sync 同步函数

文件: `backend/app/execution/feed/data_sync.py`

```python
def sync_xxx(conn, svc, trade_date=None):
    sync_tracker.begin("xxx", trade_date)
    try:
        df = svc.new_api(trade_date=trade_date)
        # 写入逻辑...
        sync_tracker.success("xxx", len(df))
    except Exception as exc:
        sync_tracker.fail("xxx", exc)
        raise
```

关键: 必须调用 `sync_tracker.begin()` / `.success()` / `.fail()`。

## Step 6: data_health CheckDef

文件: `backend/app/shared/data_health.py` 的 `CHECKS` 数组

```python
CheckDef(
    table="xxx",
    label="中文标签",
    group="对应的前端路由分组",  # console/trading/strategy/system/news/sentiment/fundamental/infra
    date_col="trade_date",       # 用于 MAX() 检查的日期列
    freshness="daily",           # daily/daily_t1/quarterly/event/realtime/static
    severity="important",        # critical/important/minor
    sync_name="xxx",             # 必须匹配 data_sync.py 的函数名后缀
),
```

## Step 7: pull 脚本

文件: `scripts/pull_xxx.py` — 手动/历史补数据用。
在 scheduler 的 `run_post_market_sync()` 中注册自动同步。

## Step 8: API 端点 + 前端展示

1. `backend/app/shared/data/data_loader.py` — 添加查询方法
2. `backend/app/main.py` — 添加 REST 端点
3. `frontend/src/services/api.ts` — 添加类型定义和 API 方法
4. 前端页面组件 — 使用 `useQuery()` 消费数据
