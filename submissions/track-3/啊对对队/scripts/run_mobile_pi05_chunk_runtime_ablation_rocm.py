#!/usr/bin/env python3
"""Run the pre-registered matched PI0.5 action-chunk runtime ablation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
from typing import Any

from parcel_sorter.rocm_telemetry import RocmTelemetryRecorder


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _validate_route_screen(screen: dict[str, Any], checkpoint: Path) -> None:
    if screen.get("status") != "passed":
        raise ValueError("route screen has not passed")
    if Path(str(screen.get("checkpoint", ""))).resolve() != checkpoint.resolve():
        raise ValueError("route screen checkpoint does not match the requested checkpoint")
    metrics = screen.get("metrics") or {}
    if float(metrics.get("probe_accuracy", 0.0)) != 1.0:
        raise ValueError("route screen is not 100% correct")
    if int(metrics.get("fallback_count", 0)) != 0:
        raise ValueError("route screen contains expert fallback")


def _campaign_command(
    *,
    checkpoint: Path,
    episode_config: Path,
    output: Path,
    arm: dict[str, Any],
    policy_hz: int,
) -> list[str]:
    return [
        sys.executable,
        str(PROJECT_ROOT / "scripts/collect_mobile_suction_dataset_rocm.py"),
        "--config",
        str(episode_config),
        "--output",
        str(output),
        "--backend",
        "rocm",
        "--resume",
        "--audit-only",
        "--smolvla-checkpoint",
        str(checkpoint),
        "--policy-mode",
        "pi05_absolute",
        "--policy-hz",
        str(policy_hz),
        "--pi05-chunk-execution-protocol",
        str(arm["chunk_execution_protocol"]),
        "--pi05-chunk-execution-steps",
        str(int(arm["chunk_execution_steps"])),
        "--require-vla-goal-verdict",
        "--require-vla-grasp-mode",
        "--workers",
        "1",
    ]


def _summarize_arm(
    arm: dict[str, Any],
    audit: dict[str, Any],
    telemetry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runs = list(audit.get("runs") or ())
    policies = [run.get("policy") or {} for run in runs]
    expected_protocol = str(arm["chunk_execution_protocol"])
    expected_steps = int(arm["chunk_execution_steps"])
    errors: list[str] = []
    if audit.get("status") != "passed":
        errors.append("campaign_audit_failed")
    if any(policy.get("chunk_execution_protocol") != expected_protocol for policy in policies):
        errors.append("chunk_execution_protocol_mismatch")
    if any(int(policy.get("chunk_execution_steps", -1)) != expected_steps for policy in policies):
        errors.append("chunk_execution_steps_mismatch")
    if telemetry is None:
        errors.append("missing_rocm_energy_telemetry")

    def mean_metric(name: str) -> float | None:
        values = [float(policy[name]) for policy in policies if policy.get(name) is not None]
        return statistics.fmean(values) if values else None

    successes = int(audit.get("successes", 0))
    trials = int(audit.get("trials", 0))
    energy_wh = float(telemetry["energy_wh"]) if telemetry else None
    return {
        "id": str(arm["id"]),
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "chunk_execution_protocol": expected_protocol,
        "chunk_execution_steps": expected_steps,
        "successes": successes,
        "trials": trials,
        "success_rate": float(audit.get("success_rate", 0.0)),
        "force_violation_count": int(audit.get("force_violation_count", 0)),
        "expert_fallback_count": int(audit.get("expert_fallback_count", 0)),
        "vla_qualified_run_count": int(audit.get("vla_qualified_run_count", 0)),
        "mean_inference_latency_ms": mean_metric("mean_latency_ms"),
        "mean_p95_inference_latency_ms": mean_metric("p95_latency_ms"),
        "mean_residual_boundary_l2": mean_metric("mean_residual_boundary_l2"),
        "mean_policy_inference_count": mean_metric("policy_inference_count"),
        "mean_policy_selection_count": mean_metric("policy_selection_count"),
        "rocm_energy_wh": energy_wh,
        "rocm_wh_per_attempt": energy_wh / trials if energy_wh is not None and trials else None,
        "rocm_wh_per_success": (
            energy_wh / successes if energy_wh is not None and successes else None
        ),
        "rocm_mean_package_power_w": (
            telemetry.get("mean_package_power_w") if telemetry else None
        ),
        "rocm_peak_vram_allocated_percent": (
            telemetry.get("peak_vram_allocated_percent") if telemetry else None
        ),
        "rocm_vram_growth_percentage_points": (
            telemetry.get("vram_growth_percentage_points") if telemetry else None
        ),
    }


def _run(command: list[str], log_path: Path, env: dict[str, str]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed with code {completed.returncode}: {log_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--route-screen", type=Path, required=True)
    parser.add_argument(
        "--episode-config",
        type=Path,
        default=PROJECT_ROOT / "configs/mobile_pi05_r3b_strict_dev_v1.json",
    )
    parser.add_argument(
        "--ablation-config",
        type=Path,
        default=PROJECT_ROOT / "configs/mobile_pi05_chunk_runtime_ablation_v1.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    checkpoint = args.checkpoint.resolve()
    if not (checkpoint / "config.json").is_file():
        parser.error(f"checkpoint config is missing: {checkpoint}")
    for path in (args.route_screen, args.episode_config, args.ablation_config):
        if not path.is_file():
            parser.error(f"required input is missing: {path}")
    route_screen = _read_json(args.route_screen)
    try:
        _validate_route_screen(route_screen, checkpoint)
    except ValueError as exc:
        parser.error(str(exc))

    ablation = _read_json(args.ablation_config)
    runtime = ablation.get("fixed_runtime") or {}
    telemetry_config = ablation.get("rocm_telemetry") or {}
    arms = list(ablation.get("arms") or ())
    if ablation.get("protocol") != "parcel-pi05-matched-chunk-runtime-ablation-v1":
        parser.error("unexpected runtime ablation protocol")
    if len(arms) != 3 or int(runtime.get("policy_inference_hz", 0)) != 3:
        parser.error("runtime ablation must contain the frozen three-arm 3 Hz design")

    output = args.output.resolve()
    state_path = output / "runtime-ablation-state.json"
    if output.exists() and any(output.iterdir()) and not args.resume:
        parser.error(f"output must be empty or --resume must be used: {output}")
    output.mkdir(parents=True, exist_ok=True)
    inputs = {
        "checkpoint": str(checkpoint),
        "checkpoint_config_sha256": _sha256(checkpoint / "config.json"),
        "route_screen": str(args.route_screen.resolve()),
        "route_screen_sha256": _sha256(args.route_screen),
        "episode_config": str(args.episode_config.resolve()),
        "episode_config_sha256": _sha256(args.episode_config),
        "ablation_config": str(args.ablation_config.resolve()),
        "ablation_config_sha256": _sha256(args.ablation_config),
    }
    if args.resume and state_path.is_file():
        state = _read_json(state_path)
        if state.get("inputs") != inputs:
            raise RuntimeError("resume rejected because a frozen input changed")
    else:
        state = {
            "schema_version": 1,
            "protocol": "parcel-pi05-chunk-runtime-runner-v1",
            "status": "prepared",
            "inputs": inputs,
            "arms": {},
            "claim_boundary": "Development-only matched runtime ablation, not frozen 105-episode evidence.",
        }
        _write_json(state_path, state)

    commands: dict[str, dict[str, list[str]]] = {}
    for arm in arms:
        arm_id = str(arm["id"])
        arm_root = output / arm_id.lower()
        commands[arm_id] = {
            "collect": _campaign_command(
                checkpoint=checkpoint,
                episode_config=args.episode_config.resolve(),
                output=arm_root / "rollouts",
                arm=arm,
                policy_hz=int(runtime["policy_inference_hz"]),
            ),
            "summarize": [
                sys.executable,
                str(PROJECT_ROOT / "scripts/summarize_mobile_vla_campaign.py"),
                "--collection-summary",
                str(arm_root / "rollouts/collection-summary.json"),
                "--output",
                str(arm_root / "campaign-audit.json"),
            ],
        }
    state["commands"] = commands
    if args.dry_run:
        state["status"] = "dry_run"
        _write_json(state_path, state)
        print(json.dumps(state, indent=2, sort_keys=True))
        return 0

    env = os.environ.copy()
    env["HIP_VISIBLE_DEVICES"] = env.get("HIP_VISIBLE_DEVICES", "0")
    env["PYTHONPATH"] = f"{PROJECT_ROOT / 'src'}{os.pathsep}{env.get('PYTHONPATH', '')}"
    state["status"] = "running"
    _write_json(state_path, state)
    arm_summaries = []
    for arm in arms:
        arm_id = str(arm["id"])
        arm_root = output / arm_id.lower()
        audit_path = arm_root / "campaign-audit.json"
        telemetry_path = arm_root / "rocm-telemetry-summary.json"
        arm_state = state["arms"].setdefault(arm_id, {})
        if not audit_path.is_file():
            with RocmTelemetryRecorder(
                arm_root / "rocm-telemetry.jsonl",
                interval_seconds=float(telemetry_config.get("interval_seconds", 1.0)),
                gpu_id=str(telemetry_config.get("gpu_id", "card0")),
            ) as recorder:
                _run(commands[arm_id]["collect"], arm_root / "collect.log", env)
            _write_json(telemetry_path, recorder.summary())
            _run(commands[arm_id]["summarize"], arm_root / "summarize.log", env)
        audit = _read_json(audit_path)
        telemetry = _read_json(telemetry_path) if telemetry_path.is_file() else None
        summary = _summarize_arm(arm, audit, telemetry)
        arm_state.update(summary)
        arm_state["campaign_audit"] = str(audit_path)
        arm_state["campaign_audit_sha256"] = _sha256(audit_path)
        if telemetry_path.is_file():
            arm_state["rocm_telemetry"] = str(telemetry_path)
            arm_state["rocm_telemetry_sha256"] = _sha256(telemetry_path)
        _write_json(state_path, state)
        arm_summaries.append(summary)

    status = "passed" if all(item["status"] == "passed" for item in arm_summaries) else "failed"
    result = {
        "schema_version": 1,
        "protocol": "parcel-pi05-matched-chunk-runtime-result-v1",
        "status": status,
        "inputs": inputs,
        "arms": arm_summaries,
        "rtc_authorized": False,
        "rtc_authorization_rule": (
            "Requires C2 to improve sealing or complete success over C0 without "
            "increasing force violations; three development episodes alone do not "
            "establish statistical superiority."
        ),
        "claim_boundary": "Development-only matched runtime ablation, not frozen 105-episode evidence.",
    }
    result_path = output / "runtime-ablation-result.json"
    _write_json(result_path, result)
    state["status"] = status
    state["result"] = str(result_path)
    state["result_sha256"] = _sha256(result_path)
    _write_json(state_path, state)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if status == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
