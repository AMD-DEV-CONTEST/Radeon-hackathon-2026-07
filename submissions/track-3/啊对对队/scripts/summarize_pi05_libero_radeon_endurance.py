#!/usr/bin/env python3
"""Summarize persistent PI0.5 Radeon success, latency, energy, and VRAM drift."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any

from parcel_sorter.rocm_telemetry import summarize_rocm_samples


def canonical_sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_config(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    recorded = payload.pop("config_sha256")
    actual = canonical_sha256(payload)
    payload["config_sha256"] = recorded
    if actual != recorded:
        raise RuntimeError(f"endurance config hash mismatch: {actual} != {recorded}")
    return payload


def _timing_metric(episode_timing: dict[str, Any], name: str) -> float:
    return float(episode_timing["model_inference_calls"][name])


def summarize(config: dict[str, Any], run_root: Path) -> dict[str, Any]:
    contract = json.loads((run_root / "run-contract.json").read_text(encoding="utf-8"))
    run_summary = json.loads((run_root / "run-summary.json").read_text(encoding="utf-8"))
    eval_info = json.loads((run_root / "eval" / "eval_info.json").read_text(encoding="utf-8"))
    selection = json.loads((run_root / "RUNTIME_SELECTION.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    if contract.get("manifest_sha256") != config["manifest"]["manifest_sha256"]:
        errors.append("manifest mismatch")
    if contract.get("phase") != "endurance":
        errors.append("phase is not endurance")
    expected_compile = "true" if selection.get("compile") else "false"
    if contract.get("compile_override") != expected_compile:
        errors.append("selected compile runtime was not executed")
    command = contract.get("command") or []
    if "--env.init_state_stride=0" not in command:
        errors.append("fixed init-state stride is missing")
    if "--eval.interleave_task_episodes=true" not in command:
        errors.append("task-interleaved repeat execution is missing")
    overall = eval_info.get("overall") or {}
    if int(overall.get("n_episodes", 0)) != int(config["experimental_design"]["attempts"]):
        errors.append("endurance attempt count mismatch")
    if int(run_summary.get("returncode", -1)) != 0:
        errors.append("endurance runner failed")
    if (run_summary.get("measurement_validation") or {}).get("status") != "passed":
        errors.append("inference measurement validation failed")
    telemetry = run_summary.get("telemetry") or {}
    if int(telemetry.get("sampling_error_count", -1)) != 0:
        errors.append("ROCm telemetry contains sampling errors")
    per_task = eval_info.get("per_task") or []
    if len(per_task) != int(config["experimental_design"]["unique_units"]):
        errors.append("endurance task count mismatch")
    cycles = int(config["experimental_design"]["cycles"])
    if any(len((item.get("metrics") or {}).get("successes", [])) != cycles for item in per_task):
        errors.append("per-task success repeats are incomplete")
    if any(
        len((item.get("metrics") or {}).get("episode_policy_timings", [])) != cycles
        for item in per_task
    ):
        errors.append("per-task timing repeats are incomplete")
    if errors:
        raise RuntimeError("invalid Radeon endurance run: " + "; ".join(errors))

    cycle_summaries = []
    for cycle in range(cycles):
        successes = [bool(item["metrics"]["successes"][cycle]) for item in per_task]
        episode_p95 = [
            _timing_metric(item["metrics"]["episode_policy_timings"][cycle], "warm_p95_ms")
            for item in per_task
        ]
        episode_p50 = [
            _timing_metric(item["metrics"]["episode_policy_timings"][cycle], "warm_p50_ms")
            for item in per_task
        ]
        cycle_summaries.append(
            {
                "cycle": cycle + 1,
                "successes": sum(successes),
                "units": len(successes),
                "success_percent": 100.0 * sum(successes) / len(successes),
                "median_episode_warm_p50_ms": statistics.median(episode_p50),
                "median_episode_warm_p95_ms": statistics.median(episode_p95),
                "max_episode_warm_p95_ms": max(episode_p95),
            }
        )

    raw_samples = [
        json.loads(line)
        for line in (run_root / "rocm-telemetry.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    window_size = len(raw_samples) // cycles
    power_windows = []
    for cycle in range(cycles):
        start = cycle * window_size
        end = len(raw_samples) if cycle == cycles - 1 else (cycle + 1) * window_size
        window = raw_samples[start:end]
        power_windows.append({"cycle": cycle + 1, **summarize_rocm_samples(window)})

    first = cycle_summaries[0]
    last = cycle_summaries[-1]
    success_drop = first["success_percent"] - last["success_percent"]
    latency_drift = 100.0 * (
        last["median_episode_warm_p95_ms"] - first["median_episode_warm_p95_ms"]
    ) / first["median_episode_warm_p95_ms"]
    vram_growth = float(telemetry.get("vram_growth_percentage_points") or 0.0)
    gate = config["stability_gate"]
    checks = {
        "cycle3_success_drop": success_drop
        <= float(gate["maximum_cycle3_success_drop_percentage_points"]),
        "cycle3_latency_drift": latency_drift
        <= float(gate["maximum_cycle3_median_episode_p95_drift_percent"]),
        "vram_growth": vram_growth <= float(gate["maximum_vram_growth_percentage_points"]),
        "rocm_sampling": int(telemetry["sampling_error_count"])
        <= int(gate["rocm_sampling_errors_allowed"]),
    }
    return {
        "schema_version": 1,
        "protocol_id": config["protocol_id"],
        "config_sha256": config["config_sha256"],
        "runtime_selection": selection,
        "cycle_summaries": cycle_summaries,
        "power_time_windows": power_windows,
        "overall": {
            "successes": sum(sum(bool(value) for value in item["metrics"]["successes"]) for item in per_task),
            "attempts": int(overall["n_episodes"]),
            "independent_units": int(config["experimental_design"]["unique_units"]),
            "energy_wh": float(telemetry["energy_wh"]),
            "energy_wh_per_attempt": float(telemetry["energy_wh"]) / int(overall["n_episodes"]),
            "mean_package_power_w": float(telemetry["mean_package_power_w"]),
            "peak_vram_allocated_percent": telemetry.get("peak_vram_allocated_percent"),
            "vram_growth_percentage_points": vram_growth,
            "peak_allocated_gib": overall["accelerator_memory"]["peak_allocated_gib"],
            "success_drop_cycle1_to_cycle3_percentage_points": success_drop,
            "median_episode_p95_drift_cycle1_to_cycle3_percent": latency_drift,
        },
        "stability_checks": checks,
        "stability_status": "passed" if all(checks.values()) else "rejected",
        "claim_boundary": config["claim_boundary"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = summarize(load_config(args.config), args.run_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
