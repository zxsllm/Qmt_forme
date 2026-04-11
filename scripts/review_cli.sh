#!/usr/bin/env bash
# review_cli.sh — 收盘复盘报告生成脚本（两轮生成）
#
# 流程: curl 获取后端数据 → Round 1 核心判断 → Round 2 详细文本 → 合并 → POST 保存
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

# 加载公共函数库
. "$SCRIPT_DIR/_common.sh"

API_BASE="${API_BASE:-$(_detect_api_base)}"
CLAUDE_CMD="${CLAUDE_CMD:-claude-sg}"
TRADE_DATE="${1:-$(date +%Y%m%d)}"
PROMPTS_DIR="$SCRIPT_DIR/prompts"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

# 初始化日志（stdout/stderr 同时写入日志文件）
_init_logging "review" "$TRADE_DATE"

echo "=== 收盘复盘报告生成（两轮） ==="
echo "交易日: $TRADE_DATE"
echo "后端地址: $API_BASE"
echo ""

# ── 1. 检查后端可用性 ──────────────────────────────────────────
echo "[1/6] 检查后端连接..."
if ! _check_health "$API_BASE"; then
    exit 1
fi
echo "  ✓ 后端连接正常"

# ── 2. 拉取市场数据 ────────────────────────────────────────────
echo "[2/6] 拉取市场数据..."

echo "  - 聚合数据端点..."
REVIEW_DATA=$(_curl -sf "$API_BASE/api/v1/review/data/$TRADE_DATE" 2>/dev/null || echo "")

if [ -n "$REVIEW_DATA" ] && echo "$REVIEW_DATA" | python3 -m json.tool > /dev/null 2>&1; then
    echo "  ✓ 聚合数据拉取成功"
    DATA_CONTENT="$REVIEW_DATA"
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
    echo "  ⚠️  聚合端点不可用，回退到逐个拉取..."
    SENTIMENT=$(_curl -sf "$API_BASE/api/v1/sentiment/temperature?trade_date=$TRADE_DATE" || echo '{}')
    LIMIT_BOARD=$(_curl -sf "$API_BASE/api/v1/sentiment/limit-board?trade_date=$TRADE_DATE" || echo '[]')
    LIMIT_STEP=$(_curl -sf "$API_BASE/api/v1/sentiment/limit-step?trade_date=$TRADE_DATE" || echo '[]')
    DRAGON_TIGER=$(_curl -sf "$API_BASE/api/v1/sentiment/dragon-tiger?trade_date=$TRADE_DATE&limit=30" || echo '[]')
    SECTOR_RANK=$(_curl -sf "$API_BASE/api/v1/sector/rankings" || echo '[]')
    MONEYFLOW=$(_curl -sf "$API_BASE/api/v1/market/moneyflow" || echo '{}')
    MARGIN=$(_curl -sf "$API_BASE/api/v1/market/margin?days=5" || echo '{}')
    RISK_ALERTS=$(_curl -sf "$API_BASE/api/v1/risk/alerts" || echo '{}')
    LEADERS=$(_curl -sf "$API_BASE/api/v1/sentiment/leaders?trade_date=$TRADE_DATE" || echo '{}')
    HOT_MONEY=$(_curl -sf "$API_BASE/api/v1/sentiment/hot-money?trade_date=$TRADE_DATE" || echo '{}')
    DATA_CONTENT="{\"trade_date\":\"$TRADE_DATE\",\"sentiment\":$SENTIMENT,\"limit_board\":$LIMIT_BOARD,\"limit_step\":$LIMIT_STEP,\"dragon_tiger\":$DRAGON_TIGER,\"sector_rankings\":$SECTOR_RANK,\"moneyflow\":$MONEYFLOW,\"margin\":$MARGIN,\"risk_alerts\":$RISK_ALERTS,\"leaders\":$LEADERS,\"hot_money\":$HOT_MONEY}"
    echo "  ✓ 数据拉取完成"
fi

SIMILAR="暂无历史相似行情数据"

# ── 3. Round 1: 核心判断 ───────────────────────────────────────
echo "[3/6] Round 1: 生成核心判断..."
echo "  (约 15-30 秒)"

# 写入数据文件供 Python 模板渲染使用
echo "$DATA_CONTENT" > "$TMP_DIR/data.json"
echo "$SIMILAR" > "$TMP_DIR/similar.txt"

