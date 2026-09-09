"""Run the frozen closed-loop protocol across all external MetaDrive domains."""

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
    parser.add_argument("--model", type=Path, default=Path("artifacts/hybrid_timing_gru_v2/model.pt"))
    parser.add_argument("--output", type=Path, default=Path("results/paper_multiseed_closed_loop"))
    parser.add_argument("--log-dir", type=Path, default=Path("evidence/paper_multiseed_closed_loop"))
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def bootstrap_interval(
    values: list[float],
    resamples: int,
    confidence: float,
    rng: np.random.Generator,
) -> list[float]:
    array = np.asarray(values, dtype=np.float64)
    if not len(array):
        return [float("nan"), float("nan")]
    indices = rng.integers(0, len(array), size=(resamples, len(array)))
    means = array[indices].mean(axis=1)
    tail = (1.0 - confidence) / 2.0
    return [float(np.quantile(means, tail)), float(np.quantile(means, 1.0 - tail))]


def load_run_metrics(run_dir: Path, compound_onset: int) -> dict[str, object]:
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    with (run_dir / "closed_loop.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    first_degraded = next(
        (int(row["step"]) for row in rows if row["mode"] == "DEGRADED"), None
    )
    first_mrm = next(
        (int(row["step"]) for row in rows if row["mode"] == "MINIMAL_RISK"), None
    )
    stop_step = None
    if first_mrm is not None:
        stop_step = next(
            (
                int(row["step"])
                for row in rows
                if int(row["step"]) >= first_mrm and float(row["speed_km_h"]) <= 0.1
            ),
            None,
        )
    steps = int(summary["steps"])
    mode_counts = summary["mode_counts"]
    final_speed = float(summary["final_speed_km_h"])
    reached = bool(summary["minimal_risk_reached"])
    return {
        "seed": int(summary["seed"]),
        "scenario_accuracy": float(summary["scenario_accuracy"]),
        "risk_mae": float(summary["risk_mae"]),
        "upper_risk_coverage": float(summary["upper_risk_coverage"]),
        "first_degraded_step": first_degraded,
        "first_mrm_step": first_mrm,
        "compound_onset_step": compound_onset,
        "mrm_trigger_delay_steps": None if first_mrm is None else first_mrm - compound_onset,
        "premature_mrm": first_mrm is not None and first_mrm < compound_onset,
        "mrm_reached": reached,
        "mrm_success": reached and final_speed <= 0.1,
        "stop_step": stop_step,
        "stopping_steps": None if first_mrm is None or stop_step is None else stop_step - first_mrm,
        "final_speed_km_h": final_speed,
        "normal_fraction": int(mode_counts["NORMAL"]) / steps,
        "degraded_fraction": int(mode_counts["DEGRADED"]) / steps,
        "minimal_risk_fraction": int(mode_counts["MINIMAL_RISK"]) / steps,
    }


def metric_summary(
    runs: list[dict[str, object]],
    key: str,
    resamples: int,
    confidence: float,
    rng: np.random.Generator,
) -> dict[str, object]:
    values = [float(run[key]) for run in runs if run[key] is not None]
    array = np.asarray(values, dtype=np.float64)
    return {
        "count": len(values),
        "mean": round(float(array.mean()), 6),
        "std": round(float(array.std(ddof=1)), 6) if len(array) > 1 else 0.0,
        "ci95": [round(value, 6) for value in bootstrap_interval(values, resamples, confidence, rng)],
        "min": round(float(array.min()), 6),
        "max": round(float(array.max()), 6),
    }


def main() -> None:
    args = parse_args()
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    seeds = [int(value) for value in protocol["metadrive"]["external_closed_loop_seeds"]]
    closed_loop = protocol["closed_loop"]
    steps = int(closed_loop["steps"])
    compound_onset = steps * 5 // 7
    args.output.mkdir(parents=True, exist_ok=True)
    args.log_dir.mkdir(parents=True, exist_ok=True)
    run_metrics: list[dict[str, object]] = []

    for index, seed in enumerate(seeds, start=1):
        run_dir = args.output / f"seed_{seed}"
        summary_path = run_dir / "summary.json"
        if args.resume and summary_path.is_file():
            print(f"seed {index}/{len(seeds)}: {seed} (reuse)", flush=True)
        else:
            print(f"seed {index}/{len(seeds)}: {seed}", flush=True)
            command = [
                sys.executable,
                "scripts/run_compositional_closed_loop.py",
                "--model",
                str(args.model),
                "--output",
                str(run_dir),
                "--steps",
                str(steps),
                "--seed",
                str(seed),
                "--warmup-steps",
                str(closed_loop["warmup_steps"]),
                "--degraded-threshold",
                str(closed_loop["degraded_threshold"]),
                "--minimal-risk-threshold",
                str(closed_loop["minimal_risk_threshold"]),
            ]
            completed = subprocess.run(command, text=True, capture_output=True, check=False)
            log_text = completed.stdout + ("\nSTDERR:\n" + completed.stderr if completed.stderr else "")
            (args.log_dir / f"seed_{seed}.log").write_text(log_text, encoding="utf-8")
            if completed.returncode:
                print(log_text)
                raise RuntimeError(f"Closed-loop run failed for frozen seed {seed}")
        metric = load_run_metrics(run_dir, compound_onset)
        run_metrics.append(metric)
        print(
            f"  accuracy={metric['scenario_accuracy']:.4f} "
            f"coverage={metric['upper_risk_coverage']:.4f} "
            f"mrm={metric['first_mrm_step']} final_speed={metric['final_speed_km_h']:.4f}",
            flush=True,
        )

    csv_path = args.output / "per_seed_metrics.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(run_metrics[0]))
        writer.writeheader()
        writer.writerows(run_metrics)

    statistics = protocol["statistics"]
    resamples = int(statistics["bootstrap_resamples"])
    confidence = float(statistics["confidence_level"])
    rng = np.random.default_rng(2026)
    aggregate_keys = (
        "scenario_accuracy",
        "risk_mae",
        "upper_risk_coverage",
        "mrm_trigger_delay_steps",
        "stopping_steps",
        "final_speed_km_h",
        "normal_fraction",
        "degraded_fraction",
        "minimal_risk_fraction",
    )
    aggregate = {
        "protocol": str(args.protocol),
        "model": str(args.model),
        "seeds": seeds,
        "runs": len(run_metrics),
        "compound_onset_step": compound_onset,
        "mrm_success_rate": round(float(np.mean([run["mrm_success"] for run in run_metrics])), 6),
        "premature_mrm_rate": round(
            float(np.mean([run["premature_mrm"] for run in run_metrics])), 6
        ),
        "mrm_reached_rate": round(float(np.mean([run["mrm_reached"] for run in run_metrics])), 6),
        "metrics": {
            key: metric_summary(run_metrics, key, resamples, confidence, rng)
            for key in aggregate_keys
        },
    }
    (args.output / "aggregate.json").write_text(json.dumps(aggregate, indent=2), encoding="utf-8")
    print(json.dumps(aggregate, indent=2))
    print(f"per-seed metrics: {csv_path}")
    print("ChronoSafe paper multi-seed closed-loop: PASS")


if __name__ == "__main__":
    main()
