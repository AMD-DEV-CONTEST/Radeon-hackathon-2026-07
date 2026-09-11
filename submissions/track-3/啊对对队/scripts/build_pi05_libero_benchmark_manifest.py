#!/usr/bin/env python3
"""Freeze disjoint LIBERO development, confirmation, and Radeon soak runs."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import random
from typing import Any

import numpy as np


SUITE_HORIZONS = {
    "libero_spatial": 280,
    "libero_object": 280,
    "libero_goal": 300,
    "libero_10": 520,
}
ASSETS_REVISION = "0b3ea86be5fe169d0fd036ae63d1070ec09e90f6"
MODEL_REVISION = "dbf8a3f794a9c4297b44f40b752712f50073d945"
MODEL_SHA256 = "877b3ec1130548b69af7f8aeef3ec9d3fc7738040f0b9beb490857ec970997ae"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def array_sha256(value: np.ndarray) -> str:
    array = np.ascontiguousarray(value)
    digest = hashlib.sha256()
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(json.dumps(array.shape).encode("ascii"))
    digest.update(array.tobytes())
    return digest.hexdigest()


def build_run_records(
    tasks: list[dict[str, Any]],
    *,
    init_state_ids: range,
    seed: int,
    phase: str,
    randomize: bool = False,
) -> list[dict[str, Any]]:
    records = [
        {
            "phase": phase,
            "suite": task["suite"],
            "task_id": task["task_id"],
            "task_name": task["task_name"],
            "init_state_id": init_state_id,
            "experimental_unit": f"{task['suite']}:{task['task_id']}:{init_state_id}",
            "horizon": task["horizon"],
        }
        for task in tasks
        for init_state_id in init_state_ids
    ]
    if randomize:
        random.Random(seed).shuffle(records)
    for order, record in enumerate(records):
        record["run_order"] = order
    return records


def canonical_sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    from libero.libero import benchmark, get_libero_path
    from lerobot.envs.libero import get_task_init_states

    if args.episodes_per_task < 1:
        raise ValueError("episodes_per_task must be positive")
    development_ids = range(args.development_start, args.development_start + args.episodes_per_task)
    confirmation_ids = range(args.confirmation_start, args.confirmation_start + args.episodes_per_task)
    if set(development_ids) & set(confirmation_ids):
        raise ValueError("development and confirmation init states must be disjoint")

    tasks: list[dict[str, Any]] = []
    task_sources: list[dict[str, Any]] = []
    suites = benchmark.get_benchmark_dict()
    maximum_state_id = max(*development_ids, *confirmation_ids, args.soak_init_state)
    init_root = Path(get_libero_path("init_states"))
    for suite_name, horizon in SUITE_HORIZONS.items():
        suite = suites[suite_name]()
        if len(suite.tasks) != 10:
            raise RuntimeError(f"{suite_name} has {len(suite.tasks)} tasks instead of 10")
        for task_id in range(10):
            task = suite.get_task(task_id)
            states = np.asarray(get_task_init_states(suite, task_id))
            if maximum_state_id >= len(states):
                raise RuntimeError(
                    f"{suite_name}:{task_id} has only {len(states)} initial states"
                )
            source = init_root / task.problem_folder / Path(task.init_states_file).name
            selected_hashes = {
                str(state_id): array_sha256(states[state_id])
                for state_id in sorted(set(development_ids) | set(confirmation_ids) | {args.soak_init_state})
            }
            tasks.append(
                {
                    "suite": suite_name,
                    "task_id": task_id,
                    "task_name": task.name,
                    "instruction": task.language,
                    "horizon": horizon,
                }
            )
            task_sources.append(
                {
                    "suite": suite_name,
                    "task_id": task_id,
                    "init_state_file": str(source),
                    "init_state_file_sha256": sha256_file(source),
                    "available_init_states": len(states),
                    "selected_init_state_sha256": selected_hashes,
                }
            )

    development = build_run_records(
        tasks,
        init_state_ids=development_ids,
        seed=args.seed + 1,
        phase="development",
    )
    confirmation = build_run_records(
        tasks,
        init_state_ids=confirmation_ids,
        seed=args.seed + 2,
        phase="confirmation",
    )
    soak_base = build_run_records(
        tasks,
        init_state_ids=range(args.soak_init_state, args.soak_init_state + 1),
        seed=args.seed + 3,
        phase="radeon_soak",
    )
    soak = []
    for repetition in range(args.soak_repetitions):
        for record in soak_base:
            item = dict(record)
            item["repetition"] = repetition
            item["experimental_unit"] += f":repeat-{repetition}"
            soak.append(item)
    for order, record in enumerate(soak):
        record["run_order"] = order

    source_root = args.lerobot_root / "src" / "lerobot"
    payload: dict[str, Any] = {
        "schema_version": 2,
        "protocol_id": "pi05-libero-public-benchmark-v2",
        "created_utc": args.created_utc,
        "frozen_before_model_selection": True,
        "benchmark": {
            "name": "LIBERO",
            "suites": list(SUITE_HORIZONS),
            "tasks_per_suite": 10,
            "camera_names": ["agentview_image", "robot0_eye_in_hand_image"],
            "observation_size": [256, 256],
            "action_dimension": 7,
            "control_mode": "relative",
            "settle_steps": 10,
            "sparse_success_reward": True,
            "action_chunk_size": 50,
            "executed_action_steps_per_inference": 10,
        },
        "sources": {
            "hf_libero_version": importlib.metadata.version("hf-libero"),
            "assets_repo": "lerobot/libero-assets",
            "assets_revision": ASSETS_REVISION,
            "assets_files": 586,
            "assets_bytes": 422_320_936,
            "baseline_model_repo": "lerobot/pi05_libero_finetuned",
            "baseline_model_revision": MODEL_REVISION,
            "baseline_model_safetensors_sha256": MODEL_SHA256,
            "baseline_model_bytes": 7_473_096_344,
            "lerobot_version": "0.6.1",
            "lerobot_base_revision": "73dbb6f43a5088583706c91fb73c6957bca5f806",
            "lerobot_protocol_patch_sha256": (
                "b1fa102a4d667af6dfd44110acac304a9ce9679554b1f3391a9a157d1e0f0af5"
            ),
            "lerobot_source_hashes": {
                "envs/libero.py": sha256_file(source_root / "envs" / "libero.py"),
                "envs/configs.py": sha256_file(source_root / "envs" / "configs.py"),
                "configs/default.py": sha256_file(source_root / "configs" / "default.py"),
                "scripts/lerobot_eval.py": sha256_file(source_root / "scripts" / "lerobot_eval.py"),
                "utils/inference_timing.py": sha256_file(
                    source_root / "utils" / "inference_timing.py"
                ),
            },
        },
        "experimental_design": {
            "unit": "one suite/task/fixed-init-state rollout",
            "blocking": ["suite", "task_id", "init_state_id"],
            "paired_model_comparison": True,
            "run_order_seed": args.seed,
            "run_order_protocol": {
                "development": "lerobot-suite-task-init-state-v1",
                "confirmation": "lerobot-suite-task-init-state-v1",
                "radeon_soak": "lerobot-interleaved-task-repeat-v1",
            },
            "development": {
                "init_state_ids": list(development_ids),
                "episodes": len(development),
                "may_drive_model_selection": True,
            },
            "confirmation": {
                "init_state_ids": list(confirmation_ids),
                "episodes": len(confirmation),
                "may_drive_model_selection": False,
                "matches_lerobot_10_episodes_per_task": args.confirmation_start == 0,
            },
            "radeon_soak": {
                "init_state_id": args.soak_init_state,
                "repetitions_per_task": args.soak_repetitions,
                "episodes": len(soak),
                "shared_policy_process_required": True,
                "score_is_secondary": True,
            },
        },
        "primary_endpoint": {
            "metric": "mean sparse task success over 400 confirmation rollouts",
            "published_pi05_openpi_average_percent": 96.85,
            "published_pi05_lerobot_average_percent": 97.5,
            "engineering_target_percent": 98.0,
            "claim_rule": (
                "A superiority claim requires paired outcomes for the same 400 units, "
                "a positive lower 95% paired confidence bound, and no frozen-set reuse."
            ),
        },
        "secondary_endpoints": {
            "suite_success_percent": list(SUITE_HORIZONS),
            "latency": ["p50_ms", "p95_ms", "p99_ms"],
            "radeon": ["peak_vram_gb", "mean_watts", "watt_hours_per_100_episodes"],
            "endurance": ["thermal_drift", "latency_drift", "success_drift"],
        },
        "purity_gate": {
            "policy_type": "pi05",
            "absolute_or_relative_policy_actions_only": True,
            "expert_reference_allowed": False,
            "expert_fallback_allowed": False,
            "parcel_harness_allowed": False,
            "hybrid_success_credit": 0,
        },
        "self_improvement_gate": {
            "confirmation_replay_into_training": False,
            "accepted_training_replay": ["development_success", "verified_development_correction"],
            "promotion_requires": [
                "paired confirmation improvement",
                "no success regression in any suite beyond preregistered tolerance",
                "no Radeon energy or tail-latency regression beyond preregistered tolerance",
            ],
        },
        "task_sources": task_sources,
        "run_schedule": {
            "development": development,
            "confirmation": confirmation,
            "radeon_soak": soak,
        },
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--lerobot-root",
        type=Path,
        default=Path("/workspace/parcel-sorter-rocm/third_party/lerobot"),
    )
    parser.add_argument("--episodes-per-task", type=int, default=10)
    parser.add_argument("--development-start", type=int, default=10)
    parser.add_argument("--confirmation-start", type=int, default=0)
    parser.add_argument("--soak-init-state", type=int, default=20)
    parser.add_argument("--soak-repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260728)
    parser.add_argument("--created-utc", default="2026-07-28T15:00:00Z")
    args = parser.parse_args()
    payload = build_manifest(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "manifest_sha256": payload["manifest_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
