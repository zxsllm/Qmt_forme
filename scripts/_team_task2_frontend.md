# Task 2: 投资决策中枢页面 (Command Center)

## 目标
新建前端页面 `CommandCenter`，一屏整合所有投资决策信息。

## 路由
- 路径: `/command`
- 在 `App.tsx` 添加路由
- 在 `MainLayout.tsx` 侧边栏添加菜单项（图标用 AimOutlined 或 DashboardOutlined，放在第一个位置）

## 页面布局 (响应式两列)

```
┌─────────────────────────────────────────────────────────┐
│ 顶栏: 市场温度计 + 日期 + 大盘快照(上证/深成/创业板)     │
├──────────────────────────┬──────────────────────────────┤
│ 左列 (60%)               │ 右列 (40%)                   │
│                          │                              │
│ [Card] 今日早盘计划       │ [Card] 信号排行榜 TOP 20     │
│  - watchlist 表格        │  - 综合评分柱状图             │
│  - 目标价/止损位          │  - 四维雷达图(选中股)        │
│  - 入场条件              │  - 点击查看详情              │
│                          │                              │
│ [Card] 昨日复盘结论       │ [Card] 风险警报              │
│  - 市场总结(markdown)    │  - ST预警                    │
│  - 策略结论              │  - 炸板风险                   │
│  - 准确率追踪            │  - 重大负面新闻              │
│                          │                              │
│ [Card] 计划执行验证       │ [Card] 快捷操作              │
│  - 计划 vs 实际对比      │  - 快捷下单按钮              │
│  - 偏差分析              │  - 杀停开关                  │
└──────────────────────────┴──────────────────────────────┘
```

## 数据源 (已有 API)

1. **早盘计划**: `api.planData(tradeDate)` → GET /api/v1/plan/data/{trade_date}
2. **昨日复盘**: `api.reviewData(tradeDate)` → GET /api/v1/review/data/{trade_date}
3. **计划历史**: `api.planHistory()` → GET /api/v1/plan/history
4. **市场温度**: `api.marketTemperature(tradeDate)` → GET /api/v1/sentiment/temperature
5. **风险警报**: `api.riskAlerts()` → GET /api/v1/risk/alerts (如果不存在先检查)
6. **信号排行**: 新端点 GET /api/v1/signals/ranked (Task 1 创建)
7. **杀停开关**: `api.killSwitch()` / `api.killSwitchOff()`

## 前端 API 客户端扩展

在 `services/api.ts` 添加:
```typescript
// 信号排行
signalRanked: (tradeDate = '', limit = 50, minScore = 0) =>
  fetchJson<SignalRankedResp>(`/api/v1/signals/ranked?trade_date=${tradeDate}&limit=${limit}&min_score=${minScore}`),

// 计划数据
planData: (tradeDate: string) =>
  fetchJson<PlanDataResp>(`/api/v1/plan/data/${tradeDate}`),

// 复盘数据
reviewData: (tradeDate: string) =>
  fetchJson<ReviewDataResp>(`/api/v1/review/data/${tradeDate}`),
```

## UI 规范
严格遵循 `frontend/CLAUDE.md` 的 VoidCore 深空玻璃拟态:
- 面板: glass 渐变背景 + blur + inset shadow
- 色板: --bg-deep, --bg-mid, --blue, --red, --orange 等
- 圆角: 大面板 24px / 卡片 22px / 按钮 14px
- 使用 `Panel` 组件包裹每个 Card

## 关键组件

1. **MarketBar**: 顶部横条，显示温度 + 3 大指数涨跌
2. **PlanCard**: 早盘计划卡片，watchlist 用 Ant Design Table
3. **ReviewCard**: 复盘结论卡片，market_summary 渲染 markdown
4. **SignalRankCard**: 信号排行，柱状图 + 点击展开雷达图
5. **RiskAlertCard**: 风险警报列表，按严重度排序
6. **QuickActionCard**: 快捷下单 + 杀停开关

## 文件清单
- 新建: `frontend/src/pages/CommandCenter.tsx`
- 修改: `frontend/src/App.tsx` (路由)
- 修改: `frontend/src/layouts/MainLayout.tsx` (菜单)
- 修改: `frontend/src/services/api.ts` (新 API 类型+调用)

## 注意
- 信号排行 API 可能还没就绪，用 useQuery + enabled 控制，API 404 时优雅降级显示"评分引擎加载中"
- planData / reviewData 可能已在 api.ts 中定义，先检查再添加
- 日期默认用今天(交易日)，提供日期选择器切换历史
