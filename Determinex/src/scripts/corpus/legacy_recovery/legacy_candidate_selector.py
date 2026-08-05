#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.legacy_recovery.legacy_promotion_budget import PromotionBudget


def select_candidates(
    scan_artifact: dict[str, Any], *, minimum_tools: int = 5, minimum_classes: int = 3
) -> dict[str, Any]:
    primary: list[dict[str, Any]] = []
    extras: list[dict[str, Any]] = []
    for tool_row in scan_artifact.get("top_replay_candidates") or []:
        tool = str(tool_row.get("tool") or "")
        labels = _ordered_labels(tool_row.get("top_failure_classes") or {"uncategorized": 1})
        for i, label in enumerate(labels):
            row = {
                "tool": tool,
                "candidate_rows": int(tool_row.get("candidate_rows") or 0),
                "failure_classes": [str(label)],
                "duplicate_cluster_id": _cluster_id(tool, str(label)),
                "expected_verifier": "programbench eval",
                "language_guess": _language_guess(tool),
                "legacy_row_hash": str(
                    tool_row.get("legacy_row_hash") or _cluster_legacy_hash(tool, str(label))
                ),
                "priority_score": int(tool_row.get("candidate_rows") or 0),
                "training_eligible": False,
                "requires_fresh_verifier": True,
            }
            if i == 0:
                primary.append(row)
            else:
                extras.append(row)
    selected = PromotionBudget(max_attempts_per_scan=10, max_per_tool=3, max_per_cluster=1).select(
        primary + extras
    )
    selected["diversity"] = {
        "distinct_tools": len({row.get("tool") for row in selected["selected"]}),
        "distinct_failure_classes": len(
            {(row.get("failure_classes") or ["uncategorized"])[0] for row in selected["selected"]}
        ),
        "minimum_tools": minimum_tools,
        "minimum_failure_classes": minimum_classes,
    }
    selected["policy"] = (
        "Selected candidates are promotion attempts only after fresh verifier replay; selection itself creates no training rows."
    )
    return selected


def _ordered_labels(classes: dict[str, Any]) -> list[str]:
    labels = [str(label) for label in classes.keys()]
    labels.sort(key=lambda label: (label == "uncategorized", label))
    return labels or ["uncategorized"]


def _cluster_id(tool: str, label: str) -> str:
    return hashlib.sha256(f"{tool}::{label}".encode("utf-8", "replace")).hexdigest()[:24]


def _cluster_legacy_hash(tool: str, label: str) -> str:
    return "legacy_cluster:" + _cluster_id(tool, label)


def _language_guess(tool: str) -> str:
    lowered = tool.lower()
    if any(
        token in lowered
        for token in ("rust", "bat", "fd", "ripgrep", "mdbook", "typst", "pastel", "dust")
    ):
        return "rust"
    if any(token in lowered for token in ("go", "fzf", "peco", "gdu", "atlas")):
        return "go"
    if any(token in lowered for token in ("sqlite", "duckdb", "samtools")):
        return "c_cpp"
    if any(token in lowered for token in ("fx", "json")):
        return "javascript"
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Select diverse legacy replay promotion candidates under budget."
    )
    parser.add_argument("scan_artifact", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("assurance/evidence/legacy_replay_promotion_batch_001.json"),
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    selected = select_candidates(json.loads(args.scan_artifact.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(selected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not args.quiet:
        print(json.dumps(selected, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
