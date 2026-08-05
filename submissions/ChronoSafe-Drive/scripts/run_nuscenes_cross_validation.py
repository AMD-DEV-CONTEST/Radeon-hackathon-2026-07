"""Run frozen five-fold, three-seed scene-level nuScenes cross-validation."""

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
        "--simulation-data", type=Path, default=Path("data/chronosafe_metadrive_timing_32seeds.npz")
    )
    parser.add_argument(
        "--real-data", type=Path, default=Path("data/chronosafe_nuscenes_timing_v2.npz")
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/paper_nuscenes_cross_validation"))
    parser.add_argument("--log-dir", type=Path, default=Path("evidence/paper_nuscenes_cross_validation"))
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--hidden-size", type=int, default=128)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--sequences-per-source", type=int, default=30000)
    parser.add_argument("--scenario-loss-weight", type=float, default=0.75)
    parser.add_argument(
        "--train-source-mode",
        choices=("hybrid", "simulation_only", "real_only"),
        default="hybrid",
    )
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def bootstrap_fold_interval(
    fold_values: list[float], resamples: int, confidence: float, rng: np.random.Generator
) -> list[float]:
    values = np.asarray(fold_values, dtype=np.float64)
    indices = rng.integers(0, len(values), size=(resamples, len(values)))
    means = values[indices].mean(axis=1)
    tail = (1.0 - confidence) / 2.0
    return [float(np.quantile(means, tail)), float(np.quantile(means, 1.0 - tail))]


def fold_partitions(scenes: list[int], folds: int, test_count: int, calibration_count: int):
    if len(scenes) != folds * test_count:
        raise ValueError("Frozen protocol requires every scene to appear in exactly one test fold")
    for fold in range(folds):
        start = fold * test_count
        test = scenes[start : start + test_count]
        remaining_cycle = scenes[start + test_count :] + scenes[:start]
        calibration = remaining_cycle[:calibration_count]
        train = [scene for scene in scenes if scene not in set(test + calibration)]
        yield fold, train, calibration, test


def summarize_metric(
    rows: list[dict[str, object]],
    key: str,
    folds: int,
    resamples: int,
    confidence: float,
    rng: np.random.Generator,
) -> dict[str, object]:
    values = np.asarray([float(row[key]) for row in rows], dtype=np.float64)
    fold_means = [
        float(np.mean([float(row[key]) for row in rows if int(row["fold"]) == fold]))
        for fold in range(folds)
    ]
    return {
        "runs": len(values),
        "mean": round(float(values.mean()), 6),
        "std_across_runs": round(float(values.std(ddof=1)), 6),
        "fold_means": [round(value, 6) for value in fold_means],
        "fold_bootstrap_ci95": [
            round(value, 6)
            for value in bootstrap_fold_interval(fold_means, resamples, confidence, rng)
        ],
        "min": round(float(values.min()), 6),
        "max": round(float(values.max()), 6),
    }


