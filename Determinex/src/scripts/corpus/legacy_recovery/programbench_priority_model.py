#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.legacy_recovery.legacy_scan import scan_legacy_roots


def build_priority_model(scan_report: dict[str, Any]) -> dict[str, Any]:
    candidates = scan_report.get("replay_candidates_sample") or []
    replay_by_tool = scan_report.get("replay_by_tool_top") or {}
    by_tool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        by_tool[row.get("tool") or "unknown"].append(row)

    scored = []
    for tool, replayable in replay_by_tool.items():
        rows = by_tool.get(tool, [])
        classes = Counter(label for row in rows for label in row.get("failure_classes", []))
        risk = classes.get("wrapper_churn_risk", 0) + classes.get("argv0_alias_regression", 0)
        clarity = classes.get("date_time_nondeterminism", 0) + classes.get(
            "stdout_stderr_mismatch", 0
        )
        score = int(replayable) * 3 + clarity * 2 - risk
        scored.append(
            {
                "tool": tool,
                "priority_score": score,
                "replayable_rows": int(replayable),
                "repair_hint_clarity": clarity,
                "regression_risk": risk,
                "top_failure_classes": dict(classes.most_common(5)),
                "training_eligible": False,
            }
        )
    scored.sort(key=lambda row: row["priority_score"], reverse=True)
    return {
        "schema_version": "determinex-programbench-priority-model-v1",
        "rows_scanned": scan_report.get("rows_scanned", 0),
        "tools": scored[:100],
        "policy": "Priority ranking may use weak legacy evidence; repair training may not.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rank ProgramBench replay/repair priority from legacy evidence."
    )
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument(
        "--output", type=Path, default=Path("assurance/evidence/programbench_priority_model.json")
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    model = build_priority_model(scan_legacy_roots(args.roots, max_rows=args.max_rows))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(model, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not args.quiet:
        print(json.dumps(model, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
