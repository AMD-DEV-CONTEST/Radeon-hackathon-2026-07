#!/usr/bin/env python3
"""assert_drain_released.py — assert the drain is fully released for a given DB.

Derives state/lock paths from --db (same directory) and checks:
  - drain.state.json.state == "accepting"
  - LOCK_EX|LOCK_NB acquisition succeeds on BOTH drain.lock and maintenance.lock

Exits 0 only when all three hold; else nonzero with the failing check named.
Usage: python scripts/assert_drain_released.py --db <path>
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from pathlib import Path


def probe_exclusive(path: Path) -> bool:
    """True if we can acquire an EXCLUSIVE flock non-blocking (i.e. it is free)."""
    if not path.exists():
        return True
    fd = os.open(path, os.O_RDWR)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return True
        except OSError:
            return False
    finally:
        os.close(fd)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    args = ap.parse_args()
    db = Path(args.db).resolve()
    base = db.parent
    state_file = base / "drain.state.json"
    drain_lock = base / "drain.lock"
    maint_lock = base / "maintenance.lock"

    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            cur = state.get("state")
        except (json.JSONDecodeError, OSError):
            print("ASSERT_FAIL: drain.state.json unreadable")
            return 1
    else:
        cur = None
    if cur != "accepting":
        print(f"ASSERT_FAIL: state={cur} (expected accepting)", file=sys.stderr)
        return 1
    if not probe_exclusive(drain_lock):
        print("ASSERT_FAIL: drain.lock is held")
        return 1
    if not probe_exclusive(maint_lock):
        print("ASSERT_FAIL: maintenance.lock is held")
        return 1
    print(f"ASSERT_DRAIN_RELEASED_OK: db={db} state=accepting both locks free")
    return 0


if __name__ == "__main__":
    sys.exit(main())
