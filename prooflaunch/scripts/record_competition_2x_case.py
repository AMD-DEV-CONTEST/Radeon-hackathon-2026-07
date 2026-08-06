#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.competition_benchmark import (
    BaselineCaseJournal,
    CompetitionCaseJournal,
)


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Append or inspect durable competition-2X case journals"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    proof = subparsers.add_parser("prooflaunch")
    _add_common(proof)
    proof.add_argument("--case-id", required=True)
    proof.add_argument("--gate-evidence", required=True, type=Path)
    proof.add_argument("--output", type=Path)
    proof.add_argument("--video-output", type=Path)

    baseline = subparsers.add_parser("baseline")
    _add_common(baseline)
    baseline.add_argument("--case-id", required=True)
    baseline.add_argument("--completed", action="store_true")
    baseline.add_argument("--crashed", action="store_true")
    baseline.add_argument("--output", type=Path)

    pending = subparsers.add_parser("pending")
    _add_common(pending)
    pending.add_argument(
        "--kind",
        required=True,
        choices=("prooflaunch", "baseline"),
    )
    pending.add_argument("--limit", type=int, default=20)

    arguments = parser.parse_args()
    if arguments.command == "prooflaunch":
        journal = CompetitionCaseJournal(arguments.manifest, arguments.results)
        row = journal.append(
            case_id=arguments.case_id,
            gate_evidence_path=arguments.gate_evidence,
            output_path=arguments.output,
            video_output_path=arguments.video_output,
        )
        print(json.dumps(row, indent=2, sort_keys=True))
        return 0
    if arguments.command == "baseline":
        journal = BaselineCaseJournal(arguments.manifest, arguments.results)
        row = journal.append(
            case_id=arguments.case_id,
            completed=arguments.completed,
            crashed=arguments.crashed,
            output_path=arguments.output,
        )
        print(json.dumps(row, indent=2, sort_keys=True))
        return 0

    journal = (
        CompetitionCaseJournal(arguments.manifest, arguments.results)
        if arguments.kind == "prooflaunch"
        else BaselineCaseJournal(arguments.manifest, arguments.results)
    )
    pending_cases = journal.pending_cases
    print(
        json.dumps(
            {
                "kind": arguments.kind,
                "pendingCount": len(pending_cases),
                "nextCases": [
                    {
                        "case_id": case.case_id,
                        "product_id": case.product_id,
                        "aspect_ratio": case.aspect_ratio,
                        "seed": case.seed,
                        "video_required": case.video_required,
                    }
                    for case in pending_cases[: max(0, arguments.limit)]
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
