#!/usr/bin/env python3
"""Check the frozen Agility BBC contract and run a short UniLab flat rollout."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
AGILITY_ROOT = ROOT / "quadrupedal-agility"
DEPLOYMENT_CHECKPOINT = (
    AGILITY_ROOT / "go2_deploy/models/ll_policy/3_model/model.pt"
)
SOURCE_CHECKPOINT = AGILITY_ROOT / "tsc/weights/bbc/model.pt"
DEFAULT_OUTPUT = ROOT / "experiment-results/neupan-agility/NAG-101/result.json"
SOURCE_OUTPUT = (
    ROOT / "experiment-results/quadrupedal-agility/NAG-102/result.json"
)
sys.path.insert(0, str(ROOT / "experiments/cpp_adapter"))

from cpp_loco_sanity import _compose_env, _sha256  # noqa: E402
from unilab.algos.torch.cpp_loco import (  # noqa: E402
    DEFAULT_CPP_LOCO_CONTRACT,
    unilab_action_to_canonical_target,
)
from unilab.algos.torch.quadrupedal_agility import (  # noqa: E402
    AgilityBbcContract,
    AgilityBbcPolicyAdapter,
    DEFAULT_AGILITY_BBC_CONTRACT,
    SOURCE_AGILITY_BBC_CONTRACT,
    agility_action_to_unilab,
)
from unilab.envs.locomotion.go2.rough import (  # noqa: E402
    GO2_ACTUATOR_TO_DOF_INDICES,
)
from unilab.terrains import flat  # noqa: E402


DEPLOYMENT_COMMAND = np.asarray(
    [[0.8, 0.0, 0.0, 0.0, 0.30, 0.0, 1.0, 0.0, 0.0]],
    dtype=np.float32,
)
SOURCE_COMMAND = np.asarray(
    [[0.8, 0.0, 0.0, 0.0, 0.30, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0]],
    dtype=np.float32,
)
def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _device(requested: str) -> torch.device:
    if requested == "auto":
        requested = "cuda" if torch.cuda.is_available() else "cpu"
    device = torch.device(requested)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA/ROCm requested but torch.cuda.is_available() is false")
    if device.type != "cuda":
        raise RuntimeError("BBC sanity requires a CUDA/ROCm device")
    return device


def _reference_models(
    device: torch.device,
    checkpoint: Path,
    contract: AgilityBbcContract,
    mode_count: int,
) -> tuple[Any, Any, np.ndarray, np.ndarray]:
    for path in (AGILITY_ROOT / "tsc", AGILITY_ROOT):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    from go2_deploy.scripts.common import (
        build_low_level_model,
        validate_low_level_checkpoint,
    )
    model, estimator = build_low_level_model(mode_count, str(device), False)
    payload = torch.load(checkpoint, map_location=device, weights_only=False)
    validate_low_level_checkpoint(payload, mode_count)
    model.load_state_dict(payload["actor_critic"])
    estimator.load_state_dict(payload["estimator"])
    source_default = np.asarray(contract.source_default_dof, dtype=np.float32)
    source_action_scale = np.full(
        12, float(contract.source_action_scale), dtype=np.float32
    )
    source_action_scale[[0, 3, 6, 9]] *= float(
        contract.source_hip_scale_reduction
    )
    return (
        model.eval(),
        estimator.eval(),
        source_default,
        source_action_scale,
    )


def _reference_proprio(
    base_quat: np.ndarray,
    gyro: np.ndarray,
    dof_pos: np.ndarray,
    dof_vel: np.ndarray,
    previous_action: np.ndarray,
    foot_contact: np.ndarray,
    source_default: np.ndarray,
) -> np.ndarray:
    """Independent transcription of go2_deploy LCMAgent.get_obs()."""
    w, x, y, z = np.asarray(base_quat, dtype=np.float32).T
    roll = np.arctan2(
        2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y)
    )
    pitch = np.arcsin(np.clip(2.0 * (w * y - z * x), -1.0, 1.0))
    return np.concatenate(
        (
            np.stack((roll, pitch), axis=1),
            np.asarray(gyro, dtype=np.float32) * 0.25,
            np.asarray(dof_pos, dtype=np.float32) - source_default,
            np.asarray(dof_vel, dtype=np.float32) * 0.05,
            np.asarray(previous_action, dtype=np.float32),
            (np.asarray(foot_contact) > 0.5).astype(np.float32) - 0.5,
            np.zeros((len(base_quat), 12), dtype=np.float32),
        ),
        axis=1,
    )


def _reference_inference(
    model: Any,
    estimator: Any,
    device: torch.device,
    proprio: np.ndarray,
    history: np.ndarray,
    command: np.ndarray,
    explicit_override: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    proprio_tensor = torch.as_tensor(proprio, device=device)
    with torch.inference_mode():
        explicit = (
            estimator(proprio_tensor)
            if explicit_override is None
            else torch.as_tensor(explicit_override, device=device)
        )
        low_input = torch.cat(
            (
                proprio_tensor,
                explicit,
                torch.zeros((1, 29), device=device),
                torch.as_tensor(history, device=device),
                torch.as_tensor(command, device=device),
            ),
            dim=1,
        )
        action = model.act_inference(low_input, hist_encoding=True)
    return (
        explicit.cpu().numpy(),
        low_input.cpu().numpy(),
        action.cpu().numpy(),
    )


def _live_env_contract(env: Any) -> dict[str, float | bool]:
    contract = DEFAULT_CPP_LOCO_CONTRACT
    expected_default = np.asarray(contract.unilab_default_dof, dtype=np.float32)
    expected_scale = np.asarray(
        contract.unilab_action_scale_actuator, dtype=np.float32
    )
    expected_mapping = np.asarray(contract.actuator_to_dof, dtype=np.int32)
    default_error = float(np.max(np.abs(env.default_angles - expected_default)))
    scale_error = float(np.max(np.abs(env._action_scale - expected_scale)))
    actuator_default_error = float(
        np.max(
            np.abs(
                env._default_angles_actuator
                - expected_default[expected_mapping]
            )
        )
    )
    mapping_matches = bool(
        np.array_equal(GO2_ACTUATOR_TO_DOF_INDICES, expected_mapping)
    )
    return {
        "live_default_pose_max_abs_error_rad": default_error,
        "live_action_scale_max_abs_error": scale_error,
        "live_actuator_default_max_abs_error_rad": actuator_default_error,
        "live_actuator_mapping_matches": mapping_matches,
        "passed": (
            default_error <= 1.0e-6
            and scale_error <= 1.0e-6
            and actuator_default_error <= 1.0e-6
            and mapping_matches
        ),
    }


def _synthetic_parity(
    adapter: AgilityBbcPolicyAdapter,
    model: Any,
    estimator: Any,
    device: torch.device,
    source_default: np.ndarray,
    command: np.ndarray,
    privileged_explicit: bool,
) -> dict[str, float]:
    quat = np.asarray([[0.91, 0.11, -0.23, 0.31]], dtype=np.float32)
    quat /= np.linalg.norm(quat, axis=1, keepdims=True)
    gyro = np.asarray([[0.17, -0.29, 0.43]], dtype=np.float32)
    dof_pos = (
        source_default + np.linspace(-0.12, 0.15, 12, dtype=np.float32)
    ).reshape(1, 12)
    dof_vel = np.linspace(1.1, -0.8, 12, dtype=np.float32).reshape(1, 12)
    contact = np.asarray([[1.0, 0.0, 1.0, 0.0]], dtype=np.float32)
    previous = np.linspace(-0.3, 0.4, 12, dtype=np.float32).reshape(1, 12)
    history = np.linspace(-0.7, 0.8, 570, dtype=np.float32).reshape(1, 570)
    adapter.previous_action[:] = previous
    adapter.history[:] = history

    reference_proprio = _reference_proprio(
        quat, gyro, dof_pos, dof_vel, previous, contact, source_default
    )
    explicit_override = (
        np.asarray([[0.42, 0.1, -0.2, 0.3]], dtype=np.float32)
        if privileged_explicit
        else None
    )
    explicit, low_input, action = _reference_inference(
        model,
        estimator,
        device,
        reference_proprio,
        history,
        command,
        explicit_override,
    )
    _, diagnostics = adapter.act(
        base_quat_wxyz=quat,
        base_ang_vel=gyro,
        dof_pos=dof_pos,
        dof_vel=dof_vel,
        foot_contact=contact,
        command=command,
        explicit=explicit_override,
    )
    errors = {
        "proprio": float(
            np.max(np.abs(diagnostics["proprio"] - reference_proprio))
        ),
        "history": float(
            np.max(np.abs(diagnostics["history"] - history))
        ),
        "low_input": float(
            np.max(np.abs(diagnostics["low_input"] - low_input))
        ),
        "estimator": float(
            np.max(np.abs(diagnostics["explicit"] - explicit))
        ),
        "action": float(
            np.max(np.abs(diagnostics["source_action"] - action))
        ),
    }
    adapter.reset()
    return errors


def _flat_terrain(
    seed: int, horizontal_scale: float | None = None
) -> dict[str, Any]:
    config = {
        "seed": seed,
        "curriculum": False,
        "num_rows": 1,
        "num_cols": 1,
        "sub_terrains": {"flat": flat(proportion=1.0)},
    }
    if horizontal_scale is not None:
        config["horizontal_scale"] = horizontal_scale
    return config


def _set_upright_state(env: Any, *, source: bool) -> None:
    """Replace the rough-task recovery reset with the selected policy start."""
    qpos = np.asarray(env._init_qpos, dtype=np.float32).reshape(1, -1).copy()
    if source:
        qpos[0, 2] = 0.42
        qpos[0, -12:] = SOURCE_AGILITY_BBC_CONTRACT.source_default_dof
    env._backend.set_state(
        np.asarray([0], dtype=np.int32),
        qpos,
        np.zeros_like(env._init_qvel, dtype=np.float32).reshape(1, -1),
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.steps != 64:
        raise ValueError("BBC fidelity gate requires exactly 64 steps")
    if args.seed != 7:
        raise ValueError("BBC fidelity gate requires seed 7")
    source_profile = args.profile == "source"
    if args.horizontal_scale is not None and args.horizontal_scale <= 0:
        raise ValueError("horizontal_scale must be positive")
    run_id = (
        "NAG-102H"
        if source_profile and args.horizontal_scale is not None
        else "NAG-102"
        if source_profile
        else "NAG-101"
    )
    checkpoint = SOURCE_CHECKPOINT if source_profile else DEPLOYMENT_CHECKPOINT
    contract = (
        SOURCE_AGILITY_BBC_CONTRACT
        if source_profile
        else DEFAULT_AGILITY_BBC_CONTRACT
    )
    mode_count = 5 if source_profile else 3
    command = SOURCE_COMMAND if source_profile else DEPLOYMENT_COMMAND
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = _device(args.device)
    adapter = AgilityBbcPolicyAdapter(
        AGILITY_ROOT,
        checkpoint,
        device=device,
        contract=contract,
        mode_count=mode_count,
    )
    (
        reference_model,
        reference_estimator,
        source_default,
        source_action_scale,
    ) = _reference_models(device, checkpoint, contract, mode_count)
    synthetic = _synthetic_parity(
        adapter,
        reference_model,
        reference_estimator,
        device,
        source_default,
        command,
        source_profile,
    )
    env = _compose_env(
        terrain_generator_override=_flat_terrain(
            args.seed, args.horizontal_scale
        ),
        control_gains=(40.0, 1.0),
        simulate_action_latency=source_profile,
    )

    proprio_error = synthetic["proprio"]
    history_error = synthetic["history"]
    low_input_error = synthetic["low_input"]
    estimator_error = synthetic["estimator"]
    action_error = synthetic["action"]
    target_error = 0.0
    done_count = 0
    all_finite = True
    base_heights: list[float] = []
    tilts: list[float] = []
    inference_ms: list[float] = []
    source_action_max = 0.0
    unilab_action_max = 0.0
    started = time.monotonic()
    try:
        live_contract = _live_env_contract(env)
        if not bool(live_contract["passed"]):
            raise RuntimeError(f"live UniLab action contract mismatch: {live_contract}")
        state = env.init_state()
        randomized_gravity = env.get_projected_gravity()[0]
        randomized_reset_tilt = math.acos(
            float(np.clip(-randomized_gravity[2], -1.0, 1.0))
        )
        _set_upright_state(env, source=source_profile)
        state = env.update_state(state)
        initial_latency_action = agility_action_to_unilab(
            np.zeros((1, 12), dtype=np.float32), contract
        )
        initial_latency_target_error = float(
            np.max(
                np.abs(
                    unilab_action_to_canonical_target(initial_latency_action)
                    - source_default
                )
            )
        )
        if source_profile:
            state.info["current_actions"] = initial_latency_action.copy()
        upright_gravity = env.get_projected_gravity()[0]
        upright_reset_tilt = math.acos(
            float(np.clip(-upright_gravity[2], -1.0, 1.0))
        )
        start_xy = env._backend.get_base_pos()[0, :2].copy()
        reference_previous_action = np.zeros((1, 12), dtype=np.float32)
        reference_history = np.zeros((1, 570), dtype=np.float32)
        last_contact = np.zeros((1, 4), dtype=bool)
        for step in range(args.steps):
            base_quat = env._backend.get_base_quat().copy()
            gyro = env.get_gyro().copy()
            dof_pos = env.get_dof_pos().copy()
            dof_vel = env.get_dof_vel().copy()
            raw_contact = (
                np.linalg.norm(env.feet_force, axis=2) > 2.0
                if source_profile
                else env._foot_contact_mask().copy() > 0.5
            )
            foot_contact = np.logical_or(raw_contact, last_contact).astype(
                np.float32
            )
            last_contact = raw_contact
            reference_proprio = _reference_proprio(
                base_quat,
                gyro,
                dof_pos,
                dof_vel,
                reference_previous_action,
                foot_contact,
                source_default,
            )
            explicit_override = (
                np.concatenate(
                    (
                        env._backend.get_base_pos()[:, 2:3],
                        env.get_local_linvel() * 0.5,
                    ),
                    axis=1,
                ).astype(np.float32)
                if source_profile
                else None
            )
            (
                reference_explicit,
                reference_low_input,
                reference_action,
            ) = _reference_inference(
                reference_model,
                reference_estimator,
                device,
                reference_proprio,
                reference_history,
                command,
                explicit_override,
            )
            inference_started = time.perf_counter()
            unilab_action, diagnostics = adapter.act(
                base_quat_wxyz=base_quat,
                base_ang_vel=gyro,
                dof_pos=dof_pos,
                dof_vel=dof_vel,
                foot_contact=foot_contact,
                command=command,
                explicit=explicit_override,
            )
            if device.type == "cuda":
                torch.cuda.synchronize(device)
            inference_ms.append(
                (time.perf_counter() - inference_started) * 1000.0
            )

            proprio_error = max(
                proprio_error,
                float(
                    np.max(
                        np.abs(diagnostics["proprio"] - reference_proprio)
                    )
                ),
            )
            history_error = max(
                history_error,
                float(
                    np.max(
                        np.abs(diagnostics["history"] - reference_history)
                    )
                ),
            )
            low_input_error = max(
                low_input_error,
                float(
                    np.max(
                        np.abs(
                            diagnostics["low_input"] - reference_low_input
                        )
                    )
                ),
            )
            estimator_error = max(
                estimator_error,
                float(
                    np.max(
                        np.abs(
                            diagnostics["explicit"]
                            - reference_explicit
                        )
                    )
                ),
            )
            action_error = max(
                action_error,
                float(
                    np.max(
                        np.abs(
                            diagnostics["source_action"]
                            - reference_action
                        )
                    )
                ),
            )
            reference_previous_action[:] = reference_action
            reference_history[:, :-57] = reference_history[:, 57:]
            reference_history[:, -57:] = reference_proprio
            if source_profile and step < 1:
                reference_history[:] = np.tile(reference_proprio, (1, 10))
                adapter.history[:] = reference_history
            expected_target = (
                source_default
                + diagnostics["source_action"] * source_action_scale
            )
            target_error = max(
                target_error,
                float(
                    np.max(
                        np.abs(
                            diagnostics["canonical_target"] - expected_target
                        )
                    )
                ),
            )
            source_action_max = max(
                source_action_max,
                float(np.max(np.abs(diagnostics["source_action"]))),
            )
            unilab_action_max = max(
                unilab_action_max, float(np.max(np.abs(unilab_action)))
            )

            state = env.step(unilab_action)
            done = state.terminated | state.truncated
            done_count += int(np.count_nonzero(done))
            base_height = float(env._backend.get_base_pos()[0, 2])
            gravity = env.get_projected_gravity()[0]
            tilt = math.acos(float(np.clip(-gravity[2], -1.0, 1.0)))
            base_heights.append(base_height)
            tilts.append(tilt)
            all_finite = all_finite and all(
                np.isfinite(value).all()
                for value in (
                    unilab_action,
                    diagnostics["proprio"],
                    diagnostics["explicit"],
                    diagnostics["source_action"],
                    state.obs["obs"],
                    state.reward,
                    env._backend.get_base_pos(),
                )
            )

        elapsed = time.monotonic() - started
        end_xy = env._backend.get_base_pos()[0, :2].copy()
    finally:
        env.close()

    checks = {
        "live_env_contract": bool(live_contract["passed"]),
        "upright_deployment_reset": upright_reset_tilt <= 1.0e-6,
        "proprio_parity": proprio_error <= 1.0e-6,
        "history_parity": history_error <= 1.0e-6,
        "low_input_parity": low_input_error <= 1.0e-6,
        "estimator_parity": estimator_error <= 1.0e-6,
        "bbc_action_parity": action_error <= 1.0e-6,
        "physical_target_mapping": target_error <= 1.0e-6,
        "native_action_latency": bool(
            env._cfg.control_config.simulate_action_latency
        )
        == source_profile,
        "latency_initial_target": (
            initial_latency_target_error <= 1.0e-6
            if source_profile
            else True
        ),
        "rollout_finite": all_finite,
        "no_early_done": done_count == 0,
        "base_height": min(base_heights) > 0.16,
        "tilt": max(tilts) < 1.2,
        "rolling_history": bool(np.any(adapter.history)),
    }
    if source_profile:
        checks["forward_displacement"] = (
            float(np.linalg.norm(end_xy - start_xy)) > 0.20
        )
    passed = all(checks.values())
    return {
        "run_id": run_id,
        "status": "PASSED" if passed else "FAILED",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "scope": (
            "source BBC checkpoint/control fidelity + 64-step UniLab flat smoke"
            if source_profile
            else "deployment implementation parity + 64-step UniLab flat smoke"
        ),
        "profile": args.profile,
        "seed": args.seed,
        "steps": args.steps,
        "terrain_horizontal_scale_m": args.horizontal_scale,
        "device": str(device),
        "device_name": (
            torch.cuda.get_device_name(device) if device.type == "cuda" else None
        ),
        "torch_version": torch.__version__,
        "checkpoint": str(checkpoint),
        "checkpoint_sha256": _sha256(checkpoint),
        "source_control_contract": {
            "default_dof": list(contract.source_default_dof),
            "action_scale": contract.source_action_scale,
            "hip_scale_reduction": contract.source_hip_scale_reduction,
            "kp": 40.0,
            "kd": 1.0,
            "control_period_s": 0.02,
        },
        "command": {
            "values": command[0].tolist(),
            "skill": "trot",
            "units": [
                "m/s",
                "m/s",
                "rad/s",
                "m",
                "m",
                "unitless",
            ]
            + ["one_hot"] * mode_count,
        },
        "checks": checks,
        "metrics": {
            "proprio_max_abs_error": proprio_error,
            "history_max_abs_error": history_error,
            "low_input_max_abs_error": low_input_error,
            "estimator_max_abs_error": estimator_error,
            "bbc_action_max_abs_error": action_error,
            "physical_target_max_abs_error_rad": target_error,
            "latency_initial_target_max_abs_error_rad": (
                initial_latency_target_error
            ),
            "min_base_height_m": min(base_heights),
            "max_base_height_m": max(base_heights),
            "final_base_height_m": base_heights[-1],
            "min_base_height_step": int(np.argmin(base_heights)) + 1,
            "max_tilt_rad": max(tilts),
            "final_tilt_rad": tilts[-1],
            "max_tilt_step": int(np.argmax(tilts)) + 1,
            "tail_16_max_tilt_rad": max(tilts[-16:]),
            "xy_displacement_m": float(np.linalg.norm(end_xy - start_xy)),
            "done_count": done_count,
            "max_abs_source_action": source_action_max,
            "max_abs_unilab_action": unilab_action_max,
            "inference_ms_mean": float(np.mean(inference_ms)),
            "inference_ms_p99": float(np.quantile(inference_ms, 0.99)),
            "duration_sec": elapsed,
            "gpu_hours": elapsed / 3600.0 if device.type == "cuda" else 0.0,
        },
        "live_env_contract": live_contract,
        "reset_contract": {
            "rough_randomized_reset_tilt_rad": randomized_reset_tilt,
            "upright_reset_tilt_rad": upright_reset_tilt,
            "deployment_upright_reset_tilt_rad": upright_reset_tilt,
            "source_base_height_and_joint_pose": source_profile,
            "base_qvel_zeroed": True,
        },
        "asymmetric_synthetic_parity_errors": synthetic,
        "contact_contract": (
            "current OR previous 2 N foot-contact mask"
            if source_profile
            else "current OR previous UniLab-native foot-contact mask"
        ),
        "known_difference": (
            "source policy was trained with Isaac Gym/PhysX assets; this rollout "
            "uses UniLab MuJoCo assets."
        ),
        "source_sha256": {
            "adapter": _sha256(
                ROOT
                / "UniLab/src/unilab/algos/torch/quadrupedal_agility.py"
            ),
            "runner": _sha256(Path(__file__).resolve()),
            "source_common": _sha256(
                AGILITY_ROOT / "go2_deploy/scripts/common.py"
            ),
            "source_history_wrapper": _sha256(
                AGILITY_ROOT / "go2_deploy/envs/history_wrapper.py"
            ),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile", choices=("deployment", "source"), default="deployment"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--steps", type=int, default=64)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--horizontal-scale", type=float)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output is None:
        args.output = SOURCE_OUTPUT if args.profile == "source" else DEFAULT_OUTPUT
    try:
        payload = run(args)
    except Exception as exc:
        payload = {
            "run_id": (
                "NAG-102H"
                if args.profile == "source"
                and args.horizontal_scale is not None
                else "NAG-102"
                if args.profile == "source"
                else "NAG-101"
            ),
            "status": "FAILED",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
        }
    _write_json(args.output, payload)
    print(f"{payload['status']}: {args.output}")
    return 0 if payload["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
