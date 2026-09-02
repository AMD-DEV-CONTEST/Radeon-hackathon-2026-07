#!/usr/bin/env python3
"""Recompute and gate the frozen Challenge Arena from immutable raw pair records."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "challenge_arena_v1.json"
RUNNER_PATH = ROOT / "scripts" / "run_challenge_arena_amd.py"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_immutable(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing input: {path}")
    stat = path.stat()
    require(stat.st_nlink == 1, f"input must have nlink=1: {path}")
    require(stat.st_mode & 0o222 == 0, f"input must be read-only: {path}")
    return json.loads(path.read_bytes())


def recompute_run(
    path: Path,
    *,
    seed: int,
    profile: str,
    pairs: int,
    config_sha256: str,
    runner_sha256: str,
) -> dict[str, Any]:
    data = load_immutable(path)
    require(data["status"] == "MEASURED", f"run is not MEASURED: {path}")
    require(data["mode"] == "compare", f"run mode mismatch: {path}")
    require(data["frozen_config"]["sha256"] == config_sha256, "config binding mismatch")
    require(data["source"]["runner_sha256"] == runner_sha256, "runner binding mismatch")
    experiment = data["experiment"]
    require(experiment["seed"] == seed, "seed mismatch")
    require(experiment["domain_profile"] == profile, "profile mismatch")
    require(experiment["pairs"] == pairs, "pair count mismatch")
    require(experiment["same_initial_state"] is True, "initial-state pairing is false")
    require(experiment["same_domain_parameters"] is True, "domain pairing is false")
    require(experiment["only_controller_profile_changes"] is True, "paired intervention is not controller-only")
    require(all(data["integrity"].values()), f"integrity failed: {path}")
    records = data["pair_records"]
    require(len(records) == pairs, "pair-record count mismatch")
    require(sorted(record["pair_index"] for record in records) == list(range(pairs)), "pair indexes are not exact")

    nominal_success = robust_success = nominal_strike = robust_strike = 0
    nominal_terminal_failure = robust_terminal_failure = 0
    nominal_only = robust_only = both_success = both_fail = 0
    max_nominal_saturation = max_robust_saturation = 0.0
    strata: dict[int, dict[str, Any]] = {}
    robust_only_records: list[dict[str, Any]] = []
    for record in records:
        nominal = record["arms"]["nominal"]
        robust = record["arms"]["robust_z"]
        ns = bool(nominal["mission_success"])
        rs = bool(robust["mission_success"])
        nominal_success += ns
        robust_success += rs
        nominal_strike += bool(nominal["strike"])
        robust_strike += bool(robust["strike"])
        nominal_terminal_failure += bool(nominal["terminal"] and not ns)
        robust_terminal_failure += bool(robust["terminal"] and not rs)
        nominal_only += bool(ns and not rs)
        robust_only += bool(rs and not ns)
        both_success += bool(ns and rs)
        both_fail += bool(not ns and not rs)
        max_nominal_saturation = max(max_nominal_saturation, float(nominal["applied_action_saturation_fraction"]))
        max_robust_saturation = max(max_robust_saturation, float(robust["applied_action_saturation_fraction"]))
        stratum = int(record["stratum"])
        if stratum not in strata:
            strata[stratum] = {
                "stratum": stratum,
                "name": record["stratum_name"],
                "pair_count": 0,
                "nominal_success_count": 0,
                "robust_success_count": 0,
                "nominal_only_success": 0,
                "robust_only_success": 0,
            }
        row = strata[stratum]
        require(row["name"] == record["stratum_name"], "stratum name drift")
        row["pair_count"] += 1
        row["nominal_success_count"] += ns
        row["robust_success_count"] += rs
        row["nominal_only_success"] += bool(ns and not rs)
        row["robust_only_success"] += bool(rs and not ns)
        if rs and not ns:
            robust_only_records.append(record)

    recomputed_outcomes = {
        "both_fail": both_fail,
        "both_success": both_success,
        "candidate_minus_nominal_success_count": robust_success - nominal_success,
        "nominal_only_success": nominal_only,
        "robust_only_success": robust_only,
    }
    require(recomputed_outcomes == data["paired_outcomes"], "paired outcomes do not recompute")
    for arm, success, strike, terminal_failure in (
        ("nominal", nominal_success, nominal_strike, nominal_terminal_failure),
        ("robust_z", robust_success, robust_strike, robust_terminal_failure),
    ):
        advertised = data["arms"][arm]
        require(advertised["mission_success_count"] == success, f"{arm} success mismatch")
        require(advertised["mission_failure_count"] == pairs - success, f"{arm} failure mismatch")
        require(advertised["strike_count"] == strike, f"{arm} strike mismatch")
        require(advertised["terminal_failure_count"] == terminal_failure, f"{arm} terminal failure mismatch")

    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "seed": seed,
        "profile": profile,
        "pairs": pairs,
        "nominal_success_count": nominal_success,
        "robust_success_count": robust_success,
        "success_delta_count": robust_success - nominal_success,
        "nominal_failure_count": pairs - nominal_success,
        "robust_failure_count": pairs - robust_success,
        "nominal_strike_count": nominal_strike,
        "robust_strike_count": robust_strike,
        "nominal_terminal_failure_count": nominal_terminal_failure,
        "robust_terminal_failure_count": robust_terminal_failure,
        "nominal_only_success": nominal_only,
        "robust_only_success": robust_only,
        "maximum_applied_saturation_fraction": {
            "nominal": max_nominal_saturation,
            "robust_z": max_robust_saturation,
        },
        "per_stratum": [strata[key] for key in sorted(strata)],
        "robust_only_records": robust_only_records,
        "runtime": data["runtime"],
    }


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(run["pairs"] for run in runs)
    nominal = sum(run["nominal_success_count"] for run in runs)
    robust = sum(run["robust_success_count"] for run in runs)
    nominal_failure = total - nominal
    robust_failure = total - robust
    strata: dict[int, dict[str, Any]] = {}
    for run in runs:
        for source in run["per_stratum"]:
            key = source["stratum"]
            if key not in strata:
                strata[key] = dict(source)
                continue
            target = strata[key]
            require(target["name"] == source["name"], "aggregate stratum name drift")
            for name in ("pair_count", "nominal_success_count", "robust_success_count", "nominal_only_success", "robust_only_success"):
                target[name] += source[name]
    return {
        "pair_count": total,
        "nominal_success_count": nominal,
        "robust_success_count": robust,
        "success_delta_count": robust - nominal,
        "nominal_success_rate": nominal / total,
        "robust_success_rate": robust / total,
        "success_delta_percentage_points": 100.0 * (robust - nominal) / total,
        "nominal_failure_count": nominal_failure,
        "robust_failure_count": robust_failure,
        "failure_reduction_fraction": (nominal_failure - robust_failure) / nominal_failure if nominal_failure else 0.0,
        "nominal_strike_count": sum(run["nominal_strike_count"] for run in runs),
        "robust_strike_count": sum(run["robust_strike_count"] for run in runs),
        "nominal_terminal_failure_count": sum(run["nominal_terminal_failure_count"] for run in runs),
        "robust_terminal_failure_count": sum(run["robust_terminal_failure_count"] for run in runs),
        "nominal_only_success": sum(run["nominal_only_success"] for run in runs),
        "robust_only_success": sum(run["robust_only_success"] for run in runs),
        "positive_seed_count": sum(run["success_delta_count"] > 0 for run in runs),
        "per_seed_success_delta": {str(run["seed"]): run["success_delta_count"] for run in runs},
        "maximum_applied_saturation_fraction": {
            arm: max(run["maximum_applied_saturation_fraction"][arm] for run in runs)
            for arm in ("nominal", "robust_z")
        },
        "per_stratum": [strata[key] for key in sorted(strata)],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), f"refusing to overwrite: {args.output}")
    config = json.loads(CONFIG_PATH.read_bytes())
    config_sha = sha256_file(CONFIG_PATH)
    runner_sha = sha256_file(RUNNER_PATH)

    noop_path = args.input_dir / f"noop-seed{config['diagnostics']['no_op']['seed']}-recovery-v2.json"
    kill_path = args.input_dir / f"kill-seed{config['diagnostics']['kill_magnitude']['seed']}.json"
    noop = load_immutable(noop_path)
    kill = load_immutable(kill_path)
    require(noop["status"] == "PASS" and noop["diagnostic"]["bit_exact"] is True, "no-op gate failed")
    require(kill["status"] == "PASS" and all(kill["diagnostic"]["checks"].values()), "kill-magnitude gate failed")
    for diagnostic in (noop, kill):
        require(diagnostic["frozen_config"]["sha256"] == config_sha, "diagnostic config binding mismatch")
        require(diagnostic["source"]["runner_sha256"] == runner_sha, "diagnostic runner binding mismatch")
        require(all(diagnostic["integrity"].values()), "diagnostic integrity failed")

    primary_runs = [
        recompute_run(
            args.input_dir / f"primary-adversarial-seed{seed}.json",
            seed=seed,
            profile=config["primary"]["domain_profile"],
            pairs=config["primary"]["pairs_per_seed"],
            config_sha256=config_sha,
            runner_sha256=runner_sha,
        )
        for seed in config["primary"]["seeds"]
    ]
    retention_runs = [
        recompute_run(
            args.input_dir / f"retention-heldout-seed{seed}.json",
            seed=seed,
            profile=config["retention"]["domain_profile"],
            pairs=config["retention"]["pairs_per_seed"],
            config_sha256=config_sha,
            runner_sha256=runner_sha,
        )
        for seed in config["retention"]["seeds"]
    ]
    primary = aggregate(primary_runs)
    retention = aggregate(retention_runs)
    acceptance = config["acceptance"]
    saturation_max = acceptance["per_episode_applied_action_saturation_fraction_max"]
    gates = {
        "no_op_bit_exact": True,
        "kill_magnitude": True,
        "primary_pair_count_exact": primary["pair_count"] == config["primary"]["total_pairs"],
        "primary_success_delta": primary["success_delta_count"] >= acceptance["primary_success_delta_min_count"],
        "primary_zero_regressions": primary["nominal_only_success"] <= acceptance["primary_nominal_success_to_robust_failure_max_count"],
        "primary_each_seed_nonnegative": all(run["success_delta_count"] >= acceptance["per_seed_success_delta_min_count"] for run in primary_runs),
        "primary_positive_seed_count": primary["positive_seed_count"] >= acceptance["minimum_positive_seed_count"],
        "primary_strikes_no_worse": primary["robust_strike_count"] <= primary["nominal_strike_count"],
        "primary_terminal_failures_no_worse": primary["robust_terminal_failure_count"] <= primary["nominal_terminal_failure_count"],
        "retention_pair_count_exact": retention["pair_count"] == config["retention"]["total_pairs"],
        "retention_zero_regressions": retention["nominal_only_success"] <= acceptance["retention_nominal_success_to_robust_failure_max_count"],
        "retention_degradation": max(0.0, retention["nominal_success_rate"] - retention["robust_success_rate"]) <= acceptance["retention_success_rate_degradation_max"],
        "all_finite_and_paired": all(all(load_immutable(Path(run["path"]))["integrity"].values()) for run in primary_runs + retention_runs),
        "all_saturation_below_limit": all(
            run["maximum_applied_saturation_fraction"][arm] <= saturation_max
            for run in primary_runs + retention_runs
            for arm in ("nominal", "robust_z")
        ),
    }
    robust_only = sorted(
        (run["seed"], record["pair_index"], run["path"], record)
        for run in primary_runs
        for record in run["robust_only_records"]
    )
    require(robust_only, "no robust-only success exists for deterministic demo selection")
    seed, pair_index, raw_path, record = robust_only[0]
    payload = {
        "schema_version": "flightguard.challenge_arena.summary.v1",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "simulation_only": True,
        "claim_boundary": config["claim_boundary"],
        "bindings": {
            "config": {"path": str(CONFIG_PATH), "sha256": config_sha},
            "runner": {"path": str(RUNNER_PATH), "sha256": runner_sha},
            "noop": {"path": str(noop_path), "sha256": sha256_file(noop_path)},
            "kill": {"path": str(kill_path), "sha256": sha256_file(kill_path)},
        },
        "gates": gates,
        "primary": primary,
        "retention": retention,
        "per_seed": {
            "primary": [{key: value for key, value in run.items() if key != "robust_only_records"} for run in primary_runs],
            "retention": [{key: value for key, value in run.items() if key != "robust_only_records"} for run in retention_runs],
        },
        "demo_pair": {"seed": seed, "pair_index": pair_index, "raw_path": raw_path, "raw_sha256": sha256_file(Path(raw_path)), "record": record},
    }
    raw = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    print(json.dumps({"status": payload["status"], "output": str(args.output), "sha256": hashlib.sha256(raw).hexdigest(), "primary": primary, "retention": retention, "demo_pair": payload["demo_pair"], "gates": gates}, sort_keys=True))
    raise SystemExit(0 if payload["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
