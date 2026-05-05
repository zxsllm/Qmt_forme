# 题材主线判定链路（LLM v2）

> 类似 `morning_plan` / `review` 的链路，但本流程**不输出 .md 报告**——结果直接入库 `daily_sector_review` 表。
> 每天盘后调用 LLM 判断当日题材主线，与板块必读 / 韭研人工标签做对照。

---

## 一、与早盘计划/复盘的对比

| | 早盘计划 | 收盘复盘 | **题材主线判定（本链路）** |
|---|---|---|---|
| 启动脚本 | `scripts/morning_plan_cli.sh` | `scripts/review_cli.sh` | `scripts/llm_main_line.py` |
| Prompt 文件 | `scripts/prompts/morning_plan_prompt.txt` 等 | `scripts/prompts/review_prompt*.txt` | **内嵌** 在 `scripts/llm_main_line.py` 的 `PROMPT_V2` 变量 |
| LLM 调用方式 | `claude-sg --print` | `claude-sg --print` | `claude-sg --print`（subprocess + stdin）|
| 产出 | `reports/plan_YYYYMMDD.md` | `reports/review_YYYYMMDD.md` | **DB 入库**（`daily_sector_review` 表，`source='llm_v2'`）|

> Prompt 内嵌而非独立文件，因为本 prompt 依赖 `theme_taxonomy.py` 动态生成，不适合 .txt 静态化。
> 如需统一风格，将来可拆出 `scripts/prompts/sector_main_line_prompt.tmpl`。

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
└─────────────────────┬────────────────────────────────────────┘
                      ↓
┌──────────────────────────────────────────────────────────────┐
│  Step 5 对照人工标签（scripts/llm_main_line_diff.py）        │
│    LLM 主线 vs 板块必读 daily 主线（source='bankuai'）       │
│    输出板块级匹配 + 命中率                                    │
└──────────────────────────────────────────────────────────────┘
```

---

## 三、核心文件清单

### 算法/数据层

| 文件 | 职责 |
|---|---|
| `backend/app/research/signals/theme_taxonomy.py` | 主线 → 细分概念外延地图（喂 LLM 用）|
| `backend/app/research/signals/long_head_detector.py` | 龙1 / 龙2 / 影子龙识别 |
| `backend/app/research/signals/concept_blacklist.py` | 概念黑名单（资金属性/宽基类）|
| `backend/app/research/signals/concept_tagger.py` | 算法 B 旧版（concept_detail 聚合，已被 LLM 替代但保留作 baseline）|
| `backend/app/shared/models/stock.py` | `DailySectorReview` ORM（表存所有人工/算法标签）|

### 脚本层

**用户日常工作流（`scripts/` 根，与早盘/复盘平级）：**

| 文件 | 职责 |
|---|---|
| `scripts/llm_main_line.py` | ⭐ 主脚本：跑 LLM 主线判定 |
| `scripts/llm_main_line_diff.py` | ⭐ 对比 LLM 输出 vs 板块必读人工标签 |
| `scripts/_cache/` | 自动生成：每次跑的 prompt + LLM 原始返回（debug 用，可随时删）|

**开发期工具（`backend/scripts/`）：**

| 文件 | 职责 |
|---|---|
| `test_long_head.py` | 龙1识别测试（开发期）|
| `bench_api_latency.py` | API 性能 bench（开发期）|
| `check_min_coverage.py` | 分钟K覆盖率扫描（运维诊断）|
| `archive/sector_imports/` | 4/28-4/30 三天人工标签一次性入库脚本（已跑过归档）|
| `archive/probes/` | 一次性诊断/探针（已完成使命）|
| `archive/legacy/` | 5/2 + 5/4 历史会话产物 |

### 文档层

| 文件 | 职责 |
|---|---|
| `docs/sector_review_workflow.md` | 用户贴板块必读/韭研截图时的处理流程 |
| `docs/sector_main_line_pipeline.md` | **本文件** —— 链路全景 |
| `12模式策略详解.md` (项目根) | 12 个交易模式手册，策略落地的需求文档 |

---

## 四、运行方式

### 跑一次主线判定（单日）

```bash
cd E:/Project/Qmt_forme
.venv/Scripts/python.exe scripts/llm_main_line.py 20260506
# 或对齐 morning_plan_cli.sh / review_cli.sh 风格的话，将来可包一层 scripts/main_line_cli.sh
```

输出：
- DB：`daily_sector_review` 表插入若干行（source='llm_v2'）
- 调试缓存（自动生成在 `scripts/_cache/`）：
  - `prompt_YYYYMMDD.txt` — 实际发给 LLM 的完整 prompt
  - `llm_raw_YYYYMMDD.txt` — LLM 原始返回
  - 这个目录可随时整体删除，不影响功能

### 跑对比

```bash
.venv/Scripts/python.exe scripts/llm_main_line_diff.py 20260506
```

### 测龙1识别

```bash
.venv/Scripts/python.exe backend/scripts/test_long_head.py
```
（默认跑 4/30，要改日期改脚本里的 `td = "20260430"`）

---

## 五、注意事项

### claude-sg 并发陷阱（⚠️ 重要）
`claude-sg --print` 启动本地 proxy（127.0.0.1:18880），**不支持并发调用**。
两个任务同时跑时第二个会卡死直到 timeout。

→ 跑批量历史数据时必须**串行**（一个跑完再跑下一个）。

### prompt 长度
当前 v2 prompt 约 6000-7000 字符。卡死的原因 99% 是并发，不是长度。

### v1 已淘汰
原 `llm_main_line.py` (v1) 已删除。v2 完全替代。

---

## 六、5/6 起的日常（你的角色）

每个交易日：
1. **17:00 后**：把韭研复盘截图发给我（对话窗口）
2. **20:00 后**：把板块必读 3 张图（连板天梯 / 月度主线 / 最强转债）发给我

我会自动：
- OCR → 入库 `daily_sector_review` 表
- 跑一次 LLM v2 → 入库
- 跑对比 → 给你命中率报告
- 命中率高 = LLM 调好了；低 = 需要调 prompt（更新 `theme_taxonomy.py` 或加 few-shot）
