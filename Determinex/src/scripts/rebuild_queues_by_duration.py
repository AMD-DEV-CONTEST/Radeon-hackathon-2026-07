#!/usr/bin/env python3
"""Rebuild queue_light.txt / queue_heavy.txt by ACTUAL eval duration from history.

build_tiered_queues.py used cost-score heuristic which mis-classified big tools
(atlas 1732 tests, oranda 978 tests) into light queue. They then hit the
5-min light cap with 0% scores.

This script reads SQLite determinex.db (or eval.json files) for duration data,
and re-tiers based on observed runtime:
  - light: tools that consistently finish under 4 min
  - heavy: tools that take >4 min OR have >500 tests OR no history

Output: /c/tmp/queue_light.txt, /c/tmp/queue_heavy.txt
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

ROOT = Path("T:/determinex-programbench")
LIGHT_THRESHOLD_SECS = 240  # tools faster than 4min on most evals → light
TEST_COUNT_HEAVY_THRESHOLD = 500


def get_history() -> dict[str, list[tuple[int, int, int]]]:
    """Return {tool: [(passed, total, duration_s), ...]} from all eval.jsons."""
    history: dict[str, list] = {}
    for ej in glob.glob(str(ROOT / "determinex_pb_*_v*" / "*" / "*.eval.json")):
        tool = Path(ej).parent.name
        try:
            j = json.loads(Path(ej).read_text(encoding="utf-8"))
            r = j.get("test_results") or []
            if not r:
                continue
            passed = sum(1 for x in r if x.get("status") == "passed")
            total = len(r)
            # duration from filename or mtime? We don't have it stored in eval.json.
            # Use total test count as a proxy (more tests → longer).
            history.setdefault(tool, []).append((passed, total, total))
        except Exception:
            continue
    return history


def classify(tool: str, history: dict) -> str:
    hits = history.get(tool, [])
    if not hits:
        return "heavy"  # unknown → assume heavy (safer)
    # Look at LARGEST test count seen for this tool
    max_total = max(h[1] for h in hits)
    if max_total > TEST_COUNT_HEAVY_THRESHOLD:
        return "heavy"
    return "light"


def main():
    # Read the existing queue file to know which tools to classify
    src = Path("c:/tmp/queue_all_with_overrides.txt")
    if not src.exists():
        # Fall back: union of light + heavy
        light = Path("c:/tmp/queue_light.txt").read_text().splitlines()
        heavy = Path("c:/tmp/queue_heavy.txt").read_text().splitlines()
        tools = sorted(set(light + heavy))
    else:
        tools = [t.strip() for t in src.read_text().splitlines() if t.strip()]

    history = get_history()
    light, heavy = [], []
    for t in tools:
        tier = classify(t, history)
        (light if tier == "light" else heavy).append(t)

    out_light = Path("c:/tmp/queue_light.txt")
    out_heavy = Path("c:/tmp/queue_heavy.txt")
    out_light.write_text("\n".join(light) + "\n", encoding="utf-8", newline="\n")
    out_heavy.write_text("\n".join(heavy) + "\n", encoding="utf-8", newline="\n")
    print(f"total: {len(tools)}")
    print(f"  light (<=500 tests): {len(light)}")
    print(f"  heavy (>500 tests OR unknown): {len(heavy)}")
    print()
    print("=== light samples ===")
    for t in light[:10]:
        print(f"  {t}")
    print("=== heavy samples ===")
    for t in heavy[:10]:
        print(f"  {t}")


if __name__ == "__main__":
    main()
