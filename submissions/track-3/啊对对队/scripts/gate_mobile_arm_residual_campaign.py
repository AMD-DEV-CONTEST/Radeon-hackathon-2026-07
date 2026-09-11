#!/usr/bin/env python3
"""Apply the paired development gate for mobile VLA arm residual execution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.mobile_arm_residual_ablation import (
    evaluate_arm_residual_development_gate,
    evaluate_arm_residual_holdout_gate,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--phase", choices=("development", "holdout"), default="development"
    )
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    result = (
        evaluate_arm_residual_holdout_gate(baseline, candidate)
        if args.phase == "holdout"
        else evaluate_arm_residual_development_gate(baseline, candidate)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
