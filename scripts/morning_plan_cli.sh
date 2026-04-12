#!/usr/bin/env bash
# morning_plan_cli.sh — 早盘计划生成脚本（两轮生成）
#
# 流程: curl 获取数据 → Round 1 核心判断 → Round 2 详细计划 → 合并 → POST 保存
#
# 用法:
#   ./scripts/morning_plan_cli.sh            # 使用今天日期
#   ./scripts/morning_plan_cli.sh 20260411   # 指定交易日（计划目标日）
#
# 环境变量:
#   API_BASE  — 后端地址，默认 http://localhost:8000
#   CLAUDE_CMD — Claude CLI 命令，默认 claude-sg

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 加载公共函数库
. "$SCRIPT_DIR/_common.sh"

API_BASE="${API_BASE:-$(_detect_api_base)}"
CLAUDE_CMD="${CLAUDE_CMD:-claude-sg}"
TRADE_DATE="${1:-$(date +%Y%m%d)}"
PROMPTS_DIR="$SCRIPT_DIR/prompts"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

# 初始化日志（stdout/stderr 同时写入日志文件）
_init_logging "plan" "$TRADE_DATE"

echo "=== 早盘计划生成（两轮） ==="
echo "计划目标日: $TRADE_DATE"
echo "后端地址: $API_BASE"
echo ""

# ── 1. 检查后端可用性 ──────────────────────────────────────────
echo "[1/6] 检查后端连接..."
if ! _check_health "$API_BASE"; then
    exit 1
fi
echo "  ✓ 后端连接正常"

# ── 2. 拉取数据 ────────────────────────────────────────────────
echo "[2/6] 拉取数据..."

echo "  - 聚合数据端点..."
# 直接写文件，避免 bash 变量存大 JSON 导致编码/截断问题
_curl -sf "$API_BASE/api/v1/plan/data/$TRADE_DATE" > "$TMP_DIR/plan_raw.json" 2>/dev/null || echo "{}" > "$TMP_DIR/plan_raw.json"

if python3 -m json.tool "$TMP_DIR/plan_raw.json" > /dev/null 2>&1; then
    echo "  ✓ 聚合数据拉取成功"

    # 从文件中提取各子数据（避免 bash 变量传递大 JSON）
    python3 -c "
import json, sys, pathlib
raw = pathlib.Path(sys.argv[1])
tmp = pathlib.Path(sys.argv[2])
d = json.loads(raw.read_text(encoding='utf-8'))

review = d.get('yesterday_review') or {}
review['premarket'] = d.get('premarket', {})
review['margin'] = d.get('margin', {})
json.dump(review, open(tmp / 'review.json', 'w', encoding='utf-8'), ensure_ascii=False)

out = {'trade_date': d.get('trade_date'), 'premarket': d.get('premarket', {}),
       'overnight_markets': d.get('overnight_markets', {}), 'key_events': d.get('key_events', {})}
json.dump(out, open(tmp / 'premarket.json', 'w', encoding='utf-8'), ensure_ascii=False)

alerts = d.get('risk_alerts', {}).get('data', [])
filtered = [a for a in alerts if a.get('level') in ('high', 'warning')]
json.dump(filtered[:30], open(tmp / 'risk.json', 'w', encoding='utf-8'), ensure_ascii=False)

json.dump(d.get('dragon_tiger', {}), open(tmp / 'dragon_tiger.json', 'w', encoding='utf-8'), ensure_ascii=False)
json.dump(d.get('watchlist_anns', []), open(tmp / 'watchlist_anns.json', 'w', encoding='utf-8'), ensure_ascii=False)
" "$TMP_DIR/plan_raw.json" "$TMP_DIR" 2>/dev/null || {
        echo '{}' > "$TMP_DIR/review.json"
        echo '{}' > "$TMP_DIR/premarket.json"
        echo '[]' > "$TMP_DIR/risk.json"
        echo '{}' > "$TMP_DIR/dragon_tiger.json"
        echo '[]' > "$TMP_DIR/watchlist_anns.json"
    }
else
    echo "  ⚠️  聚合端点不可用，使用空数据..."
    echo '{}' > "$TMP_DIR/review.json"
    echo '{}' > "$TMP_DIR/premarket.json"
    echo '[]' > "$TMP_DIR/risk.json"
    echo '{}' > "$TMP_DIR/dragon_tiger.json"
    echo '[]' > "$TMP_DIR/watchlist_anns.json"
