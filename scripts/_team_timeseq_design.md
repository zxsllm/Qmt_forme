# 决策中枢时序逻辑设计

## 背景
决策中枢 CommandCenter 在不同日期/时段显示的数据时序混乱。需要定义清晰的规则。

## 核心概念
- **selected_date**: 用户在 DatePicker 选择的日期
- **last_trade_date**: 最近的交易日(如果 selected_date 是非交易日，回退到上一个交易日)
- **prev_trade_date**: last_trade_date 的前一个交易日

## 当前 Bug (从截图观察)

### Bug 1: 方向矛盾
- 4/12(周日) 显示"偏多 置信78%" — 因为 yesterday_review 回退到 4/10 的 review
- 4/10(周五) 显示"待分析" — 因为 plan_data(4/10) 的 yesterday_review 是 4/9 的，可能没有 strategy_conclusion
- 根因: ActionBanner 的方向来源不一致，非交易日和交易日取不同字段

### Bug 2: 温度/涨跌停矛盾
- 4/12: 温度"中性"，涨跌停 0/0/0，封板 0% — 因为 reviewData(4/12) 查不到数据
- 4/10: 温度"偏热"，涨跌停 77/12/34，封板 6940% — 6940% 是 seal_rate 重复 ×100
- 根因: 不同 panel 取数逻辑不统一

### Bug 3: 封板率 6940%
- seal_rate 在 DB 中已是 0-100 的百分比值(如 69.4)
- 前端又做了 `seal_rate * 100`，变成 6940%

## 正确的时序规则

### 场景 1: 非交易日 (周末/节假日)
用户选 4/12(周日):
- **自动回退**: selected_date → last_trade_date = 4/10(周五)
- **ActionBanner**: 显示 4/10 的数据，标注"(上一交易日 04-10)"
- **WatchlistCards**: 显示 4/10 早盘计划的 watchlist
- **ReviewCard**: 显示 4/10 收盘后的复盘(4/10 的 review)
- **SignalRankCard**: 显示 4/10 的信号排行
- **PlanVerification**: 显示 4/10 的计划验证

### 场景 2: 交易日盘前 (开盘前, < 09:30)
用户选今天(假设今天是交易日):
- **ActionBanner**: 显示今天早盘计划的方向(08:00 生成)
- **WatchlistCards**: 显示今天的 watchlist
- **ReviewCard**: 显示昨天收盘的复盘
- **SignalRankCard**: 显示"盘前暂无信号"(今天还没交易)
- **PlanVerification**: 显示昨天的计划验证

### 场景 3: 交易日盘中 (09:30 ~ 15:00)
- **ActionBanner**: 同盘前
- **SignalRankCard**: 可能有实时数据(如果 scorer 支持)，否则显示昨天的

### 场景 4: 交易日盘后 (> 15:00)
- **ActionBanner**: 今天计划 + 今天实际结果
- **ReviewCard**: 如果 16:00 后，显示今天的复盘；否则显示昨天的
- **SignalRankCard**: 显示今天的信号排行

### 场景 5: 用户选择历史日期 (如 4/10)
- **ActionBanner**: 显示 4/10 的计划方向 + 4/10 的指数数据
- **WatchlistCards**: 显示 4/10 的 watchlist
- **ReviewCard**: 显示 4/10 的 review (4/10 收盘后生成的)
- **SignalRankCard**: 显示 4/10 的信号排行
- **PlanVerification**: 显示 4/10 的验证

## 数据源统一规则

ActionBanner 的方向应该来自:
1. 首选: plan_data(date).yesterday_plan.predicted_direction (当日计划的预测方向)
2. 次选: review_data(date) 的 strategy_conclusion (当日复盘的结论)
3. 兜底: "待分析"

温度和涨跌停应该来自:
1. 首选: review_data(date) 的 temperature 数据
2. 次选: plan_data(date).yesterday_review 的温度
3. 非交易日: 自动回退到 last_trade_date

指数数据应该来自:
1. review_data(date) 的 index_summary (当日的指数收盘)
2. 非交易日回退到 last_trade_date

## 实现方案

### 后端: 新增交易日解析
plan_api.py 和 review_api.py 在收到非交易日请求时，自动回退到 last_trade_date:
```python
async def _resolve_trade_date(session, date_str):
    """如果 date_str 不是交易日，回退到最近的交易日"""
    r = await session.execute(text("""
        SELECT cal_date FROM trade_cal
        WHERE is_open = '1' AND cal_date <= :d
        ORDER BY cal_date DESC LIMIT 1
    """), {"d": date_str})
    row = r.fetchone()
    return row[0] if row else date_str
```
返回数据中增加 `resolved_trade_date` 字段让前端知道实际日期。

### 前端: ActionBanner 数据源统一
1. 方向: 从 planData.yesterday_plan?.predicted_direction 取
2. 温度: 从 reviewData 取，没有则从 planData.yesterday_review 取
3. 指数: 从 reviewData.index_summary 取
4. 封板率: 修复 ×100 bug
5. 非交易日: 显示 "(数据日期: 04-10)"

## 文件清单
- 修改: backend/app/shared/plan_api.py — 增加交易日回退
- 修改: backend/app/shared/review_api.py — 增加交易日回退
- 修改: frontend/src/pages/CommandCenter.tsx — 统一数据源 + 显示回退日期提示
