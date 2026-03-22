# AI Trade - 项目进度记忆

> 本文件供AI每次新对话时读取，快速恢复项目上下文。人工和AI共同维护。

## 当前状态

- **当前Phase**: Phase 4 (策略框架与回测系统)
- **子计划**: `.cursor/plans/p4-strategy-backtest.plan.md`
- **最后更新**: 2026-03-22

## 数据时效

- **数据覆盖范围**: 20250922 ~ 20260320 (半年)
- **最后拉取时间**: 2026-03-21 晚
- **分钟表分区范围**: 2025-09 ~ 2026-03 (超出此范围需先建新分区)
- **注意**: 数据是离线快照，不会自动更新。增量更新见 `project-overview.mdc`

## 已完成

- [x] **Phase 1**: 骨架 + 模型 + Tushare封装 + 半年日线/指标/指数/分钟数据 + DataLoader + 增量同步
- [x] **Phase 2a (P2-Core)**: 前端交易控制台 (React19+Vite+AntD5+klinecharts+Storybook+设计Token)
- [x] **Phase 3** (10 Steps): Redis(Memurai) + shared/interfaces/(通信协议) + SimOrder/SimTrade等DB模型 + OMS(order_manager/position_book/account) + 风控(pre_trade/realtime/kill_switch) + 撮合(matcher+fee+slippage) + 行情Feed(Redis pub/sub→WS) + REST API + 可观测性(heartbeat/audit/daily_summary) + 前端对接(useQuery轮询+useMarketFeed WS)

## 数据统计

| 表 | 行数 | 说明 |
|---|------|------|
| stock_basic | 5,811 | 含在市(L)+退市(D)股票 |
| trade_cal | 181 | 其中116个交易日 |
| stock_daily | 632,199 | 116天 x ~5,450只/天 |
| daily_basic | 632,199 | PE/PB/换手率/市值等 |
| index_basic | 6,716 | SSE/SZSE/CSI/SW指数 |
| index_daily | 812 | 7大核心指数半年日线 |
| index_classify | 511 | 申万2021行业分类 |
| stock_min_kline | 152,810,886 | 1min按月分区, ~39GB |
| sim_orders | 0+ | 模拟订单 (Phase 3) |
| sim_trades | 0+ | 模拟成交 (Phase 3) |
| sim_positions | 0+ | 模拟持仓快照 (Phase 3) |
| sim_account | 1 | 模拟账户 (单行, id=1) |
| audit_log | 0+ | 审计日志 (Phase 3) |

## 项目文件地图

```
backend/
  app/
    core/
      config.py             -- Settings (DB_URL, TUSHARE_TOKEN, 日期范围)
      database.py           -- async engine + session factory
      redis.py              -- Redis 连接池 (Memurai)
    main.py                 -- FastAPI入口 + CORS + WS bridge
    shared/
      interfaces/
        types.py            -- Enums (OrderSide/Status/Type, RiskAction, AuditAction)
        models.py           -- Pydantic models (BarData/Signal/Order/Position/Account等)
      models/
        base.py             -- DeclarativeBase
        stock.py            -- 所有ORM (StockBasic~AuditLog, 共14个)
      data/data_loader.py   -- DataLoader (异步, 返回DataFrame)
    research/
      data/tushare_service.py -- TushareService (频次控制+重试)
    execution/
      engine.py             -- TradingEngine 协调层 (单例)
      api.py                -- REST API router (/orders, /positions, /account, /risk)
      fee.py                -- A股手续费
      slippage.py           -- 滑点模型
      matcher.py            -- 模拟撮合引擎
      oms/                  -- 订单状态机 + 持仓账本 + 资金账本
      risk/                 -- 下单前风控 + 盘中风控 + Kill Switch
      feed/                 -- MarketFeed (Redis pub/sub) + WSManager
      observability/        -- 心跳 + 审计日志 + 每日摘要
  alembic/                  -- 迁移 (仅管常规表)

scripts/
  init_data.py              -- stock_basic + trade_cal + stock_daily
  pull_batch1.py            -- daily_basic + index_*
  create_min_partitions.py  -- stock_min_kline 月分区
  pull_minutes.py           -- 1min数据 (--test N / --resume)
  sync_incremental.py       -- 增量同步 (--dry-run)

frontend/                   -- React 19 + TypeScript + Vite + Storybook
  src/
    pages/Dashboard.tsx     -- 控制台首页 (K线+账户+持仓+订单+风控+策略+日志)
    pages/KlinePage.tsx     -- 独立K线页
    components/             -- Panel, AccountCard, KlineChart, PositionTable, OrderTable, RiskPanel 等
    services/api.ts         -- 后端API调用 + useMarketFeed WebSocket
```