fi

echo "暂无历史相似行情数据" > "$TMP_DIR/similar.txt"

# ── 3. Round 1: 核心判断 ───────────────────────────────────────
echo "[3/6] Round 1: 生成核心判断..."
echo "  (约 15-30 秒)"

_render_prompt "$TMP_DIR/core_prompt.txt" \
    "$PROMPTS_DIR/plan_prompt_core.txt" \
    "{review}" "$TMP_DIR/review.json" \
    "{premarket}" "$TMP_DIR/premarket.json" \
    "{risk}" "$TMP_DIR/risk.json" \
    "{similar}" "$TMP_DIR/similar.txt" \
    "{dragon_tiger}" "$TMP_DIR/dragon_tiger.json" \
    "{watchlist_anns}" "$TMP_DIR/watchlist_anns.json"

if ! _run_claude_round "$TMP_DIR/core_prompt.txt" "$TMP_DIR/core_raw.txt"; then
    _save_raw_on_failure "$TMP_DIR/core_raw.txt" "Round1"
    echo "❌ Round 1 $CLAUDE_CMD 调用失败"; exit 1
fi

if ! _extract_json "$TMP_DIR/core_raw.txt" "$TMP_DIR/core.json"; then
    _save_raw_on_failure "$TMP_DIR/core_raw.txt" "Round1-JSON"
    echo "❌ Round 1 JSON 提取失败"
    trap - EXIT; exit 1
fi

# 校验 Round 1 输出
if ! _validate_report "$TMP_DIR/core.json" "plan_core"; then
    echo "⚠️  Round 1 校验未通过，尝试重新生成..."
    _save_raw_on_failure "$TMP_DIR/core_raw.txt" "Round1-validate-fail"
    if ! _run_claude_round "$TMP_DIR/core_prompt.txt" "$TMP_DIR/core_raw.txt"; then
        echo "❌ Round 1 重试失败"; exit 1
    fi
    if ! _extract_json "$TMP_DIR/core_raw.txt" "$TMP_DIR/core.json"; then
        echo "❌ Round 1 重试 JSON 提取失败"; trap - EXIT; exit 1
    fi
    if ! _validate_report "$TMP_DIR/core.json" "plan_core"; then
        echo "⚠️  Round 1 重试仍未通过校验，继续使用当前结果"
    fi
fi
echo "  ✓ 核心判断生成完成"

# ── 4. Round 2: 详细计划 ───────────────────────────────────────
echo "[4/6] Round 2: 生成详细计划..."
echo "  (约 30-60 秒)"

cat "$TMP_DIR/core.json" > "$TMP_DIR/core_content.json"

_render_prompt "$TMP_DIR/detail_prompt.txt" \
    "$PROMPTS_DIR/plan_prompt_detail.txt" \
    "{core}" "$TMP_DIR/core_content.json" \
    "{review}" "$TMP_DIR/review.json" \
    "{premarket}" "$TMP_DIR/premarket.json" \
    "{risk}" "$TMP_DIR/risk.json" \
    "{dragon_tiger}" "$TMP_DIR/dragon_tiger.json" \
    "{watchlist_anns}" "$TMP_DIR/watchlist_anns.json"

if ! _run_claude_round "$TMP_DIR/detail_prompt.txt" "$TMP_DIR/detail_raw.txt"; then
    _save_raw_on_failure "$TMP_DIR/detail_raw.txt" "Round2"
    echo "❌ Round 2 $CLAUDE_CMD 调用失败"; exit 1
fi

if ! _extract_json "$TMP_DIR/detail_raw.txt" "$TMP_DIR/detail.json"; then
    _save_raw_on_failure "$TMP_DIR/detail_raw.txt" "Round2-JSON"
    echo "❌ Round 2 JSON 提取失败"
    trap - EXIT; exit 1
fi

# 校验 Round 2 输出
if ! _validate_report "$TMP_DIR/detail.json" "plan_detail"; then
    echo "⚠️  Round 2 校验未通过，尝试重新生成..."
    _save_raw_on_failure "$TMP_DIR/detail_raw.txt" "Round2-validate-fail"
    if ! _run_claude_round "$TMP_DIR/detail_prompt.txt" "$TMP_DIR/detail_raw.txt"; then
        echo "❌ Round 2 重试失败"; exit 1
    fi
    if ! _extract_json "$TMP_DIR/detail_raw.txt" "$TMP_DIR/detail.json"; then
        echo "❌ Round 2 重试 JSON 提取失败"; trap - EXIT; exit 1
    fi
    if ! _validate_report "$TMP_DIR/detail.json" "plan_detail"; then
        echo "⚠️  Round 2 重试仍未通过校验，继续使用当前结果"
    fi
