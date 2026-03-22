# AI Trade - 项目进度记忆

> 本文件供AI每次新对话时读取，快速恢复项目上下文。人工和AI共同维护。

## 当前状态

- **当前Phase**: Phase 4.7 模拟盘A股市场规则合规 (已完成)
- **下一步**: P2-Plus (资讯仪表盘) → Phase 5 (QMT实盘桥接)
- **执行顺序**: P2-Plus → 跑一个月模拟盘 → Phase 5
- **主计划**: `.cursor/plans/ai_trade_量化交易系统_725fc656.plan.md`
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
- [x] **Phase 4** (10 Steps): IStrategy接口 + 回测可信性规则(backtest-rules.mdc) + stk_limit/suspend_d数据(85万行) + 技术指标库(MA/EMA/MACD/RSI/KDJ/BOLL) + TradabilityFilter + BacktestEngine(T+1/复用OMS) + ReportGenerator(Sharpe/回撤/胜率) + MACrossover示范策略 + DB持久化(strategy_meta/backtest_run/promotion_history) + REST API(4端点) + 前端回测页(/backtest)
- [x] **Phase 4.5** (5 Steps): 手动交易UI(下单Modal/平仓/改单/K线快捷下单/账户重置) + MarketDataScheduler(实时行情调度) + StrategyRunner(策略实时执行) + 假数据替换(StrategyPanel/LogPanel对接API) + 路由实体化(5个独立页面)
- [x] **Phase 4.6** (4 Steps): OMS状态持久化(DB写回+重启恢复) + 启动自检(数据时效+增量更新+OMS恢复) + 盘中自动化(scheduler自启+交易日历+watch_codes) + 收盘结算(end_day+日终数据同步)
- [x] **Phase 4.7**: 模拟盘A股市场规则合规 — T+1交割(available_qty) + 涨停不买/跌停不卖/一字板拦截(SimMatcher) + 限价单涨跌停校验(api) + 整手100股校验 + 价格tick 0.01校验 + 涨跌停限价缓存(每日自动加载)

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
| stock_limit | 858,468 | 每日涨跌停价格 (Phase 4) |
| suspend_d | 1,428 | 每日停复牌 (Phase 4) |
| strategy_meta | 0+ | 策略注册表 (Phase 4) |
| backtest_run | 0+ | 回测运行记录 (Phase 4) |
| promotion_history | 0+ | 策略晋级历史 (Phase 4) |

## 项目文件地图

