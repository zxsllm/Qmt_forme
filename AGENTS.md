# AI Trade - 项目进度记忆

> 本文件供AI每次新对话时读取，快速恢复项目上下文。人工和AI共同维护。

## 当前状态

- **当前Phase**: Phase 1-后续 大部分完成
- **下一步**: Phase 2a (P2-Core交易控制台)
- **最后更新**: 2026-03-22

## 数据时效

- **数据覆盖范围**: 20250922 ~ 20260320 (半年)
- **最后拉取时间**: 2026-03-21 晚
- **分钟表分区范围**: 2025-09 ~ 2026-03 (超出此范围需先建新分区)
- **注意**: 数据是离线快照，不会自动更新。增量更新方法见 `project-overview.mdc` 数据时效性约束。

## 已完成

- [x] 总体计划制定 (`.cursor/plans/ai_trade_量化交易系统_725fc656.plan.md`)
- [x] `.cursor/rules/project-overview.mdc` 防遗忘约束
- [x] Phase 1-MVP Step 1~5: 骨架 + 模型 + Tushare封装 + 半年日线拉取
- [x] Phase 1-后续 Batch 1: daily_basic + index_basic + index_daily + index_classify
- [x] Phase 1-后续 Batch 2: stock_min_kline 分区表 + 1min全量拉取 (152,810,886行)
- [x] Phase 1-后续 Batch 3(部分): DataLoader统一数据访问层 + REST API

## 数据统计

| 表 | 行数 | 说明 |
|---|------|------|
| stock_basic | 5,811 | 含在市(L)+退市(D)股票 |
| trade_cal | 181 | 其中116个交易日 |
| stock_daily | 632,199 | 116天 x ~5,450只/天 |
| daily_basic | 632,199 | PE/PB/换手率/市值等 |
| index_basic | 6,716 | SSE/SZSE/CSI/SW指数 |
| index_daily | 812 | 7大核心指数半年日线 |
| index_classify | 511 | 申万2021行业分类 (L1:31 L2:134 L3:346) |
| stock_min_kline | 152,810,886 | 1min按月分区, ~39GB(含索引) |

## 项目文件地图

```
backend/
  app/
    core/config.py            -- Settings (DB_URL, TUSHARE_TOKEN, 日期范围)
    core/database.py          -- async engine + session factory
    main.py                   -- FastAPI入口, 已有端点见下
    shared/
      models/base.py          -- DeclarativeBase
      models/stock.py         -- 所有表模型 (8个: StockBasic~StockMinKline)
      data/data_loader.py     -- DataLoader (异步, 返回DataFrame)
    research/
      data/tushare_service.py -- TushareService (频次控制+重试+封装方法)
  alembic/                    -- 迁移 (仅管常规表, 不管分区表)

scripts/
  init_data.py                -- 拉取 stock_basic + trade_cal + stock_daily
  pull_batch1.py              -- 拉取 daily_basic + index_* + index_classify
  create_min_partitions.py    -- 创建/扩展 stock_min_kline 月分区
  pull_minutes.py             -- 拉取1min数据 (支持 --test N / --resume)
```

## 已有API端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/v1/stock/{ts_code}/daily?start=&end=` | 个股日线+基本面 |
| GET | `/api/v1/market/snapshot/{trade_date}` | 全市场当日截面 (TOP20) |
| GET | `/api/v1/index/{ts_code}/daily?start=&end=` | 指数日线 |
| GET | `/api/v1/classify/sw?level=` | 申万行业分类 |

## 待做 (按优先级)

- [ ] Phase 1-后续 (剩余): Redis缓存 / 增量同步 (可推迟)
- [ ] Phase 2a (P2-Core): 交易控制台 (K线/持仓/风控/策略开关)
- [ ] Phase 3: 实时数据流 + OMS/模拟交易引擎
- [ ] Phase 4: 策略框架与回测系统
- [ ] Phase 5: QMT实盘桥接
- [ ] Phase 6: AI/ML策略增强

## 关键决策记录

| 日期 | 决策 | 原因 |
|------|------|------|
| 2026-03-21 | PostgreSQL 18 on E盘 | 用户本地已安装 |
| 2026-03-21 | Python 3.12.4 | 用户本地版本 |
| 2026-03-21 | MVP先拉半年日线 | 避免一次性做太多，先跑通闭环 |
| 2026-03-21 | Phase 2拆为P2-Core+P2-Plus | P2-Core交易必需面板先行 |
| 2026-03-21 | 模拟盘仅服务中低频策略 | 分钟K线驱动，不适用超短/打板 |
| 2026-03-21 | Alembic用psycopg(v3) | psycopg2在中文Windows有编码问题 |
| 2026-03-21 | 分钟表用原生SQL分区 | Alembic不擅长PostgreSQL分区表 |
| 2026-03-21 | 核心指数选7个 | 上证/深证/创业板/沪深300/中证500/科创50/北证50 |

## 已知限制

- `stock_min_kline` 在 Alembic 迁移链之外，schema变更需手动SQL
- 39GB分钟数据的全表聚合查询较慢 (按ts_code查询走索引，秒级响应)
- API返回的DataFrame中有NaN值，`main.py` 里用 `_df_to_records()` 处理
- Windows PowerShell默认编码显示中文乱码，不影响数据正确性

## 核心指数代码

000001.SH, 399001.SZ, 399006.SZ, 000300.SH, 000905.SH, 000688.SH, 899050.BJ

## 环境信息

- **OS**: Windows 10 (也兼容 Linux/macOS)
- **Python**: 3.10+, venv at `.venv/`
- **PostgreSQL**: 18+, DB name: `ai_trade`
- **Tushare Token**: 环境变量 `TUSHARE_TOKEN`
- **uvicorn启动**: 在 `backend/` 目录下运行 `uvicorn app.main:app --port 8000`
