---
name: backtest-guard
description: Use when the task touches backend/app/research/backtest, backend/app/research/strategies, backend/app/execution/matcher.py, or backend/app/execution/fee.py, or when the user asks about backtest execution correctness, tradability filters, fees, slippage, or survivor bias.
---

# A股回测可信性参考

## 信号执行时机 (防偷看未来)

- bar 内信号在**下一个 bar 开盘价**执行，禁止当前 bar 内成交
- 日线: T 日收盘信号 → T+1 日开盘执行
- 引擎禁止提供当前 bar 的 close/high/low 给策略后又在同一 bar 撮合

## 不可交易过滤

| 场景 | 处理 |
|------|------|
| 涨停板买入 (目标价 >= 涨停价) | 订单取消 |
| 跌停板卖出 (目标价 <= 跌停价) | 订单取消 |
| 一字板 (open == close) | 双向拦截 |
| 停牌 (`suspend_d` 表) | 自动跳过 |
| ST 股 | 涨跌停 ±5% |
| 新股上市首日 | 不参与 |

所有过滤必须记录审计日志 (FilterReason + 原始信号)

## 复权口径

- 技术指标: **后复权** (hfq)，保证价格连续性
- 手续费/滑点: **不复权**真实价格
- 收益计算: **后复权**

## 费用模型 (A股)

- 佣金: max(成交额 × 万2.5, 5元)，双向
- 印花税: 成交额 × 0.05%，仅卖出
- 过户费: 成交额 × 0.001%，仅沪市 (.SH)，双向
- 滑点: 1 tick (0.01元) + 成交量冲击 (订单/bar量 > 1% 时加大)
- 最小: 100 股整手，单笔 ≤ bar 成交量 20%

## 幸存者偏差

- 股票池用**时点列表**，禁止用当前上市股回测历史
- 已退市股必须包含 (`stock_basic.list_status='D'`)
- 财务数据以**披露日期**为可用时间点 (非报告期)
