# 题材主线判定链路（LLM v3）

> 类似 `morning_plan` / `review` 的链路，但本流程**不输出 .md 报告**——结果直接入库 `daily_sector_review` 表。
> 每天盘后调用 LLM 判断当日题材主线，作为龙头隔夜模式的板块成分输入。

---

## 一、与早盘计划/复盘的对比

| | 早盘计划 | 收盘复盘 | **题材主线判定（本链路）** |
|---|---|---|---|
| 启动脚本 | `scripts/morning_plan_cli.sh` | `scripts/review_cli.sh` | `scripts/llm_main_line.py` |
| Prompt 文件 | `scripts/prompts/morning_plan_prompt.txt` 等 | `scripts/prompts/review_prompt*.txt` | **内嵌** 在 `scripts/llm_main_line.py` 的 `PROMPT_V2` 变量 |
| LLM 调用方式 | `claude-sg --print` | `claude-sg --print` | `claude-sg --print`（subprocess + stdin）|
| 产出 | `reports/plan_YYYYMMDD.md` | `reports/review_YYYYMMDD.md` | **DB 入库**（`daily_sector_review` 表，`source='llm_v2'`）|

> Source 标签历史叫 `llm_v2`（口语版本号 v3）。Prompt 内嵌而非独立文件，因为依赖 `theme_taxonomy.py` 动态生成。

---

## 二、链路全景

```
┌──────────────────────────────────────────────────────────────┐
│  Step 1 数据拉取                                              │
│    limit_stats (当日涨停池)                                  │
│    limit_step (连续连板天数)                                 │
│    limit_list_ths.tag (THS 涨停标签：首板/X天Y板)            │
│    stock_basic.industry (主营行业)                           │
└─────────────────────┬────────────────────────────────────────┘
                      ↓
┌──────────────────────────────────────────────────────────────┐
│  Step 2 构造 Prompt（scripts/llm_main_line.py: build_prompt）│
│    - 涨停清单（ts_code|名字|连板|首封时间|流通市值|行业）    │
│    - 主线-细分概念地图（theme_taxonomy.py）                  │
│    - 4 大指引（外延/壳股/主线vs补涨/few-shot）               │
└─────────────────────┬────────────────────────────────────────┘
                      ↓
┌──────────────────────────────────────────────────────────────┐
│  Step 3 LLM 调用                                              │
│    subprocess.run([claude-sg.cmd, --print], input=prompt)    │
│    串行，不要并发（claude-sg 不支持并发）                    │
└─────────────────────┬────────────────────────────────────────┘
                      ↓
┌──────────────────────────────────────────────────────────────┐
│  Step 4 解析 + 入库                                           │
│    JSON → daily_sector_review 表（source='llm_v2'）          │
│    成为龙头隔夜模式 load_sectors(source='llm_v2') 的输入      │
└──────────────────────────────────────────────────────────────┘
```

---

## 三、核心文件清单

### 算法/数据层

| 文件 | 职责 |
|---|---|
| `backend/app/research/signals/theme_taxonomy.py` | 主线 → 细分概念外延地图（喂 LLM 用）|
| `backend/app/research/signals/long_head_detector.py` | 龙1 / 龙2 / 影子龙识别 |
| `backend/app/research/strategies/pattern_01_long1_natural.py` | 龙头隔夜模式（合并原模式 1/2） |
| `backend/app/research/strategies/base_pattern.py` | 模式基类 + load_sectors / detect_long_head |
| `backend/app/shared/models/stock.py` | `DailySectorReview` ORM（表存所有人工/LLM 标签）|

### 脚本层

**用户日常工作流（`scripts/` 根）：**

| 文件 | 职责 |
|---|---|
| `scripts/llm_main_line.py` | ⭐ 主脚本：跑 LLM 主线判定 |
| `scripts/_cache/` | 自动生成：每次跑的 prompt + LLM 原始返回（debug 用，可随时删）|

**开发期工具（`backend/scripts/`）：**

| 文件 | 职责 |
|---|---|
| `test_pattern_backtest.py` | 龙头隔夜回测（含模式 3-12）|
| `test_long_head.py` | 龙1识别测试（开发期）|
| `check_min_coverage.py` | 分钟K覆盖率扫描（运维诊断）|
| `archive/sector_imports/` | 历史人工标签入库脚本（已归档）|

---

## 四、运行方式

### 跑一次主线判定（单日）

```bash
cd E:/Project/Qmt_forme
.venv/Scripts/python.exe scripts/llm_main_line.py 20260506
```

输出：
- DB：`daily_sector_review` 表插入若干行（source='llm_v2'）
- 调试缓存：`scripts/_cache/prompt_YYYYMMDD.txt` / `llm_raw_YYYYMMDD.txt`

### 龙头隔夜回测

```bash
.venv/Scripts/python.exe backend/scripts/test_pattern_backtest.py 20260506 --pattern 1
```

`load_sectors` 默认读 `source='bankuai'`（人工标签），如需用 LLM 主线作为板块成分，传 `source='llm_v2'`。

---

## 五、注意事项

### claude-sg 并发陷阱（⚠️ 重要）
`claude-sg --print` 启动本地 proxy（127.0.0.1:18880），**不支持并发调用**。
两个任务同时跑时第二个会卡死直到 timeout。

→ 跑批量历史数据时必须**串行**（一个跑完再跑下一个）。

### 已淘汰
- ~~算法 B (concept_tagger / concept_blacklist)~~：基于 Tushare concept_detail 命中率仅 35%，已删除
- ~~LLM v1 (source='llm')~~：已被 LLM v2 替代，DB 历史数据已清
- ~~一字预测器 (long1_yizi_predictor)~~：基于全天数据预测次日是未来函数，已删除
- ~~`scripts/llm_main_line_diff.py`~~：v1 已删，对比脚本无意义

---

## 六、日常工作流（你的角色）

每个交易日：
1. **17:00 后**：把韭研复盘截图发给我
2. **20:00 后**：把板块必读 3 张图（连板天梯 / 月度主线 / 最强转债）发给我

我会自动：
- OCR → 入库 `daily_sector_review` 表（source='bankuai' / 'jiuyan'）
- 跑 LLM v2 → 入库（source='llm_v2'）
- 用 LLM 主线作为板块成分跑龙头隔夜模式回测，看信号生成与命中
