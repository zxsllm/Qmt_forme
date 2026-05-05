---
paths:
  - "scripts/**"
  - "backend/scripts/**"
---

# Scripts 目录组织约定

> 防止 AI 协作时一次性脚本到处乱放、临时文件不及时清理。

## 一、两个 scripts 目录的分工

| 目录 | 角色 | 内容特征 | 谁跑 |
|---|---|---|---|
| `scripts/`（项目根） | **用户日常工作流** | bash CLI 入口 + Python 工作流脚本 + Prompt 模板 | 用户每天/定时跑 |
| `backend/scripts/` | **开发期工具** | 测试 / 性能 bench / 运维诊断 | 开发期偶尔跑 |

### 决策树：新脚本应该放哪？

```
是否会被用户日常使用（每天/每周/触发式）？
├── 是 → scripts/
│         例：scripts/llm_main_line.py（每日盘后跑）
│              scripts/morning_plan_cli.sh（每日 9:00 前）
│              scripts/review_cli.sh（每日 15:30 后）
│
└── 否 → 是开发期内部用的吗？
          ├── 测试/bench/运维诊断（重复使用） → backend/scripts/
          │     例：backend/scripts/test_long_head.py
          │          backend/scripts/bench_api_latency.py
          │          backend/scripts/check_min_coverage.py
          │
          └── 一次性诊断 / 探针 / 数据导入 → backend/scripts/archive/<分类>/
                 跑完就归档（不在主目录占空间）
                 例：backend/scripts/archive/probes/
                      backend/scripts/archive/sector_imports/
                      backend/scripts/archive/legacy/
```

## 二、命名约定

| 前缀/后缀 | 用途 | 示例 |
|---|---|---|
| `<topic>_cli.sh` | 用户工作流 bash 入口 | `morning_plan_cli.sh` |
| `<topic>.py` | 用户工作流 Python 主脚本 | `llm_main_line.py` |
| `<topic>_diff.py` | 对照/对比类辅助脚本 | `llm_main_line_diff.py` |
| `test_*.py` | 开发期测试 | `test_long_head.py` |
| `bench_*.py` | 性能测试 | `bench_api_latency.py` |
| `check_*.py` | 数据/状态健康检查 | `check_min_coverage.py` |
| `probe_*.py` | **一次性探针**（写完即归档）| `probe_cb_min.py` |
| `repair_*.py` | **一次性修复**（跑完即归档）| `repair_min_0430.py` |
| `import_*.py` | **一次性数据导入**（跑完即归档）| `import_bankuai_20260430.py` |
| `_xxx.py`（下划线开头）| bash 脚本调用的内部 helper | `_render_prompt.py` |

## 三、临时输出文件强约束（⚠️ AI 必读）

### 禁止
- ❌ **不要在 `scripts/` 或 `backend/scripts/` 根目录写 `_*.txt`** 这类临时输出文件做排错
- ❌ **不要用 PowerShell `Out-File` 落 .txt 中转**，再 `Get-Content` 读出来给用户看 — 直接让 Python 用 `print` 输出，或在 PowerShell 里设置 `$env:PYTHONIOENCODING="utf-8"` 处理中文编码
- ❌ **不要在脚本里把调试产物写到任意目录** — 必须落到约定的 `_cache/` 子目录

### 允许
- ✅ 长期需要的调试缓存写到 `scripts/_cache/`（例：`llm_main_line.py` 的 prompt + LLM 原始返回）
- ✅ `_cache/` 整体可随时清空，不影响功能
- ✅ 一次性脚本的诊断输出可走 stdout，让用户/AI 直接看

### 临时文件命名
若必须落临时文件，命名清晰：
- ✅ `prompt_20260506.txt`（带日期，落 `_cache/`）
- ❌ `_v2_run.txt`、`_cmp.txt`、`_diag.txt`（无意义、无日期）

## 四、一次性脚本生命周期

### 写之前
- 先确认是不是可以用 `print` + 命令行参数解决，避免新建文件
- 探针类（probe_*）写之前问：跑完后会归档吗？

### 跑完之后
- **当场归档或删除**，不要留在主目录"以防万一"
- 探针 → `backend/scripts/archive/probes/`
- 数据导入 → `backend/scripts/archive/<分类>/`
- 历史会话产物 → `backend/scripts/archive/legacy/`

### 归档原则
- 归档的脚本不许再被 import / 调用
- 归档的脚本可以保留作为"代码档案"参考字段映射、SQL 语句等
- 主目录 `scripts/` 和 `backend/scripts/` 根**只放当前还会重复使用的脚本**

## 五、Prompt 模板

| 来源 | 风格 | 示例 |
|---|---|---|
| 早盘计划 / 收盘复盘 | 独立 .txt 文件 | `scripts/prompts/morning_plan_prompt.txt` |
| 题材主线判定 | **内嵌**在 .py（依赖 theme_taxonomy 动态生成）| `scripts/llm_main_line.py` 的 `PROMPT_V2` 变量 |

> 长期目标：把动态 prompt 拆成 `scripts/prompts/<topic>_prompt.tmpl` + 模板渲染。
> 短期允许内嵌，但要在脚本头注释里指明 prompt 在哪里。

## 六、违规清单（看到这些就要清理）

- 主目录 `scripts/` 或 `backend/scripts/` 出现 `_*.txt` 临时文件
- 主目录出现已确认完成使命的 `probe_*.py` / `repair_*.py` / `import_*.py`
- 多个版本共存（如 `llm_main_line.py` + `llm_main_line_v2.py`）—— 验证后立即删除旧版
- 同功能脚本 / 文件夹重复（如 `compare_xxx.py` + `diff_xxx.py` + `check_xxx.py` 都干一样的事）

## 七、对应 docs

- `docs/sector_main_line_pipeline.md` — 题材主线判定链路全景
- `docs/sector_review_workflow.md` — 截图入库流程

新加用户工作流脚本时，**必须**同步在 `docs/` 下写一份链路文档。
