#!/usr/bin/env bash
# review_cli.sh — 收盘复盘报告生成脚本
#
# 流程: curl 获取后端数据 → 拼装 prompt → claude-sg 生成 → 提取 JSON → curl POST 保存
#
# 用法:
#   ./scripts/review_cli.sh              # 使用今天日期
#   ./scripts/review_cli.sh 20260410     # 指定交易日
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
PROMPT_FILE="$SCRIPT_DIR/prompts/review_prompt.txt"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

echo "=== 收盘复盘报告生成 ==="
echo "交易日: $TRADE_DATE"
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

# ── 2. 拉取市场数据（使用聚合端点） ─────────────────────────────
echo "[2/5] 拉取市场数据..."

# 优先使用聚合端点 /api/v1/review/data/{trade_date}
echo "  - 聚合数据端点..."
REVIEW_DATA=$(curl -sf "$API_BASE/api/v1/review/data/$TRADE_DATE" 2>/dev/null || echo "")

if [ -n "$REVIEW_DATA" ] && echo "$REVIEW_DATA" | python3 -m json.tool > /dev/null 2>&1; then
    echo "  ✓ 聚合数据拉取成功"
    DATA_CONTENT="$REVIEW_DATA"
    # 提取 sentiment 供后续 save payload 使用
    SENTIMENT=$(echo "$REVIEW_DATA" | python3 -c "
import json, sys
d = json.load(sys.stdin)
json.dump(d.get('temperature', {}), sys.stdout, ensure_ascii=False)
" 2>/dev/null || echo '{}')
    RISK_ALERTS=$(echo "$REVIEW_DATA" | python3 -c "
import json, sys
d = json.load(sys.stdin)
json.dump(d.get('risk_alerts', {}), sys.stdout, ensure_ascii=False)
" 2>/dev/null || echo '{}')
else
    # 回退：逐个端点拉取
    echo "  ⚠️  聚合端点不可用，回退到逐个拉取..."

    echo "  - 情绪温度..."
    SENTIMENT=$(curl -sf "$API_BASE/api/v1/sentiment/temperature?trade_date=$TRADE_DATE" || echo '{}')
    echo "  - 涨跌停列表..."
    LIMIT_BOARD=$(curl -sf "$API_BASE/api/v1/sentiment/limit-board?trade_date=$TRADE_DATE" || echo '[]')
    echo "  - 连板梯队..."
    LIMIT_STEP=$(curl -sf "$API_BASE/api/v1/sentiment/limit-step?trade_date=$TRADE_DATE" || echo '[]')
    echo "  - 龙虎榜..."
    DRAGON_TIGER=$(curl -sf "$API_BASE/api/v1/sentiment/dragon-tiger?trade_date=$TRADE_DATE&limit=30" || echo '[]')
    echo "  - 板块排名..."
    SECTOR_RANK=$(curl -sf "$API_BASE/api/v1/sector/rankings" || echo '[]')
    echo "  - 资金流向..."
    MONEYFLOW=$(curl -sf "$API_BASE/api/v1/market/moneyflow" || echo '{}')
    echo "  - 两融数据..."
    MARGIN=$(curl -sf "$API_BASE/api/v1/market/margin?days=5" || echo '{}')
    echo "  - 风险预警..."
    RISK_ALERTS=$(curl -sf "$API_BASE/api/v1/risk/alerts" || echo '{}')
    echo "  - 情绪领袖..."
    LEADERS=$(curl -sf "$API_BASE/api/v1/sentiment/leaders?trade_date=$TRADE_DATE" || echo '{}')
    echo "  - 游资信号..."
    HOT_MONEY=$(curl -sf "$API_BASE/api/v1/sentiment/hot-money?trade_date=$TRADE_DATE" || echo '{}')

    DATA_CONTENT="{\"trade_date\":\"$TRADE_DATE\",\"sentiment\":$SENTIMENT,\"limit_board\":$LIMIT_BOARD,\"limit_step\":$LIMIT_STEP,\"dragon_tiger\":$DRAGON_TIGER,\"sector_rankings\":$SECTOR_RANK,\"moneyflow\":$MONEYFLOW,\"margin\":$MARGIN,\"risk_alerts\":$RISK_ALERTS,\"leaders\":$LEADERS,\"hot_money\":$HOT_MONEY}"

    echo "  ✓ 数据拉取完成"
fi

# ── 3. 组装 Prompt ──────────────────────────────────────────
echo "[3/5] 组装数据..."

# 历史相似行情（如果有向量检索端点则调用，否则留空）
SIMILAR="暂无历史相似行情数据"

# 读取 prompt 模板并替换占位符
PROMPT_TEMPLATE=$(cat "$PROMPT_FILE")

# 将 {data} 和 {similar} 占位符替换为实际数据
PROMPT="${PROMPT_TEMPLATE//\{data\}/$DATA_CONTENT}"
PROMPT="${PROMPT//\{similar\}/$SIMILAR}"

echo "$PROMPT" > "$TMP_DIR/full_prompt.txt"
echo "  ✓ Prompt 组装完成 ($(wc -c < "$TMP_DIR/full_prompt.txt") bytes)"

# ── 4. 调用 Claude CLI 生成报告 ──────────────────────────────
echo "[4/5] 调用 $CLAUDE_CMD 生成复盘报告..."
echo "  (这可能需要 30-60 秒)"

RAW_OUTPUT=$($CLAUDE_CMD -p "$(cat "$TMP_DIR/full_prompt.txt")" 2>/dev/null) || {
    echo "❌ $CLAUDE_CMD 调用失败"
    echo "   请检查 $CLAUDE_CMD 是否已安装并配置"
    exit 1
}

# 提取 JSON：去除可能的 markdown 代码块包裹
REVIEW_JSON=$(echo "$RAW_OUTPUT" | sed -n '/^```json/,/^```$/p' | sed '1d;$d')
if [ -z "$REVIEW_JSON" ]; then
    # 尝试直接去除 ``` 包裹
    REVIEW_JSON=$(echo "$RAW_OUTPUT" | sed -n '/^```/,/^```$/p' | sed '1d;$d')
fi
if [ -z "$REVIEW_JSON" ]; then
    # 没有代码块包裹，尝试直接提取 JSON 对象
    REVIEW_JSON=$(echo "$RAW_OUTPUT" | grep -Pzo '\{[\s\S]*\}' | tr '\0' '\n' || echo "")
fi
if [ -z "$REVIEW_JSON" ]; then
    echo "❌ 无法从 Claude 输出中提取 JSON"
    echo "原始输出已保存到: $TMP_DIR/raw_output.txt"
    echo "$RAW_OUTPUT" > "$TMP_DIR/raw_output.txt"
    # 不删除临时目录，方便调试
    trap - EXIT
    exit 1
fi

# 验证 JSON 格式
if ! echo "$REVIEW_JSON" | python3 -m json.tool > /dev/null 2>&1; then
    echo "⚠️  JSON 格式校验失败，尝试修复..."
    echo "$RAW_OUTPUT" > "$TMP_DIR/raw_output.txt"
    echo "原始输出已保存到: $TMP_DIR/raw_output.txt"
    trap - EXIT
    exit 1
fi

echo "$REVIEW_JSON" > "$TMP_DIR/review.json"
echo "  ✓ 报告生成成功"

# ── 5. 保存到后端 ──────────────────────────────────────────
echo "[5/5] 保存复盘报告..."

# 合并交易日期与 AI 生成的文本字段
SAVE_PAYLOAD=$(python3 -c "
import json, sys

review = json.load(open('$TMP_DIR/review.json'))
sentiment = json.loads('''$SENTIMENT''') if '''$SENTIMENT'''.strip() else {}

# 从 sentiment 中提取数值字段
sent_data = sentiment.get('data', {})

payload = {
    'trade_date': '$TRADE_DATE',
    # 情绪数值字段
    'temperature': sent_data.get('temperature'),
    'limit_up_count': sent_data.get('limit_up'),
    'limit_down_count': sent_data.get('limit_down'),
    'broken_count': sent_data.get('broken'),
    'seal_rate': sent_data.get('seal_rate'),
    'max_board': sent_data.get('max_board'),
    # AI 文本字段
    'market_summary': review.get('market_summary', ''),
    'sector_analysis': review.get('sector_analysis', ''),
    'sentiment_narrative': review.get('sentiment_narrative', ''),
    'board_play_summary': review.get('board_play_summary', ''),
    'swing_trade_summary': review.get('swing_trade_summary', ''),
    'value_invest_summary': review.get('value_invest_summary', ''),
    'strategy_conclusion': json.dumps(review['strategy_conclusion'], ensure_ascii=False) if isinstance(review.get('strategy_conclusion'), dict) else review.get('strategy_conclusion', ''),
    'risk_summary': review.get('risk_summary', ''),
    'dominant_strategy': review.get('dominant_strategy', ''),
    'strategy_switch_signal': review.get('strategy_switch_signal', ''),
    # 结构化 JSON 字段
    'risk_alerts_json': json.dumps(json.loads('''$RISK_ALERTS''').get('data', []), ensure_ascii=False) if '''$RISK_ALERTS'''.strip() else '[]',
}

json.dump(payload, sys.stdout, ensure_ascii=False)
" 2>/dev/null) || {
    echo "⚠️  Payload 组装失败，跳过保存"
    echo "  报告已保存到本地: $TMP_DIR/review.json"
    trap - EXIT
    exit 0
}

# POST 保存（端点由 Task #12 实现，可能尚不可用）
HTTP_CODE=$(curl -sf -o "$TMP_DIR/save_response.json" -w "%{http_code}" \
    -X POST "$API_BASE/api/v1/review/save" \
    -H "Content-Type: application/json" \
    -d "$SAVE_PAYLOAD" 2>/dev/null || echo "000")

if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ]; then
    echo "  ✓ 复盘报告已保存到数据库"
elif [ "$HTTP_CODE" = "000" ] || [ "$HTTP_CODE" = "404" ]; then
    echo "  ⚠️  保存端点尚未实现 (HTTP $HTTP_CODE)，报告仅保存到本地"
    cp "$TMP_DIR/review.json" "$PROJECT_ROOT/scripts/output/review_${TRADE_DATE}.json" 2>/dev/null || {
        mkdir -p "$PROJECT_ROOT/scripts/output"
        cp "$TMP_DIR/review.json" "$PROJECT_ROOT/scripts/output/review_${TRADE_DATE}.json"
    }
    echo "  → $PROJECT_ROOT/scripts/output/review_${TRADE_DATE}.json"
else
    echo "  ⚠️  保存失败 (HTTP $HTTP_CODE)"
    cat "$TMP_DIR/save_response.json" 2>/dev/null
fi

echo ""
echo "=== 复盘报告生成完毕 ==="
echo "交易日: $TRADE_DATE"
echo "主导策略: $(echo "$REVIEW_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('dominant_strategy','N/A'))" 2>/dev/null || echo 'N/A')"
