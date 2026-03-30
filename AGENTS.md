# AI Trade - 项目进度记忆

> 本文件供AI每次新对话时读取，快速恢复项目上下文。人工和AI共同维护。

## 当前状态

- **当前Phase**: Phase 4.8 四维能力建设 (消息面/基本面/情绪面/技术面)
- **当前子计划**: `.cursor/plans/四维能力建设子计划_31334356.plan.md`
- **主计划**: `.cursor/plans/ai_trade_量化交易系统_725fc656.plan.md`
- **路线**: 完成四维剩余步骤 → 模拟盘验证 → Phase 5 (QMT实盘) → Phase 6 (AI/ML)
- **最后更新**: 2026-03-30

### 四维能力建设详细进度

| 维度 | Step | 状态 | 说明 |
|------|------|------|------|
| A 消息面 | A1-Step1~4 | ✅ | 规则分类引擎 + news_classified/anns_classified表 + 3个API + NewsPage前端 |
| A 消息面 | A1-Step5 | ⏳ | 分类质量迭代 (人工纠正UI + 关键词库优化 + 大模型接口预留) |
| A 消息面 | A2 | 📋 | 更多消息源 (待用户提供) |
| B 基本面 | B-Step1 | ✅ | 5个财务表(fina_indicator/income/forecast/fina_mainbz/disclosure_date) + pull_fina.py |
| B 基本面 | B-Step2 | ❌ | concept_list/concept_detail表已建但数据为空，pull_concept.py未创建 |
| B 基本面 | B-Step3 | ✅ | 公司画像数据 (fina_mainbz + disclosure_date) |
| B 基本面 | B-Step4 | ⏳ | 行业画像+公司筛选器 (fundamental.py + API + FundamentalPage) |
| C 情绪面 | C-Step1~3 | ✅ | 7个情绪表 + pull_limit_board.py统一脚本 + 4个sentiment API + SentimentPage |
| C 情绪面 | C-Step4 | ⏳ | 情绪分析引擎 (market_temperature/board_leader/continuation_analysis) |
| C 情绪面 | C-Step5 | ⏳ | 盘前计划系统 (消息+涨停+基本面 → 关注列表+风险警示) |
| D 技术面 | D-Step1 | ⏳ | 技术信号检测 (连板计数/量能异动/缺口/支撑压力) |
| D 技术面 | D-Step2 | ⏳ | 风控辅助规则 (断板预警/天量见天价 → risk模块) |

> ✅ 已完成  ⏳ 待做  ❌ 标记错误需返工  📋 暂不可执行

## 数据时效

- **数据覆盖**: 20250922 ~ 20260323 (半年滚动)
- **最后拉取**: 2026-03-23
- **分钟分区**: 2025-09 ~ 2026-03 (超范围需先建分区)
- **注意**: 离线快照，增量更新见 `scripts/daily_sync.py`

## 已完成历程 (精简版)

| Phase | 核心产出 |
|-------|----------|
| P1 | 骨架 + ORM + Tushare封装 + 半年日线/指数/分钟数据 + DataLoader + 增量同步 |
| P2a | 前端交易控制台 (React19 + AntD5 + klinecharts + Storybook) |
| P2b | 资讯仪表盘 (K线多周期 + 7排行榜 + Sidebar新闻9源WS推送 + 拼音搜索) |
| P2-Opt | TushareService fields优化 + 批量INSERT + stock_st/adj_factor/sw_daily + 前复权 |
| P3 | 模拟交易引擎 (Redis + OMS + 风控 + 撮合 + Feed + REST API + WS + 审计) |
| P4 | 策略回测 (BacktestEngine + TradabilityFilter + ReportGenerator + 前端/backtest) |
| P4.5 | 模拟盘闭环 (手动交易UI + MarketDataScheduler + StrategyRunner) |
| P4.6 | 日运行周期 (OMS持久化 + 启动自检 + 盘中自动化 + 收盘结算) |
| P4.7 | A股规则合规 (T+1 + 涨跌停 + 一字板 + 整手100 + tick 0.01) |
| P4.8-A | 消息面分类 (news_classified + anns_classified + 规则引擎 + 3 API + NewsPage) |
| P4.8-B | 基本面数据 (5个财务表 + pull_fina.py + daily_sync注册) |
| P4.8-C | 情绪面数据 (7个打板表 + pull_limit_board.py + 4 sentiment API + SentimentPage) |
| 路由重构 | 合并8→5+3路由 (trading/strategy/system + news/sentiment/fundamental) |

