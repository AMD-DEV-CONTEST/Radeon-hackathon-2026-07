#!/usr/bin/env python3
"""Pair two frozen mobile audits and apply the registered promotion gate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from parcel_sorter.mobile_self_improvement_cycle import (
    promotion_gate,
    validate_paired_campaigns,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unique_checkpoints(audit: dict) -> list[str]:
    return sorted(
        {
            str((run.get("policy") or {}).get("checkpoint"))
            for run in audit.get("runs", ())
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-audit", type=Path, required=True)
    parser.add_argument("--candidate-audit", type=Path, required=True)
    parser.add_argument("--baseline-checkpoint-sha256", required=True)
    parser.add_argument("--candidate-checkpoint-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    baseline = json.loads(args.baseline_audit.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate_audit.read_text(encoding="utf-8"))
    result = promotion_gate(baseline, candidate)
    pairing = validate_paired_campaigns(baseline, candidate)
    payload = {
        **result,
        "pairing": {
            **pairing,
            "baseline_audit": str(args.baseline_audit.resolve()),
            "baseline_audit_sha256": sha256_file(args.baseline_audit),
            "candidate_audit": str(args.candidate_audit.resolve()),
            "candidate_audit_sha256": sha256_file(args.candidate_audit),
            "baseline_checkpoint_paths": unique_checkpoints(baseline),
            "candidate_checkpoint_paths": unique_checkpoints(candidate),
            "baseline_checkpoint_sha256": args.baseline_checkpoint_sha256,
            "candidate_checkpoint_sha256": args.candidate_checkpoint_sha256,
            "baseline_reused_from_prior_frozen_campaign": True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
