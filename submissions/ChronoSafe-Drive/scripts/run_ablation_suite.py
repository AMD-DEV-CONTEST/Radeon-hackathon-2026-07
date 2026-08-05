"""Run paired paper ablations under the frozen nuScenes CV protocol."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=Path("configs/paper_protocol.json"))
    parser.add_argument(
        "--timing-simulation-data",
        type=Path,
        default=Path("data/chronosafe_metadrive_timing_32seeds.npz"),
    )
    parser.add_argument(
        "--timing-real-data",
        type=Path,
        default=Path("data/chronosafe_nuscenes_timing_v2.npz"),
    )
    parser.add_argument(
        "--basic-simulation-data",
        type=Path,
        default=Path("data/chronosafe_metadrive_basic_32seeds.npz"),
    )
    parser.add_argument(
        "--basic-real-data",
        type=Path,
        default=Path("data/chronosafe_nuscenes_basic_v2.npz"),
    )
    parser.add_argument(
        "--full-reference",
        type=Path,
        default=Path("artifacts/paper_nuscenes_cross_validation"),
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/paper_ablation_suite"))
    parser.add_argument("--log-dir", type=Path, default=Path("evidence/paper_ablation_suite"))
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def run_streamed(command: list[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log_handle.write(line)
            log_handle.flush()
        return_code = process.wait()
    if return_code:
        raise RuntimeError(f"Command failed with exit code {return_code}: {command}")


def ensure_basic_projection(source: Path, target: Path) -> None:
    if target.is_file():
        return
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/project_feature_set.py",
            "--input",
            str(source),
            "--output",
            str(target),
            "--mode",
            "basic",
        ],
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(f"Could not create basic feature projection: {target}")


def read_rows(path: Path, method: str) -> list[dict[str, object]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [{"method": method, **row} for row in csv.DictReader(handle)]


def average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2.0
        ranks[order[start:end]] = rank
        start = end
    return ranks


def exact_wilcoxon_two_sided(differences: list[float]) -> float:
    difference = np.asarray(differences, dtype=np.float64)
    difference = difference[np.abs(difference) > 1e-12]
    if not len(difference):
        return 1.0
    ranks = average_ranks(np.abs(difference))
    observed_positive = float(ranks[difference > 0].sum())
    total = float(ranks.sum())
    observed = min(observed_positive, total - observed_positive)
    assignments = np.arange(1 << len(ranks), dtype=np.uint64)
    positive_sums = np.zeros(len(assignments), dtype=np.float64)
    for index, rank in enumerate(ranks):
        positive_sums += ((assignments >> index) & 1) * rank
    statistics = np.minimum(positive_sums, total - positive_sums)
    return float(np.mean(statistics <= observed + 1e-12))


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values, key=p_values.get)
    adjusted: dict[str, float] = {}
    running = 0.0
    count = len(ordered)
    for index, name in enumerate(ordered):
        running = max(running, (count - index) * p_values[name])
        adjusted[name] = min(1.0, running)
    return adjusted


def main() -> None:
    args = parse_args()
    ensure_basic_projection(args.timing_simulation_data, args.basic_simulation_data)
    ensure_basic_projection(args.timing_real_data, args.basic_real_data)
    reference_csv = args.full_reference / "cross_validation_runs.csv"
    reference_json = args.full_reference / "cross_validation_aggregate.json"
    if not reference_csv.is_file() or not reference_json.is_file():
        raise FileNotFoundError("Full-method cross-validation reference is missing")
    args.output.mkdir(parents=True, exist_ok=True)
    args.log_dir.mkdir(parents=True, exist_ok=True)

    configurations = {
        "no_scenario_loss": {
            "simulation": args.timing_simulation_data,
            "real": args.timing_real_data,
            "source_mode": "hybrid",
            "scenario_weight": 0.0,
        },
        "no_timing_features": {
            "simulation": args.basic_simulation_data,
            "real": args.basic_real_data,
            "source_mode": "hybrid",
            "scenario_weight": 0.75,
        },
        "simulation_only": {
            "simulation": args.timing_simulation_data,
            "real": args.timing_real_data,
            "source_mode": "simulation_only",
            "scenario_weight": 0.75,
        },
        "real_only": {
            "simulation": args.timing_simulation_data,
            "real": args.timing_real_data,
            "source_mode": "real_only",
            "scenario_weight": 0.75,
        },
    }

    for method, config in configurations.items():
        method_dir = args.output / method
        aggregate_path = method_dir / "cross_validation_aggregate.json"
        if args.resume and aggregate_path.is_file():
            print(f"ablation {method}: reuse", flush=True)
            continue
        command = [
            sys.executable,
            "scripts/run_nuscenes_cross_validation.py",
            "--protocol",
            str(args.protocol),
            "--simulation-data",
            str(config["simulation"]),
            "--real-data",
            str(config["real"]),
            "--output",
            str(method_dir),
            "--log-dir",
            str(args.log_dir / method),
            "--train-source-mode",
            str(config["source_mode"]),
            "--scenario-loss-weight",
            str(config["scenario_weight"]),
        ]
        if args.resume:
            command.append("--resume")
        print(f"ablation {method}: start", flush=True)
        run_streamed(command, args.log_dir / f"{method}_master.log")

    method_rows: dict[str, list[dict[str, object]]] = {
        "full": read_rows(reference_csv, "full")
    }
    for method in configurations:
        method_rows[method] = read_rows(
            args.output / method / "cross_validation_runs.csv", method
        )
    all_rows = [row for rows in method_rows.values() for row in rows]
    combined_csv = args.output / "ablation_runs.csv"
    with combined_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)

    metric_keys = (
        "real_scenario_accuracy",
        "real_risk_mae",
        "real_upper_risk_coverage",
        "simulation_scenario_accuracy",
        "simulation_risk_mae",
        "simulation_upper_risk_coverage",
    )
    comparison: dict[str, object] = {"methods": {}, "paired_tests": {}}
    for method, rows in method_rows.items():
        comparison["methods"][method] = {
            key: {
                "mean": round(float(np.mean([float(row[key]) for row in rows])), 6),
                "std": round(float(np.std([float(row[key]) for row in rows], ddof=1)), 6),
            }
            for key in metric_keys
        }

    full_lookup = {
        (int(row["fold"]), int(row["training_seed"])): row for row in method_rows["full"]
    }
    raw_p_values: dict[str, float] = {}
    effects: dict[str, float] = {}
    for method in configurations:
        method_lookup = {
            (int(row["fold"]), int(row["training_seed"])): row
            for row in method_rows[method]
        }
        keys = sorted(full_lookup)
        differences = [
            float(full_lookup[key]["real_scenario_accuracy"])
            - float(method_lookup[key]["real_scenario_accuracy"])
            for key in keys
        ]
        raw_p_values[method] = exact_wilcoxon_two_sided(differences)
        effects[method] = float(np.mean(differences))
    adjusted = holm_adjust(raw_p_values)
    comparison["paired_tests"] = {
        method: {
            "metric": "real_scenario_accuracy",
            "mean_full_minus_ablation": round(effects[method], 6),
            "wilcoxon_exact_p": round(raw_p_values[method], 8),
            "holm_adjusted_p": round(adjusted[method], 8),
        }
        for method in configurations
    }
    comparison["full_reference"] = str(args.full_reference)
    comparison["runs_per_method"] = len(method_rows["full"])
    comparison["total_runs"] = len(all_rows)
    (args.output / "ablation_summary.json").write_text(
        json.dumps(comparison, indent=2), encoding="utf-8"
    )
    print(json.dumps(comparison, indent=2))
    print(f"ablation runs: {combined_csv}")
    print("ChronoSafe paper ablation suite: PASS")


if __name__ == "__main__":
    main()
