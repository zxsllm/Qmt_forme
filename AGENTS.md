# AI Trade - 项目进度记忆

> 本文件供AI每次新对话时读取，快速恢复项目上下文。人工和AI共同维护。

## 当前状态

- **当前Phase**: P2-Plus-Opt 性能优化 & 数据增强 (已完成)
- **下一步**: 跑一个月模拟盘 → Phase 5 (QMT实盘桥接)
- **执行顺序**: 跑一个月模拟盘 → Phase 5 → Phase 6
- **主计划**: `.cursor/plans/ai_trade_量化交易系统_725fc656.plan.md`
- **最后更新**: 2026-03-25

## 数据时效

- **数据覆盖范围**: 20250922 ~ 20260323 (半年)
- **最后拉取时间**: 2026-03-23
- **分钟表分区范围**: 2025-09 ~ 2026-03 (超出此范围需先建新分区)
- **分钟数据清理**: `scripts/cleanup_minutes.py` 自动清理6个月前的分区
- **注意**: 数据是离线快照，增量更新见 `scripts/daily_sync.py`

## 已完成

- [x] **Phase 1**: 骨架 + 模型 + Tushare封装 + 半年日线/指标/指数/分钟数据 + DataLoader + 增量同步
- [x] **Phase 2a (P2-Core)**: 前端交易控制台 (React19+Vite+AntD5+klinecharts+Storybook+设计Token)
- [x] **Phase 3** (10 Steps): Redis(Memurai) + shared/interfaces/(通信协议) + SimOrder/SimTrade等DB模型 + OMS(order_manager/position_book/account) + 风控(pre_trade/realtime/kill_switch) + 撮合(matcher+fee+slippage) + 行情Feed(Redis pub/sub→WS) + REST API + 可观测性(heartbeat/audit/daily_summary) + 前端对接(useQuery轮询+useMarketFeed WS)
- [x] **Phase 4** (10 Steps): IStrategy接口 + 回测可信性规则(backtest-rules.mdc) + stk_limit/suspend_d数据(85万行) + 技术指标库(MA/EMA/MACD/RSI/KDJ/BOLL) + TradabilityFilter + BacktestEngine(T+1/复用OMS) + ReportGenerator(Sharpe/回撤/胜率) + MACrossover示范策略 + DB持久化(strategy_meta/backtest_run/promotion_history) + REST API(4端点) + 前端回测页(/backtest)
- [x] **Phase 4.5** (5 Steps): 手动交易UI(下单Modal/平仓/改单/K线快捷下单/账户重置) + MarketDataScheduler(实时行情调度) + StrategyRunner(策略实时执行) + 假数据替换(StrategyPanel/LogPanel对接API) + 路由实体化(5个独立页面)
- [x] **Phase 4.6** (4 Steps): OMS状态持久化(DB写回+重启恢复) + 启动自检(数据时效+增量更新+OMS恢复) + 盘中自动化(scheduler自启+交易日历+watch_codes) + 收盘结算(end_day+日终数据同步)
- [x] **Phase 4.7**: 模拟盘A股市场规则合规 — T+1交割(available_qty) + 涨停不买/跌停不卖/一字板拦截(SimMatcher) + 限价单涨跌停校验(api) + 整手100股校验 + 价格tick 0.01校验 + 涨跌停限价缓存(每日自动加载)
- [x] **P2-Plus**: 资讯仪表盘 — Dashboard重做(K线+排行榜+新闻公告) + K线多周期(分时/日/周/月) + 7个排行榜面板(板块涨跌/股票涨跌/换手率/主力净流入/全球指数) + Sidebar新闻快讯(6源5秒轮询+WS推送+3天清理+来源标注) + 个股新闻(按股票名称匹配)/公告/互动问答面板 + 拼音首字母搜索 + 新Tushare API(moneyflow_dc/news/anns_d/concept/irm_qa_sh/irm_qa_sz等) + 新DB表5个 + 性能索引4个 + 同步脚本3个 + 分钟数据清理脚本
- [x] **P2-Plus-Opt**: 性能优化 & 数据增强 — TushareService全部方法补fields参数(减少网络传输) + 8个脚本补try-except错误处理(失败不中断后续) + news/anns批量INSERT(execute_values替代逐行) + scheduler新闻DRY重构(复用pull_news.fetch_latest_news) + 新增3个API(stock_st/adj_factor/sw_daily) + stock_st动态ST风控(替代名称静态匹配) + adj_factor前复权支持(DataLoader.daily_qfq) + sw_daily板块排行升级(真实申万行业指数替代AVG近似)

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
| stock_limit | 858,468 | 每日涨跌停价格 (Phase 4) |
| suspend_d | 1,428 | 每日停复牌 (Phase 4) |
| moneyflow_dc | 0+ | 个股资金流向 (P2-Plus) |
| stock_news | 0+ | 市场新闻快讯 (P2-Plus) |
| stock_anns | 0+ | 公司公告 (P2-Plus) |
| concept_list | 0+ | 概念板块列表 (P2-Plus) |
| concept_detail | 0+ | 概念板块成分 (P2-Plus) |
| stock_st | 0+ | ST股票每日列表 (P2-Plus-Opt) |
| adj_factor | 0+ | 复权因子 (P2-Plus-Opt) |
| sw_daily | 0+ | 申万行业指数日线 (P2-Plus-Opt) |
| index_global | 1,443 | 国际指数日线12个×半年 (P2-Plus-Data) |
| stk_auction | 0+ | 集合竞价成交 (P2-Plus-Data) |
| eco_cal | 0+ | 全球财经日历 (P2-Plus-Data) |
| moneyflow_ind_ths | 0+ | THS行业资金流向 (P2-Plus-Data) |
| sim_orders | 0+ | 模拟订单 (Phase 3) |
| sim_trades | 0+ | 模拟成交 (Phase 3) |
| sim_positions | 0+ | 模拟持仓快照 (Phase 3) |
| sim_account | 1 | 模拟账户 (单行, id=1) |
| audit_log | 0+ | 审计日志 (Phase 3) |
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
    main.py                 -- FastAPI入口 + CORS + WS bridge + P2-Plus REST端点
    shared/
      interfaces/
        types.py            -- Enums (OrderSide/Status/Type, RiskAction, AuditAction)
        models.py           -- Pydantic models (BarData含pre_close/Signal/Order/Position含available_qty/Account等)
      models/
        base.py             -- DeclarativeBase
        stock.py            -- 所有ORM (StockBasic~ConceptDetail+StockST+AdjFactor+SwDaily+StkAuction+EcoCal+MoneyflowIndThs+IndexGlobal, 共26个表)
      data/data_loader.py   -- DataLoader (异步, 含排行榜/板块/资金流/新闻/周线/月线/ST查询/复权/前复权日线/集合竞价/财经日历/行业资金流向/国际指数)
      data/pinyin_cache.py  -- 拼音首字母搜索缓存 (5400+股票内存映射, lazy-load)
    research/
      data/tushare_service.py -- TushareService (频次控制+重试+fields优化, 含stock_st/adj_factor/sw_daily/rt_k/rt_idx_k/stk_mins/stk_auction/stk_auction_o/eco_cal/moneyflow_ind_ths等27个封装方法)
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
      feed/                 -- MarketFeed + WSManager + scheduler.py (rt_k 1.2s全市场统一轮询 + 新闻9源5秒轮询+WS推送+3天清理)
      observability/        -- 心跳 + 审计日志 + 每日摘要
  alembic/                  -- 迁移 (仅管常规表)

