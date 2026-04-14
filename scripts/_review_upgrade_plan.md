# Review/Plan System Upgrade — Implementation Instructions

Based on 4-agent deep review (2026-04-12). Comprehensive upgrade plan.

## Task 1: Price Anchors (data + prompt)

### Goal
Make entry_plan_json and exit_plan_json include concrete target_price and stop_loss values.

### Data Layer Changes
File: `backend/app/shared/plan_api.py`

Add new helper `_get_price_anchors(session, ts_codes, trade_date)`:
- For each ts_code, call `support_resistance(session, ts_code, days=60)` from `app.shared.tech_signal`
- Also call `data_loader.stk_limit(ts_code, trade_date)` for limit prices
- Return dict per stock: `{ts_code, close, ma5, ma10, ma20, ma60, support_levels, resistance_levels, up_limit, down_limit, period_high, period_low}`
- Inject result into `aggregate_plan_data()` return under key `price_anchors`

Also add to `aggregate_review_data()` in `review_api.py` — for sector leaders/dragon stocks, include their MA positions.

### Prompt Changes
File: `scripts/prompts/plan_prompt_detail.txt`

Add to data section:
```
## 关注个股价格锚点
{price_anchors}
```

Change entry_plan_json schema:
- target_price: "基于阻力位或前高计算，必须填写具体数字"
- stop_loss: "基于MA20或支撑位计算，必须填写具体数字"
- Add instruction: "你有每只股票的MA5/MA10/MA20/MA60和支撑阻力位数据，请据此给出具体价格"

### CLI Changes
Files: `scripts/morning_plan_cli.sh`, `scripts/review_cli.sh`

In data extraction section, extract price_anchors from PLAN_DATA and pass to detail prompt.

---

## Task 2: Learning Loop (retrospect + yesterday_plan)

### Goal
Inject historical prediction accuracy and yesterday's plan into prompts. Keep corrections gentle to avoid overfitting.

### Data Layer Changes
File: `backend/app/shared/plan_api.py`

Add helper `_get_retrospect_summary(session, trade_date, lookback=10)`:
```sql
SELECT trade_date, predicted_direction, predicted_temperature,
       actual_result, accuracy_score, retrospect_note
FROM daily_plan
WHERE trade_date < :td AND actual_result IS NOT NULL
ORDER BY trade_date DESC LIMIT :lookback
```
Compute: total_count, correct_count, partial_count, wrong_count, avg_accuracy.
Return: `{stats: {accuracy_rate, avg_score, recent_bias}, recent_predictions: [...]}`

Add helper `_get_yesterday_plan(session, trade_date)`:
```sql
SELECT predicted_direction, predicted_temperature, confidence_score,
       watch_sectors_json, watch_stocks_json, entry_plan_json,
       key_logic, actual_result, accuracy_score
FROM daily_plan WHERE trade_date < :td ORDER BY trade_date DESC LIMIT 1
```

Inject both into `aggregate_plan_data()` return.

### Prompt Changes
File: `scripts/prompts/plan_prompt_core.txt`

Add sections:
```
## 历史预判回溯（仅供参考，避免过度修正）
{retrospect}

## 昨日计划执行回顾
{yesterday_plan}
```

Add instruction: "参考历史预判准确率，如存在系统性偏差（如连续偏多但实际偏空），适度校正本次判断。注意：不要过度修正，保持独立分析。"

### CLI Changes
Extract retrospect and yesterday_plan from PLAN_DATA, inject into prompt.

---

## Task 3: Activate Similar Market Injection

### Goal
Replace hardcoded `SIMILAR="暂无..."` with actual similar market data from existing API.

### CLI Changes
Files: `scripts/review_cli.sh`, `scripts/morning_plan_cli.sh`

After data fetch, add:
```bash
# Fetch similar markets (requires previous day's vector)
SIMILAR=$(_curl -sf "$API_BASE/api/v1/review/similar/$PREV_TRADE_DATE?top_k=3" || echo '{"data":[]}')
```

For plan: use `/api/v1/plan/similar/` endpoint.

Format the similar data as readable text before injection.

---

## Task 4: Post-Generation Validation

### Goal
Prevent TEST/placeholder text from appearing in final reports.

