# AI Trade - A股量化交易系统

## 当前状态

Phase 5.0 已完成 (自动化复盘与早盘计划) → 下一步: Phase 6 (QMT实盘) → Phase 7 (AI/ML)
数据覆盖: 20250922 ~ 20260401 | 核心指数: 000001.SH 399001.SZ 399006.SZ 000300.SH 000905.SH 000688.SH 899050.BJ

## 执行纪律

- **不许扩范围**: 严格遵守当前 Phase MVP 边界
- **先复用**: 新增前先查 `scripts/`、`backend/app/`、已有模型和端点
- **改后必验**: 未验证不得标记完成
- **不重构无关模块**: 只改当前任务涉及的代码
- **端口**: 后端 8000，前端 5173，启动前检查占用

## 隔离规则 (硬约束)

- `execution/` **禁止** import `research/` 下任何模块
- `research/` 可 import `execution/oms/`, `matcher.py`, `fee.py`, `slippage.py` (回测复用撮合)
- `research/` **禁止** import `execution/engine.py` (不能用实时交易单例)
- 两层通过 `shared/interfaces/` 定义契约

## 技术栈

Python 3.12 | FastAPI | SQLAlchemy 2.0 (async) + asyncpg | PostgreSQL 18 + Alembic | Redis (Memurai 6379)
React 19 | TypeScript 5.9 | Vite 8 | Ant Design 6 | TailwindCSS 4 | klinecharts 9.8 | Zustand + React Query
Tushare Pro (满权限) | venv `.venv/` | Windows 环境

## 数据库

- 常规表用 Alembic 管理迁移
- 分区表 `stock_min_kline` 用原生 SQL (`scripts/create_min_partitions.py`)
- Alembic autogenerate 会误删分区子表 → 迁移后必须检查删除 `op.drop_table("stock_min_kline_*")`

## 数据健康检查 (关键维护点)

引入新数据源或修改数据拉取/展示逻辑时，**必须同步维护**数据健康检查系统:
1. 新 DB 表 → 在 `data_health.py` 的 `CHECKS` 数组添加 `CheckDef`
2. 新 sync 函数 → 确保调用 `sync_tracker.begin()` / `.success()` / `.fail()`
3. `CheckDef.sync_name` 必须匹配 `data_sync.py` 中的函数名，否则自动修复失败
4. `CheckDef.group` 必须匹配前端路由分组，否则健康面板不显示

## 数据所有权

- 所有 Tushare 调用通过 `TushareService` (`backend/app/research/data/tushare_service.py`)
- 所有数据读取通过 `DataLoader` (`backend/app/shared/data/data_loader.py`)
- 数据同步统一由 `scheduler` 管理 (`backend/app/execution/feed/scheduler.py` + `data_sync.py`)
- 实时数据 fallback 链: rt_snapshot (内存) → DB → Tushare API

## 参考文档

- Tushare API 参考: `.cursor/skills/skill-tushare-data/references/`
- 数据管线注册表: `.cursor/rules/data-pipeline.mdc`
- 前端 UI 规范: `frontend/CLAUDE.md`
