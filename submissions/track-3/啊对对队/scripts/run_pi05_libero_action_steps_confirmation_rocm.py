#!/usr/bin/env python3
"""Run one-shot confirmation for a development-frozen action-step candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from summarize_pi05_libero_benchmark import (
    flatten_successes,
    paired_comparison,
    summarize_successes,
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_inputs(
    config: dict[str, Any],
    manifest: dict[str, Any],
    development: dict[str, Any],
) -> int:
    if config.get("protocol_id") != "pi05-libero-action-steps-confirmation-v1":
        raise ValueError("unexpected action-step confirmation protocol")
    if config.get("phase") != "confirmation" or int(config.get("units", 0)) != 400:
        raise ValueError("confirmation must contain exactly 400 units")
    if config.get("benchmark_manifest_protocol") != manifest.get("protocol_id"):
        raise ValueError("confirmation config and benchmark protocols differ")
    if config.get("benchmark_manifest_canonical_sha256") != manifest.get("manifest_sha256"):
        raise ValueError("confirmation config and canonical manifest hashes differ")
    if config.get("development_protocol") != development.get("protocol_id"):
        raise ValueError("confirmation config and development protocols differ")
    selection = development.get("selection") or {}
    if selection.get("status") != "candidate_frozen":
        raise ValueError("development did not freeze a non-control candidate")
    if not bool(selection.get("candidate_strictly_better")) or not bool(
        selection.get("confirmation_may_start")
    ):
        raise ValueError("development did not authorize confirmation")
    candidate_steps = int(selection.get("selected_action_steps", 0))
    if candidate_steps == 10 or not 1 <= candidate_steps <= int(
        manifest["benchmark"]["action_chunk_size"]
    ):
        raise ValueError("development selected an invalid action-step count")
    return candidate_steps


def validate_baseline(config: dict[str, Any], baseline_root: Path) -> dict:
    expected = config["baseline"]
    files = {
        "eval_info": baseline_root / "eval" / "eval_info.json",
        "run_summary": baseline_root / "run-summary.json",
        "run_contract": baseline_root / "run-contract.json",
    }
    for name, path in files.items():
        actual = sha256_file(path)
        if actual != expected[f"{name}_sha256"]:
            raise ValueError(f"immutable baseline {name} hash mismatch")
    outcomes = flatten_successes(load_json(files["eval_info"]))
    if len(outcomes) != 400 or sum(outcomes.values()) != int(expected["successes"]):
        raise ValueError("immutable baseline outcome count mismatch")
    return outcomes


def build_claims(baseline: dict, candidate: dict) -> dict[str, Any]:
    paired = paired_comparison(baseline, candidate)
    return {
        "candidate_strictly_higher_than_local_pi05": sum(candidate.values())
        > sum(baseline.values()),
        "paired_local_superiority_at_alpha_0_05": paired["superiority_at_alpha_0_05"],
        "pi06_superiority_claim_permitted": False,
        "paired": paired,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--development-summary", type=Path, required=True)
    parser.add_argument("--baseline-output", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "configs" / "pi05_libero_action_steps_confirmation_v1.json",
    )
    parser.add_argument(
        "--runner",
        type=Path,
        default=root / "scripts" / "run_pi05_libero_eval_rocm.py",
    )
    parser.add_argument("--seed", type=int, default=20260729)
    args = parser.parse_args()

    config = load_json(args.config)
    manifest = load_json(args.manifest)
    development = load_json(args.development_summary)
    candidate_steps = validate_inputs(config, manifest, development)
    baseline = validate_baseline(config, args.baseline_output)
    if args.output_root.exists() and any(args.output_root.iterdir()):
        raise FileExistsError(f"confirmation output root is not empty: {args.output_root}")
    args.output_root.mkdir(parents=True, exist_ok=True)
    candidate_output = args.output_root / f"steps{candidate_steps}_candidate"
    contract = {
        "schema_version": 1,
        "protocol_id": config["protocol_id"],
        "config_sha256": sha256_file(args.config),
        "manifest_sha256": sha256_file(args.manifest),
        "development_summary_sha256": sha256_file(args.development_summary),
        "baseline_eval_info_sha256": sha256_file(
            args.baseline_output / "eval" / "eval_info.json"
        ),
        "runner_sha256": sha256_file(args.runner),
        "checkpoint": str(args.checkpoint),
        "seed": args.seed,
        "selected_action_steps": candidate_steps,
        "units": 400,
        "confirmation_accessed": True,
        "claim_boundary": config["claim_boundary"],
    }
    (args.output_root / "CONFIRMATION_CONTRACT.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    command = [
        sys.executable,
        str(args.runner),
        "--checkpoint",
        str(args.checkpoint),
        "--manifest",
        str(args.manifest),
        "--output",
        str(candidate_output),
        "--phase",
        "confirmation",
        "--compile",
        "false",
        "--action-steps",
        str(candidate_steps),
        "--seed",
        str(args.seed),
    ]
    completed = subprocess.run(command)
    if completed.returncode != 0:
        raise RuntimeError(f"confirmation run failed with {completed.returncode}")
    run_summary = load_json(candidate_output / "run-summary.json")
    eval_info = load_json(candidate_output / "eval" / "eval_info.json")
    candidate = flatten_successes(eval_info)
    telemetry = run_summary.get("telemetry") or {}
    if int(run_summary.get("returncode", -1)) != 0 or len(candidate) != 400:
        raise RuntimeError("confirmation output is incomplete")
    if int(telemetry.get("sampling_error_count", -1)) != 0:
        raise RuntimeError("confirmation telemetry is ineligible")
    summary = {
        "schema_version": 1,
        "protocol_id": config["protocol_id"],
        "baseline": summarize_successes(baseline),
        "candidate": summarize_successes(candidate),
        "claims": build_claims(baseline, candidate),
        "telemetry": telemetry,
        "claim_boundary": config["claim_boundary"],
    }
    rendered = json.dumps(summary, indent=2, sort_keys=True)
    (args.output_root / "CONFIRMATION_SUMMARY.json").write_text(
        rendered + "\n", encoding="utf-8"
    )
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
