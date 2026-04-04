---
name: add-endpoint
description: 新增 REST API 端点的标准流程——当用户要求添加接口、暴露数据给前端、创建新页面时使用
---

# 新增 API 端点 — 标准流程

当用户要求添加新的 API 接口或前端需要新数据时，按以下步骤完成。

## Step 1: DataLoader 方法

文件: `backend/app/shared/data/data_loader.py`

所有数据读取必须通过 DataLoader，不直接写 SQL 到路由中。

```python
async def new_query(self, ts_code: str, start_date: str = "", end_date: str = "") -> pd.DataFrame:
    async with self._session() as session:
        stmt = select(Model).where(...)
        result = await session.execute(stmt)
        return pd.DataFrame(...)
```

## Step 2: main.py 端点

文件: `backend/app/main.py`

```python
@app.get("/api/v1/xxx/{ts_code}/yyy")
async def get_xxx_yyy(ts_code: str, ...):
    loader = DataLoader()
    df = await loader.new_query(ts_code, ...)
    return _df_to_records(df)
```

实时数据 fallback 链: `get_rt_snapshot()` (内存) → DataLoader (DB) → TushareService (API)

## Step 3: 前端 api.ts

文件: `frontend/src/services/api.ts`

```typescript
// 类型定义
export interface XxxYyy { field1: string; field2: number; ... }

// API 方法
xxxYyy: (tsCode: string) => fetchJson<XxxYyy[]>(`/api/v1/xxx/${tsCode}/yyy`),
```

所有 API 调用必须通过 `api` 对象，禁止直接 `fetch()`。

## Step 4: 前端组件

使用 `useQuery()` + `api.xxxYyy()` 消费数据:

```tsx
const { data } = useQuery({
  queryKey: ['xxx-yyy', tsCode],
  queryFn: () => api.xxxYyy(tsCode),
  refetchInterval: 30_000,
});
```

mutation 后用 `qc.invalidateQueries()` 失效缓存。

## Step 5: 健康检查注册

如果该数据有独立的 DB 表和同步函数，在 `data_health.py` CHECKS 数组添加 CheckDef。
详见 `add-data-source` skill。
