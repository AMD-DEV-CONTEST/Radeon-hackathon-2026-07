"""Calibrate the MRM threshold on frozen MetaDrive calibration seeds only."""

from __future__ import annotations

import argparse
import copy
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
        "--model",
        type=Path,
        default=Path("artifacts/hybrid_timing_gru_v3_timestamp_robust_seed2026/model.pt"),
    )
    parser.add_argument(
        "--candidates",
        default="0.62,0.68,0.74,0.80,0.86,0.92,0.96",
        help="Comma-separated minimal-risk thresholds evaluated on calibration seeds.",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("results/mrm_threshold_calibration")
    )
    parser.add_argument(
        "--log-dir", type=Path, default=Path("evidence/mrm_threshold_calibration")
    )
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def run_metrics(run_dir: Path, compound_onset: int) -> dict[str, object]:
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    with (run_dir / "closed_loop.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    first_mrm = next(
        (int(row["step"]) for row in rows if row["mode"] == "MINIMAL_RISK"), None
    )
    stop_step = (
        None
        if first_mrm is None
        else next(
            (
                int(row["step"])
                for row in rows
                if int(row["step"]) >= first_mrm and float(row["speed_km_h"]) <= 0.1
            ),
            None,
        )
    )
    final_speed = float(summary["final_speed_km_h"])
    reached = bool(summary["minimal_risk_reached"])
    return {
        "seed": int(summary["seed"]),
        "first_mrm_step": first_mrm,
        "trigger_delay_steps": None if first_mrm is None else first_mrm - compound_onset,
        "premature_mrm": first_mrm is not None and first_mrm < compound_onset,
        "mrm_reached": reached,
        "mrm_success": reached and final_speed <= 0.1,
        "stopping_steps": (
            None if first_mrm is None or stop_step is None else stop_step - first_mrm
        ),
        "final_speed_km_h": final_speed,
        "scenario_accuracy": float(summary["scenario_accuracy"]),
        "upper_risk_coverage": float(summary["upper_risk_coverage"]),
    }


def finite_mean(values: list[object]) -> float | None:
    selected = [float(value) for value in values if value is not None]
    return None if not selected else float(np.mean(selected))


def main() -> None:
    args = parse_args()
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    seeds = [int(value) for value in protocol["metadrive"]["calibration_seeds"]]
    closed_loop = protocol["closed_loop"]
    steps = int(closed_loop["steps"])
    compound_onset = steps * 5 // 7
    degraded_threshold = float(closed_loop["degraded_threshold"])
    candidates = sorted({float(value) for value in args.candidates.split(",")})
    if not candidates or any(
        not degraded_threshold < threshold <= 1.0 for threshold in candidates
    ):
        raise ValueError("Every MRM candidate must be above degraded threshold and at most 1")

    args.output.mkdir(parents=True, exist_ok=True)
    args.log_dir.mkdir(parents=True, exist_ok=True)
    candidate_summaries: list[dict[str, object]] = []
    for threshold_index, threshold in enumerate(candidates, start=1):
        threshold_name = f"threshold_{threshold:.3f}".replace(".", "p")
        runs: list[dict[str, object]] = []
        print(
            f"threshold {threshold_index}/{len(candidates)}: {threshold:.3f}", flush=True
        )
        for seed_index, seed in enumerate(seeds, start=1):
            run_dir = args.output / threshold_name / f"seed_{seed}"
            summary_path = run_dir / "summary.json"
            if args.resume and summary_path.is_file():
                print(f"  seed {seed_index}/{len(seeds)}: {seed} (reuse)", flush=True)
            else:
                print(f"  seed {seed_index}/{len(seeds)}: {seed}", flush=True)
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
                    str(degraded_threshold),
                    "--minimal-risk-threshold",
                    str(threshold),
                ]
                completed = subprocess.run(command, text=True, capture_output=True, check=False)
                log_text = completed.stdout + (
                    "\nSTDERR:\n" + completed.stderr if completed.stderr else ""
                )
                (args.log_dir / f"{threshold_name}_seed_{seed}.log").write_text(
                    log_text, encoding="utf-8"
                )
                if completed.returncode:
                    print(log_text)
                    raise RuntimeError(
                        f"MRM calibration failed at threshold={threshold:.3f}, seed={seed}"
                    )
            runs.append(run_metrics(run_dir, compound_onset))

        candidate = {
            "threshold": threshold,
            "seeds": seeds,
            "runs": runs,
            "mrm_success_rate": float(np.mean([run["mrm_success"] for run in runs])),
            "mrm_reached_rate": float(np.mean([run["mrm_reached"] for run in runs])),
            "premature_mrm_rate": float(
                np.mean([run["premature_mrm"] for run in runs])
            ),
            "mean_trigger_delay_steps": finite_mean(
                [run["trigger_delay_steps"] for run in runs]
            ),
            "mean_stopping_steps": finite_mean([run["stopping_steps"] for run in runs]),
            "mean_scenario_accuracy": finite_mean(
                [run["scenario_accuracy"] for run in runs]
            ),
            "mean_upper_risk_coverage": finite_mean(
                [run["upper_risk_coverage"] for run in runs]
            ),
        }
        candidate_summaries.append(candidate)
        print(
            "  "
            f"success={candidate['mrm_success_rate']:.3f} "
            f"premature={candidate['premature_mrm_rate']:.3f} "
            f"delay={candidate['mean_trigger_delay_steps']}",
            flush=True,
        )

    minimum_success = float(closed_loop["minimum_mrm_success_rate"])
    eligible = [
        candidate
        for candidate in candidate_summaries
        if float(candidate["mrm_success_rate"]) >= minimum_success
        and float(candidate["premature_mrm_rate"]) == 0.0
        and candidate["mean_trigger_delay_steps"] is not None
    ]
    selected = min(
        eligible,
        key=lambda candidate: (
            float(candidate["mean_trigger_delay_steps"]),
            float(candidate["threshold"]),
        ),
    ) if eligible else None
    result = {
        "protocol": str(args.protocol),
        "model": str(args.model),
        "selection_split": "MetaDrive calibration_seeds",
        "calibration_seeds": seeds,
        "compound_onset_step": compound_onset,
        "degraded_threshold": degraded_threshold,
        "minimum_mrm_success_rate": minimum_success,
        "candidate_summaries": candidate_summaries,
        "selection_valid": selected is not None,
        "selected_threshold": None if selected is None else selected["threshold"],
    }
    (args.output / "calibration.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    if selected is None:
        print(json.dumps(result, indent=2))
        raise RuntimeError("No candidate met the frozen MRM calibration constraints")

    selected_protocol = copy.deepcopy(protocol)
    selected_protocol["closed_loop"]["minimal_risk_threshold"] = selected["threshold"]
    selected_protocol["mrm_threshold_calibration"] = {
        "source": str(args.output / "calibration.json"),
        "selection_split": "MetaDrive calibration_seeds",
        "calibration_seeds": seeds,
        "selected_threshold": selected["threshold"],
    }
    (args.output / "selected_protocol.json").write_text(
        json.dumps(selected_protocol, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
    print(f"selected protocol: {args.output / 'selected_protocol.json'}")
    print("MRM threshold calibration: PASS")


if __name__ == "__main__":
    main()
