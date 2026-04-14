# Task 1: StockScorer 信号聚合评分引擎

## 目标
创建 `backend/app/shared/stock_scorer.py`，整合四维数据为单一可排序的综合评分。
新增 API 端点 `GET /api/v1/signals/ranked`，返回评分排行。

## 评分维度 (各 0-100 分)

### 技术面 (权重 30%)
复用 `tech_signal.py` 中已有函数:
- `consecutive_limit_count` → 连板数，每板 +20 分(上限 100)
- `volume_anomaly` → ratio>2 得 80，ratio>1.5 得 60，ratio>1 得 40
- `gap_analysis` → 向上跳空 +30，向下跳空 -30
- `support_resistance` → 接近支撑 +20，接近阻力 -20
- `indicator_snapshot` → RSI<30 超卖 +30，RSI>70 超买 -30；MACD 金叉 +20

### 情绪面 (权重 25%)
复用 `sentiment.py`:
- `market_temperature` → 温度为"热"/"偏热" +60-80，"冷"/"偏冷" -30
- 个股是否在涨停榜 → +40
- 个股是否在龙虎榜 → +30
- 板块是否为当日热门 → +20

### 基本面 (权重 25%)
复用 `fundamental.py`:
- PE_TTM 百分位(行业内) → 低于 30% 得 70，低于 50% 得 50
- ROE > 15% 得 80，> 10% 得 60
- 营收增速 > 20% 得 70，> 10% 得 50
- 净利润增速 > 30% 得 80

### 消息面 (权重 20%)
复用 `news_classifier.py` 的关键词:
- 最近 3 天正面新闻数 vs 负面新闻数 → 净正面每条 +15(上限 60)
- 重大公告(业绩预增/中标/战略合作) → +40

## API 设计

```python
# GET /api/v1/signals/ranked?trade_date=20260411&limit=50&min_score=60
# Response:
{
  "trade_date": "20260411",
  "scored_stocks": [
    {
      "ts_code": "000001.SZ",
      "name": "平安银行",
      "total_score": 78.5,
      "tech_score": 65,
      "sentiment_score": 80,
      "fundamental_score": 85,
      "news_score": 70,
      "signals": ["volume_surge", "limit_board", "roe_high"],
      "tech_detail": {...},
      "sentiment_detail": {...},
      "fundamental_detail": {...},
      "news_detail": {...}
    }
  ],
  "market_overview": {
    "temperature": "偏热",
    "avg_score": 52.3,
    "high_score_count": 15
  }
}
```

## 实现要点

1. **stock_scorer.py** 核心类 `StockScorer`:
   - `async def score_stock(session, ts_code, trade_date) -> StockScore`
   - `async def rank_stocks(session, trade_date, limit, min_score) -> list[StockScore]`
   - `rank_stocks` 不需要遍历全部 5000+ 股票，先用 SQL 预筛选:
     - 当日有交易(stock_daily 存在)
     - 非停牌、非ST(除非连板)
     - 换手率 > 1% 或成交额 > 5000万
   - 预筛后约 500-1000 只，再逐只评分

2. **路由注册**: 在 `main.py` 新增 `from app.shared.stock_scorer import scorer_router`，`app.include_router(scorer_router)`

3. **NaN 处理**: 使用统一的 `_clean_float()` 函数，不要再写新的

4. **性能**: 评分计算要快(<3 秒)，大量用 SQL 批量查询而非逐条

## 文件清单
- 新建: `backend/app/shared/stock_scorer.py`
- 修改: `backend/app/main.py` (注册 router)
