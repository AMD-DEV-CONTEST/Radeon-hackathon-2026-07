#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.config import load_config
from parcel_sorter.finger_constraint_repro import (
    summarize_finger_constraint_repro,
)
from parcel_sorter.genesis_env import GenesisParcelEnv
from parcel_sorter.randomization import DomainRandomizer


PROFILE = "medium_carton"
EPISODE = 4_120_001
TRACE_END_EFFECTOR_POSE = (
    0.5733487606048584,
    0.07402051240205765,
    0.3134603500366211,
    -0.0010698031401261687,
    0.9870076179504395,
    0.16057124733924866,
    -0.005630024708807468,
)
TRACE_PARCEL_POSE = (
    0.5724396109580994,
    0.0743669643998146,
    0.155442014336586,
    0.16022130846977234,
    -0.07681524753570557,
    -0.010555305518209934,
    -0.9840311408042908,
)
TRACE_FINGER_POSITION_M = (
    0.03228778392076492,
    0.0322871059179306,
)
FORCE_ABORT_N = 35.0
PENETRATION_LIMIT_M = 0.001
PHYSICS_STEPS = 64
PHYSICS_STEPS_PER_CONTROL = 8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run one preregistered fixed-command Panda finger constraint "
            "reproduction on a fresh Genesis scene."
        )
    )
    parser.add_argument(
        "--variant",
        choices=("stock-inertia", "mass-aware"),
        required=True,
    )
    parser.add_argument("--backend", choices=("cpu", "rocm"), default="rocm")
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "configs/catalog_v2.toml",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _flat_tuple(value: Any) -> tuple[float, ...]:
    if hasattr(value, "detach"):
        value = value.detach().cpu()
    if hasattr(value, "reshape"):
        value = value.reshape(-1)
    if hasattr(value, "tolist"):
        value = value.tolist()
    return tuple(float(item) for item in value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _max_abs_difference(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return max(abs(a - b) for a, b in zip(left, right, strict=True))


def _quaternion_distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    direct = math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))
    negated = math.sqrt(sum((a + b) ** 2 for a, b in zip(left, right, strict=True)))
    return min(direct, negated)


def _variant_config(args: argparse.Namespace) -> tuple[Any, Any]:
    config = load_config(args.config)
    mass_aware = args.variant == "mass-aware"
    config = replace(
        config,
        task=replace(
            config.task,
            parcel_gripper_adapter_enabled=True,
            parcel_gripper_adapter_extension_m=0.030,
            parcel_gripper_adapter_density_kg_m3=1240.0,
            parcel_gripper_adapter_inertia_enabled=mass_aware,
        ),
        sensors=replace(config.sensors, rgb=False, depth=False),
    )
    config.validate()
    randomizer = DomainRandomizer(
        config.randomization,
        config.seed,
        config.parcel_profiles,
    )
    return config, randomizer.sample_profile(PROFILE, EPISODE)


