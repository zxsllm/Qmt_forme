---
name: ""
overview: ""
todos: []
isProject: false
---

# Phase 4: 策略框架与回测系统 — 分步执行计划

> **状态**: 规划完成, 待执行

## 核心决策


| 决策                                    | 理由                            |
| ------------------------------------- | ----------------------------- |
| 回测引擎**不复用** `TradingEngine` 单例        | 每次回测需要独立 OMS/Account 状态       |
| 回测引擎**复用** OMS/Matcher/Fee/Slippage 类 | 保证回测与模拟交易撮合逻辑一致               |
| 回测引擎同步执行                              | 数据预加载到内存后逐 bar 遍历，无需 async    |
| `IStrategy` 放 `shared/interfaces/`    | 作为 research/execution 共享的策略契约 |
| 先做**日线回测**，分钟级后续扩展                    | 降低复杂度，先跑通闭环                   |


## Step 1: backtest-rules.mdc + 策略接口定义

- `.cursor/rules/backtest-rules.mdc` — 回测可信性规则 (信号执行时机 / 不可交易过滤 / 复权 / 幸存者偏差 / 费用滑点 / 分钟特殊规则)
- `shared/interfaces/strategy.py` — IStrategy ABC (on_init / on_bar / on_stop)
- `shared/interfaces/models.py` — 新增 BacktestConfig, BacktestContext, TradeRecord, BacktestResult
- `shared/interfaces/types.py` — 新增 PromotionLevel, StrategyStatus, FilterReason 枚举
- 验收: `from app.shared.interfaces.strategy import IStrategy` 无报错

## Step 2: 拉取涨跌停 + 停复牌数据

- ORM: StockLimit, SuspendD → `shared/models/stock.py`
- Alembic migration
- TushareService 新增 `stk_limit()`, `suspend_d()`
- `scripts/pull_stk_limit.py` — 拉取半年数据 (~63万行 stk_limit + suspend_d)
- DataLoader 新增 `stk_limit()`, `stk_limit_batch()`, `is_suspended()`, `suspended_stocks()`
- 验收: `SELECT COUNT(*) FROM stock_limit` 返回合理行数

## Step 3: 技术指标库

- `research/indicators/moving_average.py` — MA, EMA, WMA
- `research/indicators/oscillators.py` — MACD, RSI, KDJ
- `research/indicators/bands.py` — BOLL
- 纯 pandas/numpy，零 DB 依赖
- 验收: 用真实 stock_daily 数据计算 MA5/MA20/MACD, 人工确认合理

## Step 4: 可信性过滤器

- `research/backtest/credibility.py` — TradabilityFilter
  - 停牌检查 (suspend_d)
  - 涨停板买入拦截 (price >= up_limit)
  - 跌停板卖出拦截 (price <= down_limit)
  - 一字板 (open == high == low == close 且涨/跌停)
  - ST 股 ±5% 限制
  - 新股上市首日
- 初始化时批量预加载到 dict，避免逐信号查 DB
- 验收: 构造测试用例，确认正确拦截

## Step 5: 回测引擎核心

- `research/backtest/engine.py` — BacktestEngine.run()
  - 预加载: daily bars, stk_limit, suspend_d, stock_basic, benchmark
  - 创建独立 OMS 实例 (OrderManager(dedup_window=0), PositionBook, AccountManager, SimMatcher)
  - 事件循环: for trade_date → fill 上日 signals (next-bar rule) → on_bar → collect signals → credibility check → queue
  - 记录 equity snapshot + 被过滤信号审计日志
- 验收: dummy 策略跑 30 天，产出 equity curve

## Step 6: 回测报告生成器

- `research/backtest/report.py` — ReportGenerator
  - 年化收益率, 最大回撤 (金额+%), 夏普比率 (rf=3%), 索提诺比率
  - 胜率, 盈亏比, 交易次数, 平均持仓天数
  - 基准对比 (vs 沪深300 000300.SH)
  - 被过滤信号统计 (按 FilterReason 分组)
- 验收: 数学公式正确

## Step 7: 示范策略 + 端到端验证

- `research/strategies/ma_crossover.py` — MA5/MA20 金叉/死叉
- `scripts/run_backtest_demo.py` — 调用 BacktestEngine + MACrossover + ReportGenerator
- 验证清单:
  - 信号 T 日产生 → T+1 开盘执行
  - 涨跌停/停牌信号被拦截，出现在 filtered 审计日志
  - 手续费和滑点正确计算
  - equity curve 合理, 报告指标正确
- 验收: `python scripts/run_backtest_demo.py` 打印完整报告

## Step 8: DB 模型 (策略 + 回测 + 晋级)

- ORM: StrategyMeta, BacktestRun, PromotionHistory → `shared/models/stock.py`
- Alembic migration
- 验收: 表存在

## Step 9: REST API 端点

- `research/api.py` — backtest_router
  - POST `/api/v1/backtest/run` — 提交回测
  - GET `/api/v1/backtest/{run_id}` — 获取结果
  - GET `/api/v1/backtest/list` — 历史列表
  - GET `/api/v1/strategies` — 可用策略
- `main.py` 注册路由
- 回测用 `asyncio.to_thread()` 避免阻塞 event loop
- 验收: curl 测试

## Step 10: 前端回测页面

- `pages/BacktestPage.tsx` — 策略选择 + 参数表单 + 运行按钮 + 结果展示
  - 统计卡片 (年化/回撤/夏普/胜率)
  - 收益曲线图
  - 交易明细表 + 被过滤信号表
- MainLayout 侧边栏 + App.tsx 路由 + api.ts 方法
- 验收: 浏览器访问 `/backtest`，运行 MA 交叉策略，看到结果

## 依赖关系

```
Step 1 (接口) ──→ Step 4 ──→ Step 5 ──→ Step 6 ──→ Step 7 ──→ Step 8 ──→ Step 9 ──→ Step 10
Step 2 (数据) ──→ Step 4
Step 3 (指标) ────────────────────────→ Step 7
```

- Step 1 和 Step 2 可并行
- Step 3 和 Step 4 可并行
- Step 5 等 Step 1+2+4
- Step 7 等 Step 3+5+6
- Step 8~10 串行

## 新增目录结构

```
backend/app/research/
  backtest/
    __init__.py
    engine.py          -- 回测引擎
    credibility.py     -- 可信性过滤器
    report.py          -- 报告生成器
  indicators/
    __init__.py
    moving_average.py  -- MA/EMA/WMA
    oscillators.py     -- MACD/RSI/KDJ
    bands.py           -- BOLL
  strategies/
    __init__.py
    ma_crossover.py    -- 示范策略
  api.py               -- REST 端点
```

