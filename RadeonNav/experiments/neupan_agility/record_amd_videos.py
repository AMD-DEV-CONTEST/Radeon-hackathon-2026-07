#!/usr/bin/env python3
"""Record the auditable AMD migration video suite."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import torch


ROOT = Path(__file__).resolve().parents[2]
SOURCE_RUNNER = ROOT / "experiments/neupan_agility/run_source_task.py"
NEUPAN_RUNNER = ROOT / "experiments/neupan_agility/run_dynamic_planner.py"
DEFAULT_PLANNER = ROOT / "experiments/neupan_agility/go2_planner.yaml"
DEFAULT_OUTPUT = (
    ROOT / "experiment-results/quadrupedal-agility/M-ROCM-VIDEOS"
)
DEFAULT_ENCODER = (
    ROOT
    / "experiment-results/quadrupedal-agility/M-ROCM-6-HISTDATA/TRAIN"
    / "ft1_depth_encoder_epoch6.pt"
)
TASKS = ("frame", "tunnel", "poles", "bar_jump", "tire_jump", "seesaw")
STACKS = ("released", "amd-student")
STACK_CHOICES = (*STACKS, "teacher")
COMMON_CHECKS = (
    "live_env_action_contract",
    "rollout_finite",
    "step_count",
    "video_created",
)


@dataclass(frozen=True)
class Recording:
    name: str
    kind: str
    stack: str
    task: str
    command: tuple[str, ...]
    output_dir: Path
    canonical_video: Path


def source_command(
    task: str,
    stack: str,
    checkpoint: Path,
    output_dir: Path,
    device: str,
    bar_height: float,
) -> tuple[str, ...]:
    command = [
        sys.executable,
        str(SOURCE_RUNNER),
        "--task",
        task,
        "--seed",
        "7",
        "--device",
        device,
        "--output-dir",
        str(output_dir),
    ]
    if task == "bar_jump":
        command.extend(("--bar-height", f"{bar_height:.2f}"))
    if stack in ("released", "teacher"):
        command.extend(
            (
                "--policy-profile",
                "source5",
                "--high-branch",
                "teacher",
                "--precision",
                "float32",
            )
        )
    else:
        command.extend(
            (
                "--policy-profile",
                "deployment3",
                "--high-branch",
                "student",
                "--precision",
                "float16",
                "--yaw-source",
                "waypoint",
                "--onehot-source",
                "gt",
                "--depth-encoder-checkpoint",
                str(checkpoint),
            )
        )
    return tuple(command)


def build_recordings(args: argparse.Namespace) -> list[Recording]:
    recordings = []
    if not args.neupan_only:
        stacks = STACKS if args.stack == "both" else (args.stack,)
        for stack in stacks:
            for task in args.tasks:
                task_variant = (
                    f"{task}_h{args.bar_height:.2f}"
                    if task == "bar_jump" and args.bar_height != 0.20
                    else task
                )
                output_dir = (
                    args.output_dir / f"tsc_bbc_{stack}" / task_variant
                )
                recordings.append(
                    Recording(
                        name=f"tsc_bbc_{stack}_{task_variant}",
                        kind="tsc_bbc_single_task",
                        stack=stack,
                        task=task,
                        command=source_command(
                            task,
                            stack,
                            args.checkpoint,
                            output_dir,
                            args.device,
                            args.bar_height,
                        ),
                        output_dir=output_dir,
                        canonical_video=output_dir / f"{task}_10s.mp4",
                    )
                )
    if args.include_neupan:
        output_dir = args.output_dir / "neupan_tire_avoidance"
        recordings.append(
            Recording(
                name="neupan_tire_avoidance",
                kind="neupan_tire_avoidance",
                stack="amd-student-low-level",
                task="tire-static",
                command=(
                    sys.executable,
                    str(NEUPAN_RUNNER),
                    "--arm",
                    "neupan",
                    "--layout",
                    "tire-static",
                    "--seed",
                    "7",
                    "--device",
                    args.device,
                    "--planner-config",
                    str(args.planner_config),
                    "--depth-encoder-checkpoint",
                    str(args.checkpoint),
                    "--output-dir",
                    str(output_dir),
                ),
                output_dir=output_dir,
                canonical_video=(
                    output_dir / "nag501_tire-static_neupan_s7.mp4"
                ),
            )
        )
    return recordings


def result_is_reusable(recording: Recording) -> bool:
    result_path = recording.output_dir / "result.json"
    if not result_path.is_file() or not recording.canonical_video.is_file():
        return False
    payload = json.loads(result_path.read_text())
    return "error" not in payload and all(
        payload.get("checks", {}).get(check, False) for check in COMMON_CHECKS
    )


def run_recording(recording: Recording, rerun: bool) -> tuple[str, str]:
    if not rerun and result_is_reusable(recording):
        payload = json.loads((recording.output_dir / "result.json").read_text())
        return recording.name, str(payload["status"])
    recording.output_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("MUJOCO_GL", "egl")
    completed = subprocess.run(
        recording.command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    result_path = recording.output_dir / "result.json"
    if not result_path.is_file():
        raise RuntimeError(
            f"{recording.name} produced no result\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    payload = json.loads(result_path.read_text())
    if "error" in payload:
        raise RuntimeError(f"{recording.name}: {payload['error']}")
    if not recording.canonical_video.is_file():
        raise RuntimeError(f"{recording.name}: missing canonical video")
    failed_checks = [
        check
        for check in COMMON_CHECKS
        if not payload.get("checks", {}).get(check, False)
    ]
    if failed_checks:
        raise RuntimeError(
            f"{recording.name}: runtime checks failed: {failed_checks}"
        )
    return recording.name, str(payload["status"])


def build_manifest(
    args: argparse.Namespace, recordings: list[Recording]
) -> dict:
    rows = []
    runtime_failures = []
    functional_failures = []
    device_names = set()
    for recording in recordings:
        result_path = recording.output_dir / "result.json"
        payload = json.loads(result_path.read_text())
        checks = payload.get("checks", {})
        video = payload.get("video", {})
        runtime_ok = all(checks.get(check, False) for check in COMMON_CHECKS)
        if recording.kind == "neupan_tire_avoidance":
            functional_success = bool(payload.get("episode_success"))
        else:
            functional_success = payload.get("status") == "PASSED"
        device_name = payload.get("device_name")
        if device_name is None and torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
        if device_name:
            device_names.add(str(device_name))
        row = {
            "name": recording.name,
            "kind": recording.kind,
            "stack": recording.stack,
            "task": recording.task,
            "bar_height_m": payload.get("contracts", {}).get(
                "bar_height_m"
            ),
            "policy_status": payload.get("status"),
            "functional_success": functional_success,
            "runtime_contract_passed": runtime_ok,
            "device_name": device_name,
            "neupan_runtime": payload.get("contracts", {}).get(
                "neupan_runtime"
            ),
            "result": str(result_path.relative_to(ROOT)),
            "video": str(recording.canonical_video.relative_to(ROOT)),
            "video_sha256": video.get("sha256"),
            "frames": video.get("frames"),
            "fps": video.get("fps"),
            "width": video.get("width"),
            "height": video.get("height"),
        }
        if not runtime_ok:
            runtime_failures.append(recording.name)
        if not functional_success:
            functional_failures.append(recording.name)
        rows.append(row)
    teacher_only = bool(recordings) and all(
        recording.stack == "teacher" for recording in recordings
    )
    teacher_bar_variant = (
        teacher_only
        and len(recordings) == 1
        and recordings[0].task == "bar_jump"
        and args.bar_height != 0.20
    )
    blocking_failures = list(runtime_failures)
    if args.require_policy_success:
        blocking_failures.extend(functional_failures)
    # NeuPAN's public wrapper is itself a functional single-task test, not a
    # best-effort recording suite, so its episode must always succeed.
    blocking_failures.extend(
        recording.name
        for recording in recordings
        if recording.kind == "neupan_tire_avoidance"
        and recording.name in functional_failures
    )
    manifest = {
        "run_id": (
            f"M-ROCM-VIDEOS-TEACHER-BAR-H{args.bar_height:.2f}"
            if teacher_bar_variant
            else (
                "M-ROCM-VIDEOS-TEACHER"
                if teacher_only
                else "M-ROCM-VIDEOS"
            )
        ),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASSED" if not blocking_failures else "FAILED",
        "scope": (
            f"AMD/ROCm UniLab TSC teacher + source5 BBC bar at "
            f"{args.bar_height:.2f} m"
            if teacher_bar_variant
            else (
                "AMD/ROCm UniLab independent TSC teacher + source5 BBC tasks"
                if teacher_only
                else "AMD/ROCm NeuPAN tire avoidance and independent TSC+BBC tasks"
            )
        ),
        "environment": {
            "torch_version": torch.__version__,
            "torch_hip_version": torch.version.hip,
            "torch_cuda_available": torch.cuda.is_available(),
            "device_names": sorted(device_names),
            "physical_nvidia_device_used": False,
        },
        "checkpoint": str(args.checkpoint),
        "planner_config": str(args.planner_config),
        "recording_count": len(rows),
        "require_policy_success": args.require_policy_success,
        "runtime_failures": sorted(set(runtime_failures)),
        "functional_failures": sorted(set(functional_failures)),
        "recordings": rows,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_ENCODER)
    parser.add_argument("--planner-config", type=Path, default=DEFAULT_PLANNER)
    parser.add_argument(
        "--stack", choices=(*STACK_CHOICES, "both"), default="both"
    )
    parser.add_argument("--tasks", nargs="+", choices=TASKS, default=TASKS)
    parser.add_argument("--bar-height", type=float, default=0.20)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--device", default="cuda")
    suite = parser.add_mutually_exclusive_group()
    suite.add_argument(
        "--no-neupan", dest="include_neupan", action="store_false"
    )
    suite.add_argument("--neupan-only", action="store_true")
    parser.add_argument("--rerun", action="store_true")
    parser.add_argument(
        "--require-policy-success",
        action="store_true",
        help="return failure unless every recorded policy completes its task",
    )
    args = parser.parse_args()
    args.output_dir = args.output_dir.resolve()
    args.checkpoint = args.checkpoint.resolve()
    args.planner_config = args.planner_config.resolve()
    if not args.checkpoint.is_file():
        parser.error(f"missing checkpoint: {args.checkpoint}")
    if not args.planner_config.is_file():
        parser.error(f"missing planner config: {args.planner_config}")
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if not 0.05 <= args.bar_height <= 0.30:
        parser.error("--bar-height must stay within [0.05, 0.30]")
    if "bar_jump" not in args.tasks and args.bar_height != 0.20:
        parser.error("--bar-height requires bar_jump in --tasks")
    if not torch.cuda.is_available() or torch.version.hip is None:
        parser.error("this recording suite requires an AMD ROCm torch runtime")
    full_suite = (
        args.stack == "both"
        and tuple(args.tasks) == TASKS
        and args.include_neupan
        and not args.neupan_only
    )
    if full_suite:
        manifest_name = "manifest.json"
    elif args.neupan_only:
        manifest_name = "manifest_neupan.json"
    elif (
        args.stack == "teacher"
        and tuple(args.tasks) == TASKS
        and args.bar_height == 0.20
        and not args.include_neupan
    ):
        manifest_name = "manifest_teacher.json"
    else:
        tasks = "-".join(args.tasks)
        height_suffix = (
            f"_h{args.bar_height:.2f}"
            if "bar_jump" in args.tasks and args.bar_height != 0.20
            else ""
        )
        suffix = "_plus_neupan" if args.include_neupan else ""
        manifest_name = (
            f"manifest_{args.stack}_{tasks}{height_suffix}{suffix}.json"
        )
    args.manifest_path = args.output_dir / manifest_name
    return args


def main() -> int:
    args = parse_args()
    recordings = build_recordings(args)
    failures = []
    complete = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(run_recording, recording, args.rerun): recording
            for recording in recordings
        }
        for future in concurrent.futures.as_completed(futures):
            recording = futures[future]
            try:
                name, status = future.result()
            except Exception as exc:  # preserve all independent recordings
                failures.append(recording.name)
                print(f"TECHNICAL_FAILURE {exc}", flush=True)
                continue
            complete += 1
            print(
                f"RECORDED {name} policy_status={status} "
                f"progress={complete}/{len(recordings)}",
                flush=True,
            )
    if failures:
        print("FAILED_RECORDINGS " + " ".join(sorted(failures)), flush=True)
        return 1
    manifest = build_manifest(args, recordings)
    print(
        f"MANIFEST {manifest['status']}: {args.manifest_path}",
        flush=True,
    )
    return 0 if manifest["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