def main() -> None:
    args = parse_args()
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    cv = protocol["nuscenes_mini"]
    training_seeds = [int(value) for value in cv["training_random_seeds"]]
    folds = int(cv["folds"])
    test_count = int(cv["test_scenes_per_fold"])
    calibration_count = int(cv["calibration_scenes_per_fold"])
    payload = np.load(args.real_data)
    scenes = sorted(int(value) for value in np.unique(payload["scene_ids"]))
    partitions = list(fold_partitions(scenes, folds, test_count, calibration_count))
    args.output.mkdir(parents=True, exist_ok=True)
    args.log_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    run_total = len(partitions) * len(training_seeds)
    run_index = 0

    for fold, train_scenes, calibration_scenes, test_scenes in partitions:
        for seed in training_seeds:
            run_index += 1
            run_dir = args.output / f"fold_{fold}" / f"seed_{seed}"
            metrics_path = run_dir / "metrics.json"
            if args.resume and metrics_path.is_file():
                print(f"run {run_index}/{run_total}: fold={fold} seed={seed} (reuse)", flush=True)
            else:
                print(
                    f"run {run_index}/{run_total}: fold={fold} seed={seed} "
                    f"train={train_scenes} calibration={calibration_scenes} test={test_scenes}",
                    flush=True,
                )
                command = [
                    sys.executable,
                    "scripts/train_hybrid_nuscenes_gru.py",
                    "--simulation-data",
                    str(args.simulation_data),
                    "--real-data",
                    str(args.real_data),
                    "--output",
                    str(run_dir),
                    "--epochs",
                    str(args.epochs),
                    "--hidden-size",
                    str(args.hidden_size),
                    "--batch-size",
                    str(args.batch_size),
                    "--sequences-per-source",
                    str(args.sequences_per_source),
                    "--scenario-loss-weight",
                    str(args.scenario_loss_weight),
                    "--train-source-mode",
                    args.train_source_mode,
                    "--real-train-scenes",
                    ",".join(map(str, train_scenes)),
                    "--real-calibration-scenes",
                    ",".join(map(str, calibration_scenes)),
                    "--real-test-scenes",
                    ",".join(map(str, test_scenes)),
                    "--seed",
                    str(seed),
                    "--deterministic",
                ]
                completed = subprocess.run(command, text=True, capture_output=True, check=False)
                log_text = completed.stdout + ("\nSTDERR:\n" + completed.stderr if completed.stderr else "")
                (args.log_dir / f"fold_{fold}_seed_{seed}.log").write_text(
                    log_text, encoding="utf-8"
                )
                if completed.returncode:
                    print(log_text)
                    raise RuntimeError(f"Cross-validation failed for fold={fold}, seed={seed}")
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            real_metrics = metrics["nuScenes_test"]
            simulation_metrics = metrics["simulation_test"]
            row: dict[str, object] = {
                "fold": fold,
                "training_seed": seed,
                "train_scenes": ",".join(map(str, train_scenes)),
                "calibration_scenes": ",".join(map(str, calibration_scenes)),
                "test_scenes": ",".join(map(str, test_scenes)),
                "training_seconds": float(metrics["training_seconds"]),
                "conformal_radius": float(metrics["robust_conformal_radius"]),
            }
            for prefix, source in (("real", real_metrics), ("simulation", simulation_metrics)):
                for key in (
                    "scenario_accuracy",
                    "camera_accuracy",
                    "lidar_accuracy",
                    "delay_accuracy",
                    "risk_mae",
                    "upper_risk_coverage",
                ):
                    row[f"{prefix}_{key}"] = float(source[key])
            rows.append(row)
            print(
                f"  real_accuracy={row['real_scenario_accuracy']:.4f} "
                f"coverage={row['real_upper_risk_coverage']:.4f} "
                f"sim_accuracy={row['simulation_scenario_accuracy']:.4f}",
                flush=True,
            )

    csv_path = args.output / "cross_validation_runs.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    statistics = protocol["statistics"]
    resamples = int(statistics["bootstrap_resamples"])
    confidence = float(statistics["confidence_level"])
    rng = np.random.default_rng(2026)
    metric_keys = [
        key
        for key in rows[0]
        if key.startswith("real_") or key.startswith("simulation_")
    ] + ["training_seconds", "conformal_radius"]
    aggregate = {
        "protocol": str(args.protocol),
        "simulation_data": str(args.simulation_data),
        "real_data": str(args.real_data),
        "folds": folds,
        "training_seeds": training_seeds,
        "runs": len(rows),
        "train_source_mode": args.train_source_mode,
        "scenario_loss_weight": args.scenario_loss_weight,
        "partitions": [
            {
                "fold": fold,
                "train": train,
                "calibration": calibration,
                "test": test,
            }
            for fold, train, calibration, test in partitions
        ],
        "metrics": {
            key: summarize_metric(rows, key, folds, resamples, confidence, rng)
            for key in metric_keys
        },
    }
    (args.output / "cross_validation_aggregate.json").write_text(
        json.dumps(aggregate, indent=2), encoding="utf-8"
    )
    print(json.dumps(aggregate, indent=2))
    print(f"cross-validation runs: {csv_path}")
    print("ChronoSafe paper nuScenes cross-validation: PASS")


if __name__ == "__main__":
    main()