## 项目文件地图

```
backend/app/
  core/
    config.py            -- Settings (DB_URL, TUSHARE_TOKEN, 日期范围)
    database.py          -- async engine + session factory
    redis.py             -- Redis 连接池 (Memurai)
    startup.py           -- 启动自检 + 交易日历工具
  main.py                -- FastAPI入口 + CORS + WS bridge + 全部REST端点
  shared/
    interfaces/
      types.py           -- Enums (OrderSide/Status/Type, RiskAction, AuditAction)
      models.py          -- Pydantic models (BarData/Signal/Order/Position/Account等)
    models/
      base.py            -- DeclarativeBase
      stock.py           -- 全部ORM (~40个表: 行情+财务+情绪+消息分类)
    data/
      data_loader.py     -- DataLoader (异步统一数据访问层)
      pinyin_cache.py    -- 拼音首字母搜索缓存
    news_classifier.py   -- 规则引擎: 新闻/公告分类
  research/
    data/tushare_service.py -- TushareService (39个方法, 频次控制+重试+fields优化)
    indicators/          -- MA/EMA/WMA/MACD/RSI/KDJ/BOLL
    backtest/            -- BacktestEngine + TradabilityFilter + ReportGenerator
    strategies/          -- ma_crossover.py 示范策略
    api.py               -- backtest REST router
  execution/
    engine.py            -- TradingEngine 协调层 (单例+持久化+恢复)
    persistence.py       -- OMS状态DB持久化
    strategy_runner.py   -- 策略实时执行
    api.py               -- REST router (orders/positions/account/risk/strategy/feed)
    fee.py / slippage.py / matcher.py -- 手续费/滑点/撮合(含A股规则)
    oms/                 -- 订单状态机 + 持仓账本 + 资金账本
    risk/                -- 下单前风控 + 盘中风控 + Kill Switch
    feed/                -- MarketFeed + WSManager + scheduler(rt_k 1.2s全市场轮询+新闻9源5秒WS推送)
    observability/       -- 心跳 + 审计日志 + 每日摘要
  alembic/               -- 迁移 (仅管常规表)

scripts/
  daily_sync.py          -- 日终综合同步 (调用下方脚本+classify_news+pull_fina --daily)
  init_data.py           -- stock_basic + trade_cal + stock_daily
  pull_batch1.py         -- daily_basic + index_*
  pull_minutes.py        -- 1min数据 (按月分区)
  pull_stk_limit.py      -- 涨跌停 + 停复牌
  pull_moneyflow.py      -- 个股资金流向
  pull_news.py           -- 新闻快讯
  pull_anns.py           -- 公司公告
  pull_st_list.py        -- ST股票列表
  pull_adj_factor.py     -- 复权因子
  pull_sw_daily.py       -- 申万行业指数日线
  pull_stk_auction.py    -- 集合竞价成交
  pull_eco_cal.py        -- 全球财经日历
  pull_moneyflow_ind.py  -- THS行业资金流向
  pull_index_global.py   -- 国际指数日线
  classify_news.py       -- 新闻/公告分类回填+增量
  pull_fina.py           -- 财务数据 (--daily轻量模式)
  pull_limit_board.py    -- 涨跌停/龙虎榜/游资/连板/热榜 (统一7个API)
  sync_incremental.py    -- 增量同步
  create_min_partitions.py -- 分钟K线月分区
  cleanup_minutes.py     -- 清理超6个月分钟分区

frontend/src/            -- React 19 + TypeScript + Vite + AntD5
  pages/
    Dashboard.tsx        -- 首页 (K线多周期+排行榜)
    KlinePage.tsx        -- K线详情
    TradingPage.tsx      -- 交易中心 (持仓+订单+下单 Tabs)
    StrategyPage.tsx     -- 策略研究 (策略管理+回测 Tabs)
    SystemPage.tsx       -- 系统监控 (风控+历史+审计+行情调度 Tabs)
    NewsPage.tsx         -- 消息中心 (分类新闻/公告+统计)
    SentimentPage.tsx    -- 情绪看板 (涨停榜/连板/龙虎榜/热榜)
    FundamentalPage.tsx  -- 基本面 (占位, 待B-Step4)
  components/
    KlineChart.tsx       -- K线 (分时/日/周/月)
    SidebarNews.tsx      -- Sidebar新闻快讯
    rankings/            -- 7个排行榜面板
  layouts/MainLayout.tsx -- Sidebar导航 + 新闻区
  services/api.ts        -- API客户端 + 类型定义
  services/useMarketFeed.ts -- WS hook (行情+新闻双通道)
```

