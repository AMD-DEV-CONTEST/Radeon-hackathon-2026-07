#!/usr/bin/env python3
"""Run the frozen LIBERO development action-step screen on Radeon."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_config(config: dict[str, Any], manifest: dict[str, Any]) -> None:
    if config.get("protocol_id") != "pi05-libero-development-action-steps-screen-v1":
        raise ValueError("unexpected action-step screen protocol")
    if config.get("phase") != "efficiency" or int(config.get("units_per_arm", 0)) != 40:
        raise ValueError("screen must use exactly 40 LIBERO efficiency units per arm")
    if config.get("benchmark_manifest_protocol") != manifest.get("protocol_id"):
        raise ValueError("screen and benchmark manifest protocols differ")
    if config.get("benchmark_manifest_canonical_sha256") != manifest.get("manifest_sha256"):
        raise ValueError("screen and benchmark manifest hashes differ")
    arms = config.get("run_order")
    if not isinstance(arms, list) or len(arms) < 2:
        raise ValueError("screen requires a control and at least one candidate")
    ids = [str(arm.get("arm_id")) for arm in arms]
    steps = [int(arm.get("action_steps", 0)) for arm in arms]
    if len(set(ids)) != len(ids) or len(set(steps)) != len(steps):
        raise ValueError("screen arm ids and action steps must be unique")
    if ids[0] != "steps10_control" or steps[0] != 10:
        raise ValueError("the first screen arm must be the 10-step control")
    chunk_size = int(manifest["benchmark"]["action_chunk_size"])
    if any(step < 1 or step > chunk_size for step in steps):
        raise ValueError("screen action steps violate the checkpoint chunk contract")


def summarize_arm(output: Path, arm: dict[str, Any], expected_units: int) -> dict[str, Any]:
    run_summary = load_json(output / "run-summary.json")
    eval_info = load_json(output / "eval" / "eval_info.json")
    outcomes = [
        bool(success)
        for task in eval_info.get("per_task", [])
        for success in (task.get("metrics", {}).get("successes") or [])
    ]
    telemetry = run_summary.get("telemetry") or {}
    timing = (eval_info.get("overall") or {}).get("policy_timing") or {}
    model_timing = timing.get("model_inference_calls") or {}
    eligible = (
        int(run_summary.get("returncode", -1)) == 0
        and len(outcomes) == expected_units
        and int(telemetry.get("sampling_error_count", -1)) == 0
    )
    successes = sum(outcomes)
    energy_wh = float(telemetry.get("energy_wh", 0.0))
    return {
        "arm_id": str(arm["arm_id"]),
        "action_steps": int(arm["action_steps"]),
        "eligible": eligible,
        "successes": successes,
        "units": len(outcomes),
        "success_percent": 100.0 * successes / len(outcomes) if outcomes else None,
        "model_inference_calls": int(model_timing.get("count", 0)),
        "warm_model_p95_ms": model_timing.get("warm_p95_ms"),
        "energy_wh": energy_wh,
        "energy_wh_per_episode": energy_wh / len(outcomes) if outcomes else None,
        "peak_allocated_gib": (
            (eval_info.get("overall") or {}).get("accelerator_memory", {}).get(
                "peak_allocated_gib"
            )
        ),
        "eval_info_sha256": sha256_file(output / "eval" / "eval_info.json"),
        "run_contract_sha256": sha256_file(output / "run-contract.json"),
        "run_summary_sha256": sha256_file(output / "run-summary.json"),
    }


def select_arm(results: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [result for result in results if result["eligible"]]
    if not eligible:
        return {"status": "failed", "reason": "no eligible arms", "selected_arm_id": None}
    control = next(
        (result for result in eligible if result["arm_id"] == "steps10_control"),
        None,
    )
    if control is None:
        return {"status": "failed", "reason": "control arm is ineligible", "selected_arm_id": None}
    best = max(eligible, key=lambda result: (result["successes"], result["action_steps"]))
    promoted = best["arm_id"] != control["arm_id"] and best["successes"] > control["successes"]
    return {
        "status": "candidate_selected" if promoted else "control_retained",
        "selected_arm_id": best["arm_id"] if promoted else control["arm_id"],
        "selected_action_steps": best["action_steps"] if promoted else control["action_steps"],
        "control_successes": control["successes"],
        "selected_successes": best["successes"] if promoted else control["successes"],
        "promotion_requires_full_development": promoted,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "configs" / "pi05_libero_action_steps_screen_v1.json",
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
    validate_config(config, manifest)
    if args.output_root.exists() and any(args.output_root.iterdir()):
        raise FileExistsError(f"screen output root is not empty: {args.output_root}")
    args.output_root.mkdir(parents=True, exist_ok=True)
    contract = {
        "schema_version": 1,
        "protocol_id": config["protocol_id"],
        "config_sha256": sha256_file(args.config),
        "manifest_sha256": sha256_file(args.manifest),
        "runner_sha256": sha256_file(args.runner),
        "checkpoint": str(args.checkpoint),
        "seed": args.seed,
        "run_order": config["run_order"],
        "selection_rule": config["selection_rule"],
        "claim_boundary": config["claim_boundary"],
    }
    (args.output_root / "SCREEN_CONTRACT.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    results = []
    for arm in config["run_order"]:
        output = args.output_root / str(arm["arm_id"])
        command = [
            sys.executable,
            str(args.runner),
            "--checkpoint",
            str(args.checkpoint),
            "--manifest",
            str(args.manifest),
            "--output",
            str(output),
            "--phase",
            "efficiency",
            "--compile",
            "false",
            "--action-steps",
            str(int(arm["action_steps"])),
            "--seed",
            str(args.seed),
        ]
        completed = subprocess.run(command)
        if completed.returncode != 0:
            raise RuntimeError(f"screen arm {arm['arm_id']} failed with {completed.returncode}")
        results.append(summarize_arm(output, arm, int(config["units_per_arm"])))

    summary = {
        "schema_version": 1,
        "protocol_id": config["protocol_id"],
        "config_sha256": sha256_file(args.config),
        "arms": results,
        "selection": select_arm(results),
        "claim_boundary": config["claim_boundary"],
    }
    rendered = json.dumps(summary, indent=2, sort_keys=True)
    (args.output_root / "SCREEN_SUMMARY.json").write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
