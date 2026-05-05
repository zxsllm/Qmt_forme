"""一次性测 MonitorPage 与 CommandCenter 用到的 API 后端耗时。

run: python scripts/bench_api_latency.py
"""
from __future__ import annotations

import statistics
import time
from datetime import date

import urllib.request

BASE = "http://127.0.0.1:8000"
TODAY = date.today().strftime("%Y%m%d")

ENDPOINTS: list[tuple[str, str]] = [
    ("MonitorPage", f"/api/v1/monitor/snapshot"),
    ("MonitorPage", f"/api/v1/monitor/events?limit=50"),
    ("MonitorPage", f"/api/v1/monitor/largecap?limit=50"),
    ("MonitorPage", f"/api/v1/monitor/events/stats?days=7"),
    ("MonitorPage", f"/api/v1/monitor/outcomes/baseline?days=30&source=all"),
    ("MonitorPage", f"/api/v1/monitor/outcomes/distribution?days=30"),
    ("MonitorPage", f"/api/v1/monitor/outcomes/slices?group_by=pattern&source=largecap"),
    ("CommandCenter", f"/api/v1/plan/data/{TODAY}"),
    ("CommandCenter", f"/api/v1/review/data/{TODAY}"),
    ("CommandCenter", f"/api/v1/signals/ranked?limit=20"),
    ("CommandCenter", f"/api/v1/market/global-indices"),
    ("CommandCenter", f"/api/v1/execution/risk-status"),
]

ROUNDS = 5


def time_one(url: str) -> tuple[float, int]:
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(BASE + url, timeout=15) as r:
            body = r.read()
            ms = (time.perf_counter() - t0) * 1000
            return ms, len(body)
    except Exception as e:
        return -1, -1


def main() -> None:
    print(f"{'page':<14} {'endpoint':<60} {'p50_ms':>8} {'p95_ms':>8} {'max_ms':>8} {'kb':>7}")
    print("-" * 110)
    for page, url in ENDPOINTS:
        samples: list[float] = []
        size = 0
        for _ in range(ROUNDS):
            ms, sz = time_one(url)
            if ms >= 0:
                samples.append(ms)
                size = sz
        if not samples:
            print(f"{page:<14} {url:<60} {'ERR':>8}")
            continue
        p50 = statistics.median(samples)
        p95 = sorted(samples)[max(0, int(len(samples) * 0.95) - 1)]
        mx = max(samples)
        kb = size / 1024
        flag = " SLOW" if p50 > 500 else ("" if p50 < 200 else " ~")
        print(f"{page:<14} {url:<60} {p50:>8.1f} {p95:>8.1f} {mx:>8.1f} {kb:>7.1f}{flag}")


if __name__ == "__main__":
    main()