fi
echo "  ✓ 详细计划生成完成"

# ── 5. 合并 + 默认值兜底 + 保存 ────────────────────────────────
echo "[5/6] 合并并保存..."

# Python 直接写 save_payload.json，不经过 bash 变量
python3 - "$TMP_DIR" "$TRADE_DATE" <<'PYEOF'
import json, sys, pathlib

tmp = pathlib.Path(sys.argv[1])
trade_date = sys.argv[2]

core = json.load(open(tmp / "core.json"))
detail = json.load(open(tmp / "detail.json"))

def to_json_str(val, default="[]"):
    if isinstance(val, (list, dict)):
        return json.dumps(val, ensure_ascii=False)
    if isinstance(val, str):
        try:
            json.loads(val)
            return val
        except (json.JSONDecodeError, TypeError):
            pass
    return default

payload = {
    "trade_date": trade_date,
    "predicted_direction": core.get("predicted_direction", "震荡"),
    "predicted_temperature": core.get("predicted_temperature", "中性"),
    "confidence_score": core.get("confidence_score", 50),
    "key_logic": core.get("key_logic", ""),
    "risk_notes": core.get("risk_notes", ""),
    "watch_sectors_json": to_json_str(core.get("watch_sectors_json", []), "[]"),
    "avoid_sectors_json": to_json_str(core.get("avoid_sectors_json", []), "[]"),
    "strategy_weights_json": to_json_str(core.get("strategy_weights_json", {}), "{}"),
    "position_plan_json": to_json_str(core.get("position_plan_json", {}), "{}"),
    "overnight_summary": detail.get("overnight_summary", ""),
    "board_play_plan": detail.get("board_play_plan", ""),
    "swing_trade_plan": detail.get("swing_trade_plan", ""),
    "value_invest_plan": detail.get("value_invest_plan", ""),
    "watch_stocks_json": to_json_str(detail.get("watch_stocks_json", []), "[]"),
    "entry_plan_json": to_json_str(detail.get("entry_plan_json", []), "[]"),
    "exit_plan_json": to_json_str(detail.get("exit_plan_json", []), "[]"),
}

json.dump(payload, open(tmp / "save_payload.json", "w"), ensure_ascii=False)

merged = {**core, **detail}
json.dump(merged, open(tmp / "plan.json", "w"), ensure_ascii=False, indent=2)
PYEOF

if [ $? -ne 0 ]; then
    echo "⚠️  Payload 组装失败"
    trap - EXIT; exit 0
fi

HTTP_CODE=$(_save_to_backend "/api/v1/plan/save" "$TMP_DIR/save_payload.json")

if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ]; then
    echo "  ✓ 早盘计划已保存到数据库"
else
    echo "  ⚠️  保存失败 (HTTP $HTTP_CODE)，保存到本地"
    mkdir -p "$PROJECT_ROOT/scripts/output"
    cp "$TMP_DIR/plan.json" "$PROJECT_ROOT/scripts/output/plan_${TRADE_DATE}.json"
    echo "  → scripts/output/plan_${TRADE_DATE}.json"
fi

# ── 6. 生成 Markdown 报告 ──────────────────────────────────────
echo "[6/6] 生成 Markdown 报告..."

REPORT_DIR="$PROJECT_ROOT/reports"
mkdir -p "$REPORT_DIR"
MD_FILE="$REPORT_DIR/plan_${TRADE_DATE}.md"

python3 - "$TMP_DIR" "$TRADE_DATE" "$MD_FILE" <<'PYEOF'
import json, pathlib, sys

tmp = pathlib.Path(sys.argv[1])
trade_date, md_path = sys.argv[2], sys.argv[3]
core = json.load(open(tmp / "core.json"))
detail = json.load(open(tmp / "detail.json"))

date_fmt = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"

# ── 作战卡（主报告）──────────────────────────────────────────
pp = core.get("position_plan_json", {})
if not isinstance(pp, dict): pp = {}
sw = core.get("strategy_weights_json", {})
if not isinstance(sw, dict): sw = {}

