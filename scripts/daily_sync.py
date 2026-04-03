"""
Daily sync — CLI fallback for manual runs.

In normal operation, the scheduler handles all data syncs in-process at 15:30.
This script is kept for:
  1. Manual full sync: python scripts/daily_sync.py
  2. Minutes-only sync: python scripts/daily_sync.py --minutes-only
  3. Startup recovery when scheduler hasn't run yet

The heavy sync_minutes_incremental is always run as subprocess (30-60 min).
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable

sys.path.insert(0, str(SCRIPTS_DIR.parent / "backend"))


def run_script(script: str, args: list[str] | None = None):
    cmd = [PYTHON, str(SCRIPTS_DIR / script)] + (args or [])
    print(f"\n{'='*60}")
    print(f"  Running: {' '.join(cmd)}")
    print(f"{'='*60}\n")
    t0 = time.time()
    result = subprocess.run(cmd, cwd=str(SCRIPTS_DIR.parent))
    elapsed = time.time() - t0
    status = "OK" if result.returncode == 0 else f"FAILED (exit {result.returncode})"
    print(f"\n  → {script}: {status} ({elapsed:.1f}s)")
    return result.returncode == 0


def run_in_process_sync():
    """Run all non-minute syncs via data_sync module (same as scheduler does)."""
    from app.execution.feed.data_sync import run_post_market_sync
    from datetime import datetime

    today = datetime.now().strftime("%Y%m%d")
    results = run_post_market_sync(today)
    return all(results.values())


def main():
    parser = argparse.ArgumentParser(description="Daily data sync")
    parser.add_argument("--minutes-only", action="store_true", help="Only run minute data sync")
    parser.add_argument("--no-minutes", action="store_true", help="Skip minute data sync")
    args = parser.parse_args()

    results = {}

    if not args.minutes_only:
        print("\n=== Phase 1: In-process data sync (all non-minute data) ===\n")
        t0 = time.time()
        results["in_process_sync"] = run_in_process_sync()
        print(f"\n  In-process sync: {'OK' if results['in_process_sync'] else 'PARTIAL FAIL'} ({time.time()-t0:.1f}s)")

    if not args.no_minutes:
        print("\n=== Phase 2: Minute data sync (subprocess, 30-60 min) ===\n")
        results["sync_minutes"] = run_script("sync_minutes_incremental.py")

    print(f"\n{'='*60}")
    print("  Daily Sync Summary")
    print(f"{'='*60}")
    for name, ok in results.items():
        print(f"  {'[OK]' if ok else '[FAIL]'} {name}")
    print()


if __name__ == "__main__":
    main()
