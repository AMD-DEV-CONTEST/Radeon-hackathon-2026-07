#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.quality_contract import QualityTier, contract_for


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed ProofLaunch competition-2X acceptance gate"
    )
    parser.add_argument("evidence", type=Path, help="JSON file with measured evidence")
    parser.add_argument(
        "--output",
        type=Path,
        help="optional path for the complete acceptance report",
    )
    arguments = parser.parse_args()
    payload = json.loads(arguments.evidence.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("evidence JSON must contain an object")
    if payload.get("schema") != "ProofLaunchCompetition2XCompiledEvidenceV2":
        raise SystemExit(
            "raw aggregate evidence is not accepted; run "
            "scripts/compile_competition_2x_evidence.py first"
        )
    report = contract_for(QualityTier.COMPETITION_2X).evaluate(payload)
    serialized = json.dumps(
        report.to_dict(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
