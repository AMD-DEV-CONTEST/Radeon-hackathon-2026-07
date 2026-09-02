"""Run resumable multi-seed evaluation of the physical mobile MJCF pipeline."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from .mjcf_mobile_pipeline import OBJECT_PROFILES
from .spatial_tasks import SEMANTIC_DOCKS


def wilson_interval(successes: int, trials: int, z: float = 1.959964) -> list[float]:
    """Return the two-sided 95% Wilson score interval for a binomial rate."""
    if trials == 0:
        return [0.0, 0.0]
    rate = successes / trials
    denominator = 1.0 + z * z / trials
    centre = (rate + z * z / (2.0 * trials)) / denominator
    margin = (
        z
        * math.sqrt(
            rate * (1.0 - rate) / trials + z * z / (4.0 * trials * trials)
        )
        / denominator
    )
    return [max(0.0, centre - margin), min(1.0, centre + margin)]


def _nested(result: dict, *path: str):
    value = result
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def classify_trial(result: dict) -> str:
    if result.get("transport_success"):
        return "success"
    if not result.get("grasp_success"):
        return "grasp_failure"
    if result.get("payload_lost_during_transport"):
        return "payload_lost"
    if not result.get("place_success"):
        return "placement_failure"
    return "unclassified_failure"


def aggregate_results(results: list[dict], execution_failures: list[dict]) -> dict:
    attempted = len(results) + len(execution_failures)
    successes = sum(bool(item.get("transport_success")) for item in results)
    grasps = sum(bool(item.get("grasp_success")) for item in results)
    retained = sum(
        bool(item.get("grasp_success"))
        and not bool(item.get("payload_lost_during_transport"))
        for item in results
    )
    placements = sum(bool(item.get("place_success")) for item in results)

    def mean(path: tuple[str, ...]) -> float | None:
        values = [_nested(item, *path) for item in results]
        numeric = [float(value) for value in values if value is not None]
        return sum(numeric) / len(numeric) if numeric else None

    outcome_counts = Counter(classify_trial(item) for item in results)
    if execution_failures:
        outcome_counts["execution_failure"] = len(execution_failures)
    object_names = sorted(
        {
            str(_nested(item, "task", "physical_object"))
            for item in results
            if _nested(item, "task", "physical_object") is not None
        }
        | {
            str(item["object_profile"])
            for item in execution_failures
            if item.get("object_profile") is not None
        }
    )
    per_object = {}
    for name in object_names:
        object_results = [
            item
            for item in results
            if _nested(item, "task", "physical_object") == name
        ]
        object_failures = [
            item for item in execution_failures if item.get("object_profile") == name
        ]
        object_attempted = len(object_results) + len(object_failures)
        object_successes = sum(
            bool(item.get("transport_success")) for item in object_results
        )
        object_outcomes = Counter(classify_trial(item) for item in object_results)
        if object_failures:
            object_outcomes["execution_failure"] = len(object_failures)
        per_object[name] = {
            "attempted_trials": object_attempted,
            "successful_trials": object_successes,
            "transport_success_rate": (
                object_successes / object_attempted if object_attempted else 0.0
            ),
            "transport_success_wilson_95": wilson_interval(
                object_successes, object_attempted
            ),
            "outcome_counts": dict(sorted(object_outcomes.items())),
        }

    return {
        "attempted_trials": attempted,
        "completed_trials": len(results),
        "successful_trials": successes,
        "transport_success_rate": successes / attempted if attempted else 0.0,
        "transport_success_wilson_95": wilson_interval(successes, attempted),
        "grasp_success_rate": grasps / attempted if attempted else 0.0,
        "payload_retention_rate": retained / attempted if attempted else 0.0,
        "place_success_rate": placements / attempted if attempted else 0.0,
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "per_object": per_object,
        "mean_transform_error_m": mean(
            ("coordinate_transforms", "transform_error_m")
        ),
        "mean_pickup_dock_error_m": mean(
            ("navigation", "pickup_error_m")
        ),
        "mean_delivery_dock_error_m": mean(
            ("navigation", "delivery_error_m")
        ),
        "mean_object_lift_m": mean(("manipulation", "object_lift_m")),
        "mean_place_horizontal_error_m": mean(
            ("manipulation", "placement_metrics", "horizontal_error_m")
        ),
        "mean_trial_runtime_s": mean(("evaluation", "runtime_s")),
        "trials": results,
        "execution_failures": execution_failures,
    }


def run_batch(
    *,
    seeds: list[int],
    object_profiles: list[str],
    output_dir: Path,
    reference_root: Path | None,
    source_zone: str | None,
    target_zone: str | None,
    navigation_steps: int,
    transport_steps: int,
    carry_mode: str,
    slip_monitoring: bool,
    record_video: bool,
    resume: bool,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    failures: list[dict] = []
    trials = [
        (object_profile, seed)
        for object_profile in object_profiles
        for seed in seeds
    ]
    for index, (object_profile, seed) in enumerate(trials, start=1):
        trial_dir = output_dir / f"{object_profile}-seed-{seed}"
        result_path = trial_dir / "mobile_mjcf_pipeline_result.json"
        log_path = output_dir / f"{object_profile}-seed-{seed}.log"
        if resume and result_path.is_file():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result.setdefault("evaluation", {})["resumed"] = True
            results.append(result)
            print(
                f"[{index}/{len(trials)}] object={object_profile} "
                f"seed={seed} resumed",
                flush=True,
            )
            continue

        command = [
            sys.executable,
            "-m",
            "radeon_home.mjcf_mobile_pipeline",
            "--output-dir",
            str(trial_dir),
            "--seed",
            str(seed),
            "--object-profile",
            object_profile,
            "--navigation-steps",
            str(navigation_steps),
            "--transport-steps",
            str(transport_steps),
            "--carry-mode",
            carry_mode,
        ]
        if not record_video:
            command.append("--no-video")
        if not slip_monitoring:
            command.append("--disable-slip-monitoring")
        if reference_root is not None:
            command.extend(["--reference-root", str(reference_root)])
        if source_zone is not None:
            command.extend(["--source-zone", source_zone])
        if target_zone is not None:
            command.extend(["--target-zone", target_zone])
        print(
            f"[{index}/{len(trials)}] object={object_profile} "
            f"seed={seed} running",
            flush=True,
        )
        started = time.monotonic()
        with log_path.open("w", encoding="utf-8") as log:
            completed = subprocess.run(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        runtime_s = time.monotonic() - started
        if completed.returncode == 0 and result_path.is_file():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["evaluation"] = {
                "runtime_s": runtime_s,
                "log": str(log_path),
                "resumed": False,
            }
            results.append(result)
            print(
                f"[{index}/{len(trials)}] object={object_profile} seed={seed} "
                f"outcome={classify_trial(result)} runtime={runtime_s:.1f}s",
                flush=True,
            )
        else:
            failures.append(
                {
                    "seed": seed,
                    "object_profile": object_profile,
                    "returncode": completed.returncode,
                    "runtime_s": runtime_s,
                    "log": str(log_path),
                }
            )
            print(
                f"[{index}/{len(trials)}] object={object_profile} seed={seed} "
                f"execution_failure={completed.returncode}",
                flush=True,
            )

        summary = aggregate_results(results, failures)
        summary["benchmark"] = {
            "seeds": seeds,
            "object_profiles": object_profiles,
            "source_zone": source_zone,
            "target_zone": target_zone,
            "navigation_steps": navigation_steps,
            "transport_steps": transport_steps,
            "carry_mode": carry_mode,
            "slip_monitoring": slip_monitoring,
            "video_recording": record_video,
            "pipeline": "single_scene_planar_mjcf_physical_contact",
        }
        (output_dir / "batch_summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )

    summary = aggregate_results(results, failures)
    summary["benchmark"] = {
        "seeds": seeds,
        "object_profiles": object_profiles,
        "source_zone": source_zone,
        "target_zone": target_zone,
        "navigation_steps": navigation_steps,
        "transport_steps": transport_steps,
        "carry_mode": carry_mode,
        "slip_monitoring": slip_monitoring,
        "video_recording": record_video,
        "pipeline": "single_scene_planar_mjcf_physical_contact",
    }
    (output_dir / "batch_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch-evaluate the physical mobile MJCF pipeline"
    )
    seed_group = parser.add_mutually_exclusive_group(required=True)
    seed_group.add_argument("--seeds", nargs="+", type=int)
    seed_group.add_argument("--start-seed", type=int)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument(
        "--object-profiles",
        nargs="+",
        choices=sorted(OBJECT_PROFILES),
        default=["parcel_medium"],
    )
    parser.add_argument("--source-zone", choices=sorted(SEMANTIC_DOCKS))
    parser.add_argument("--target-zone", choices=sorted(SEMANTIC_DOCKS))
    parser.add_argument("--navigation-steps", type=int, default=40)
    parser.add_argument("--transport-steps", type=int, default=300)
    parser.add_argument(
        "--carry-mode",
        choices=("auto", "lifted", "body_centered"),
        default="auto",
    )
    parser.add_argument(
        "--disable-slip-monitoring",
        action="store_true",
        help="Ablation only: disable continuous transport slip monitoring.",
    )
    parser.add_argument(
        "--record-video",
        action="store_true",
        help="Record each trial instead of using the faster metrics-only path.",
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be at least 1")
    seeds = (
        args.seeds
        if args.seeds is not None
        else list(range(args.start_seed, args.start_seed + args.count))
    )
    run_batch(
        seeds=seeds,
        object_profiles=args.object_profiles,
        output_dir=args.output_dir,
        reference_root=args.reference_root,
        source_zone=args.source_zone,
        target_zone=args.target_zone,
        navigation_steps=args.navigation_steps,
        transport_steps=args.transport_steps,
        carry_mode=args.carry_mode,
        slip_monitoring=not args.disable_slip_monitoring,
        record_video=args.record_video,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()
