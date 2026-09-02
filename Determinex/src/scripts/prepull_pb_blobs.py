#!/usr/bin/env python3
"""Pre-pull HF blob test caches for every ProgramBench task.

Without this, `programbench eval` does a cold HF fetch on first eval per tool —
~5-10 min per tool of pure download latency. Pre-pulling once keeps the mass
run focused on real work, not network I/O.

Usage:
  python scripts/prepull_pb_blobs.py            # pull all 200 (idempotent)
  python scripts/prepull_pb_blobs.py --limit 5  # pull first 5 only (smoke)
  python scripts/prepull_pb_blobs.py --check    # report what's cached, no pulls

Cache lives at ~/.cache/huggingface/hub/datasets--programbench--ProgramBench-Tests
(hardcoded in `determinex_programbench_probe.py:_HF_SNAPSHOT_ROOT` — do not redirect).

Expected size: ~2-3 GB total. Disk usage warning printed if C: has <20 GB free.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TASKS_DIR = Path("T:/Dev/ProgramBench/src/programbench/data/tasks")
HF_CACHE_ROOT = (
    Path.home() / ".cache/huggingface/hub/datasets--programbench--ProgramBench-Tests/snapshots"
)

# Force ProgramBench's blob_store import path to find the right module
sys.path.insert(0, str(Path("T:/Dev/ProgramBench/src")))


def list_tasks() -> list[str]:
    if not TASKS_DIR.is_dir():
        print(f"ERROR: ProgramBench tasks dir not found: {TASKS_DIR}", file=sys.stderr)
        sys.exit(2)
    return sorted([p.name for p in TASKS_DIR.iterdir() if p.is_dir() and "__" in p.name])


def find_local_snapshot(instance_id: str) -> Path | None:
    if not HF_CACHE_ROOT.exists():
        return None
    for snap in sorted(HF_CACHE_ROOT.iterdir(), reverse=True):
        p = snap / instance_id
        if p.exists():
            return p
    return None


HF_REPO_ID = "programbench/ProgramBench-Tests"
HF_REVISION = "main"


def pull_one(instance_id: str) -> tuple[bool, str, int]:
    """Returns (cached_now, msg, size_kb)."""
    existing = find_local_snapshot(instance_id)
    if existing:
        size_kb = sum(f.stat().st_size for f in existing.rglob("*") if f.is_file()) // 1024
        return False, "already cached", size_kb
    try:
        from huggingface_hub import snapshot_download
    except Exception as e:
        return False, f"huggingface_hub import failed: {e}", 0
    try:
        base = Path(
            snapshot_download(
                HF_REPO_ID,
                repo_type="dataset",
                revision=HF_REVISION,
                allow_patterns=f"{instance_id}/**",
            )
        )
    except Exception as e:
        return False, f"download failed: {type(e).__name__}: {str(e)[:160]}", 0
    result = base / instance_id
    if not result.exists():
        return False, "HF returned no files (instance not in dataset)", 0
    size_kb = sum(f.stat().st_size for f in result.rglob("*") if f.is_file()) // 1024
    return True, "pulled", size_kb


def main():
    ap = argparse.ArgumentParser(description="Pre-pull ProgramBench HF blob caches")
    ap.add_argument(
        "--limit", type=int, default=0, help="pull only the first N tasks (default: all)"
    )
    ap.add_argument("--check", action="store_true", help="don't pull, just report cache state")
    ap.add_argument("--only", nargs="+", help="pull only these specific instance IDs")
    args = ap.parse_args()

    free_gb = shutil.disk_usage("c:/").free / (1024**3)
    print(f"=== Pre-pull ProgramBench HF blobs ===  C: free = {free_gb:.1f} GB")
    if free_gb < 20:
        print(f"⚠ WARNING: C: drive has only {free_gb:.1f} GB free. Pre-pull needs ~2-3 GB.")

    tasks = list_tasks()
    if args.only:
        tasks = [t for t in tasks if t in args.only]
    if args.limit and not args.only:
        tasks = tasks[: args.limit]
    print(f"Tasks to inspect: {len(tasks)}")

    if args.check:
        cached = sum(1 for t in tasks if find_local_snapshot(t))
        missing = len(tasks) - cached
        print(f"Cached: {cached}/{len(tasks)}    Missing: {missing}")
        if missing and missing <= 30:
            print("Missing list:")
            for t in tasks:
                if not find_local_snapshot(t):
                    print(f"  - {t}")
        return

    t0 = time.time()
    n_pulled = 0
    n_skipped = 0
    n_failed = 0
    total_kb = 0
    for i, iid in enumerate(tasks, 1):
        sys.stdout.write(f"[{i:>3}/{len(tasks)}] {iid:60s} ")
        sys.stdout.flush()
        pulled_now, msg, size_kb = pull_one(iid)
        if pulled_now:
            n_pulled += 1
            print(f"  PULLED ({size_kb / 1024:.1f} MB)")
        elif msg == "already cached":
            n_skipped += 1
            print(f"  cached ({size_kb / 1024:.1f} MB)")
        else:
            n_failed += 1
            print(f"  FAILED — {msg}")
        total_kb += size_kb

    dt = time.time() - t0
    print(f"\n=== Done in {dt:.0f}s ({dt / 60:.1f}m) ===")
    print(f"Pulled now: {n_pulled}    Already cached: {n_skipped}    Failed: {n_failed}")
    print(f"Total cache size: {total_kb / 1024 / 1024:.2f} GB")
    sys.exit(0 if n_failed == 0 else 1)


if __name__ == "__main__":
    main()
