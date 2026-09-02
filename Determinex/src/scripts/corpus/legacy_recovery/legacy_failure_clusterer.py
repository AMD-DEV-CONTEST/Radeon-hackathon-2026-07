#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.legacy_recovery.legacy_scan import scan_legacy_roots


def build_failure_taxonomy(scan_report: dict[str, Any]) -> dict[str, Any]:
    counts = Counter(scan_report.get("by_failure_class") or {})
    return {
        "schema_version": "determinex-legacy-failure-taxonomy-v1",
        "rows_scanned": scan_report.get("rows_scanned", 0),
        "clusters": [
            {"failure_class": label, "count": count, "recommended_use": _recommended_use(label)}
            for label, count in counts.most_common()
        ],
        "training_eligible_rows": 0,
        "policy": "Use clusters to create fresh synthetic/replay tasks; do not train directly from legacy rows.",
    }


def _recommended_use(label: str) -> str:
    if label == "date_time_nondeterminism":
        return "build fixed-date/timezone mutation suite"
    if label == "argv0_alias_regression":
        return "build argv0 preservation gate and wrapper anti-churn tests"
    if label == "stdout_stderr_mismatch":
        return "build narrow stdout/stderr normalization tasks"
    if label == "wrapper_churn_risk":
        return "route to native/source validation before wrapper edits"
    if label == "parse_error":
        return "improve JSONL parser and keep row quarantined"
    return "mine examples for replay candidates"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build legacy failure taxonomy from quarantined corpus."
    )
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument(
        "--output", type=Path, default=Path("assurance/evidence/legacy_failure_taxonomy.json")
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    taxonomy = build_failure_taxonomy(scan_legacy_roots(args.roots, max_rows=args.max_rows))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(taxonomy, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not args.quiet:
        print(json.dumps(taxonomy, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