## 数据库表概览

**行情基础** (有实际数据):
stock_basic(5811) / trade_cal(181) / stock_daily(632K) / daily_basic(632K) / stock_min_kline(1.5亿, 按月分区~39GB) / stock_limit(858K) / suspend_d(1428)

**指数**: index_basic(6716) / index_daily(812) / index_classify(511) / index_global(1443)

**消息分类**: news_classified(9077) / anns_classified(314K) / stock_news / stock_anns

**财务**: fina_indicator / income / forecast / fina_mainbz / disclosure_date

**情绪面**: limit_list_ths / limit_stats / limit_step / top_list / hm_detail / limit_cpt_list / dc_hot

**其他数据**: moneyflow_dc / stock_st / adj_factor / sw_daily / stk_auction / eco_cal / moneyflow_ind_ths / concept_list(空!) / concept_detail(空!)

**交易系统**: sim_orders / sim_trades / sim_positions / sim_account(1) / audit_log / strategy_meta / backtest_run / promotion_history

## API端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/v1/stock/search?q=` | 股票搜索(代码/名称/拼音) |
| GET | `/api/v1/stock/{ts_code}/daily` | 日线+基本面 |
| GET | `/api/v1/stock/{ts_code}/weekly` | 周K线 |
| GET | `/api/v1/stock/{ts_code}/monthly` | 月K线 |
| GET | `/api/v1/stock/{ts_code}/minutes` | 分钟K线 |
| GET | `/api/v1/stock/{ts_code}/news` | 个股新闻 |
| GET | `/api/v1/stock/{ts_code}/anns` | 公司公告 |
| GET | `/api/v1/stock/{ts_code}/irm_qa` | 互动问答 |
| GET | `/api/v1/market/snapshot/{trade_date}` | 全市场截面 |
| GET | `/api/v1/market/rankings` | 涨跌幅/换手率排行 |
| GET | `/api/v1/sector/rankings` | 板块涨跌幅排行 |
| GET | `/api/v1/market/moneyflow` | 主力资金流向 |
| GET | `/api/v1/market/global-indices` | 全球指数 |
| GET | `/api/v1/market/auction` | 集合竞价成交 |
| GET | `/api/v1/market/eco-cal` | 财经日历 |
| GET | `/api/v1/market/moneyflow-ind` | 行业资金流向 |
| GET | `/api/v1/market/news` | 新闻快讯 |
| GET | `/api/v1/market/news/classified` | 分类新闻 |
| GET | `/api/v1/market/anns/classified` | 分类公告 |
| GET | `/api/v1/market/news/stats` | 新闻分类统计 |
| GET | `/api/v1/sentiment/limit-board` | 涨跌停榜 |
| GET | `/api/v1/sentiment/limit-step` | 连板天梯 |
| GET | `/api/v1/sentiment/dragon-tiger` | 龙虎榜 |
| GET | `/api/v1/sentiment/hot-list` | 市场热榜 |
| GET | `/api/v1/index/{ts_code}/daily` | 指数日线 |
| GET | `/api/v1/classify/sw` | 申万行业分类 |
| POST | `/api/v1/orders` | 提交订单 |
| DELETE | `/api/v1/orders/{order_id}` | 撤单 |
| GET | `/api/v1/orders` | 订单列表 |
| GET | `/api/v1/positions` | 持仓 |
| GET | `/api/v1/account` | 账户概览 |
| POST | `/api/v1/account/reset` | 账户重置 |
| GET | `/api/v1/risk/status` | 风控状态 |
| POST/DELETE | `/api/v1/risk/kill-switch` | 紧急停机 |
| POST | `/api/v1/backtest/run` | 提交回测 |
| GET | `/api/v1/backtest/list` | 回测历史 |
| GET | `/api/v1/backtest/result/{run_id}` | 回测结果 |
| GET | `/api/v1/backtest/strategies` | 可用策略 |
| POST | `/api/v1/strategy/start` | 启动策略 |
| POST | `/api/v1/strategy/{name}/stop` | 停止策略 |
| GET | `/api/v1/strategy/running` | 运行中策略 |
| GET | `/api/v1/feed/status` | 行情调度器状态 |
| POST | `/api/v1/feed/start` | 启动行情 |
| POST | `/api/v1/feed/stop` | 停止行情 |
| WS | `/ws/market` | 实时行情+新闻推送 |

