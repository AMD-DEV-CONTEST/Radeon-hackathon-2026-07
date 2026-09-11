#!/usr/bin/env python3
"""Validate and summarize the paired PI0.5 Radeon compile ablation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any

from summarize_pi05_libero_benchmark import flatten_successes, paired_comparison


def canonical_sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_config(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    recorded = payload.pop("config_sha256")
    actual = canonical_sha256(payload)
    payload["config_sha256"] = recorded
    if recorded != actual:
        raise RuntimeError(f"ablation config hash mismatch: {actual} != {recorded}")
    return payload


def _percent_improvement(control: float, candidate: float) -> float:
    if control <= 0:
        raise ValueError("control metric must be positive")
    return 100.0 * (control - candidate) / control


def load_run(
    run_root: Path,
    *,
    run_contract: dict[str, Any],
    manifest_sha256: str,
) -> dict[str, Any]:
    contract = json.loads((run_root / "run-contract.json").read_text(encoding="utf-8"))
    summary = json.loads((run_root / "run-summary.json").read_text(encoding="utf-8"))
    eval_info = json.loads((run_root / "eval" / "eval_info.json").read_text(encoding="utf-8"))
    expected_compile = "true" if bool(run_contract["compile"]) else "false"
    errors: list[str] = []
    if contract.get("manifest_sha256") != manifest_sha256:
        errors.append("manifest mismatch")
    if contract.get("phase") != "efficiency":
        errors.append("phase is not efficiency")
    if contract.get("compile_override") != expected_compile:
        errors.append("compile treatment mismatch")
    scope = contract.get("run_scope") or {}
    if scope.get("score_eligible") is not False or int(scope.get("episodes_per_task", 0)) != 1:
        errors.append("development efficiency scope mismatch")
    overall = eval_info.get("overall") or {}
    if int(overall.get("n_episodes", 0)) != 40:
        errors.append("run does not contain 40 LIBERO units")
    if int(summary.get("returncode", -1)) != 0:
        errors.append("runner returncode is nonzero")
    if (summary.get("measurement_validation") or {}).get("status") != "passed":
        errors.append("measurement validation did not pass")
    telemetry = summary.get("telemetry") or {}
    if int(telemetry.get("sampling_error_count", -1)) != 0:
        errors.append("ROCm telemetry contains sampling errors")
    if errors:
        raise RuntimeError(f"invalid {run_contract['run_id']} run: {errors}")

    timing = overall["policy_timing"]["model_inference_calls"]
    memory = overall["accelerator_memory"]
    outcomes = flatten_successes(eval_info)
    successes = sum(outcomes.values())
    energy_wh = float(telemetry["energy_wh"])
    return {
        "run_id": run_contract["run_id"],
        "compile": bool(run_contract["compile"]),
        "treatment": run_contract["treatment"],
        "successes": successes,
        "episodes": len(outcomes),
        "success_percent": 100.0 * successes / len(outcomes),
        "outcomes": outcomes,
        "model_inference_calls": int(timing["count"]),
        "cold_start_ms": float(timing["cold_start_ms"]),
        "warm_p50_ms": float(timing["warm_p50_ms"]),
        "warm_p95_ms": float(timing["warm_p95_ms"]),
        "warm_p99_ms": float(timing["warm_p99_ms"]),
        "peak_allocated_gib": float(memory["peak_allocated_gib"]),
        "peak_reserved_gib": float(memory["peak_reserved_gib"]),
        "energy_wh": energy_wh,
        "energy_wh_per_episode": energy_wh / len(outcomes),
        "mean_package_power_w": float(telemetry["mean_package_power_w"]),
        "vram_growth_percentage_points": telemetry.get("vram_growth_percentage_points"),
        "run_contract_sha256": sha256_file(run_root / "run-contract.json"),
        "run_summary_sha256": sha256_file(run_root / "run-summary.json"),
        "eval_info_sha256": sha256_file(run_root / "eval" / "eval_info.json"),
    }


def summarize(config: dict[str, Any], run_root: Path) -> dict[str, Any]:
    expected_runs = config["experimental_design"]["execution_order"]
    runs = {
        item["run_id"]: load_run(
            run_root / item["run_id"],
            run_contract=item,
            manifest_sha256=config["manifest"]["manifest_sha256"],
        )
        for item in expected_runs
    }
    paired = []
    for control_id, candidate_id in config["experimental_design"]["pairing"]:
        result = paired_comparison(runs[control_id]["outcomes"], runs[candidate_id]["outcomes"])
        result.update({"control_run_id": control_id, "candidate_run_id": candidate_id})
        paired.append(result)

    controls = [run for run in runs.values() if run["treatment"] == "control"]
    candidates = [run for run in runs.values() if run["treatment"] == "candidate"]
    median_control_p95 = statistics.median(run["warm_p95_ms"] for run in controls)
    median_candidate_p95 = statistics.median(run["warm_p95_ms"] for run in candidates)
    median_control_energy = statistics.median(run["energy_wh_per_episode"] for run in controls)
    median_candidate_energy = statistics.median(run["energy_wh_per_episode"] for run in candidates)
    p95_improvement = _percent_improvement(median_control_p95, median_candidate_p95)
    energy_improvement = _percent_improvement(median_control_energy, median_candidate_energy)
    control_peak = max(run["peak_allocated_gib"] for run in controls)
    candidate_peak = max(run["peak_allocated_gib"] for run in candidates)
    peak_regression = 100.0 * (candidate_peak - control_peak) / control_peak
    gate = config["promotion_gate"]
    checks = {
        "success_non_regression": all(item["candidate_losses"] <= item["candidate_wins"] for item in paired),
        "warm_p95_improvement": p95_improvement
        >= float(gate["minimum_median_warm_p95_improvement_percent"]),
        "energy_per_episode_improvement": energy_improvement
        >= float(gate["minimum_median_energy_per_episode_improvement_percent"]),
        "peak_vram_regression": peak_regression
        <= float(gate["maximum_peak_allocated_vram_regression_percent"]),
    }
    serializable_runs = {
        run_id: {key: value for key, value in run.items() if key != "outcomes"}
        for run_id, run in runs.items()
    }
    return {
        "schema_version": 1,
        "protocol_id": config["protocol_id"],
        "config_sha256": config["config_sha256"],
        "runs": serializable_runs,
        "paired_success": paired,
        "aggregate": {
            "median_control_warm_p95_ms": median_control_p95,
            "median_candidate_warm_p95_ms": median_candidate_p95,
            "warm_p95_improvement_percent": p95_improvement,
            "median_control_energy_wh_per_episode": median_control_energy,
            "median_candidate_energy_wh_per_episode": median_candidate_energy,
            "energy_per_episode_improvement_percent": energy_improvement,
            "control_peak_allocated_gib": control_peak,
            "candidate_peak_allocated_gib": candidate_peak,
            "peak_allocated_vram_regression_percent": peak_regression,
        },
        "promotion_checks": checks,
        "promotion_status": "passed" if all(checks.values()) else "rejected",
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
