import urllib.request, json, sys, os
sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://127.0.0.1:8000'

def fetch(path):
    try:
        r = urllib.request.urlopen(f'{BASE}{path}', timeout=10)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')[:300] if e.fp else ""
        return e.code, {"_error": body}
    except Exception as e:
        return 0, {"_error": str(e)}

# Simulate what the frontend SentimentPage does on load
# 1. First it fetches limitBoard to get latest trade date
code, d = fetch('/api/v1/sentiment/limit-board?trade_date=&limit_type=')
trade_date = d.get('trade_date', '?')
print(f"1. limitBoard -> trade_date={trade_date} (HTTP {code})")

# 2. Then with that tradeDate, it loads each tab
tabs = [
    ('temperature', f'/api/v1/sentiment/temperature?trade_date={trade_date}'),
    ('premarket', f'/api/v1/premarket/plan?date={trade_date}'),
    ('leaders', f'/api/v1/sentiment/leaders?trade_date={trade_date}&concept='),
    ('hot-money', f'/api/v1/sentiment/hot-money?trade_date={trade_date}'),
    ('dragon-tiger', f'/api/v1/sentiment/dragon-tiger?trade_date={trade_date}&limit=30'),
    ('hot-list', f'/api/v1/sentiment/hot-list?trade_date={trade_date}'),
    ('limit-step', f'/api/v1/sentiment/limit-step?trade_date={trade_date}'),
]

for name, path in tabs:
    code, d = fetch(path)
    if code != 200:
        print(f"  [{code}] {name:20} BROKEN!")
        print(f"         error: {d.get('_error', '')[:200]}")
    else:
        count = d.get('count')
        data = d.get('data')
        if count is not None:
            detail = f"count={count}"
        elif isinstance(data, list):
            detail = f"data: {len(data)} items"
        elif isinstance(data, dict):
            detail = f"data keys: {list(data.keys())[:6]}"
        else:
            detail = f"keys: {list(d.keys())[:6]}"
        print(f"  [200 ] {name:20} {detail}")

# 3. Also test with today's date (20260402) since user might have selected today
print(f"\n--- Same but with trade_date=20260402 (today) ---")
tabs_today = [
    ('temperature-today', '/api/v1/sentiment/temperature?trade_date=20260402'),
    ('premarket-today', '/api/v1/premarket/plan?date=20260402'),
    ('leaders-today', '/api/v1/sentiment/leaders?trade_date=20260402&concept='),
]
for name, path in tabs_today:
    code, d = fetch(path)
    if code != 200:
        print(f"  [{code}] {name:20} BROKEN!")
        print(f"         error: {d.get('_error', '')[:200]}")
    else:
        count = d.get('count')
        data = d.get('data')
        if count is not None:
            detail = f"count={count}"
        elif isinstance(data, list):
            detail = f"data: {len(data)} items"
        elif isinstance(data, dict):
            detail = f"data keys: {list(data.keys())[:6]}"
        elif data is None:
            detail = "data=null"
        else:
            detail = f"keys: {list(d.keys())[:6]}"
        print(f"  [200 ] {name:20} {detail}")