def _contract(sample: Any) -> dict[str, Any]:
    return {
        "simulator": "Genesis 1.2.3",
        "genesis_revision": "ec0efcc0daf9b9932920e6b73f5f810961330997",
        "profile": PROFILE,
        "episode": EPISODE,
        "sample": asdict(sample),
        "source_trace": (
            "outputs/contact-branch-development-v1/"
            "4120001-45-mass-aware.json at control frame 196"
        ),
        "initial_end_effector_pose_wxyz": list(TRACE_END_EFFECTOR_POSE),
        "initial_parcel_pose_wxyz": list(TRACE_PARCEL_POSE),
        "initial_finger_position_m": list(TRACE_FINGER_POSITION_M),
        "state_reconstruction": (
            "arm IK from frozen reset_qpos; exact finger and parcel pose; "
            "all velocities reset to zero"
        ),
        "adapter_extension_m": 0.030,
        "adapter_density_kg_m3": 1240.0,
        "arm_command": "fixed position hold",
        "finger_command_force_n": [-20.0, -20.0],
        "physics_hz": 240,
        "physics_steps": PHYSICS_STEPS,
        "physics_steps_per_control": PHYSICS_STEPS_PER_CONTROL,
        "force_abort_n": FORCE_ABORT_N,
        "penetration_limit_m": PENETRATION_LIMIT_M,
        "force_difference_n": 1.0,
        "finger_position_difference_m": 0.0001,
        "finger_velocity_difference_m_s": 0.01,
        "finger_force_difference_n": 1.0,
        "stop_on_force_or_penetration_gate": True,
        "controller_or_state_machine_used": False,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    config, sample = _variant_config(args)
    mass_aware = args.variant == "mass-aware"
    events: list[dict[str, Any]] = []
    with GenesisParcelEnv(
        config,
        sample,
        backend=args.backend,
        defer_initialization_settle=True,
    ) as env:
        qpos, ik_error = env.robot.inverse_kinematics(
            link=env.end_effector,
            pos=env.np.asarray(TRACE_END_EFFECTOR_POSE[:3]),
            quat=env.np.asarray(TRACE_END_EFFECTOR_POSE[3:]),
            init_qpos=env.np.asarray(config.control.reset_qpos),
            respect_joint_limit=True,
            max_samples=4,
            max_solver_iters=50,
            return_error=True,
        )
        qpos_values = list(_flat_tuple(qpos))
        if len(qpos_values) != 9:
            raise RuntimeError("Panda IK must return nine joint positions")
        qpos_values[7:] = TRACE_FINGER_POSITION_M
        env.robot.set_qpos(env.np.asarray(qpos_values), zero_velocity=True)
        env.parcel.set_pos(
            env.np.asarray(TRACE_PARCEL_POSE[:3]),
            zero_velocity=True,
        )
        env.parcel.set_quat(
            env.np.asarray(TRACE_PARCEL_POSE[3:]),
            zero_velocity=True,
        )
        env.robot.set_dofs_velocity(env.np.zeros(9))

        actual_ee_pose = (
            *_flat_tuple(env.end_effector.get_pos()),
            *_flat_tuple(env.end_effector.get_quat()),
        )
        actual_parcel_pose = (
            *_flat_tuple(env.parcel.get_pos()),
            *_flat_tuple(env.parcel.get_quat()),
        )
        position_error_m = _max_abs_difference(
            actual_ee_pose[:3],
            TRACE_END_EFFECTOR_POSE[:3],
        )
        orientation_error = _quaternion_distance(
            actual_ee_pose[3:],
            TRACE_END_EFFECTOR_POSE[3:],
        )
        parcel_position_error_m = _max_abs_difference(
            actual_parcel_pose[:3],
            TRACE_PARCEL_POSE[:3],
        )
        parcel_orientation_error = _quaternion_distance(
            actual_parcel_pose[3:],
            TRACE_PARCEL_POSE[3:],
        )
        if position_error_m > 0.002 or orientation_error > 0.01:
            raise RuntimeError("fixed end-effector pose reconstruction failed")
        if parcel_position_error_m > 1e-5 or parcel_orientation_error > 1e-5:
            raise RuntimeError("fixed parcel pose reconstruction failed")

        env.robot.control_dofs_position(
            env.np.asarray(qpos_values[:7]),
            env.arm_dofs,
        )
        env.robot.control_dofs_force(
            env.np.asarray((-20.0, -20.0)),
            env.finger_dofs,
        )
        env._last_applied_command = "fixed_grasp_hold"

        stopped = False
        for linear_step in range(PHYSICS_STEPS):
            env.scene.step()
            env.control_step = linear_step // PHYSICS_STEPS_PER_CONTROL
            env._record_contact_branch(linear_step % PHYSICS_STEPS_PER_CONTROL)
            event = env._contact_branch_events[-1]
            events.append(event)
            force_gate = event["peak_parcel_contact_force_n"] > FORCE_ABORT_N
            penetration_gate = any(
                contact["penetration_m"] >= PENETRATION_LIMIT_M
                for contact in event["contacts"]
            )
            if force_gate or penetration_gate:
                stopped = True
                break

        asset_path = Path(env._robot_mjcf_path).resolve()
        initialization = {
            "ik_error": list(_flat_tuple(ik_error)),
            "robot_qpos": qpos_values,
            "actual_end_effector_pose_wxyz": list(actual_ee_pose),
            "end_effector_max_position_error_m": position_error_m,
            "end_effector_quaternion_distance": orientation_error,
            "actual_parcel_pose_wxyz": list(actual_parcel_pose),
            "parcel_max_position_error_m": parcel_position_error_m,
            "parcel_quaternion_distance": parcel_orientation_error,
            "robot_asset_path": str(asset_path),
            "robot_asset_sha256": _sha256(asset_path),
            "adapter_mass_per_finger_kg": env._robot_adapter_mass_per_finger_kg,
        }
        runtime = {
            "backend": args.backend,
            "torch_hip": env.torch.version.hip,
            "device": (
                env.torch.cuda.get_device_name(0)
                if env.torch.cuda.is_available()
                else "cpu"
            ),
        }

    summary = summarize_finger_constraint_repro(
        events,
        force_abort_n=FORCE_ABORT_N,
        penetration_limit_m=PENETRATION_LIMIT_M,
    )
    return {
        "schema_version": "1.0",
        "status": "safety_stopped" if stopped else "complete",
        "study_type": "genesis_panda_finger_constraint_minimal_reproduction",
        "variant": (
            "combined_rigid_body" if mass_aware else "stock_explicit_inertia_ablation"
        ),
        "contract": _contract(sample),
        "runtime": runtime,
        "initialization": initialization,
        "events": events,
        "summary": summary,
        "holdout_opened": False,
        "new_episode_opened": False,
    }


def main() -> int:
    args = parse_args()
    payload = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "status": payload["status"],
                "variant": payload["variant"],
                "summary": payload["summary"],
            },
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
