"""Failure-aware, episode-level retry evaluation for mobile manipulation."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
import sys
import time

from .mjcf_batch_evaluation import classify_trial
from .mjcf_mobile_pipeline import OBJECT_PROFILES
from .spatial_tasks import SEMANTIC_DOCKS


@dataclass(frozen=True)
class RecoveryAction:
    name: str
    grasp_z_offset_m: float = 0.0
    grip_preload_m: float = 0.0
    grip_preload_steps: int = 1
    transport_steps: int = 300


BASELINE_ACTION = RecoveryAction("baseline")


def select_recovery_action(failure: str, retry_index: int) -> RecoveryAction:
    """Choose a bounded, auditable adjustment from the observed failure stage."""
    if retry_index < 1:
        return BASELINE_ACTION
    if failure == "grasp_failure":
        return (
            RecoveryAction("lower_grasp", grasp_z_offset_m=-0.005)
            if retry_index == 1
            else RecoveryAction("raise_grasp", grasp_z_offset_m=0.005)
        )
    if failure == "payload_lost":
        return (
            RecoveryAction(
                "lower_grasp_light_preload_slow_transport",
                grasp_z_offset_m=-0.005,
                grip_preload_m=0.0003,
                grip_preload_steps=120,
                transport_steps=400,
            )
            if retry_index == 1
            else RecoveryAction(
                "raise_grasp_slowest_transport",
                grasp_z_offset_m=0.005,
                transport_steps=450,
            )
        )
    if failure == "placement_failure":
        return RecoveryAction(
            "slower_delivery_retry",
            transport_steps=400 if retry_index == 1 else 450,
        )
    return RecoveryAction(f"repeat_after_{failure}")


def run_recovery_evaluation(
    *,
    seeds: list[int],
    object_profiles: list[str],
    output_dir: Path,
    reference_root: Path | None,
    source_zone: str,
    target_zone: str,
    max_retries: int,
    navigation_steps: int,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for object_profile in object_profiles:
        for seed in seeds:
            task_dir = output_dir / f"{object_profile}-seed-{seed}"
            attempts = []
            failure = "initial"
            final_result = None
            for attempt_index in range(max_retries + 1):
                action = (
                    BASELINE_ACTION
                    if attempt_index == 0
                    else select_recovery_action(failure, attempt_index)
                )
                attempt_dir = task_dir / f"attempt-{attempt_index}"
                result_path = attempt_dir / "mobile_mjcf_pipeline_result.json"
                log_path = task_dir / f"attempt-{attempt_index}.log"
                command = [
                    sys.executable,
                    "-m",
                    "radeon_home.mjcf_mobile_pipeline",
                    "--seed",
                    str(seed),
                    "--object-profile",
                    object_profile,
                    "--source-zone",
                    source_zone,
                    "--target-zone",
                    target_zone,
                    "--output-dir",
                    str(attempt_dir),
                    "--navigation-steps",
                    str(navigation_steps),
                    "--transport-steps",
                    str(action.transport_steps),
                    "--grasp-z-offset-m",
                    str(action.grasp_z_offset_m),
                    "--grip-preload-m",
                    str(action.grip_preload_m),
                    "--grip-preload-steps",
                    str(action.grip_preload_steps),
                    "--no-video",
                ]
                if reference_root is not None:
                    command.extend(["--reference-root", str(reference_root)])
                attempt_dir.mkdir(parents=True, exist_ok=True)
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
                    failure = classify_trial(result)
                    final_result = result
                else:
                    failure = "execution_failure"
                    result = None
                attempts.append(
                    {
                        "attempt_index": attempt_index,
                        "action": asdict(action),
                        "outcome": failure,
                        "runtime_s": runtime_s,
                        "returncode": completed.returncode,
                        "result": str(result_path),
                        "log": str(log_path),
                    }
                )
                print(
                    f"object={object_profile} seed={seed} "
                    f"attempt={attempt_index} action={action.name} "
                    f"outcome={failure}",
                    flush=True,
                )
                if failure == "success":
                    break

            tasks.append(
                {
                    "object_profile": object_profile,
                    "seed": seed,
                    "recovered": (
                        bool(final_result and final_result.get("transport_success"))
                        and len(attempts) > 1
                    ),
                    "final_success": bool(
                        final_result and final_result.get("transport_success")
                    ),
                    "attempts": attempts,
                }
            )
            summary = _summarize(tasks, max_retries)
            (output_dir / "recovery_summary.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8"
            )
    summary = _summarize(tasks, max_retries)
    print(json.dumps(summary, indent=2))
    return summary


def _summarize(tasks: list[dict], max_retries: int) -> dict:
    return {
        "task_count": len(tasks),
        "baseline_successes": sum(
            task["attempts"][0]["outcome"] == "success" for task in tasks
        ),
        "recovered_tasks": sum(task["recovered"] for task in tasks),
        "final_successes": sum(task["final_success"] for task in tasks),
        "final_success_rate": (
            sum(task["final_success"] for task in tasks) / len(tasks)
            if tasks
            else 0.0
        ),
        "total_attempts": sum(len(task["attempts"]) for task in tasks),
        "max_retries": max_retries,
        "recovery_scope": (
            "episode-level retry: each attempt rebuilds the same seeded scene; "
            "no object attachment or result substitution"
        ),
        "tasks": tasks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate failure-aware retries for the physical MJCF pipeline"
    )
    parser.add_argument("--seeds", nargs="+", type=int, required=True)
    parser.add_argument(
        "--object-profiles",
        nargs="+",
        choices=sorted(OBJECT_PROFILES),
        required=True,
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument(
        "--source-zone",
        choices=sorted(SEMANTIC_DOCKS),
        default="bedside_table",
    )
    parser.add_argument(
        "--target-zone",
        choices=sorted(SEMANTIC_DOCKS),
        default="coffee_table",
    )
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--navigation-steps", type=int, default=40)
    args = parser.parse_args()
    if args.max_retries < 0:
        parser.error("--max-retries cannot be negative")
    run_recovery_evaluation(
        seeds=args.seeds,
        object_profiles=args.object_profiles,
        output_dir=args.output_dir,
        reference_root=args.reference_root,
        source_zone=args.source_zone,
        target_zone=args.target_zone,
        max_retries=args.max_retries,
        navigation_steps=args.navigation_steps,
    )


if __name__ == "__main__":
    main()
