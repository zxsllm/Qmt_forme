"""
Daily sync — run after market close to refresh all data.

Includes incremental minute data sync (~5-10 min for 1 day).

Usage:
    python scripts/daily_sync.py              # sync everything
    python scripts/daily_sync.py --dry-run    # preview only
"""

import subprocess
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable


def run(script: str, args: list[str] | None = None):
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


def main():
    dry_run = "--dry-run" in sys.argv
    extra = ["--dry-run"] if dry_run else []

    results = {}

    results["sync_incremental"] = run("sync_incremental.py", extra)

    results["pull_stk_limit"] = run("pull_stk_limit.py")

    results["pull_moneyflow"] = run("pull_moneyflow.py")
    results["pull_news"] = run("pull_news.py")
    results["pull_anns"] = run("pull_anns.py")
    results["pull_st_list"] = run("pull_st_list.py")
    results["pull_adj_factor"] = run("pull_adj_factor.py")
    results["pull_sw_daily"] = run("pull_sw_daily.py")
    results["pull_stk_auction"] = run("pull_stk_auction.py")
    results["pull_eco_cal"] = run("pull_eco_cal.py")
    results["pull_moneyflow_ind"] = run("pull_moneyflow_ind.py")
    results["pull_index_global"] = run("pull_index_global.py")

    # Incremental minute data sync (last ~5-10 min for 1 day of data)
    results["sync_minutes"] = run("sync_minutes_incremental.py")

    # Financial data (daily mode: forecast+disclosure always, fina_indicator/income only for new periods)
    results["pull_fina"] = run("pull_fina.py", ["--daily"])

    # Limit board / sentiment data (daily)
    results["pull_limit_board"] = run("pull_limit_board.py")

    # Classify new news + announcements (incremental, only unclassified)
    results["classify_news"] = run("classify_news.py")

    print(f"\n{'='*60}")
    print("  Daily Sync Summary")
    print(f"{'='*60}")
    for name, ok in results.items():
        print(f"  {'[OK]' if ok else '[FAIL]'} {name}")
    print()

    all_ok = all(results.values())
    if all_ok:
        print("  All syncs completed successfully (including minute data).")
    else:
        print("  Some syncs failed. Check output above.")
    print()


if __name__ == "__main__":
    main()
