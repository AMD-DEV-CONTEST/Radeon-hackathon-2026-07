#!/usr/bin/env python3
"""Compare paired PI0.5 campaign audits and apply the frozen promotion gate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from parcel_sorter.mobile_pi05_evaluation import compare_paired_pi05_runs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-success-rate", type=float, default=0.90)
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    result = compare_paired_pi05_runs(
        baseline.get("runs", ()),
        candidate.get("runs", ()),
        target_success_rate=args.target_success_rate,
    )
    artifact = _checkpoint_artifact(args.candidate_checkpoint)
    artifact_sha256 = _sha256(artifact)
    payload = {
        "schema_version": 1,
        "protocol": "paired-pi05-promotion-v1",
        "baseline_audit": str(args.baseline.resolve()),
        "baseline_sha256": _sha256(args.baseline),
        "candidate_audit": str(args.candidate.resolve()),
        "candidate_sha256": _sha256(args.candidate),
        "promoted": result["promotion_gate_passed"],
        "pure_vla_promoted": result["pure_vla_promotion_gate_passed"],
        "pairing": {
            "candidate_checkpoint": str(args.candidate_checkpoint.resolve()),
            "candidate_artifact": str(artifact.resolve()),
            "candidate_checkpoint_sha256": artifact_sha256,
        },
        **result,
        "claim_boundary": (
            "paired frozen simulation inference; McNemar tests task success only and does "
            "not establish unseen-geometry or sim-to-real generalization. Hybrid "
            "expert-reference residual results are never labeled pure VLA."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["promotion_gate_passed"] else 2


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _checkpoint_artifact(checkpoint: Path) -> Path:
    if checkpoint.is_file():
        return checkpoint
    for name in ("adapter_model.safetensors", "model.safetensors"):
        artifact = checkpoint / name
        if artifact.is_file():
            return artifact
    raise FileNotFoundError(
        "candidate checkpoint has neither adapter_model.safetensors nor model.safetensors"
    )


if __name__ == "__main__":
    raise SystemExit(main())
