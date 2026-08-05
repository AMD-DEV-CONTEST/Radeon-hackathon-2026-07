#!/usr/bin/env python3
"""build_tiered_queues.py - split tools into LIGHT (local) + HEAVY (Hetzner)
queues based on predicted eval cost.

Cost score = test_count + fixture_penalty + history_penalty.
Bottom 35% by score → light queue (local). Top 65% → heavy queue (Hetzner).

Inputs:
  logs/mass_run_v2/inspection_report.json   - test counts + fixtures per tool
  logs/mass_run_v2/state_audit.tsv          - prior eval durations
  factory dirs - which tools have .eval.json already (skip those)

Outputs:
  C:/tmp/queue_light.txt   - cheap tools (local pulls from this)
  C:/tmp/queue_heavy.txt   - expensive tools (Hetzner pulls)

Hetzner drains the light queue if heavy empties.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
INSPECT = ROOT / "logs" / "mass_run_v2" / "inspection_report.json"
PB = Path("T:/determinex-programbench")

# Fixture types that inflate predicted cost (each found = +N to score)
FIXTURE_COST = {
    "tmux": 500,  # near-certain timeout
    "pty": 400,
    "network_server": 300,
    "multiprocess": 200,
    "fork": 200,
    "threading": 100,
    "popen_pipe": 50,
    "mkfifo": 30,
    "git_init": 20,
    "tempfile": 5,
    "subprocess_run": 1,
}

# Subtype-flag bonuses
HINT_COST = {
    "generic_family": 0,
    "structured_output (json output mode)": 200,
    "structured_output (csv output mode)": 200,
    "golden_file_heavy (need byte-exact reproduction)": 400,
}


def cost_for(report: dict) -> int:
    score = int(report.get("test_count_total", 0))  # base = test count
    for fix, n in (report.get("fixtures_total") or {}).items():
        score += FIXTURE_COST.get(fix, 0) * min(n, 5)  # cap per fixture
    score += HINT_COST.get(report.get("scaffold_hint", ""), 0)
    if "needs_specific_subtype" in (report.get("verdict") or ""):
        score += 200
    if "golden_file_ceiling" in (report.get("verdict") or ""):
        score += 300
    return score


def has_factory_eval(inst: str) -> bool:
    ej = PB / f"determinex_pb_factory_{inst}_v1" / inst / f"{inst}.eval.json"
    if not ej.is_file():
        return False
    try:
        j = json.loads(ej.read_text(encoding="utf-8"))
        return bool(j.get("test_results") or [])
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--include-done",
        action="store_true",
        help="also include tools that already have eval.json (re-eval)",
    )
    ap.add_argument(
        "--light-pct",
        type=int,
        default=35,
        help="bottom pct by cost goes to light queue (default 35)",
    )
    ap.add_argument("--out-light", default="C:/tmp/queue_light.txt")
    ap.add_argument("--out-heavy", default="C:/tmp/queue_heavy.txt")
    args = ap.parse_args()

    if not INSPECT.is_file():
        print(
            "ERROR: inspection_report.json not found; run programbench_inspect_tool.py --all first"
        )
        return 1
    reports: dict[str, Any] = json.loads(INSPECT.read_text(encoding="utf-8"))

    scored = []
    for inst, rep in reports.items():
        if not args.include_done and has_factory_eval(inst):
            continue
        scored.append((cost_for(rep), inst))
    scored.sort()  # cheapest first

    if not scored:
        print("nothing to queue (all tools have eval.json; pass --include-done to re-eval)")
        return 0

    n = len(scored)
    cutoff = max(1, n * args.light_pct // 100)
    light = [inst for _, inst in scored[:cutoff]]
    heavy = [inst for _, inst in scored[cutoff:]]

    Path(args.out_light).write_text("\n".join(light) + "\n", encoding="utf-8", newline="\n")
    Path(args.out_heavy).write_text("\n".join(heavy) + "\n", encoding="utf-8", newline="\n")

    print(f"queued {n} tools total")
    print(f"  light (local, cost<={scored[cutoff - 1][0]}): {len(light)} -> {args.out_light}")
    print(
        f"  heavy (Hetzner, cost>={scored[cutoff][0] if cutoff < n else scored[-1][0]}): {len(heavy)} -> {args.out_heavy}"
    )
    print()
    print("=== sample cheapest 5 (local) ===")
    for c, inst in scored[:5]:
        print(f"  cost={c:>5}  {inst}")
    print("=== sample priciest 5 (Hetzner) ===")
    for c, inst in scored[-5:]:
        print(f"  cost={c:>5}  {inst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
