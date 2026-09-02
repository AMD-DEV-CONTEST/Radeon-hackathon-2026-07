#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.legacy_recovery.legacy_scan import scan_legacy_roots


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write a quarantine report for local legacy corpus roots."
    )
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument(
        "--output", type=Path, default=Path("assurance/evidence/legacy_quarantine_report.json")
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    report = scan_legacy_roots(args.roots, max_rows=args.max_rows)
    report["record_status"] = "quarantined"
    report["training_eligible"] = False
    report["promotion_rule"] = (
        "legacy rows remain quarantined; fresh verifier replay writes new rows"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not args.quiet:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