```
backend/
  app/
    core/
      config.py             -- Settings (DB_URL, TUSHARE_TOKEN, 日期范围)
      database.py           -- async engine + session factory
      redis.py              -- Redis 连接池 (Memurai)
      startup.py            -- 启动自检 + 交易日历工具 (Phase 4.6)
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
      indicators/            -- MA/EMA/WMA/MACD/RSI/KDJ/BOLL
      backtest/
        engine.py            -- BacktestEngine (T+1, 复用OMS)
        credibility.py       -- TradabilityFilter (涨跌停/停牌/一字板/ST/IPO)
        report.py            -- ReportGenerator (Sharpe/回撤/胜率等)
      strategies/
        ma_crossover.py      -- 示范策略 (MA5/20金叉死叉)
      api.py                 -- backtest REST API router
    execution/
      engine.py             -- TradingEngine 协调层 (单例, 含持久化+恢复)
      persistence.py        -- OMS状态DB持久化 (save_batch/load/clear, Phase 4.6)
      strategy_runner.py    -- StrategyRunner (实时策略执行, Phase 4.5)
      api.py                -- REST API router (/orders, /positions, /account, /risk, /strategy, /feed)
      fee.py                -- A股手续费
      slippage.py           -- 滑点模型
      matcher.py            -- 模拟撮合引擎 (含涨跌停/一字板A股规则校验)
      oms/                  -- 订单状态机 + 持仓账本 + 资金账本
      risk/                 -- 下单前风控 + 盘中风控 + Kill Switch
      feed/                 -- MarketFeed + WSManager + scheduler.py (实时行情调度)
      observability/        -- 心跳 + 审计日志 + 每日摘要
  alembic/                  -- 迁移 (仅管常规表)

scripts/
  init_data.py              -- stock_basic + trade_cal + stock_daily
  pull_batch1.py            -- daily_basic + index_*
  create_min_partitions.py  -- stock_min_kline 月分区
  pull_minutes.py           -- 1min数据 (--test N / --resume)
  pull_stk_limit.py         -- 涨跌停 + 停复牌数据 (Phase 4)
  sync_incremental.py       -- 增量同步 (--dry-run)

frontend/                   -- React 19 + TypeScript + Vite + Storybook
  src/
    pages/Dashboard.tsx     -- 控制台首页 (K线+下单+账户+持仓+订单+风控+策略+日志)
    pages/KlinePage.tsx     -- 独立K线页
    pages/PositionsPage.tsx -- 持仓明细页 (平仓/清仓)
    pages/OrdersPage.tsx    -- 订单管理页 (新建/改单)
    pages/HistoryPage.tsx   -- 历史成交页
    pages/RiskPage.tsx      -- 风控页 (风控+行情调度器+审计日志)
    pages/StrategyPage.tsx  -- 策略管理页 (配置/启停)
    components/             -- Panel, AccountCard, KlineChart, OrderSubmitForm, PositionTable, OrderTable, RiskPanel 等
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
| POST | `/api/v1/backtest/run` | 提交回测 |
| GET | `/api/v1/backtest/list` | 回测历史列表 |
| GET | `/api/v1/backtest/result/{run_id}` | 获取回测结果 |
| GET | `/api/v1/backtest/strategies` | 可用策略列表 |
| GET | `/api/v1/stock/search?q=` | 股票搜索(自动补全) |
| POST | `/api/v1/account/reset` | 模拟账户重置 |
| POST | `/api/v1/strategy/start` | 启动策略 |
| POST | `/api/v1/strategy/{name}/stop` | 停止策略 |
| GET | `/api/v1/strategy/running` | 运行中策略列表 |
| GET | `/api/v1/feed/status` | 行情调度器状态 |
| POST | `/api/v1/feed/start` | 启动行情调度 |
| POST | `/api/v1/feed/stop` | 停止行情调度 |

## 前端路由

| 路由 | 页面 | 状态 |
|------|------|------|
| `/` | Dashboard.tsx | 已实现 (交易控制台 + 下单 + K线快捷买卖) |
| `/kline` | KlinePage.tsx | 已实现 (独立K线详情) |
| `/positions` | PositionsPage.tsx | 已实现 (持仓明细 + 平仓/清仓) |
| `/orders` | OrdersPage.tsx | 已实现 (订单管理 + 新建订单 + 改单) |
| `/history` | HistoryPage.tsx | 已实现 (历史成交记录) |
| `/risk` | RiskPage.tsx | 已实现 (风控 + 行情调度器 + 审计日志) |
| `/strategy` | StrategyPage.tsx | 已实现 (策略配置 + 启停 + 参数编辑) |
| `/backtest` | BacktestPage.tsx | 已实现 (策略回测) |

## 核心指数代码

000001.SH(上证), 399001.SZ(深证), 399006.SZ(创业板), 000300.SH(沪深300), 000905.SH(中证500), 000688.SH(科创50), 899050.BJ(北证50)

## 待做

- [x] **Phase 4**: 策略框架与回测系统 ✅
- [x] **Phase 4.5**: 模拟盘闭环 ✅
- [x] **Phase 4.6**: 日运行生命周期 ✅
- [x] **Phase 4.7**: 模拟盘A股市场规则合规 ✅
- [ ] **P2-Plus**: 资讯仪表盘 (行业/宏观/北向/新闻/公告) ← 当前
- [ ] **Phase 5**: QMT实盘桥接 (先跑1个月模拟盘再考虑)
- [ ] **Phase 6**: AI/ML策略增强

## 关键决策

| 决策 | 理由 |
|------|------|
| PostgreSQL 18, E盘 | 用户本地已安装 |
| Python 3.12.4 | 用户本地版本 |
| Alembic用psycopg(v3) | psycopg2中文Windows有编码问题 |
| 分钟表原生SQL分区 | Alembic不擅长PostgreSQL分区表 |
| klinecharts | 内置指标/A股红涨绿跌/Canvas高性能 |
| TradingEngine单例+DB持久化 | Phase 3 MVP内存态; Phase 4.6 接入sim_*表持久化+重启恢复 |
| Redis: Memurai (Windows) | 原生Windows Redis替代, 端口6379 |
| 模拟盘仅服务中低频策略 | 分钟K线驱动，不适用超短/打板 |
| 模拟盘A股规则合规 | T+1/涨跌停/一字板/整手/tick, 与回测引擎规则对齐 |

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
