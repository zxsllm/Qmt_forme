# 题材主线人工标签处理流程（板块必读 / 韭研公社）

> 当用户在对话中粘贴板块必读 / 韭研公社的复盘截图时，按本文档流程处理。
> 触发短语示例：「按 sector review 流程处理」「这是 X/Y 的板块必读」「这是 X/Y 的韭研复盘」。

---

## 一、来源与可信度

| 来源 | 更新时间 | 信任度 | 用途 |
|---|---|---|---|
| 板块必读（公众号） | 当晚 ~20:00 | **更高** | 主线判定的最终标签；冲突时以此为准 |
| 韭研公社 | 当日 ~17:00 | 次之 | 早入库；用于早期算法对照 |

**规则**：同一交易日两个来源都到位时，板块必读覆盖韭研的主线判定。
DB 字段 `source ∈ {'bankuai','jiuyan'}` 显式区分。

起算日：**2026-05-06**（节后第一个交易日）。

---

## 二、两类截图的字段映射

### 2.1 板块必读（典型版）

通常 2-3 张图：

**图 A：首板汇总（如 `首板(61)` 网格）**
- 列出当日所有首板股票，按板块分组（每行 5 只）
- 提取：`板块名` + `股票名` + `涨停时间`（不一定都有）
- 入库：`source='bankuai'`、`board_count=1`、`days_to_board=1`、`is_main_line=False`

**图 B：小盘主线 / 大盘主线（柱状表格） — 月度主线**
- 表头："小盘主线股（X月）" / "大盘主线股"
- 表列：主线（板块名）、核心标记、股票名、1月涨幅 / 成交额（亿）、当日涨幅
- ⚠️ **重要语义**：板块必读这里是**月度主线**——按整月走势聚合，与"当日是否涨停"无关。
  当日回调的票仍可能是月度主线（持续性强）。
- 入库：`source='bankuai'`、`is_main_line=True`、`market_cap_tier='small'|'large'`、
  `keywords` 存"核心"标记、`raw_meta = {"scope": "monthly", "month": "YYYYMM"}` 区分

**图 D：板块最强转债（典型版第三张）**
- 表头：概念板块 / 转债名称 / 涨跌幅 / 成交额（亿）
- 入库：`source='bankuai'`、`ts_code` 用转债代码（无则只填 stock_name）、
  `raw_meta = {"scope": "cb_strongest"}` 标记

### 2.3 当日主线 vs 月度主线（区分约定）

| scope | 来源 | 含义 | 用途 |
|---|---|---|---|
| `daily` | 韭研全天复盘 / 板块必读连板天梯顶部摘要 | 当日涨停反推的题材主线 | 算法 B 训练目标 |
| `monthly` | 板块必读小盘/大盘主线柱状图 | 整月走势聚合的主线 | 题材股池、长持参考 |
| `cb_strongest` | 板块必读最强转债图 | CB 主线 | 跟风债策略候选池 |

`raw_meta.scope` 字段区分。同一只票可同时存在多个 scope 的记录。

### 2.2 韭研公社（典型版）

**图 C：全天涨停复盘简图（按板块分组的大表）**
- 顶部按板块分组（如`国产芯片*9`、`电池产业链*7`），数字 = 该板块当日涨停只数
- 表头：板数、代码、个股、涨停时间、流通市值（亿）、成交额（亿）、涨停关键词
- 板数样式：`10天8板`、`3天3板`、`2天2板`、`1`（首板）
- 提取：每一行完整入库
- 入库：`source='jiuyan'`、`sector_size`=板块名后的数字、`board_count` & `days_to_board` 解析自"X天Y板"
- 行尾"破板率/涨停数/连板数"作为 raw_meta 整页统计存到 `sector_name='__summary__'` 的特殊行

---

## 三、入库 SQL 模板

```sql
INSERT INTO daily_sector_review (
    trade_date, source, sector_name, sector_rank, sector_size,
    ts_code, stock_name, board_count, days_to_board, limit_time,
    float_mv, amount, keywords, is_main_line, market_cap_tier, raw_meta
) VALUES (...);
```

**唯一性约定**（无 DB 唯一约束，由处理流程保证）：
同一 `(trade_date, source, sector_name, ts_code)` 组合只插一行；重复入库前先 DELETE。

---

## 四、处理流程（ Claude 视角的逐步 SOP）

```
1. 用户粘图 + 一句日期/来源（如"5/6 板块必读"）
   ↓
2. 识别图类型：
   - 看到"小盘主线 / 大盘主线" → 板块必读（图 B）
   - 看到"首板(N)" 网格 → 板块必读（图 A）
   - 看到"韭研公社全天涨停复盘简图" 红蓝表 → 韭研（图 C）
   ↓
3. OCR：直接由当前对话的多模态 Claude 识别（精度最高）
   - 输出结构化 list[dict]，字段对应 DailySectorReview ORM
   - 解析"X天Y板"为 days_to_board / board_count
   ↓
4. 校验 + 落库：
   - 转账(trade_date, source) 删除已有行
   - 批量 INSERT 新行
   - 如同时拿到 2 类来源，分别落库不合并
   ↓
5. 反馈给用户：
   - 已入库 N 行
   - 主线 = [板块1(N1), 板块2(N2), ...] (按 sector_size 倒序)
   - 是否需要立刻跑算法 B 对照？(默认是)
```

---

## 五、与算法 B 的对照

每日入库后，触发：

```python
# backend/app/research/signals/sector_main_line.py
from app.research.signals.concept_tagger import compute_main_line
auto = await compute_main_line(trade_date)  # 算法 B 输出
manual = await load_manual_review(trade_date, source='bankuai')

diff = compare(auto, manual)
# 落 diff 表 / 前端面板，作为算法调参依据
```

差异指标：
- 主线漏标率 = 人工有 / 算法没识别的板块占比
- 主线错标率 = 算法识别 / 人工没列入的板块占比
- 龙头错位率 = 人工主线下 top1 票 ≠ 算法龙1 占比

---

## 六、新对话续命（关键）

`MEMORY.md` 已索引本文档。任意新对话只要：
1. 用户提到 sector / 板块必读 / 韭研 / 截图入库
2. 或贴出明显是复盘表格 / 主线柱状图的图

→ 立即查阅本文档执行流程，不要重新定义字段或建表。

DB 表已存在：`daily_sector_review`（迁移版本 `b8a91e72f4d1`）
ORM 类位置：`backend/app/shared/models/stock.py` 末尾
