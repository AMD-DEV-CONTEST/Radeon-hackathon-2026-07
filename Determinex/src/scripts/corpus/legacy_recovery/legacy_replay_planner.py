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


def build_replay_plan(scan_report: dict[str, Any]) -> dict[str, Any]:
    candidates = scan_report.get("replay_candidates_sample") or []
    replay_by_tool = scan_report.get("replay_by_tool_top") or {}
    by_tool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        by_tool[item.get("tool") or "unknown"].append(item)
    ranked = []
    for tool, count in replay_by_tool.items():
        rows = by_tool.get(tool, [])
        failures = Counter(label for row in rows for label in row.get("failure_classes", []))
        ranked.append(
            {
                "tool": tool,
                "candidate_rows": int(count),
                "top_failure_classes": dict(failures.most_common(5)),
                "replay_reason": "has legacy eval/gate/test metadata sufficient for verifier reconstruction",
                "training_eligible": False,
            }
        )
    ranked.sort(key=lambda row: row["candidate_rows"], reverse=True)
    return {
        "schema_version": "determinex-legacy-replay-plan-v1",
        "rows_scanned": scan_report.get("rows_scanned", 0),
        "replay_candidate_count": scan_report.get("replay_candidate_count", 0),
        "tools": ranked[:100],
        "policy": "Replay candidates require fresh verifier execution before any new recovered row can be training eligible.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build replay candidate list from legacy scan.")
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument(
        "--output", type=Path, default=Path("assurance/evidence/legacy_replay_candidate_list.json")
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    plan = build_replay_plan(scan_legacy_roots(args.roots, max_rows=args.max_rows))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not args.quiet:
        print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
