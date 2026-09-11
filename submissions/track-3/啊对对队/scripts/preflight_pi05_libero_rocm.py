#!/usr/bin/env python3
"""Validate the isolated LIBERO stack and render one deterministic probe."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import time

import numpy as np


EXPECTED_ASSET_FILES = 586
EXPECTED_ASSET_BYTES = 422_320_936


def directory_stats(root: Path) -> tuple[int, int]:
    files = [path for path in root.rglob("*") if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)


def array_sha256(value: np.ndarray) -> str:
    array = np.ascontiguousarray(value)
    digest = hashlib.sha256()
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(json.dumps(array.shape).encode("ascii"))
    digest.update(array.tobytes())
    return digest.hexdigest()


def run_probe(args: argparse.Namespace) -> dict[str, object]:
    import mujoco
    import robosuite
    import torch
    from libero.libero import benchmark, get_libero_path
    from lerobot.envs.libero import LiberoEnv, get_libero_dummy_action

    assets_root = Path(get_libero_path("assets"))
    asset_files, asset_bytes = directory_stats(assets_root)
    if (asset_files, asset_bytes) != (EXPECTED_ASSET_FILES, EXPECTED_ASSET_BYTES):
        raise RuntimeError(
            "LIBERO asset mismatch: "
            f"got files={asset_files}, bytes={asset_bytes}; "
            f"expected files={EXPECTED_ASSET_FILES}, bytes={EXPECTED_ASSET_BYTES}"
        )

    suites = benchmark.get_benchmark_dict()
    if args.suite not in suites:
        raise ValueError(f"unknown suite {args.suite!r}")
    task_suite = suites[args.suite]()
    if not 0 <= args.task_id < len(task_suite.tasks):
        raise ValueError(f"task_id must be in [0, {len(task_suite.tasks) - 1}]")

    env = LiberoEnv(
        task_suite=task_suite,
        task_id=args.task_id,
        task_suite_name=args.suite,
        episode_index=0,
        init_state_offset=args.init_state_id,
        n_envs=1,
        observation_width=args.image_size,
        observation_height=args.image_size,
        num_steps_wait=args.settle_steps,
        obs_type="pixels_agent_pos",
        control_mode="relative",
    )
    if env.init_state_id != args.init_state_id:
        raise RuntimeError("init_state_offset was not applied before reset")
    if env._init_states is None or args.init_state_id >= len(env._init_states):
        raise ValueError(
            f"init_state_id {args.init_state_id} is unavailable; "
            f"task has {0 if env._init_states is None else len(env._init_states)} states"
        )

    selected_init_state = np.asarray(env._init_states[args.init_state_id])
    started = time.perf_counter()
    try:
        observation, info = env.reset(seed=args.seed)
        reset_seconds = time.perf_counter() - started
        executed_init_state_id = env.init_state_id - env._reset_stride
        if executed_init_state_id != args.init_state_id:
            raise RuntimeError(
                f"wrong init state executed: {executed_init_state_id} != {args.init_state_id}"
            )

        images: dict[str, dict[str, object]] = {}
        for name, image in observation["pixels"].items():
            array = np.asarray(image)
            if array.shape != (args.image_size, args.image_size, 3):
                raise RuntimeError(f"unexpected {name} image shape {array.shape}")
            if not np.isfinite(array).all() or float(array.std()) == 0.0:
                raise RuntimeError(f"camera {name} is blank or non-finite")
            images[name] = {
                "shape": list(array.shape),
                "dtype": str(array.dtype),
                "mean": float(array.mean()),
                "std": float(array.std()),
                "sha256": array_sha256(array),
            }

        action = np.asarray(get_libero_dummy_action(), dtype=np.float32)
        step_started = time.perf_counter()
        last_reward = 0.0
        last_success = False
        for _ in range(args.probe_steps):
            _, reward, terminated, truncated, step_info = env.step(action)
            last_reward = float(reward)
            last_success = bool(step_info.get("is_success", False))
            if terminated or truncated:
                break
        step_seconds = time.perf_counter() - step_started
    finally:
        env.close()

    parcel_modules = sorted(name for name in sys.modules if name.startswith("parcel_sorter"))
    if parcel_modules:
        raise RuntimeError(f"parcel controller modules contaminated LIBERO probe: {parcel_modules}")

    task = task_suite.get_task(args.task_id)
    return {
        "schema_version": 1,
        "probe": "pi05-libero-rocm-environment-preflight-v1",
        "suite": args.suite,
        "task_id": args.task_id,
        "task_name": task.name,
        "instruction": task.language,
        "seed": args.seed,
        "init_state_id": args.init_state_id,
        "init_state_shape": list(selected_init_state.shape),
        "init_state_sha256": array_sha256(selected_init_state),
        "image_size": args.image_size,
        "images": images,
        "probe_steps": args.probe_steps,
        "last_reward": last_reward,
        "last_success": last_success,
        "timing_seconds": {"reset": reset_seconds, "probe_steps": step_seconds},
        "assets": {
            "root": str(assets_root),
            "files": asset_files,
            "bytes": asset_bytes,
        },
        "software": {
            "hf_libero": importlib.metadata.version("hf-libero"),
            "mujoco": mujoco.__version__,
            "robosuite": robosuite.__version__,
            "torch": torch.__version__,
            "rocm": torch.version.hip,
            "cuda_api_available": torch.cuda.is_available(),
        },
        "purity": {
            "policy_loaded": False,
            "expert_reference_allowed": False,
            "parcel_modules_imported": parcel_modules,
        },
        "status": "pass",
        "info": info,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default="libero_spatial")
    parser.add_argument("--task-id", type=int, default=0)
    parser.add_argument("--init-state-id", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260728)
    parser.add_argument("--image-size", type=int, default=256)
    parser.add_argument("--settle-steps", type=int, default=10)
    parser.add_argument("--probe-steps", type=int, default=2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = run_probe(args)
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
