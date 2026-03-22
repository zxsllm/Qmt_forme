# AI Trade - 项目进度记忆

> 本文件供AI每次新对话时读取，快速恢复项目上下文。人工和AI共同维护。

## 当前状态

- **当前Phase**: Phase 2a (P2-Core) 已完成，准备进入 Phase 3
- **下一步**: Phase 3 (实时数据流 + OMS/模拟交易引擎)
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
- [x] Phase 1 收尾: 增量同步脚本 (scripts/sync_incremental.py)
- [x] Phase 2a P2-Core: 前端交易控制台 (React19+Vite+AntD5+klinecharts)
- [x] Phase 2a UI重构: 设计Token + Panel容器 + 独立组件 + Storybook (见 p2-core_ui重构_688581cd.plan.md)

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
  sync_incremental.py         -- 增量同步 (日线/指标/指数, 支持 --dry-run)

frontend/                       -- React 19 + TypeScript + Vite + Storybook
  .storybook/
    main.ts                     -- Storybook配置 (过滤@tailwindcss/vite, 用PostCSS替代)
    preview.tsx                 -- 全局CSS + 暗色主题 + ConfigProvider decorator
  postcss.config.mjs            -- @tailwindcss/postcss (供Storybook使用)
  src/
    App.tsx                     -- 根组件 (ConfigProvider + QueryClient + Router)
    index.css                   -- 设计Token (@theme + @source) + Ant Design暗色覆写
    layouts/MainLayout.tsx      -- 暗色侧边栏导航 (7个菜单项)
    pages/
      Dashboard.tsx             -- 控制台首页 (纯布局编排, ~50行)
      KlinePage.tsx             -- 独立K线页 (代码切换+MACD, 尚未迁移设计Token)
    components/
      Panel.tsx                 -- 通用面板容器 (borderless/secondary/noPadding)
      AccountCard.tsx           -- 4张统计卡 (总资产/持仓/今日/累计)
      KlineChart.tsx            -- klinecharts封装 (COLORS常量, 不支持CSS变量)
      PositionTable.tsx         -- 持仓表
      OrderTable.tsx            -- 订单表
      TradePlanTable.tsx        -- 交易计划表
      PositionOrderPanel.tsx    -- 持仓+委托 Tabs封装
      RiskPanel.tsx             -- 风控面板 (Panel + Kill按钮)
      StrategyPanel.tsx         -- 策略管理 (Switch开关)
      LogPanel.tsx              -- 系统日志
      ErrorBoundary.tsx         -- React错误边界
      *.stories.tsx             -- 10个Storybook stories
    services/
      api.ts                    -- 后端API调用
      mockData.ts               -- Mock数据 (持仓/订单/风控/策略/账户)
```

## 前端路由

| 路由 | 页面 | 状态 |
|------|------|------|
| `/` | Dashboard.tsx | 已实现 (交易控制台) |
| `/kline` | KlinePage.tsx | 已实现 (独立K线, 旧色系待迁移) |
| `/positions` | Dashboard.tsx | 占位 (Phase 3 OMS后独立) |
| `/orders` | Dashboard.tsx | 占位 |
| `/history` | Dashboard.tsx | 占位 |
| `/risk` | Dashboard.tsx | 占位 |
| `/strategy` | Dashboard.tsx | 占位 |

## 已有API端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/v1/stock/{ts_code}/daily?start=&end=` | 个股日线+基本面 |
| GET | `/api/v1/market/snapshot/{trade_date}` | 全市场当日截面 (TOP20) |
| GET | `/api/v1/index/{ts_code}/daily?start=&end=` | 指数日线 |
| GET | `/api/v1/classify/sw?level=` | 申万行业分类 |

## 待做 (按优先级)

- [ ] **Phase 3**: 实时数据流 + OMS/模拟交易引擎 (Redis, WebSocket, 订单状态机, 风控, 撮合)
- [ ] Phase 4: 策略框架与回测系统
- [ ] Phase 5: QMT实盘桥接
- [ ] Phase 6: AI/ML策略增强

## Phase 3 前置要点 (从主计划摘要)

- Redis安装配置 (Windows: Memurai/WSL)
- 新目录: `backend/app/execution/` (OMS, risk, feed, observability)
- 新目录: `backend/app/shared/interfaces/` (research/execution通信协议)
- 隔离规则生效: research/ ⇄ execution/ 禁止互相import
- 前端需WebSocket接实时行情 + 替换mockData为真实OMS数据
- Tushare实时接口: rt_min, rt_k, stk_limit, suspend_d

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
| 2026-03-22 | K线库: klinecharts | 内置指标/A股红涨绿跌/Canvas高性能 |
| 2026-03-22 | 独立组件 + Panel + Storybook | Dashboard纯布局; 统一设计Token; 组件可独立预览 |
| 2026-03-22 | Storybook用PostCSS而非Vite插件 | @tailwindcss/vite与Storybook模块图冲突 |

## 已知限制

- `stock_min_kline` 在 Alembic 迁移链之外，schema变更需手动SQL
- 39GB分钟数据的全表聚合查询较慢 (按ts_code查询走索引，秒级响应)
- API返回的DataFrame中有NaN值，`main.py` 里用 `_df_to_records()` 处理
- Windows PowerShell默认编码显示中文乱码，不影响数据正确性
- `KlinePage.tsx` 仍用旧硬编码色 (`#1f1f1f`等)，未迁移设计Token
- klinecharts 为 Canvas 渲染，不支持 CSS 变量，颜色在 `COLORS` 常量中硬编码

## 核心指数代码

000001.SH, 399001.SZ, 399006.SZ, 000300.SH, 000905.SH, 000688.SH, 899050.BJ

## 环境信息

- **OS**: Windows 10 (也兼容 Linux/macOS)
- **Python**: 3.10+, venv at `.venv/`
- **PostgreSQL**: 18+, DB name: `ai_trade`
- **Tushare Token**: 环境变量 `TUSHARE_TOKEN`
- **uvicorn启动**: 在 `backend/` 目录下运行 `uvicorn app.main:app --port 8000`
- **前端**: `frontend/` 目录下 `npm run dev` (端口5173)
- **Storybook**: `frontend/` 目录下 `npm run storybook` (端口6006)