## 前端路由

| 路由 | 页面 | 状态 |
|------|------|------|
| `/` | Dashboard | K线多周期+排行榜 |
| `/kline` | KlinePage | K线详情 |
| `/trading` | TradingPage | 持仓+订单+下单 (Tabs) |
| `/strategy` | StrategyPage | 策略管理+回测 (Tabs) |
| `/system` | SystemPage | 风控+历史+审计+行情调度 (Tabs) |
| `/news` | NewsPage | 分类新闻/公告+统计 |
| `/sentiment` | SentimentPage | 涨停榜/连板/龙虎榜/热榜 |
| `/fundamental` | FundamentalPage | 占位 (待B-Step4) |

## 关键决策

| 决策 | 理由 |
|------|------|
| PostgreSQL 18 + Alembic(psycopg v3) | E盘本地, psycopg2中文Windows有编码问题 |
| 分钟表原生SQL分区 | Alembic不擅长分区表, 6个月滚动清理 |
| klinecharts (Canvas) | A股红涨绿跌, 内置指标, 高性能 |
| TradingEngine单例+DB持久化 | 内存态OMS + sim_*表持久化 + 重启恢复 |
| Redis: Memurai (Windows 6379) | 原生Windows Redis替代 |
| rt_k 1.2s全市场轮询 | 单次call ~5400股快照, 同时服务撮合+排行榜+WS推送 |
| 新闻9源5秒WS推送 | scheduler轮询→Redis pub/sub→WS→前端自动刷新, 3天清理 |
| 规则分类(非LLM) | 关键词引擎, 32万条15秒, 预留大模型接口 |
| 情绪面统一脚本 | pull_limit_board.py 一次拉7个API, 日频 |
| pull_fina --daily | forecast+disclosure日拉, fina_indicator/income按季自动检测 |
| 路由合并5+3 | 交易系统3合1, 释放slot给消息/情绪/基本面 |

## 隔离规则

- **execution/ 禁止 import research/** 下任何模块
- **research/ 可以 import execution/oms/, matcher, fee, slippage** (回测复用撮合)
- **research/ 禁止 import execution/engine.py** (不能用实时交易单例)
- 两层通过 **shared/interfaces/** 定义契约

## 已知限制

- `stock_min_kline` 在 Alembic 迁移链之外, schema变更需手动SQL
- klinecharts Canvas渲染, 颜色硬编码在 `COLORS` 常量
- 个股新闻用 `content ILIKE '%股票名%'` 匹配 (Tushare不按个股分类)
- stock_daily/daily_basic 有手动创建的 trade_date 索引 (不在Alembic内)
- concept_list/concept_detail 表已建但数据为空, pull_concept.py 未创建

## 代码审查

> 写完代码必须调用 code-reviewer subagent 审查。

- **Superpowers**: `C:\Users\MSI\.cursor\superpowers\`
- **规则**: `.cursor/rules/code-review.mdc`
- **流程**: 完成代码 → 列变更 → Task派遣reviewer → Critical必修/Important当场修/Minor记录

## 环境

| 项 | 值 |
|------|------|
| OS | Windows 10 |
| Python | 3.12.4, venv `.venv/` |
| PostgreSQL | 18+, DB `ai_trade` |
| Redis | Memurai 6379 (Windows服务) |
| 后端 | `backend/` uvicorn :8000 |
| 前端 | `frontend/` Vite :5173 |
| 核心指数 | 000001.SH 399001.SZ 399006.SZ 000300.SH 000905.SH 000688.SH 899050.BJ |
