#!/usr/bin/env python3
"""Run a frozen pure-PI0.5 LIBERO phase with Radeon telemetry."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


DEFAULT_LEROBOT_ROOT = Path("/workspace/parcel-sorter-rocm/third_party/lerobot")
DEFAULT_OVERLAY = Path("/workspace/libero-overlay")
LIBERO_SUITES = ("libero_spatial", "libero_object", "libero_goal", "libero_10")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    recorded_hash = payload.pop("manifest_sha256")
    actual_hash = canonical_sha256(payload)
    payload["manifest_sha256"] = recorded_hash
    if actual_hash != recorded_hash:
        raise RuntimeError(f"manifest hash mismatch: {actual_hash} != {recorded_hash}")
    return payload


def checkpoint_integrity(
    checkpoint: Path,
    *,
    expected_size: int,
    expected_sha256: str,
    verify_hash: bool,
) -> dict[str, Any]:
    required = [
        "config.json",
        "model.safetensors",
        "policy_preprocessor.json",
        "policy_postprocessor.json",
    ]
    missing = [name for name in required if not (checkpoint / name).is_file()]
    if missing:
        raise FileNotFoundError(f"checkpoint is missing required files: {missing}")
    weights = checkpoint / "model.safetensors"
    size = weights.stat().st_size
    if size != expected_size:
        raise RuntimeError(f"model size mismatch: {size} != {expected_size}")
    actual_hash = sha256_file(weights) if verify_hash else None
    if actual_hash is not None and actual_hash != expected_sha256:
        raise RuntimeError(f"model SHA-256 mismatch: {actual_hash} != {expected_sha256}")
    return {
        "path": str(checkpoint.resolve()),
        "model_bytes": size,
        "model_sha256": actual_hash,
        "hash_verified": verify_hash,
    }


def lerobot_source_integrity(
    manifest: dict[str, Any],
    lerobot_root: Path,
) -> dict[str, Any]:
    source_root = lerobot_root / "src" / "lerobot"
    expected = manifest["sources"]["lerobot_source_hashes"]
    actual: dict[str, str] = {}
    mismatches: dict[str, dict[str, str | None]] = {}
    for relative_path, expected_sha256 in expected.items():
        path = source_root / relative_path
        actual_sha256 = sha256_file(path) if path.is_file() else None
        if actual_sha256 is not None:
            actual[relative_path] = actual_sha256
        if actual_sha256 != expected_sha256:
            mismatches[relative_path] = {
                "expected_sha256": str(expected_sha256),
                "actual_sha256": actual_sha256,
            }
    if mismatches:
        raise RuntimeError(f"LeRobot source hash mismatch: {mismatches}")
    return {
        "root": str(source_root.resolve()),
        "verified_files": actual,
    }


def validate_eval_measurements(eval_info: dict[str, Any]) -> dict[str, Any]:
    overall = eval_info.get("overall") or {}
    timing = overall.get("policy_timing") or {}
    select_action = timing.get("select_action_calls") or {}
    model_inference = timing.get("model_inference_calls") or {}
    queued_dispatch = timing.get("queued_action_dispatch_calls") or {}
    memory = overall.get("accelerator_memory") or {}
    errors: list[str] = []
    select_count = int(select_action.get("count", 0))
    inference_count = int(model_inference.get("count", 0))
    queued_count = int(queued_dispatch.get("count", 0))
    if select_count <= 0:
        errors.append("no policy.select_action calls were timed")
    if inference_count <= 0:
        errors.append("no full model inference calls were detected")
    if select_count != inference_count + queued_count:
        errors.append("timing call partition is inconsistent")
    if int(timing.get("queue_observed_calls", 0)) != select_count:
        errors.append("PI0.5 action queue was not observed for every policy call")
    for name, value in {
        "model warm p50": model_inference.get("warm_p50_ms"),
        "model warm p95": model_inference.get("warm_p95_ms"),
        "model warm p99": model_inference.get("warm_p99_ms"),
    }.items():
        if inference_count > 1 and (value is None or float(value) <= 0):
            errors.append(f"{name} is missing or non-positive")
    if not bool(memory.get("available")):
        errors.append("accelerator memory telemetry is unavailable")
    if not memory.get("torch_hip_version"):
        errors.append("PyTorch HIP runtime was not detected")
    if int(memory.get("peak_allocated_bytes") or 0) <= 0:
        errors.append("peak allocated VRAM is missing or non-positive")
    if errors:
        raise RuntimeError("invalid LIBERO inference measurements: " + "; ".join(errors))
    return {
        "status": "passed",
        "select_action_calls": select_count,
        "model_inference_calls": inference_count,
        "queued_action_dispatch_calls": queued_count,
        "peak_allocated_bytes": int(memory["peak_allocated_bytes"]),
    }


def validate_executable_schedule(
    manifest: dict[str, Any],
    scope: dict[str, Any],
) -> None:
    if scope["phase"] in {"wiring", "efficiency"}:
        return
    if scope["phase"] == "endurance":
        protocol = manifest["experimental_design"].get("run_order_protocol", {}).get(
            "radeon_soak"
        )
        if protocol != "lerobot-interleaved-task-repeat-v1":
            raise RuntimeError(f"unsupported Radeon soak run-order protocol: {protocol!r}")
        soak = manifest["experimental_design"]["radeon_soak"]
        expected = [
            (suite, task_id, int(soak["init_state_id"]), repetition)
            for repetition in range(int(soak["repetitions_per_task"]))
            for suite in scope["suites"]
            for task_id in range(10)
        ]
        records = sorted(
            manifest["run_schedule"]["radeon_soak"],
            key=lambda record: int(record["run_order"]),
        )
        actual = [
            (
                str(record["suite"]),
                int(record["task_id"]),
                int(record["init_state_id"]),
                int(record["repetition"]),
            )
            for record in records
        ]
        if actual != expected:
            raise RuntimeError("Radeon soak schedule does not match the interleaved evaluator")
        return
    phase = str(scope["phase"])
    protocol = manifest["experimental_design"].get("run_order_protocol", {}).get(phase)
    if protocol != "lerobot-suite-task-init-state-v1":
        raise RuntimeError(f"unsupported {phase} run-order protocol: {protocol!r}")

    init_state_ids = manifest["experimental_design"][phase]["init_state_ids"]
    task_ids = range(10) if scope["task_ids"] is None else scope["task_ids"]
    expected = [
        (suite, task_id, init_state_id)
        for suite in scope["suites"]
        for task_id in task_ids
        for init_state_id in init_state_ids
    ]
    records = sorted(
        manifest["run_schedule"][phase],
        key=lambda record: int(record["run_order"]),
    )
    actual = [
        (str(record["suite"]), int(record["task_id"]), int(record["init_state_id"]))
        for record in records
    ]
    if actual != expected:
        raise RuntimeError(
            f"{phase} manifest order cannot be executed by the LeRobot task-major runner"
        )


def resolve_run_scope(args: argparse.Namespace, manifest: dict[str, Any]) -> dict[str, Any]:
    if args.phase == "wiring":
        init_state_ids = manifest["experimental_design"]["development"]["init_state_ids"]
        episodes = 1 if args.episodes is None else args.episodes
        if episodes not in (1, 3):
            raise ValueError("wiring runs must use exactly 1 or 3 development episodes")
        if args.wiring_suite not in LIBERO_SUITES:
            raise ValueError(f"unknown wiring suite {args.wiring_suite!r}")
        if not 0 <= args.wiring_task_id < 10:
            raise ValueError("wiring_task_id must be in [0, 9]")
        return {
            "phase": "wiring",
            "suites": [args.wiring_suite],
            "task_ids": [args.wiring_task_id],
            "init_state_offset": init_state_ids[0],
            "episodes_per_task": episodes,
            "may_drive_model_selection": True,
            "score_eligible": False,
            "claim_boundary": "Pure-VLA wiring only; never a benchmark or confirmation score.",
        }

    if args.phase == "efficiency":
        init_state_ids = manifest["experimental_design"]["development"]["init_state_ids"]
        if args.episodes is not None and args.episodes != 1:
            raise ValueError("efficiency runs use exactly one development state per task")
        return {
            "phase": "efficiency",
            "suites": list(LIBERO_SUITES),
            "task_ids": None,
            "init_state_offset": init_state_ids[0],
            "episodes_per_task": 1,
            "may_drive_model_selection": True,
            "score_eligible": False,
            "claim_boundary": (
                "Paired Radeon runtime ablation on development states; never a public benchmark score."
            ),
        }

    if args.phase == "endurance":
        soak = manifest["experimental_design"]["radeon_soak"]
        if args.episodes is not None and args.episodes != int(soak["repetitions_per_task"]):
            raise ValueError("endurance episode override violates the frozen soak contract")
        return {
            "phase": "endurance",
            "suites": list(LIBERO_SUITES),
            "task_ids": None,
            "init_state_offset": int(soak["init_state_id"]),
            "episodes_per_task": int(soak["repetitions_per_task"]),
            "may_drive_model_selection": False,
            "score_eligible": False,
            "claim_boundary": (
                "Repeated-state Radeon endurance evidence; repeats are not independent benchmark units."
            ),
        }

    phase_contract = manifest["experimental_design"][args.phase]
    init_state_ids = phase_contract["init_state_ids"]
    if init_state_ids != list(range(init_state_ids[0], init_state_ids[0] + len(init_state_ids))):
        raise RuntimeError("the LeRobot offset runner requires contiguous init state ids")
    if args.episodes is not None and args.episodes != len(init_state_ids):
        raise ValueError("episode override would violate the frozen phase contract")
    return {
        "phase": args.phase,
        "suites": list(LIBERO_SUITES),
        "task_ids": None,
        "init_state_offset": init_state_ids[0],
        "episodes_per_task": len(init_state_ids),
        "may_drive_model_selection": bool(phase_contract["may_drive_model_selection"]),
        "score_eligible": True,
        "claim_boundary": (
            "Frozen confirmation benchmark; outcomes are permanently excluded from training."
            if args.phase == "confirmation"
            else "Development benchmark; not a confirmation or headline result."
        ),
    }


def resolve_action_steps(args: argparse.Namespace, manifest: dict[str, Any]) -> int:
    benchmark = manifest.get("benchmark", {})
    baseline_steps = int(benchmark.get("executed_action_steps_per_inference", 10))
    chunk_size = int(benchmark.get("action_chunk_size", 50))
    configured = getattr(args, "action_steps", None)
    action_steps = baseline_steps if configured is None else int(configured)
    if not 1 <= action_steps <= chunk_size:
        raise ValueError(
            f"action_steps must be in [1, {chunk_size}], got {action_steps}"
        )
    return action_steps


def build_command(
    args: argparse.Namespace,
    manifest: dict[str, Any],
    scope: dict[str, Any] | None = None,
) -> list[str]:
    scope = resolve_run_scope(args, manifest) if scope is None else scope
    action_steps = resolve_action_steps(args, manifest)
    eval_script = args.lerobot_root / "src" / "lerobot" / "scripts" / "lerobot_eval.py"
    if not eval_script.is_file():
        raise FileNotFoundError(eval_script)
    eval_output = args.output / "eval"
    command = [
        sys.executable,
        str(eval_script),
        f"--output_dir={eval_output}",
        "--env.type=libero",
        f"--env.task={','.join(scope['suites'])}",
        f"--env.init_state_offset={scope['init_state_offset']}",
        "--env.observation_height=256",
        "--env.observation_width=256",
        "--env.control_mode=relative",
        "--env.max_parallel_tasks=1",
        "--eval.batch_size=1",
        f"--eval.n_episodes={scope['episodes_per_task']}",
        "--eval.use_async_envs=false",
        "--eval.max_episodes_rendered=0",
        f"--policy.path={args.checkpoint}",
        "--policy.device=cuda",
        "--policy.dtype=bfloat16",
        f"--policy.n_action_steps={action_steps}",
        f"--seed={args.seed}",
    ]
    if scope["task_ids"] is not None:
        task_ids = ",".join(str(task_id) for task_id in scope["task_ids"])
        command.append(f"--env.task_ids=[{task_ids}]")
    if scope["phase"] == "endurance":
        command.extend(
            [
                "--env.init_state_stride=0",
                "--eval.interleave_task_episodes=true",
            ]
        )
    if args.compile == "true":
        command.append("--policy.compile_model=true")
    elif args.compile == "false":
        command.append("--policy.compile_model=false")
    return command


def run(args: argparse.Namespace) -> int:
    repository_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository_root / "src"))
    from parcel_sorter.rocm_telemetry import RocmTelemetryRecorder

    manifest = load_manifest(args.manifest)
    source = manifest["sources"]
    lerobot_source = lerobot_source_integrity(manifest, args.lerobot_root)
    checkpoint = checkpoint_integrity(
        args.checkpoint,
        expected_size=int(source["baseline_model_bytes"]),
        expected_sha256=str(source["baseline_model_safetensors_sha256"]),
        verify_hash=args.verify_checkpoint_hash,
    )
    scope = resolve_run_scope(args, manifest)
    action_steps = resolve_action_steps(args, manifest)
    validate_executable_schedule(manifest, scope)
    command = build_command(args, manifest, scope)
    protocol_patch = repository_root / "artifacts" / "patches" / "lerobot-libero-frozen-eval.patch"
    if not protocol_patch.is_file():
        raise FileNotFoundError(protocol_patch)
    protocol_patch_sha256 = sha256_file(protocol_patch)
    expected_patch_sha256 = str(manifest["sources"]["lerobot_protocol_patch_sha256"])
    if protocol_patch_sha256 != expected_patch_sha256:
        raise RuntimeError(
            f"LeRobot protocol patch hash mismatch: {protocol_patch_sha256} != {expected_patch_sha256}"
        )
    args.output.mkdir(parents=True, exist_ok=True)
    contract = {
        "schema_version": 1,
        "protocol_id": manifest["protocol_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "phase": args.phase,
        "checkpoint": checkpoint,
        "lerobot_source": lerobot_source,
        "runtime_source_hashes": {
            "runner": sha256_file(Path(__file__).resolve()),
            "manifest_file": sha256_file(args.manifest),
            "lerobot_protocol_patch": protocol_patch_sha256,
        },
        "seed": args.seed,
        "command": command,
        "policy_classification": "pure_pi05_vla",
        "expert_reference_allowed": False,
        "expert_fallback_allowed": False,
        "parcel_harness_allowed": False,
        "compile_override": args.compile,
        "executed_action_steps_per_inference": action_steps,
        "action_steps_source": (
            "benchmark_manifest" if args.action_steps is None else "explicit_ablation"
        ),
        "run_scope": scope,
    }
    contract_path = args.output / "run-contract.json"
    contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.dry_run:
        print(json.dumps(contract, indent=2, sort_keys=True))
        return 0

    env = dict(os.environ)
    python_paths = [
        str(args.libero_overlay),
        str(args.lerobot_root / "src"),
        str(repository_root / "src"),
    ]
    if env.get("PYTHONPATH"):
        python_paths.append(env["PYTHONPATH"])
    env.update(
        {
            "PYTHONPATH": os.pathsep.join(python_paths),
            "MUJOCO_GL": "egl",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "WANDB_DISABLED": "true",
            "PYTORCH_HIP_ALLOC_CONF": "expandable_segments:True",
        }
    )
    telemetry_path = args.output / "rocm-telemetry.jsonl"
    started = time.time()
    with RocmTelemetryRecorder(
        telemetry_path,
        interval_seconds=args.telemetry_interval_seconds,
        gpu_id=args.gpu_id,
    ) as recorder:
        completed = subprocess.run(command, env=env)
    telemetry = recorder.summary()
    eval_info_path = args.output / "eval" / "eval_info.json"
    eval_info = None
    measurement_validation = None
    measurement_error = None
    if eval_info_path.is_file():
        eval_info = json.loads(eval_info_path.read_text(encoding="utf-8"))
    if completed.returncode == 0:
        try:
            measurement_validation = validate_eval_measurements(eval_info or {})
        except RuntimeError as error:
            measurement_error = str(error)
    effective_returncode = completed.returncode if completed.returncode != 0 else (4 if measurement_error else 0)
    summary = {
        "schema_version": 2,
        "returncode": effective_returncode,
        "evaluation_returncode": completed.returncode,
        "elapsed_seconds": time.time() - started,
        "telemetry": telemetry,
        "measurement_validation": measurement_validation,
        "measurement_error": measurement_error,
        "eval_info_path": str(eval_info_path),
        "overall": None if eval_info is None else eval_info.get("overall"),
    }
    (args.output / "run-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))
    return effective_returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--phase",
        choices=("wiring", "efficiency", "endurance", "development", "confirmation"),
        required=True,
    )
    parser.add_argument("--episodes", type=int)
    parser.add_argument("--wiring-suite", choices=LIBERO_SUITES, default="libero_spatial")
    parser.add_argument("--wiring-task-id", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260728)
    parser.add_argument("--compile", choices=("checkpoint", "true", "false"), default="checkpoint")
    parser.add_argument(
        "--action-steps",
        type=int,
        help="Override policy actions executed per inference; recorded in the run contract.",
    )
    parser.add_argument("--verify-checkpoint-hash", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--telemetry-interval-seconds", type=float, default=1.0)
    parser.add_argument("--gpu-id", default="card0")
    parser.add_argument("--lerobot-root", type=Path, default=DEFAULT_LEROBOT_ROOT)
    parser.add_argument("--libero-overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