scripts/
  init_data.py              -- stock_basic + trade_cal + stock_daily
  pull_batch1.py            -- daily_basic + index_*
  create_min_partitions.py  -- stock_min_kline 月分区
  pull_minutes.py           -- 1min数据 (--test N / --resume)
  pull_stk_limit.py         -- 涨跌停 + 停复牌数据 (Phase 4)
  sync_incremental.py       -- 增量同步 (--dry-run)
  daily_sync.py             -- 日终综合同步 (含moneyflow/news/anns/stk_auction/eco_cal/moneyflow_ind/index_global)
  pull_moneyflow.py         -- 个股资金流向 (P2-Plus)
  pull_news.py              -- 新闻快讯 (P2-Plus, 含fetch_latest_news公共函数供scheduler复用)
  pull_anns.py              -- 公司公告 (P2-Plus)
  pull_st_list.py           -- ST股票列表 (P2-Plus-Opt)
  pull_adj_factor.py        -- 复权因子 (P2-Plus-Opt)
  pull_sw_daily.py          -- 申万行业指数日线 (P2-Plus-Opt)
  pull_stk_auction.py       -- 集合竞价成交 (P2-Plus-Data)
  pull_eco_cal.py           -- 全球财经日历 (P2-Plus-Data)
  pull_moneyflow_ind.py     -- THS行业资金流向 (P2-Plus-Data)
  pull_index_global.py      -- 国际指数日线12个 (P2-Plus-Data)
  cleanup_minutes.py        -- 清理超6个月分钟数据分区 (P2-Plus)

