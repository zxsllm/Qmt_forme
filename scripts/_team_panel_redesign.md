# 决策中枢 Panel 重构

## 需要替换的 Panel

### 1. 风险警报 → 删除 (MonitorPage 已有完整风控)

### 2. 快捷操作 → 替换为"板块热度"
侧边栏已有导航，杀停开关在系统页。替换为有决策价值的板块热度 Panel:
- 显示当日 TOP 5 热门板块 + 涨幅
- 显示当日 TOP 5 冷门板块 + 跌幅
- 数据来源: review_api 的 sector_ranking 或 top_sectors_json

### 3. 观察标的 — 修复支撑阻力不显示

检查 price_anchors 数据链路:
- 前端 anchorMap 按 ts_code 匹配 watchlist 中的股票
- 如果 planData.price_anchors 为空或 ts_code 不匹配则不显示
- 检查 plan_api.py 的 price_anchors 返回逻辑
- 检查 premarket.py 的 price_anchors 生成逻辑
- 确保有数据返回

### 4. 复盘卡片 — 增加 reports 文件链接
用户习惯去 reports/ 文件夹看详细报告。在折叠区增加提示:
- "详细报告: reports/review_20260410.md"
- 或直接渲染报告内容(如果可以)

## 新增 Panel: 板块热度

```tsx
function SectorHeatCard({ reviewData }) {
  // 从 reviewData.sector_ranking 取 top/bottom 板块
  return (
    <Panel title="板块热度">
      <div>🔥 热门板块</div>
      {top5.map(s => <row: 板块名 + 涨幅条>)}
      <div>❄ 冷门板块</div>
      {bottom5.map(s => <row: 板块名 + 跌幅条>)}
    </Panel>
  );
}
```

## 文件清单
- 修改: frontend/src/pages/CommandCenter.tsx
  - 删除 RiskAlertCard 和 QuickActionCard
  - 新增 SectorHeatCard
  - 修复 WatchlistCards 的 price_anchors 映射
  - 修复封板率 ×100 bug