_render_prompt "$TMP_DIR/core_prompt.txt" \
    "$PROMPTS_DIR/review_prompt_core.txt" \
    "{data}" "$TMP_DIR/data.json" \
    "{similar}" "$TMP_DIR/similar.txt"

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
if ! _validate_report "$TMP_DIR/core.json" "review_core"; then
    echo "⚠️  Round 1 校验未通过，尝试重新生成..."
    _save_raw_on_failure "$TMP_DIR/core_raw.txt" "Round1-validate-fail"
    if ! _run_claude_round "$TMP_DIR/core_prompt.txt" "$TMP_DIR/core_raw.txt"; then
        echo "❌ Round 1 重试失败"; exit 1
    fi
    if ! _extract_json "$TMP_DIR/core_raw.txt" "$TMP_DIR/core.json"; then
        echo "❌ Round 1 重试 JSON 提取失败"; trap - EXIT; exit 1
    fi
    if ! _validate_report "$TMP_DIR/core.json" "review_core"; then
        echo "⚠️  Round 1 重试仍未通过校验，继续使用当前结果"
    fi
fi
echo "  ✓ 核心判断生成完成"

# ── 4. Round 2: 详细文本 ───────────────────────────────────────
echo "[4/6] Round 2: 生成详细分析..."
echo "  (约 30-60 秒)"

cat "$TMP_DIR/core.json" > "$TMP_DIR/core_content.json"

_render_prompt "$TMP_DIR/detail_prompt.txt" \
    "$PROMPTS_DIR/review_prompt_detail.txt" \
    "{core}" "$TMP_DIR/core_content.json" \
    "{data}" "$TMP_DIR/data.json"

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
if ! _validate_report "$TMP_DIR/detail.json" "review_detail"; then
    echo "⚠️  Round 2 校验未通过，尝试重新生成..."
    _save_raw_on_failure "$TMP_DIR/detail_raw.txt" "Round2-validate-fail"
    if ! _run_claude_round "$TMP_DIR/detail_prompt.txt" "$TMP_DIR/detail_raw.txt"; then
        echo "❌ Round 2 重试失败"; exit 1
    fi
    if ! _extract_json "$TMP_DIR/detail_raw.txt" "$TMP_DIR/detail.json"; then
        echo "❌ Round 2 重试 JSON 提取失败"; trap - EXIT; exit 1
    fi
    if ! _validate_report "$TMP_DIR/detail.json" "review_detail"; then
        echo "⚠️  Round 2 重试仍未通过校验，继续使用当前结果"
    fi
fi
echo "  ✓ 详细分析生成完成"

# ── 5. 合并 + 默认值兜底 + 保存 ────────────────────────────────
echo "[5/6] 合并并保存..."

echo "$SENTIMENT" > "$TMP_DIR/sentiment.json"
echo "$RISK_ALERTS" > "$TMP_DIR/risk_alerts.json"

# Python 直接写 save_payload.json，不经过 bash 变量（避免大 JSON 截断）
python3 - "$TMP_DIR" "$TRADE_DATE" <<'PYEOF'
import json, sys, pathlib, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")

tmp = pathlib.Path(sys.argv[1])
trade_date = sys.argv[2]

core = json.load(open(tmp / "core.json"))
detail = json.load(open(tmp / "detail.json"))

try:
    sentiment = json.load(open(tmp / "sentiment.json"))
except (json.JSONDecodeError, FileNotFoundError):
    sentiment = {}
try:
    risk_raw = json.load(open(tmp / "risk_alerts.json"))
except (json.JSONDecodeError, FileNotFoundError):
    risk_raw = {}

sent_data = sentiment.get("data", sentiment)

sc = core.get("strategy_conclusion", {})
if isinstance(sc, dict):
    sc = json.dumps(sc, ensure_ascii=False)

payload = {
    "trade_date": trade_date,
    "temperature": sent_data.get("temperature"),
    "limit_up_count": sent_data.get("limit_up"),
    "limit_down_count": sent_data.get("limit_down"),
    "broken_count": sent_data.get("broken"),
    "seal_rate": sent_data.get("seal_rate"),
    "max_board": sent_data.get("max_board"),
    "strategy_conclusion": sc,
    "dominant_strategy": core.get("dominant_strategy", "混合均衡"),
    "strategy_switch_signal": core.get("strategy_switch_signal", ""),
    "risk_summary": core.get("risk_summary", ""),
    "market_summary": detail.get("market_summary", ""),
    "sector_analysis": detail.get("sector_analysis", ""),
    "sentiment_narrative": detail.get("sentiment_narrative", ""),
    "board_play_summary": detail.get("board_play_summary", ""),
    "swing_trade_summary": detail.get("swing_trade_summary", ""),
    "value_invest_summary": detail.get("value_invest_summary", ""),
    "risk_alerts_json": json.dumps(
        risk_raw.get("data", []) if isinstance(risk_raw, dict) else [],
        ensure_ascii=False,
    ),
}