card = [f"# {date_fmt} 作战卡\n"]
card.append(f"方向: **{core.get('predicted_direction','?')}** | "
            f"温度: **{core.get('predicted_temperature','?')}** | "
            f"信心: **{core.get('confidence_score','?')}** | "
            f"仓位: **{pp.get('total_position','?')}**\n")

# 核心逻辑（一段话）
logic = core.get("key_logic", "")
if logic:
    card.append(f"**核心逻辑**: {logic}\n")

# 买入计划
entries = detail.get("entry_plan_json", [])
if isinstance(entries, list) and entries:
    card.append("### 买入")
    card.append("| 名称 | 策略 | 触发条件 | 仓位 |")
    card.append("|------|------|----------|------|")
    for e in entries:
        if isinstance(e, dict):
            tp = e.get("target_price", "")
            sl = e.get("stop_loss", "")
            trigger = e.get("trigger", "")
            # 有价格锚点时附加到触发条件
            extras = []
            if tp and tp not in (0, "0", None, "None"):
                extras.append(f"目标{tp}")
            if sl and sl not in (0, "0", None, "None"):
                extras.append(f"止损{sl}")
            if extras:
                trigger += f" ({', '.join(extras)})"
            card.append(f"| {e.get('name','')} | {e.get('strategy','')} | "
                        f"{trigger} | {e.get('position','')} |")
    card.append("")

# 卖出/规避
exits = detail.get("exit_plan_json", [])
if isinstance(exits, list) and exits:
    card.append("### 卖出/规避")
    card.append("| 名称 | 动作 |")
    card.append("|------|------|")
    for e in exits:
        if isinstance(e, dict):
            card.append(f"| {e.get('name','')} | {e.get('action', e.get('trigger',''))} |")
    card.append("")

# 关键观察指标
risks = core.get("risk_notes", "")
ws = core.get("watch_sectors_json", [])
avd = core.get("avoid_sectors_json", [])
card.append("### 关键观察")
if isinstance(ws, list) and ws:
    card.append(f"- 关注: {', '.join(ws)}")
if isinstance(avd, list) and avd:
    card.append(f"- 回避: {', '.join(avd)}")
# 提取风险提示中最关键的几条
if risks:
    risk_lines = [r.strip() for r in risks.replace("；", "\n").split("\n") if r.strip()]
    for r in risk_lines[:4]:
        # 清理编号前缀
        r = r.lstrip("0123456789)）.、 ")
        if r:
            card.append(f"- {r[:80]}")
card.append("")

# 策略权重（一行）
if sw:
    parts = [f"{k}:{int(v*100)}%" for k,v in sw.items() if isinstance(v, (int,float))]
    if parts:
        card.append(f"策略配比: {' / '.join(parts)}\n")

pathlib.Path(md_path).write_text("\n".join(card), encoding="utf-8")

# ── 详细分析（单独文件）─────────────────────────────────────
detail_path = md_path.replace(".md", "_detail.md")
lines = [f"# {date_fmt} 早盘计划 — 详细分析\n"]

for key, title, src in [
    ("key_logic", "核心逻辑", core),
    ("overnight_summary", "隔夜环境", detail),
    ("board_play_plan", "打板计划", detail),
    ("swing_trade_plan", "波段计划", detail),
    ("value_invest_plan", "价值计划", detail),
    ("risk_notes", "风险提示", core),
]:
    text = src.get(key, "")
    if text:
        lines.append(f"## {title}\n\n{text}\n")

stocks = detail.get("watch_stocks_json", [])
if isinstance(stocks, list) and stocks:
    lines.append("## 关注个股\n")
    lines.append("| 代码 | 名称 | 理由 |")
    lines.append("|------|------|------|")
    for s in stocks:
        if isinstance(s, dict):
            lines.append(f"| {s.get('ts_code','')} | {s.get('name','')} | {s.get('reason','')} |")
    lines.append("")

pathlib.Path(detail_path).write_text("\n".join(lines), encoding="utf-8")
PYEOF

echo "  ✓ $MD_FILE"
echo ""
echo "=== 早盘计划生成完毕 ==="
echo "目标日: $TRADE_DATE"
echo "报告文件: reports/plan_${TRADE_DATE}.md"
echo "日志文件: $LOG_FILE"
