#!/usr/bin/env python3
"""Run the frozen 400+400 LIBERO action-step development comparison."""

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
    screen: dict[str, Any],
) -> int:
    if config.get("protocol_id") != "pi05-libero-action-steps-full-development-v1":
        raise ValueError("unexpected full-development protocol")
    if config.get("phase") != "development" or int(config.get("units_per_arm", 0)) != 400:
        raise ValueError("full development must use exactly 400 units per arm")
    if config.get("benchmark_manifest_protocol") != manifest.get("protocol_id"):
        raise ValueError("development config and manifest protocols differ")
    if config.get("benchmark_manifest_canonical_sha256") != manifest.get("manifest_sha256"):
        raise ValueError("development config and canonical manifest hashes differ")
    if config.get("screen_protocol") != screen.get("protocol_id"):
        raise ValueError("development config and screen protocols differ")
    selection = screen.get("selection") or {}
    if selection.get("status") != "candidate_selected":
        raise ValueError("screen did not select a non-control candidate")
    if not bool(selection.get("promotion_requires_full_development")):
        raise ValueError("screen does not require full development")
    candidate_steps = int(selection.get("selected_action_steps", 0))
    if candidate_steps == 10 or not 1 <= candidate_steps <= int(
        manifest["benchmark"]["action_chunk_size"]
    ):
        raise ValueError("screen selected an invalid candidate action-step count")
    if int(selection.get("selected_successes", -1)) <= int(
        selection.get("control_successes", -1)
    ):
        raise ValueError("screen candidate did not strictly exceed control")
    return candidate_steps


def load_eligible_arm(output: Path, expected_units: int) -> tuple[dict[str, Any], dict]:
    run_summary = load_json(output / "run-summary.json")
    eval_info = load_json(output / "eval" / "eval_info.json")
    outcomes = flatten_successes(eval_info)
    telemetry = run_summary.get("telemetry") or {}
    if int(run_summary.get("returncode", -1)) != 0:
        raise RuntimeError(f"development arm failed: {output}")
    if len(outcomes) != expected_units:
        raise RuntimeError(
            f"development arm has {len(outcomes)} units, expected {expected_units}: {output}"
        )
    if int(telemetry.get("sampling_error_count", -1)) != 0:
        raise RuntimeError(f"development arm telemetry is ineligible: {output}")
    return run_summary, outcomes


def select_for_confirmation(
    control: dict[tuple[str, int, int], bool],
    candidate: dict[tuple[str, int, int], bool],
    candidate_steps: int,
) -> dict[str, Any]:
    paired = paired_comparison(control, candidate)
    control_successes = sum(control.values())
    candidate_successes = sum(candidate.values())
    promoted = candidate_successes > control_successes
    return {
        "status": "candidate_frozen" if promoted else "control_retained",
        "selected_action_steps": candidate_steps if promoted else 10,
        "control_successes": control_successes,
        "candidate_successes": candidate_successes,
        "candidate_strictly_better": promoted,
        "paired": paired,
        "confirmation_may_start": promoted,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--screen-summary", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "configs" / "pi05_libero_action_steps_development_v1.json",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--runner",
        type=Path,
        default=root / "scripts" / "run_pi05_libero_eval_rocm.py",
    )
    parser.add_argument("--seed", type=int, default=20260729)
    args = parser.parse_args()

    config = load_json(args.config)
    manifest = load_json(args.manifest)
    screen = load_json(args.screen_summary)
    candidate_steps = validate_inputs(config, manifest, screen)
    if args.output_root.exists() and any(args.output_root.iterdir()):
        raise FileExistsError(f"development output root is not empty: {args.output_root}")
    args.output_root.mkdir(parents=True, exist_ok=True)
    contract = {
        "schema_version": 1,
        "protocol_id": config["protocol_id"],
        "config_sha256": sha256_file(args.config),
        "manifest_sha256": sha256_file(args.manifest),
        "screen_summary_sha256": sha256_file(args.screen_summary),
        "runner_sha256": sha256_file(args.runner),
        "checkpoint": str(args.checkpoint),
        "seed": args.seed,
        "control_action_steps": 10,
        "candidate_action_steps": candidate_steps,
        "units_per_arm": 400,
        "run_order": config["run_order"],
        "claim_boundary": config["claim_boundary"],
    }
    (args.output_root / "DEVELOPMENT_CONTRACT.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    arms = (("steps10_control", 10), (f"steps{candidate_steps}_candidate", candidate_steps))
    for arm_id, action_steps in arms:
        command = [
            sys.executable,
            str(args.runner),
            "--checkpoint",
            str(args.checkpoint),
            "--manifest",
            str(args.manifest),
            "--output",
            str(args.output_root / arm_id),
            "--phase",
            "development",
            "--compile",
            "false",
            "--action-steps",
            str(action_steps),
            "--seed",
            str(args.seed),
        ]
        completed = subprocess.run(command)
        if completed.returncode != 0:
            raise RuntimeError(f"development arm {arm_id} failed with {completed.returncode}")

    control_run, control = load_eligible_arm(args.output_root / "steps10_control", 400)
    candidate_run, candidate = load_eligible_arm(
        args.output_root / f"steps{candidate_steps}_candidate", 400
    )
    summary = {
        "schema_version": 1,
        "protocol_id": config["protocol_id"],
        "control": summarize_successes(control),
        "candidate": summarize_successes(candidate),
        "selection": select_for_confirmation(control, candidate, candidate_steps),
        "telemetry": {
            "control": control_run.get("telemetry"),
            "candidate": candidate_run.get("telemetry"),
        },
        "claim_boundary": config["claim_boundary"],
    }
    rendered = json.dumps(summary, indent=2, sort_keys=True)
    (args.output_root / "DEVELOPMENT_SUMMARY.json").write_text(
        rendered + "\n", encoding="utf-8"
    )
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