frontend/                   -- React 19 + TypeScript + Vite + Storybook
  src/
    pages/Dashboard.tsx     -- 控制台首页 (K线多周期+个股新闻公告+7个排行榜面板)
    pages/KlinePage.tsx     -- 独立K线页 (多周期支持)
    pages/PositionsPage.tsx -- 持仓明细页 (平仓/清仓)
    pages/OrdersPage.tsx    -- 订单管理页 (新建/改单)
    pages/HistoryPage.tsx   -- 历史成交+审计日志 (Tabs)
    pages/RiskPage.tsx      -- 风控页 (风控+行情调度器)
    pages/StrategyPage.tsx  -- 策略管理页 (配置/启停)
    components/
      KlineChart.tsx        -- K线图表 (支持分时/日K/周K/月K)
      SidebarNews.tsx       -- 左侧Sidebar新闻快讯滚动区 (P2-Plus, 点击查看全文Modal)
      StockNewsPanel.tsx    -- 个股新闻/公司公告/互动问答Tabs (P2-Plus)
      rankings/             -- 7个排行榜面板 (P2-Plus)
        RankTable.tsx       -- 排行榜通用基础表格组件
        SectorGainPanel.tsx -- 板块涨幅榜
        SectorLosePanel.tsx -- 板块跌幅榜
        StockGainPanel.tsx  -- 涨幅榜TOP10
        StockLosePanel.tsx  -- 跌幅榜TOP10
        TurnoverPanel.tsx   -- 换手率榜TOP10
        MoneyFlowPanel.tsx  -- 主力净流入TOP10
        GlobalIndexPanel.tsx-- 全球指数
      Panel.tsx, AccountCard.tsx, OrderSubmitForm.tsx, PositionTable.tsx,
      OrderTable.tsx, RiskPanel.tsx, StrategyPanel.tsx, LogPanel.tsx 等
    layouts/MainLayout.tsx  -- Sidebar导航 + SidebarNews新闻区
    services/api.ts         -- 后端API调用 (含P2-Plus 10个新API) + useMarketFeed WebSocket
    services/useMarketFeed.ts -- WS hook (行情+新闻推送双通道)
```

## 已有API端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/v1/stock/search?q=` | 股票搜索(代码/名称/拼音首字母) |
| GET | `/api/v1/stock/{ts_code}/daily` | 个股日线+基本面 |
| GET | `/api/v1/stock/{ts_code}/weekly` | 个股周K线 (P2-Plus) |
| GET | `/api/v1/stock/{ts_code}/monthly` | 个股月K线 (P2-Plus) |
| GET | `/api/v1/stock/{ts_code}/minutes` | 个股分钟K线 (P2-Plus) |
| GET | `/api/v1/stock/{ts_code}/news` | 个股新闻 (P2-Plus) |
| GET | `/api/v1/stock/{ts_code}/anns` | 公司公告 (P2-Plus) |
| GET | `/api/v1/stock/{ts_code}/irm_qa` | 互动问答 (irm_qa_sh/irm_qa_sz) |
| GET | `/api/v1/market/snapshot/{trade_date}` | 全市场截面 |
| GET | `/api/v1/market/rankings` | 涨幅/跌幅/换手率排行 (盘中实时rt_k/盘后daily) |
| GET | `/api/v1/sector/rankings` | 板块涨跌幅排行 (盘中实时聚合/盘后sw_daily) |
| GET | `/api/v1/market/moneyflow` | 主力资金流向排行 (盘后moneyflow_dc) |
| GET | `/api/v1/market/global-indices` | 全球指数 (盘中实时rt_idx_k/盘后index_daily) |
| GET | `/api/v1/market/auction` | 集合竞价成交 (P2-Plus-Data) |
| GET | `/api/v1/market/eco-cal` | 全球财经日历 (P2-Plus-Data) |
| GET | `/api/v1/market/moneyflow-ind` | THS行业资金流向 (P2-Plus-Data) |
| GET | `/api/v1/market/news` | 市场新闻快讯 (P2-Plus) |
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
| `/` | Dashboard.tsx | 已实现 (K线多周期+个股新闻公告+7个排行榜面板) |
| `/kline` | KlinePage.tsx | 已实现 (独立K线详情) |
| `/positions` | PositionsPage.tsx | 已实现 (持仓明细 + 平仓/清仓) |
| `/orders` | OrdersPage.tsx | 已实现 (订单管理 + 新建订单 + 改单) |
| `/history` | HistoryPage.tsx | 已实现 (历史成交 + 审计日志 Tabs) |
| `/risk` | RiskPage.tsx | 已实现 (风控 + 行情调度器) |
| `/strategy` | StrategyPage.tsx | 已实现 (策略配置 + 启停 + 参数编辑) |
| `/backtest` | BacktestPage.tsx | 已实现 (策略回测) |

