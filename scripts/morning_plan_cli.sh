#!/usr/bin/env bash
# morning_plan_cli.sh — 早盘计划生成脚本
#
# 流程: curl 获取昨日复盘+隔夜外盘+风险预警 → 拼装 prompt → claude-sg 生成 → 提取 JSON → curl POST 保存
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

API_BASE="${API_BASE:-http://localhost:8000}"
CLAUDE_CMD="${CLAUDE_CMD:-claude-sg}"
TRADE_DATE="${1:-$(date +%Y%m%d)}"
PROMPT_FILE="$SCRIPT_DIR/prompts/morning_plan_prompt.txt"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

echo "=== 早盘计划生成 ==="
echo "计划目标日: $TRADE_DATE"
echo "后端地址: $API_BASE"
echo ""

# ── 1. 检查后端可用性 ──────────────────────────────────────────
echo "[1/5] 检查后端连接..."
if ! curl -sf "$API_BASE/health" > /dev/null 2>&1; then
    echo "❌ 后端不可用: $API_BASE/health"
    echo "   请确认后端已启动: cd backend && uvicorn app.main:app"
    exit 1
fi
echo "  ✓ 后端连接正常"

# ── 2. 拉取数据（使用聚合端点） ─────────────────────────────────
echo "[2/5] 拉取数据..."

# 优先使用聚合端点 /api/v1/plan/data/{trade_date}
echo "  - 聚合数据端点..."
PLAN_DATA=$(curl -sf "$API_BASE/api/v1/plan/data/$TRADE_DATE" 2>/dev/null || echo "")