### Implementation
File: `scripts/_validate_report.py` (new)

```python
BLACKLIST = ["TEST", "TODO", "PLACEHOLDER", "FIXME", "待填写"]
MIN_SECTION_LENGTH = 50  # chars

def validate(json_data, required_fields):
    errors = []
    for field in required_fields:
        value = json_data.get(field, "")
        if not value or len(str(value)) < MIN_SECTION_LENGTH:
            errors.append(f"{field}: too short ({len(str(value))} chars)")
        for word in BLACKLIST:
            if word in str(value).upper():
                errors.append(f"{field}: contains blacklisted word '{word}'")
    return errors
```

Call after each round's JSON extraction in CLI scripts. If validation fails, retry once or report error.

---

## Task 5: CLI Pipeline Improvements

### 5a. Extract common functions
Create `scripts/_common.sh` with:
- `_detect_api_base()`, `_curl()`, `_check_health()`
- `_run_claude_round(prompt_file, output_file)`
- `_save_to_backend(endpoint, payload_file)`

Both CLI scripts source it: `. "$SCRIPT_DIR/_common.sh"`

### 5b. Replace bash template with Python
Create `scripts/_render_prompt.py`:
```python
import sys, json
template = open(sys.argv[1]).read()
for i in range(2, len(sys.argv), 2):
    placeholder = sys.argv[i]
    data_file = sys.argv[i+1]
    data = open(data_file).read()
    template = template.replace(placeholder, data)
print(template)
```

CLI usage:
```bash
python3 "$SCRIPT_DIR/_render_prompt.py" \
    "$PROMPTS_DIR/review_prompt_core.txt" \
    "{data}" "$TMP_DIR/data.json" \
    "{similar}" "$TMP_DIR/similar.json" \
    > "$TMP_DIR/core_prompt.txt"
```

### 5c. Add logging
```bash
LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/${SCRIPT_NAME}_${TRADE_DATE}_$(date +%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1
```

Keep Claude raw output in logs/ on failure.

### 5d. Fix _extract_json.py greedy regex
Change `re.search(r'\{.*\}', raw, re.DOTALL)` to bracket-balanced matching.

---

## Task 6: Prompt Quality Improvements

### 6a. Fix double-quote constraint
All 4 prompt files: Replace:
`⚠️ JSON字符串值内禁止使用英文双引号，请用中文引号「」或单引号代替。`
With:
`⚠️ JSON字符串值内如需引用文本，使用中文引号「」。确保输出是合法JSON。`

### 6b. Change word count to info density
Replace "200字以上" with "至少引用3个具体数据点（股票代码、涨跌幅数字、成交额等），避免泛泛而谈"

### 6c. Add market state pre-assessment
Add to plan_prompt_core.txt before main analysis:
```
在分析前，先判断当前市场阶段：趋势上升期/高位震荡期/趋势下降期/底部筑底期。不同阶段自动调整策略权重。
```

---

## Task 7: Feature Vector Optimization

File: `backend/app/shared/review_engine.py`

### 7a. Fill placeholder dimensions in 36-dim vector
Dimensions 26-29 (技术面): Calculate from index_daily data
- [26] 上证 close vs MA5 position (0=远低于, 0.5=在MA5, 1=远高于)
- [27] 上证 close vs MA20 position
- [28] 上证 close vs MA60 position
- [29] 近20日波动率 (标准差归一化)

Need to pass these values from review_api into review_engine.

### 7b. Fix self-referencing in 16-dim vector
Dimensions 8-11 (策略预判): Replace with objective data
- [8] 全市场涨停/跌停比 (from yesterday review)
- [9] 成交额环比变化
- [10] 两融净买入方向
- [11] 外盘综合涨跌

---

## Priority Order
1. Task 4 (validation) — prevents broken reports, quick fix
2. Task 5b (bash→python template) — prevents crashes
3. Task 1 (price anchors) — highest user value
4. Task 2 (learning loop) — second highest value
5. Task 3 (similar injection) — quick activation
6. Task 6 (prompt quality) — text changes only
7. Task 5a,5c,5d (CLI improvements) — maintenance
8. Task 7 (vector optimization) — lower priority