## 核心指数代码

000001.SH(上证), 399001.SZ(深证), 399006.SZ(创业板), 000300.SH(沪深300), 000905.SH(中证500), 000688.SH(科创50), 899050.BJ(北证50)

## 待做

- [x] **Phase 4**: 策略框架与回测系统
- [x] **Phase 4.5**: 模拟盘闭环
- [x] **Phase 4.6**: 日运行生命周期
- [x] **Phase 4.7**: 模拟盘A股市场规则合规
- [x] **P2-Plus**: 资讯仪表盘
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
| 实时行情: rt_k 1.2s全市场轮询 | 每1.2s ONE call `6*.SH,0*.SZ,3*.SZ,9*.BJ`→~5400股全量快照, 同时服务: 撮合(watched bars)+排行榜+板块聚合+WS推送, 极限50次/分钟 |
| 模拟盘A股规则合规 | T+1/涨跌停/一字板/整手/tick, 与回测引擎规则对齐 |
| Dashboard=信息决策中心 | P2-Plus: 交易组件各自路由已有, Dashboard改为K线+排行榜+新闻 |
| 分钟数据6个月清理 | cleanup_minutes.py 自动DROP超期分区, 节省~67GB/年 |
| 已接入所有Tushare权限 | moneyflow_dc/major_news/anns_d/concept/index_global/stk_auction/eco_cal/moneyflow_ind_ths等全量API |
| 新闻9源轮询+WS推送 | 9个来源(sina/cls/eastmoney/wallstreetcn/10jqka/yuncaijing/fenghuang/jinrongjie/yicai)每5s轮询一个→Redis pub/sub→WS推送→前端自动刷新+来源彩色标签, 全天候, 3天清理, 去重 |
| TushareService全量fields | 所有API默认只拉需要的字段, 减少传输量+解析开销 |
| 批量INSERT(execute_values) | pull_news/pull_anns从逐行INSERT改为批量, 性能提升10-50x |
| stock_st动态ST风控 | 按交易日查DB替代静态名称匹配, 支持ST摘帽/戴帽时间线 |
| adj_factor前复权 | DataLoader.daily_qfq()按最新因子前复权, 回测更准确 |
| sw_daily板块排行 | 直接查申万行业指数替代AVG(pct_chg)近似, 数据权威 |
| 脚本全面try-except | 单日/单项API失败不中断整体sync流程, 记录failed列表 |
| pypinyin内存缓存 | 5400+股票拼音首字母lazy-load, 支持YTLF→云天励飞式搜索 |
| irm_qa直接查Tushare | 互动问答不入库, 按SH/SZ自动路由irm_qa_sh/irm_qa_sz |
| 新闻WS推送 | scheduler拉新闻后Redis publish→WS bridge→前端invalidateQueries |

## 已知限制

- `stock_min_kline` 在 Alembic 迁移链之外，schema变更需手动SQL
- API返回的DataFrame中有NaN值，`main.py` 里用 `_df_to_records()` 处理
- klinecharts 为 Canvas 渲染，不支持 CSS 变量，颜色硬编码在 `COLORS` 常量
- moneyflow_dc/stock_news/stock_anns/stock_st/adj_factor/sw_daily/stk_auction/eco_cal/moneyflow_ind_ths 表初始为空，首次需运行 `daily_sync.py` 或单独脚本拉取数据；之后新闻每5秒自动刷新+WS推送(全天候), 超3天自动清理, 收盘后 daily_sync 全量同步
- Tushare API 名称: 新闻=`news`（参考文档接口名），公告=`anns_d`（非`anns`）
- 个股新闻查询用股票名称+代码数字在 content 中 ILIKE 匹配（Tushare major_news 不按个股分类）
- stock_daily/daily_basic 有 trade_date 索引（手动创建，不在 Alembic 内）

## 环境信息

- **OS**: Windows 10
- **Python**: 3.12.4, venv at `.venv/`
- **PostgreSQL**: 18+, DB: `ai_trade`
- **Redis**: Memurai (端口6379, Windows服务自动启动)
- **后端**: `backend/` 下 `uvicorn app.main:app --port 8000`
- **前端**: `frontend/` 下 `npm run dev` (端口5173)
- **Storybook**: `frontend/` 下 `npm run storybook` (端口6006)