if [ -n "$PLAN_DATA" ] && echo "$PLAN_DATA" | python3 -m json.tool > /dev/null 2>&1; then
    echo "  ✓ 聚合数据拉取成功"

    # 从聚合数据中提取各段
    REVIEW_CONTENT=$(echo "$PLAN_DATA" | python3 -c "
import json, sys
d = json.load(sys.stdin)
review = d.get('yesterday_review') or {}
review['premarket'] = d.get('premarket', {})
review['margin'] = d.get('margin', {})
json.dump(review, sys.stdout, ensure_ascii=False)
" 2>/dev/null || echo '{}')

    PREMARKET_CONTENT=$(echo "$PLAN_DATA" | python3 -c "
import json, sys
d = json.load(sys.stdin)
out = {
    'trade_date': d.get('trade_date'),
    'premarket': d.get('premarket', {}),
    'overnight_markets': d.get('overnight_markets', {}),
    'key_events': d.get('key_events', {}),
}
json.dump(out, sys.stdout, ensure_ascii=False)
" 2>/dev/null || echo '{}')

    RISK_CONTENT=$(echo "$PLAN_DATA" | python3 -c "
import json, sys
d = json.load(sys.stdin)
alerts = d.get('risk_alerts', {}).get('data', [])
filtered = [a for a in alerts if a.get('level') in ('high', 'warning')]
json.dump(filtered[:30], sys.stdout, ensure_ascii=False)
" 2>/dev/null || echo '[]')

else
    # 回退：逐个端点拉取
    echo "  ⚠️  聚合端点不可用，回退到逐个拉取..."

    echo "  - 盘前计划数据..."
    PREMARKET=$(curl -sf "$API_BASE/api/v1/premarket/plan?date=$TRADE_DATE" || echo '{}')

    YESTERDAY=$(echo "$PREMARKET" | python3 -c "import json,sys; print(json.load(sys.stdin).get('yesterday',''))" 2>/dev/null || echo "")
    if [ -n "$YESTERDAY" ]; then
        echo "  - 昨日情绪温度 ($YESTERDAY)..."
        YESTERDAY_SENTIMENT=$(curl -sf "$API_BASE/api/v1/sentiment/temperature?trade_date=$YESTERDAY" || echo '{}')
        echo "  - 昨日板块排名..."
        YESTERDAY_SECTORS=$(curl -sf "$API_BASE/api/v1/sector/rankings" || echo '[]')
    else
        YESTERDAY_SENTIMENT='{}'
        YESTERDAY_SECTORS='[]'
    fi

    echo "  - 风险预警..."
    RISK_ALERTS=$(curl -sf "$API_BASE/api/v1/risk/alerts" || echo '{}')

    echo "  - 两融数据..."
    MARGIN=$(curl -sf "$API_BASE/api/v1/market/margin?days=5" || echo '{}')

    REVIEW_CONTENT="{\"yesterday\":\"$YESTERDAY\",\"sentiment\":$YESTERDAY_SENTIMENT,\"sector_rankings\":$YESTERDAY_SECTORS,\"margin\":$MARGIN}"
    PREMARKET_CONTENT="{\"trade_date\":\"$TRADE_DATE\",\"premarket\":$PREMARKET}"
    RISK_CONTENT=$(echo "$RISK_ALERTS" | python3 -c "
import json, sys
data = json.load(sys.stdin)
alerts = [a for a in data.get('data', []) if a.get('level') in ('high', 'warning')]
json.dump(alerts[:30], sys.stdout, ensure_ascii=False)
" 2>/dev/null || echo '[]')

    echo "  ✓ 数据拉取完成"
fi

# ── 3. 组装 Prompt ──────────────────────────────────────────
echo "[3/5] 组装数据..."

# 历史相似行情
SIMILAR="暂无历史相似行情数据"

# 读取 prompt 模板并替换占位符
PROMPT_TEMPLATE=$(cat "$PROMPT_FILE")

PROMPT="${PROMPT_TEMPLATE//\{review\}/$REVIEW_CONTENT}"
PROMPT="${PROMPT//\{premarket\}/$PREMARKET_CONTENT}"
PROMPT="${PROMPT//\{risk\}/$RISK_CONTENT}"
PROMPT="${PROMPT//\{similar\}/$SIMILAR}"

echo "$PROMPT" > "$TMP_DIR/full_prompt.txt"
echo "  ✓ Prompt 组装完成 ($(wc -c < "$TMP_DIR/full_prompt.txt") bytes)"

# ── 4. 调用 Claude CLI 生成早盘计划 ──────────────────────────
echo "[4/5] 调用 $CLAUDE_CMD 生成早盘计划..."
echo "  (这可能需要 30-60 秒)"

RAW_OUTPUT=$($CLAUDE_CMD -p "$(cat "$TMP_DIR/full_prompt.txt")" 2>/dev/null) || {
    echo "❌ $CLAUDE_CMD 调用失败"
    echo "   请检查 $CLAUDE_CMD 是否已安装并配置"
    exit 1
}

# 提取 JSON：去除可能的 markdown 代码块包裹
PLAN_JSON=$(echo "$RAW_OUTPUT" | sed -n '/^```json/,/^```$/p' | sed '1d;$d')
if [ -z "$PLAN_JSON" ]; then
    PLAN_JSON=$(echo "$RAW_OUTPUT" | sed -n '/^```/,/^```$/p' | sed '1d;$d')
fi
if [ -z "$PLAN_JSON" ]; then
    PLAN_JSON=$(echo "$RAW_OUTPUT" | grep -Pzo '\{[\s\S]*\}' | tr '\0' '\n' || echo "")
fi
if [ -z "$PLAN_JSON" ]; then
    echo "❌ 无法从 Claude 输出中提取 JSON"
    echo "$RAW_OUTPUT" > "$TMP_DIR/raw_output.txt"
    echo "原始输出已保存到: $TMP_DIR/raw_output.txt"
    trap - EXIT
    exit 1
fi

# 验证 JSON
if ! echo "$PLAN_JSON" | python3 -m json.tool > /dev/null 2>&1; then
    echo "⚠️  JSON 格式校验失败"
    echo "$RAW_OUTPUT" > "$TMP_DIR/raw_output.txt"
    echo "原始输出已保存到: $TMP_DIR/raw_output.txt"
    trap - EXIT
    exit 1
fi

echo "$PLAN_JSON" > "$TMP_DIR/plan.json"
echo "  ✓ 早盘计划生成成功"

# ── 5. 保存到后端 ──────────────────────────────────────────
echo "[5/5] 保存早盘计划..."

SAVE_PAYLOAD=$(python3 -c "
import json, sys

plan = json.load(open('$TMP_DIR/plan.json'))

def to_json_str(val):
    if isinstance(val, (list, dict)):
        return json.dumps(val, ensure_ascii=False)
    return val if val else '[]'

payload = {
    'trade_date': '$TRADE_DATE',
    # 预判字段
    'predicted_direction': plan.get('predicted_direction'),
    'predicted_temperature': plan.get('predicted_temperature'),
    'confidence_score': plan.get('confidence_score'),
    # 结构化 JSON 字段
    'watch_sectors_json': to_json_str(plan.get('watch_sectors_json', [])),
    'watch_stocks_json': to_json_str(plan.get('watch_stocks_json', [])),
    'avoid_sectors_json': to_json_str(plan.get('avoid_sectors_json', [])),
    'strategy_weights_json': to_json_str(plan.get('strategy_weights_json', {})),
    'position_plan_json': to_json_str(plan.get('position_plan_json', {})),
    'entry_plan_json': to_json_str(plan.get('entry_plan_json', [])),
    'exit_plan_json': to_json_str(plan.get('exit_plan_json', [])),
    # 文本字段
    'overnight_summary': plan.get('overnight_summary', ''),
    'board_play_plan': plan.get('board_play_plan', ''),
    'swing_trade_plan': plan.get('swing_trade_plan', ''),
    'value_invest_plan': plan.get('value_invest_plan', ''),
    'key_logic': plan.get('key_logic', ''),
    'risk_notes': plan.get('risk_notes', ''),
}

json.dump(payload, sys.stdout, ensure_ascii=False)
" 2>/dev/null) || {
    echo "⚠️  Payload 组装失败，跳过保存"
    echo "  计划已保存到本地: $TMP_DIR/plan.json"
    trap - EXIT
    exit 0
}

# POST 保存（端点由 Task #12 实现，可能尚不可用）
HTTP_CODE=$(curl -sf -o "$TMP_DIR/save_response.json" -w "%{http_code}" \
    -X POST "$API_BASE/api/v1/plan/save" \
    -H "Content-Type: application/json" \
    -d "$SAVE_PAYLOAD" 2>/dev/null || echo "000")

if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ]; then
    echo "  ✓ 早盘计划已保存到数据库"
elif [ "$HTTP_CODE" = "000" ] || [ "$HTTP_CODE" = "404" ]; then
    echo "  ⚠️  保存端点尚未实现 (HTTP $HTTP_CODE)，计划仅保存到本地"
    mkdir -p "$PROJECT_ROOT/scripts/output"
    cp "$TMP_DIR/plan.json" "$PROJECT_ROOT/scripts/output/plan_${TRADE_DATE}.json"
    echo "  → $PROJECT_ROOT/scripts/output/plan_${TRADE_DATE}.json"
else
    echo "  ⚠️  保存失败 (HTTP $HTTP_CODE)"
    cat "$TMP_DIR/save_response.json" 2>/dev/null
fi

echo ""
echo "=== 早盘计划生成完毕 ==="
echo "目标日: $TRADE_DATE"
echo "预判方向: $(echo "$PLAN_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('predicted_direction','N/A'))" 2>/dev/null || echo 'N/A')"
echo "预判温度: $(echo "$PLAN_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('predicted_temperature','N/A'))" 2>/dev/null || echo 'N/A')"
echo "信心分数: $(echo "$PLAN_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('confidence_score','N/A'))" 2>/dev/null || echo 'N/A')"
