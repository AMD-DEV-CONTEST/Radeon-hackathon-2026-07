#!/usr/bin/env python3
"""pb_failure_cluster.py — cluster non-locked ProgramBench tools by failure class.

Reads the board (`logs/programbench_lock_board.json`) for the authoritative
locked/score state (never the stale markdown queue), then joins the latest
`gate_result.json` per slug to attach the dominant regression class + hint.
Emits cluster -> tool-list mapping so a Hetzner shard can be assembled to apply
one shared fix to a whole cluster instead of one tool per shard.

Read-only.

Usage:
    python scripts/pb_failure_cluster.py
    python scripts/pb_failure_cluster.py --json
    python scripts/pb_failure_cluster.py --near-locks   # board score>=95, not locked
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOARD = ROOT / "logs" / "programbench_lock_board.json"
STAGING_GLOB = str(ROOT / ".determinex_staging" / "*" / "gate_result.json")


def load_board() -> list[dict]:
    return json.loads(BOARD.read_text(encoding="utf-8"))


def latest_gate_by_slug() -> dict[str, dict]:
    by_slug: dict[str, tuple[float, dict]] = {}
    for f in glob.glob(STAGING_GLOB):
        try:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue
        slug = d.get("slug")
        if not slug:
            continue
        mt = os.path.getmtime(f)
        if slug not in by_slug or mt > by_slug[slug][0]:
            by_slug[slug] = (mt, d)
    return {k: v[1] for k, v in by_slug.items()}


def dominant_class(gate: dict) -> tuple[str, str]:
    dl = gate.get("delta", {}) or {}
    rcc = dl.get("regression_class_counts") or {}
    if not rcc:
        return ("none", "")
    cls = max(rcc, key=lambda k: rcc[k])
    rc = dl.get("regression_classes") or {}
    hints = Counter((i.get("regression_hint") or "")[:50] for i in rc.values())
    top_hint = hints.most_common(1)[0][0] if hints else ""
    # Reclassify 127-as-behavioral into build-fix lane.
    if "127" in top_hint:
        cls = "missing_executable(rc127)"
    return (cls, top_hint)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--near-locks", action="store_true", help="only board score>=95 not locked")
    args = ap.parse_args()

    board = load_board()
    gates = latest_gate_by_slug()

    def gate_for(slug: str) -> dict | None:
        if slug in gates:
            return gates[slug]
        for k, v in gates.items():
            if k.split(".")[0] == slug or k.startswith(slug + "."):
                return v
        return None

    clusters: dict[str, list[dict]] = defaultdict(list)
    near: list[dict] = []

    for b in board:
        if b.get("locked_archive"):
            continue
        slug = b.get("slug") or b.get("base_slug") or ""
        score = b.get("score") or 0
        passed = b.get("passed")
        runnable = b.get("runnable_total")
        g = gate_for(b.get("base_slug") or slug)
        decision = g.get("decision") if g else None
        cls, hint = dominant_class(g) if g else ("no-gate", "")
        row = {
            "slug": slug,
            "score": round(score, 2),
            "passed": passed,
            "runnable": runnable,
            "gate_decision": decision,
            "cluster": cls,
            "top_hint": hint,
        }
        if score >= 95:
            near.append(row)
        clusters[cls].append(row)

    if args.near_locks:
        near.sort(key=lambda r: -r["score"])
        if args.json:
            print(json.dumps(near, indent=2))
        else:
            print(f"=== board near-locks (score>=95, not locked): {len(near)} ===")
            for r in near:
                print(
                    f"  {r['score']:6.2f}  {r['slug']:48s} gate={r['gate_decision']}  {r['cluster']}"
                )
        return 0

    if args.json:
        print(json.dumps({k: v for k, v in clusters.items()}, indent=2))
        return 0

    print("Non-locked tools clustered by dominant regression class (board-authoritative)\n")
    for cls in sorted(clusters, key=lambda k: -len(clusters[k])):
        rows = sorted(clusters[cls], key=lambda r: -(r["score"] or 0))
        print(f"=== {cls} ({len(rows)}) ===")
        for r in rows:
            acc = " [gate:accept — re-eval+archive]" if r["gate_decision"] == "accept" else ""
            print(f"  {r['score']:6.2f}  {r['slug']:48s}{acc}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
