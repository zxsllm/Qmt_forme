#!/usr/bin/env bash
# _common.sh — review_cli.sh 和 morning_plan_cli.sh 的公共函数库
#
# 用法: 在脚本开头 source 此文件
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   . "$SCRIPT_DIR/_common.sh"

# Windows 下 Python 默认编码为 GBK，强制使用 UTF-8
export PYTHONUTF8=1

# 确保 npm global bin 在 PATH 中（claude-sg 等工具）
_NPM_BIN="${APPDATA:-$HOME/AppData/Roaming}/npm"
if [ -d "$_NPM_BIN" ] && [[ ":$PATH:" != *":$_NPM_BIN:"* ]]; then
    export PATH="$_NPM_BIN:$PATH"
fi

# ── API 地址自动检测 ──────────────────────────────────────────────
# WSL2 下 localhost 不通 Windows 侧，需要用网关 IP
_detect_api_base() {
    local base="http://localhost:8000"
    if grep -qi microsoft /proc/version 2>/dev/null; then
        local win_ip
        win_ip=$(ip route show default 2>/dev/null | awk '{print $3}')
        if [ -n "$win_ip" ]; then
            base="http://${win_ip}:8000"
        fi
    fi
    echo "$base"
}

# ── curl 封装（WSL 下绕过代理）────────────────────────────────────
_curl() { curl --noproxy '*' "$@"; }

# ── 后端健康检查 ──────────────────────────────────────────────────
_check_health() {
    local api_base="$1"
    if ! _curl -sf "$api_base/health" > /dev/null 2>&1; then
        echo "后端不可用: $api_base/health" >&2
        echo "请确认后端已启动: cd backend && uvicorn app.main:app" >&2
        return 1
    fi
    return 0
}

# ── 清理残留 claude-sg 代理进程 ───────────────────────────────────
# claude-sg 在 port 18880 启动本地代理，进程可能在上一轮调用结束后残留，
# 导致下一轮 ECONNRESET 或挂死。每次调用前主动清理。
_cleanup_claude_proxy() {
    local pids
    pids=$(netstat -ano 2>/dev/null | grep ':18880 ' | grep 'LISTEN' | awk '{print $NF}' | sort -u)
    if [ -n "$pids" ]; then
        for pid in $pids; do
            taskkill //F //PID "$pid" > /dev/null 2>&1 || true
        done
        sleep 2
    fi
}

# ── Claude 调用封装 ───────────────────────────────────────────────
# 用法: _run_claude_round prompt_file output_file
# 大 prompt 通过 --append-system-prompt-file 传入（绕过命令行参数长度限制）
_run_claude_round() {
    local prompt_file="$1" output_file="$2"
    local cmd="${CLAUDE_CMD:-claude-sg}"

    # 清理上一轮残留的代理进程
    _cleanup_claude_proxy

    # git-bash 下 which 找不到 .cmd，自动加后缀
    if ! command -v "$cmd" > /dev/null 2>&1; then
        if command -v "${cmd}.cmd" > /dev/null 2>&1; then
            cmd="${cmd}.cmd"
        fi
    fi
    # Windows 上 claude-sg.cmd 的 PowerShell 封装需要 Windows 格式路径
    local win_path="$prompt_file"
    if command -v cygpath > /dev/null 2>&1; then
        win_path="$(cygpath -w "$prompt_file")"
    fi
    $cmd --print \
        --append-system-prompt-file "$win_path" \
        "基于上述指令和数据，严格按要求输出JSON。" \
        > "$output_file" 2>/dev/null
}

# ── JSON 提取 ─────────────────────────────────────────────────────
# 用法: _extract_json input_file output_file
_extract_json() {
    local infile="$1" outfile="$2"
    python3 "$SCRIPT_DIR/_extract_json.py" "$infile" "$outfile"
}

# ── 报告校验 ──────────────────────────────────────────────────────
# 用法: _validate_report json_file report_type
# report_type: review_core / review_detail / plan_core / plan_detail
_validate_report() {
    local json_file="$1" report_type="$2"
    python3 "$SCRIPT_DIR/_validate_report.py" "$json_file" "$report_type"
}

# ── 模板渲染 ──────────────────────────────────────────────────────
# 用法: _render_prompt output_file template_file placeholder1 data_file1 [...]
_render_prompt() {
    local output_file="$1"; shift
    python3 "$SCRIPT_DIR/_render_prompt.py" "$@" > "$output_file"
}

# ── 后端保存 ──────────────────────────────────────────────────────
# 用法: _save_to_backend endpoint payload_file
# 返回 HTTP 状态码
_save_to_backend() {
    local endpoint="$1" payload_file="$2"
    local api_base="${API_BASE:-http://localhost:8000}"
    _curl -sf -o /dev/null -w "%{http_code}" \
        -X POST "$api_base$endpoint" \
        -H "Content-Type: application/json" \
        -d @"$payload_file" 2>/dev/null || echo "000"
}

# ── 日志初始化 ────────────────────────────────────────────────────
# 用法: _init_logging script_name trade_date
# 设置全局 LOG_FILE 变量，并将 stdout/stderr 同时写入日志
_init_logging() {
    local script_name="$1" trade_date="$2"
    local log_dir="$PROJECT_ROOT/logs"
    mkdir -p "$log_dir"
    LOG_FILE="$log_dir/${script_name}_${trade_date}_$(date +%H%M%S).log"
    exec > >(tee -a "$LOG_FILE") 2>&1
}

# ── 失败时保留原始输出 ────────────────────────────────────────────
# 用法: _save_raw_on_failure raw_file label
_save_raw_on_failure() {
    local raw_file="$1" label="$2"
    if [ -n "${LOG_FILE:-}" ] && [ -f "$raw_file" ]; then
        echo "--- ${label} 原始输出 ---" >> "$LOG_FILE"
        cat "$raw_file" >> "$LOG_FILE"
        echo "--- END ---" >> "$LOG_FILE"
    fi
}
