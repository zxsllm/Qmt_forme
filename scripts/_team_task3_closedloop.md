# Task 3: 复盘-计划自动闭环验证

## 目标
实现计划的自动回溯验证，形成"预测→验证→学习→改进"正向循环。

## 1. 自动回溯验证模块

新建 `backend/app/shared/plan_verifier.py`:

```python
async def auto_verify_plan(trade_date: str) -> dict:
    """收盘后自动验证当日早盘计划 vs 实际结果。
    
    对比维度:
    1. 市场方向预测: plan.outlook vs 实际涨跌
    2. watchlist 个股: 目标价触达率、止损触发率
    3. 风险预警命中: 预警的风险是否实际发生
    4. 板块预测: 预测的热门板块 vs 实际热门板块
    
    Returns: {accuracy_score: float, actual_result: str, details: dict}
    """
```

### 评分规则:
- **方向准确** (30分): 预测涨/跌/震荡 vs 上证实际涨跌幅
  - 方向一致 → 30分
  - 预测震荡且实际涨跌<1% → 30分
  - 方向相反 → 0分
- **watchlist 命中** (30分): 推荐个股中实际上涨的比例 × 30
- **风险预警** (20分): 预警的风险事件实际发生比例 × 20
- **板块准确** (20分): 预测热门板块与实际 TOP5 重叠数 / 5 × 20

### 数据来源:
- 当日计划: `daily_plan` 表 (watchlist_json, risk_alerts_json 等)
- 实际结果: `stock_daily` + `daily_basic` + `index_daily` (当日收盘数据)
- 板块数据: 通过 review_api 的板块聚合逻辑

## 2. 调度集成

在 `execution/feed/scheduler.py` 的收盘后流程中添加:
- 在 REVIEW_TIME (16:00) 完成复盘数据聚合后
- 调用 `auto_verify_plan(today)` 自动填充 accuracy_score
- 调用 `PATCH /api/v1/plan/retrospect/{trade_date}` 或直接写 DB

## 3. 历史准确率注入

修改 `plan_api.py` 的 `GET /api/v1/plan/data/{trade_date}` 端点:
在返回数据中增加 `accuracy_history` 字段:

```python
# 查询最近 N 天的计划准确率
accuracy_history = await _get_recent_accuracy(session, trade_date, days=10)
# 返回: {"avg_accuracy": 65.2, "trend": "improving", "recent_scores": [70, 55, 80, ...]}
```

这个数据会被 morning_plan_cli.sh 注入到 Claude prompt 中，让 AI 知道自己最近的预测表现，从而自我校正。

## 4. 相似日激活

修改 `plan_api.py` 的数据聚合，激活已有的 pgvector 相似搜索:
- 调用 `GET /api/v1/plan/similar/{trade_date}` 获取最相似的 3 个历史交易日
- 将这些相似日的计划+实际结果作为参考注入返回数据
- 格式: `similar_days: [{date, plan_summary, actual_result, accuracy_score}]`

## 文件清单
- 新建: `backend/app/shared/plan_verifier.py`
- 修改: `backend/app/shared/plan_api.py` (增加 accuracy_history + similar_days)
- 修改: `backend/app/execution/feed/scheduler.py` (添加自动验证调度)
  - 注意: scheduler.py 可能有 REVIEW_TIME 相关逻辑，在其后添加验证步骤

## 注意事项
- daily_plan 表的 `plan_verified`, `accuracy_score`, `actual_result` 字段应该已存在(探索结果提到)，先检查 ORM 模型确认
- 如果字段不存在，需要创建 Alembic 迁移添加
- 验证逻辑要容错: 如果当日计划不存在或数据不全，跳过不报错
