#!/usr/bin/env python3
"""programbench_pool_status.py - one-shot status snapshot.

Reads all eval.json files on disk + Hetzner-cached, produces:
  - Score distribution
  - Top scorers
  - Bottom scorers (still to lift)
  - Tools missing eval.json entirely (infra failures)
  - Aggregate avg score
"""

from __future__ import annotations

import glob
import json
from collections import Counter
from pathlib import Path

ROOT = Path("T:/determinex-programbench")


def main():
    # Track latest eval per tool (by mtime). Old eval.jsons from prior iterations
    # exist in determinex_pb_X_v1/, determinex_pb_X_v2/ etc; we want the freshest.
    tools_latest = {}
    for ej in glob.glob(str(ROOT / "determinex_pb_*_v*" / "*" / "*.eval.json")):
        tool = Path(ej).parent.name
        try:
            mtime = Path(ej).stat().st_mtime
        except Exception:
            continue
        existing = tools_latest.get(tool)
        if existing is None or mtime > existing[0]:
            tools_latest[tool] = (mtime, ej)

    tools_scored = {}
    for tool, (_, ej) in tools_latest.items():
        try:
            j = json.loads(Path(ej).read_text(encoding="utf-8"))
        except Exception:
            continue
        r = j.get("test_results") or []
        if not r:
            continue
        passed = sum(1 for x in r if x.get("status") == "passed")
        tools_scored[tool] = (passed, len(r), 100.0 * passed / len(r))

    if not tools_scored:
        print("No scored evals found")
        return

    ranked = sorted(tools_scored.items(), key=lambda x: -x[1][2])
    print(f"=== {len(tools_scored)} tools with eval.json ===")
    print()
    print("Bucket distribution:")
    buckets = Counter()
    for _, (p, t, pct) in ranked:
        if pct >= 95:
            buckets["95-100%"] += 1
        elif pct >= 70:
            buckets["70-94%"] += 1
        elif pct >= 40:
            buckets["40-69%"] += 1
        elif pct >= 10:
            buckets["10-39%"] += 1
        else:
            buckets["0-9%"] += 1
    for b in ("95-100%", "70-94%", "40-69%", "10-39%", "0-9%"):
        print(f"  {b}: {buckets[b]}")

    total_pass = sum(p for p, _, _ in tools_scored.values())
    total_tests = sum(t for _, t, _ in tools_scored.values())
    avg_score = sum(pct for _, _, pct in tools_scored.values()) / len(tools_scored)
    print()
    print(
        f"Aggregate: {total_pass}/{total_tests} = {100 * total_pass / total_tests:.2f}% (weighted)"
    )
    print(f"Average per-tool: {avg_score:.2f}%")
    print()

    print("=== TOP 15 ===")
    for tool, (p, t, pct) in ranked[:15]:
        print(f"  {pct:6.2f}%  {p:>5}/{t:<5}  {tool[:50]}")
    print()
    print("=== BOTTOM 15 ===")
    for tool, (p, t, pct) in ranked[-15:]:
        print(f"  {pct:6.2f}%  {p:>5}/{t:<5}  {tool[:50]}")


if __name__ == "__main__":
    main()
