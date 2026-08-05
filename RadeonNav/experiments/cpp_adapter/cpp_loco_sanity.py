#!/usr/bin/env python3
"""Run the frozen CPP Go2 policy through the UniLab MuJoCo environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch
import yaml

from unilab.algos.torch.cpp_loco import (
    CppLocoPolicyAdapter,
    DEFAULT_CPP_LOCO_CONTRACT,
    build_cpp_observation,
    cpp_action_to_unilab,
    unilab_action_to_canonical_target,
)
from unilab.training import BackendAdapter, create_env, ensure_registries


ROOT = Path(__file__).resolve().parents[2]
UNILAB = ROOT / "UniLab"
DEFAULT_CHECKPOINT = (
    ROOT / "CPP/go2_rl_gym/deploy/pre_train/go2/go2_moe_cts_137k_0.6739.pt"
)
DEFAULT_FIXTURE = ROOT / "refine-logs/golden-contract-fixture-v1.yaml"
EXPECTED_CHECKPOINT_SHA256 = (
    "2206659a6a23886446dcfc05d86888d6cdc9b8a4e31f44cbbc4e2d17ba3d6ead"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_fixture(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a YAML mapping")
    return payload


def _contract_checks(fixture: dict[str, Any]) -> dict[str, Any]:
    tolerance = fixture["tolerance"]
    unilab_obs = np.asarray(
        fixture["expected_observation"]["unilab_rough"], dtype=np.float32
    ).reshape(1, -1)
    previous_cpp_action = np.asarray(
        fixture["physical_state"]["previous_action_canonical"], dtype=np.float32
    ).reshape(1, -1)
    projected_gravity = -np.asarray(
        fixture["physical_state"]["upvector_body"], dtype=np.float32
    ).reshape(1, -1)
    cpp_obs = build_cpp_observation(
        unilab_obs, previous_cpp_action, projected_gravity
    )
    expected_cpp_obs = np.asarray(
        fixture["expected_observation"]["cpp_moe"], dtype=np.float32
    ).reshape(1, -1)

    cpp_action = np.asarray(
        fixture["target_test"]["actor_output_model_order"], dtype=np.float32
    ).reshape(1, -1)
    unilab_action = cpp_action_to_unilab(cpp_action)
    target = unilab_action_to_canonical_target(unilab_action)
    expected_target = np.asarray(
        fixture["target_test"]["expected_target_canonical_rad"]["cpp_moe"],
        dtype=np.float32,
    ).reshape(1, -1)

    observation_error = float(np.max(np.abs(cpp_obs - expected_cpp_obs)))
    target_error = float(np.max(np.abs(target - expected_target)))
    return {
        "observation_max_abs_error": observation_error,
        "observation_atol": float(tolerance["observation_atol"]),
        "observation_passed": observation_error
        <= float(tolerance["observation_atol"]),
        "target_max_abs_error_rad": target_error,
        "target_atol_rad": float(tolerance["target_atol_rad"]),
        "target_passed": target_error <= float(tolerance["target_atol_rad"]),
    }


def _repository_state(path: Path) -> dict[str, Any]:
    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=path,
            check=False,
            capture_output=True,
            text=True,
        )

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain")
    return {
        "path": str(path),
        "commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
    }


def _source_provenance() -> dict[str, Any]:
    files = (
        Path(__file__).resolve(),
        UNILAB / "src/unilab/algos/torch/cpp_loco.py",
        UNILAB / "src/unilab/envs/locomotion/common/base.py",
        UNILAB / "src/unilab/envs/locomotion/go2/rough.py",
        UNILAB / "tests/algos/test_cpp_loco.py",
        UNILAB / "conf/ppo/task/go2_joystick_rough/mujoco.yaml",
    )
    return {
        "repositories": {
            "outer": _repository_state(ROOT),
            "unilab": _repository_state(UNILAB),
            "cpp": _repository_state(ROOT / "CPP/go2_rl_gym"),
        },
        "files_sha256": {
            str(path.relative_to(ROOT)): _sha256(path) for path in files
        },
    }


def _compose_env(
    *,
    terrain_generator_override: dict[str, Any] | None = None,
    terrain_scan_override: dict[str, Any] | None = None,
    scene_fragment_files: list[str] | None = None,
    ground_friction: float | None = None,
    control_gains: tuple[float, float] = (20.0, 0.5),
    simulate_action_latency: bool = False,
):
    from hydra import compose, initialize_config_dir
    from hydra.core.global_hydra import GlobalHydra

    GlobalHydra.instance().clear()
    with initialize_config_dir(config_dir=str(UNILAB / "conf/ppo"), version_base="1.3"):
        cfg = compose(
            config_name="config",
            overrides=[
                "task=go2_joystick_rough/mujoco",
                "algo.num_envs=1",
                "training.play_env_num=1",
                "training.no_play=true",
                "hydra.run.dir=.",
                "hydra.output_subdir=null",
                "hydra/job_logging=disabled",
                "hydra/hydra_logging=disabled",
            ],
        )
    env_override = BackendAdapter(
        cfg, root_dir=UNILAB, algo_name="ppo"
    ).build_task_env_cfg_override()
    env_override["commands"]["resampling_time"] = 0.0
    env_override["commands"]["heading_command"] = False
    env_override["control_config"]["Kp"] = float(control_gains[0])
    env_override["control_config"]["Kd"] = float(control_gains[1])
    env_override["control_config"]["simulate_action_latency"] = (
        simulate_action_latency
    )
    env_override["control_config"]["clip_actions"] = (
        DEFAULT_CPP_LOCO_CONTRACT.unilab_clip_actions
    )
    env_override["terrain_curriculum"]["enabled"] = False
    if terrain_generator_override is not None:
        env_override["scene"]["terrain"]["generator"].update(
            terrain_generator_override
        )
    if terrain_scan_override is not None:
        env_override["terrain_scan"].update(terrain_scan_override)
    for key in (
        "randomize_base_mass",
        "random_com",
        "randomize_kp",
        "randomize_kd",
        "randomize_ground_friction",
        "push_robots",
    ):
        env_override["domain_rand"][key] = False
    if ground_friction is not None:
        if ground_friction <= 0.0:
            raise ValueError("ground_friction must be positive")
        env_override["domain_rand"]["randomize_ground_friction"] = True
        env_override["domain_rand"]["ground_friction_multiplier_range"] = [
            float(ground_friction),
            float(ground_friction),
        ]
    scene = env_override["scene"]
    model_file = Path(scene["model_file"])
    if not model_file.is_absolute():
        scene["model_file"] = str((UNILAB / model_file).resolve())
    scene["fragment_files"] = [
        str((UNILAB / path).resolve()) if not Path(path).is_absolute() else str(path)
        for path in scene.get("fragment_files", [])
    ]
    if scene_fragment_files:
        scene["fragment_files"].extend(str(Path(path).resolve()) for path in scene_fragment_files)
    ensure_registries()
    return create_env(cfg, num_envs=1, env_cfg_override=env_override)


def _resolve_device(requested: str) -> str:
    if requested == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if requested.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA/ROCm device requested but torch.cuda.is_available() is false")
    return requested


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.steps != 64:
        raise ValueError("CPP adapter sanity gate requires exactly 64 steps")
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = _resolve_device(args.device)
    device_obj = torch.device(device)
    fixture = _load_fixture(args.fixture)
    checks = _contract_checks(fixture)
    checkpoint_sha256 = _sha256(args.checkpoint)
    checks["checkpoint_hash_passed"] = checkpoint_sha256 == EXPECTED_CHECKPOINT_SHA256

    started = time.monotonic()
    adapter = CppLocoPolicyAdapter(args.checkpoint, device=device)
    env = None
    try:
        env = _compose_env()
        state = env.init_state()
        command = np.asarray(args.command, dtype=np.float32).reshape(1, 3)
        expected_previous_action = np.zeros((1, 12), dtype=np.float32)

        rewards: list[float] = []
        inference_ms: list[float] = []
        expert_entropies: list[float] = []
        max_abs_cpp_action = 0.0
        max_abs_unilab_action = 0.0
        max_expert_sum_error = 0.0
        min_expert_weight = math.inf
        previous_action_error = 0.0
        command_error = 0.0
        done_count = 0
        all_finite = True

        for _ in range(args.steps):
            state.info["commands"][:] = command
            state.obs["obs"][:, 6:9] = command
            command_error = max(
                command_error,
                float(np.max(np.abs(state.info["commands"] - command))),
                float(np.max(np.abs(state.obs["obs"][:, 6:9] - command))),
            )
            projected_gravity = env.get_projected_gravity()

            policy_started = time.perf_counter()
            unilab_action, diagnostics = adapter.act(
                state.obs["obs"], projected_gravity=projected_gravity
            )
            if device_obj.type == "cuda":
                torch.cuda.synchronize(device_obj)
            inference_ms.append((time.perf_counter() - policy_started) * 1000.0)

            weights = diagnostics["expert_weights"][0]
            weight_sum_error = float(
                abs(np.sum(weights, dtype=np.float64) - 1.0)
            )
            max_expert_sum_error = max(max_expert_sum_error, weight_sum_error)
            min_expert_weight = min(min_expert_weight, float(np.min(weights)))
            previous_action_error = max(
                previous_action_error,
                float(
                    np.max(
                        np.abs(
                            diagnostics["cpp_observation"][:, 33:45]
                            - expected_previous_action
                        )
                    )
                ),
            )
            expected_previous_action[:] = diagnostics["cpp_action"]
            expert_entropies.append(
                float(-np.sum(weights * np.log(np.clip(weights, 1.0e-12, None))))
            )
            max_abs_cpp_action = max(
                max_abs_cpp_action, float(np.max(np.abs(diagnostics["cpp_action"])))
            )
            max_abs_unilab_action = max(
                max_abs_unilab_action, float(np.max(np.abs(unilab_action)))
            )

            state = env.step(unilab_action)
            done = state.terminated | state.truncated
            done_count += int(np.count_nonzero(done))
            rewards.append(float(state.reward[0]))
            all_finite = all_finite and all(
                np.isfinite(value).all()
                for value in (
                    projected_gravity,
                    state.obs["obs"],
                    state.reward,
                    unilab_action,
                    diagnostics["cpp_action_raw"],
                    diagnostics["cpp_action"],
                    diagnostics["expert_weights"],
                    diagnostics["latent"],
                )
            )
            if bool(done[0]):
                adapter.reset()
                expected_previous_action.fill(0.0)

        elapsed = time.monotonic() - started
        checks.update(
            {
                "rollout_finite_passed": all_finite,
                "expert_simplex_passed": (
                    max_expert_sum_error <= 1.0e-5 and min_expert_weight >= -1.0e-7
                ),
                "step_count_passed": len(rewards) == 64,
                "previous_action_passed": previous_action_error <= 1.0e-6,
                "command_persistence_passed": command_error <= 1.0e-6,
            }
        )
        required_checks = (
            "observation_passed",
            "target_passed",
            "checkpoint_hash_passed",
            "rollout_finite_passed",
            "expert_simplex_passed",
            "step_count_passed",
            "previous_action_passed",
            "command_persistence_passed",
        )
        passed = all(bool(checks[name]) for name in required_checks)
        sorted_latency = sorted(inference_ms)
        p99_index = max(math.ceil(0.99 * len(sorted_latency)) - 1, 0)
        device_index = None
        if device_obj.type == "cuda":
            device_index = (
                device_obj.index
                if device_obj.index is not None
                else torch.cuda.current_device()
            )
        reward_array = np.asarray(rewards, dtype=np.float64)
        return {
            "run_id": "CPP-A001",
            "status": "PASSED" if passed else "FAILED",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "source": _source_provenance(),
            "device": device,
            "torch": {
                "version": torch.__version__,
                "hip": torch.version.hip,
                "cuda_available": bool(torch.cuda.is_available()),
                "device_name": (
                    torch.cuda.get_device_name(device_index)
                    if device_obj.type == "cuda"
                    else None
                ),
            },
            "checkpoint": str(args.checkpoint),
            "checkpoint_sha256": checkpoint_sha256,
            "fixture": str(args.fixture),
            "fixture_sha256": _sha256(args.fixture),
            "adapter_contract": asdict(DEFAULT_CPP_LOCO_CONTRACT),
            "seed": args.seed,
            "steps": args.steps,
            "command_si": list(args.command),
            "checks": checks,
            "metrics": {
                "duration_sec": elapsed,
                "gpu_hours": elapsed / 3600.0 if device_obj.type == "cuda" else 0.0,
                "mean_reward": (
                    float(np.mean(reward_array))
                    if np.isfinite(reward_array).all()
                    else None
                ),
                "done_count": done_count,
                "max_abs_cpp_action": max_abs_cpp_action,
                "max_abs_unilab_action": max_abs_unilab_action,
                "expert_entropy_mean": float(np.mean(expert_entropies)),
                "expert_weights_max_sum_error": max_expert_sum_error,
                "expert_weights_min": min_expert_weight,
                "previous_action_max_abs_error": previous_action_error,
                "command_max_abs_error": command_error,
                "inference_ms_mean": float(np.mean(inference_ms)),
                "inference_ms_p99": float(sorted_latency[p99_index]),
            },
            "scope": "integration sanity only; not locomotion quality evidence",
        }
    finally:
        if env is not None:
            env.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--steps", type=int, default=64)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--command", type=float, nargs=3, default=(0.3, 0.0, 0.0), metavar=("VX", "VY", "WZ")
    )
    args = parser.parse_args()
    if args.steps != 64:
        parser.error("--steps must be exactly 64 for the CPP adapter sanity gate")
    return args


def main() -> int:
    args = parse_args()
    try:
        payload = run(args)
    except Exception as exc:
        payload = {
            "run_id": "CPP-A001",
            "status": "FAILED",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }
    _write_json(args.output, payload)
    print(f"{payload['status']}: {args.output}")
    return 0 if payload["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
