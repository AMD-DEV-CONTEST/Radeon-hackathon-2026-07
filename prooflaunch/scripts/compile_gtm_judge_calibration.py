#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from prooflaunch_remix.gtm_judge_calibration import compile_judge_calibration_bundle


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze a real, blinded ProofLaunch judge-calibration queue."
    )
    parser.add_argument("--cases", required=True, help="JSON array of 100–500 distinct cases")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    seed = os.environ.get("PROOFLAUNCH_JUDGE_CALIBRATION_SEED", "")
    if len(seed) < 16:
        raise SystemExit(
            "PROOFLAUNCH_JUDGE_CALIBRATION_SEED must be configured outside command history"
        )
    source = Path(args.cases).expanduser().resolve(strict=True)
    if source.is_symlink() or not source.is_file():
        raise SystemExit("calibration case source must be a real file")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("calibration case source must contain a JSON array")
    receipt = compile_judge_calibration_bundle(
        payload,
        Path(args.output_dir),
        assignment_seed=seed,
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