## 已有API端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/v1/stock/{ts_code}/daily` | 个股日线+基本面 |
| GET | `/api/v1/market/snapshot/{trade_date}` | 全市场截面 |
| GET | `/api/v1/index/{ts_code}/daily` | 指数日线 |
| GET | `/api/v1/classify/sw` | 申万行业分类 |
| POST | `/api/v1/orders` | 提交订单 |
| DELETE | `/api/v1/orders/{order_id}` | 撤单 |
| GET | `/api/v1/orders` | 订单列表 |
| GET | `/api/v1/positions` | 持仓 |
| GET | `/api/v1/account` | 账户概览 |
| GET | `/api/v1/risk/status` | 风控状态 |
| POST/DELETE | `/api/v1/risk/kill-switch` | 紧急停机 |
| WS | `/ws/market` | 实时行情推送 (Redis pub/sub → WebSocket) |

## 前端路由

| 路由 | 页面 | 状态 |
|------|------|------|
| `/` | Dashboard.tsx | 已实现 (交易控制台主屏) |
| `/kline` | KlinePage.tsx | 已实现 (独立K线详情) |
| `/positions` `/orders` `/history` `/risk` `/strategy` | Dashboard.tsx | 占位路由 (Phase 4+独立) |

## 核心指数代码

000001.SH(上证), 399001.SZ(深证), 399006.SZ(创业板), 000300.SH(沪深300), 000905.SH(中证500), 000688.SH(科创50), 899050.BJ(北证50)

## 待做

- [ ] **Phase 4**: 策略框架与回测系统 ← 当前
- [ ] Phase 5: QMT实盘桥接
- [ ] Phase 6: AI/ML策略增强

## 关键决策

| 决策 | 理由 |
|------|------|
| PostgreSQL 18, E盘 | 用户本地已安装 |
| Python 3.12.4 | 用户本地版本 |
| Alembic用psycopg(v3) | psycopg2中文Windows有编码问题 |
| 分钟表原生SQL分区 | Alembic不擅长PostgreSQL分区表 |
| klinecharts | 内置指标/A股红涨绿跌/Canvas高性能 |
| TradingEngine单例+内存状态 | Phase 3 MVP不需要DB持久化 |
| Redis: Memurai (Windows) | 原生Windows Redis替代, 端口6379 |
| 模拟盘仅服务中低频策略 | 分钟K线驱动，不适用超短/打板 |

## 已知限制

- `stock_min_kline` 在 Alembic 迁移链之外，schema变更需手动SQL
- API返回的DataFrame中有NaN值，`main.py` 里用 `_df_to_records()` 处理
- klinecharts 为 Canvas 渲染，不支持 CSS 变量，颜色硬编码在 `COLORS` 常量

## 环境信息

- **OS**: Windows 10
- **Python**: 3.12.4, venv at `.venv/`
- **PostgreSQL**: 18+, DB: `ai_trade`
- **Redis**: Memurai (端口6379, Windows服务自动启动)
- **后端**: `backend/` 下 `uvicorn app.main:app --port 8000`
- **前端**: `frontend/` 下 `npm run dev` (端口5173)
- **Storybook**: `frontend/` 下 `npm run storybook` (端口6006)