# 直接写文件，不经过 bash 变量
json.dump(payload, open(tmp / "save_payload.json", "w"), ensure_ascii=False)

# 合并后写入 review.json 供终端预览
merged = {**core, **detail}
json.dump(merged, open(tmp / "review.json", "w"), ensure_ascii=False, indent=2)
PYEOF

if [ $? -ne 0 ]; then
    echo "⚠️  Payload 组装失败"
    trap - EXIT; exit 0
fi

HTTP_CODE=$(_save_to_backend "/api/v1/review/save" "$TMP_DIR/save_payload.json")

if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ]; then
    echo "  ✓ 复盘报告已保存到数据库"
else
    echo "  ⚠️  保存失败 (HTTP $HTTP_CODE)，保存到本地"
    mkdir -p "$PROJECT_ROOT/scripts/output"
    cp "$TMP_DIR/review.json" "$PROJECT_ROOT/scripts/output/review_${TRADE_DATE}.json"
    echo "  → scripts/output/review_${TRADE_DATE}.json"
fi

# ── 6. 生成 Markdown 报告 ──────────────────────────────────────
echo "[6/6] 生成 Markdown 报告..."

REPORT_DIR="$PROJECT_ROOT/reports"
mkdir -p "$REPORT_DIR"
MD_FILE="$REPORT_DIR/review_${TRADE_DATE}.md"

python3 - "$TMP_DIR" "$TRADE_DATE" "$MD_FILE" <<'PYEOF'
import json, pathlib, sys

tmp = pathlib.Path(sys.argv[1])
trade_date, md_path = sys.argv[2], sys.argv[3]
core = json.load(open(tmp / "core.json"))
detail = json.load(open(tmp / "detail.json"))

sc = core.get("strategy_conclusion", {})
if isinstance(sc, str):
    try: sc = json.loads(sc)
    except: sc = {}

date_fmt = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"

# ── 作战卡（主报告）──────────────────────────────────────────
card = [f"# {date_fmt} 复盘速览\n"]
card.append(f"方向: **{sc.get('direction','?')}** | "
            f"信心: **{sc.get('confidence','?')}** | "
            f"策略: **{core.get('dominant_strategy','?')}**\n")

# 重点板块
fs = sc.get("focus_sectors", [])
if fs:
    card.append(f"**重点板块**: {', '.join(fs)}\n")

# 策略切换信号（浓缩为一句）
switch = core.get("strategy_switch_signal", "")
if switch and switch != "无需切换":
    # 取第一句话作为摘要
    first_sent = switch.split("；")[0].split("。")[0]
    card.append(f"**策略信号**: {first_sent}\n")

# 风险警示（简要列表）
rw = sc.get("risk_warnings", [])
if rw:
    card.append("### 风险警示")
    for r in rw[:4]:
        card.append(f"- {r[:80]}")
    card.append("")

# 关键数据
summary = detail.get("market_summary", "")
if summary:
    # 提取前2句作为大盘摘要
    sents = [s.strip() for s in summary.replace("；", "。").split("。") if s.strip()]
    if len(sents) >= 2:
        card.append(f"**大盘**: {sents[0]}。{sents[1]}。\n")
    elif sents:
        card.append(f"**大盘**: {sents[0]}。\n")

pathlib.Path(md_path).write_text("\n".join(card), encoding="utf-8")

# ── 详细分析（单独文件）─────────────────────────────────────
detail_path = md_path.replace(".md", "_detail.md")
lines = [f"# {date_fmt} 收盘复盘 — 详细分析\n"]

for key, title in [
    ("market_summary", "大盘综述"),
    ("sector_analysis", "板块分析"),
    ("sentiment_narrative", "情绪面"),
    ("board_play_summary", "短线打板"),
    ("swing_trade_summary", "波段趋势"),
    ("value_invest_summary", "价值投资"),
]:
    text = detail.get(key, "")
    if text:
        lines.append(f"## {title}\n\n{text}\n")

lines.append(f"## 风险提示\n\n{core.get('risk_summary', '')}\n")
lines.append(f"## 策略切换信号\n\n{core.get('strategy_switch_signal', '无需切换')}\n")

pathlib.Path(detail_path).write_text("\n".join(lines), encoding="utf-8")
PYEOF

echo "  ✓ $MD_FILE"
echo ""
echo "=== 复盘报告生成完毕 ==="
echo "交易日: $TRADE_DATE"
echo "报告文件: reports/review_${TRADE_DATE}.md"
echo "日志文件: $LOG_FILE"
