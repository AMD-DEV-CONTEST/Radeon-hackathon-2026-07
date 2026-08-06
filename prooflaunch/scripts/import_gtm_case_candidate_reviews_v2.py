#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_case_candidate_review_workbench_v2 import (
    compile_review_receipt,
    verify_review_receipt,
)


ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate source-bound candidate reviews and seal a zero-quota intake receipt."
    )
    parser.add_argument("intake", type=Path)
    parser.add_argument(
        "--binding-packets",
        type=Path,
        default=ROOT / "evidence/v10/gtm-case-candidate-binding-packets-v2.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    intake_path = args.intake if args.intake.is_absolute() else ROOT / args.intake
    packet_path = args.binding_packets if args.binding_packets.is_absolute() else ROOT / args.binding_packets
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    receipt = compile_review_receipt(_read(intake_path), _read(packet_path))
    verify_review_receipt(receipt)
    atomic_write_text(output_path, json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output_path),
        "review_count": receipt["review_count"],
        "admission_submission_count": receipt["admission_submission_count"],
        "candidate_quota_credit": receipt["candidate_quota_credit"],
        "content_sha256": receipt["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
