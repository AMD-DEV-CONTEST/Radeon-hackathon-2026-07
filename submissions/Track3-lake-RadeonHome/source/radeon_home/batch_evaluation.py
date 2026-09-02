"""Run and aggregate multiple end-to-end mobile manipulation trials."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def aggregate_results(results: list[dict], failures: list[dict]) -> dict:
    attempted = len(results) + len(failures)
    successes = [item for item in results if item.get("transport_success")]
    retries = [item for item in results if item.get("retry_count", 0) > 0]

    def mean(key: str) -> float | None:
        values = [float(item[key]) for item in results if key in item]
        return sum(values) / len(values) if values else None

    return {
        "attempted_trials": attempted,
        "completed_trials": len(results),
        "successful_trials": len(successes),
        "execution_failures": len(failures),
        "transport_success_rate": len(successes) / attempted if attempted else 0.0,
        "retry_trial_count": len(retries),
        "retry_rate": len(retries) / len(results) if results else 0.0,
        "mean_pickup_dock_error_m": mean("dock_error_m"),
        "mean_delivery_dock_error_m": mean("delivery_dock_error_m"),
        "mean_place_xy_error_m": mean("place_xy_error_m"),
        "trials": results,
        "failures": failures,
    }


def run_batch(
    *, seeds: list[int], output_dir: Path, grasp_latch: bool = False
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    failures: list[dict] = []
    for seed in seeds:
        trial_dir = output_dir / f"seed-{seed}"
        log_path = output_dir / f"seed-{seed}.log"
        command = [
            sys.executable,
            "-m",
            "radeon_home.mobile_grasp",
            "--seed",
            str(seed),
            "--output-dir",
            str(trial_dir),
        ]
        if grasp_latch:
            command.append("--grasp-latch")
        with log_path.open("w", encoding="utf-8") as log:
            completed = subprocess.run(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        result_path = trial_dir / "mobile_grasp_result.json"
        if completed.returncode == 0 and result_path.exists():
            results.append(json.loads(result_path.read_text(encoding="utf-8")))
        else:
            failures.append(
                {
                    "seed": seed,
                    "returncode": completed.returncode,
                    "log": str(log_path),
                }
            )
    summary = aggregate_results(results, failures)
    (output_dir / "batch_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch mobile manipulation evaluation")
    parser.add_argument("--seeds", nargs="+", type=int, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs/mobile-batch")
    )
    parser.add_argument("--grasp-latch", action="store_true")
    args = parser.parse_args()
    run_batch(
        seeds=args.seeds,
        output_dir=args.output_dir,
        grasp_latch=args.grasp_latch,
    )


if __name__ == "__main__":
    main()
