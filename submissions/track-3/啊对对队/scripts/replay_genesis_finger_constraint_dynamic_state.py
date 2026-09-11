#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.config import load_config
from parcel_sorter.finger_constraint_repro import (
    partition_dynamic_control_inputs,
    summarize_finger_constraint_repro,
    validate_dynamic_control_replay_source_events,
    validate_dynamic_replay_source_events,
)
from parcel_sorter.genesis_env import GenesisParcelEnv
from parcel_sorter.randomization import DomainRandomizer


PROFILE = "medium_carton"
EPISODE = 4_120_001
CANDIDATE_ID = "canonical-long-+0.000-up-0.045"
FORCE_ABORT_N = 35.0
PENETRATION_LIMIT_M = 0.001


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay a frozen Genesis generalized state and force sequence."
    )
    parser.add_argument(
        "--variant",
        choices=("stock-inertia", "mass-aware"),
        required=True,
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--replay-mode",
        choices=("recorded-force", "recorded-control-inputs"),
        default="recorded-force",
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


def _max_abs_difference(left: Any, right: Any) -> float:
    return max(
        abs(float(a) - float(b))
        for a, b in zip(left, right, strict=True)
    )


def _load_source(
    path: Path,
    *,
    replay_mode: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "complete":
        raise ValueError("dynamic source capture must be complete")
    if payload.get("episode") != EPISODE or payload.get("profile") != PROFILE:
        raise ValueError("dynamic source capture uses a different episode")
    if payload.get("tested_candidate_ids") != [CANDIDATE_ID]:
        raise ValueError("dynamic source capture uses a different candidate")
    if payload.get("repeat_count") != 1 or len(payload.get("rollouts", ())) != 1:
        raise ValueError("dynamic source capture must contain one rollout")
    contract = payload.get("contract", {})
    if not contract.get("parcel_gripper_adapter_inertia_enabled"):
        raise ValueError("dynamic source must use combined rigid-body inertia")
    expected_fields = set(contract.get("contact_branch_dynamic_state_fields", ()))
    required_fields = {
        "robot_qpos",
        "robot_dof_velocity",
        "robot_dof_actual_force_n",
        "robot_dof_control_force_n",
        "parcel_qpos",
        "parcel_dof_velocity",
    }
    if expected_fields != required_fields:
        raise ValueError("dynamic source contract does not declare exact state fields")
    events = payload["rollouts"][0]["report"]["safety_summary"][
        "contact_branch_events"
    ]
    if replay_mode == "recorded-control-inputs":
        expected_control_fields = {
            "robot_dof_control_mode",
            "robot_dof_position_target",
            "robot_dof_velocity_target",
            "robot_dof_force_target_n",
        }
        declared_control_fields = set(
            contract.get("contact_branch_control_input_fields", ())
        )
        if declared_control_fields != expected_control_fields:
            raise ValueError(
                "dynamic source contract does not declare exact control-input fields"
            )
        validator = validate_dynamic_control_replay_source_events
    else:
        validator = validate_dynamic_replay_source_events
    return payload, validator(events, expected_start=(196, 0))


def _apply_control_inputs(env: GenesisParcelEnv, event: dict[str, Any]) -> None:
    grouped = partition_dynamic_control_inputs(event)
    methods = {
        "position": env.robot.control_dofs_position,
        "velocity": env.robot.control_dofs_velocity,
        "force": env.robot.control_dofs_force,
    }
    for mode, command in grouped.items():
        indices = command["dof_indices"]
        if not indices:
            continue
        methods[mode](
            env.np.asarray(command["targets"]),
            env.np.asarray(indices, dtype=int),
        )


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
        output=replace(config.output, root_dir=str(PROJECT_ROOT / "outputs")),
    )
    config.validate()
    randomizer = DomainRandomizer(
        config.randomization,
        config.seed,
        config.parcel_profiles,
    )
    return config, randomizer.sample_profile(PROFILE, EPISODE)


def run(args: argparse.Namespace) -> dict[str, Any]:
    source_path = args.source.resolve()
    source, source_events = _load_source(
        source_path,
        replay_mode=args.replay_mode,
    )
    config, sample = _variant_config(args)
    normalized_sample = json.loads(
        json.dumps(asdict(sample), allow_nan=False)
    )
    if normalized_sample != source["sample"]:
        raise ValueError("regenerated parcel sample differs from source capture")
    mass_aware = args.variant == "mass-aware"
    initial = source_events[0]
    events: list[dict[str, Any]] = []

    with GenesisParcelEnv(
        config,
        sample,
        backend=args.backend,
        defer_initialization_settle=True,
    ) as env:
        env.robot.set_qpos(
            env.np.asarray(initial["robot_qpos"]),
            zero_velocity=True,
        )
        env.robot.set_dofs_velocity(
            env.np.asarray(initial["robot_dof_velocity"])
        )
        env.parcel.set_qpos(
            env.np.asarray(initial["parcel_qpos"]),
            zero_velocity=True,
        )
        env.parcel.set_dofs_velocity(
            env.np.asarray(initial["parcel_dof_velocity"])
        )
        state_error = {
            "robot_qpos_max_abs": _max_abs_difference(
                _flat_tuple(env.robot.get_qpos()),
                initial["robot_qpos"],
            ),
            "robot_dof_velocity_max_abs": _max_abs_difference(
                _flat_tuple(env.robot.get_dofs_velocity()),
                initial["robot_dof_velocity"],
            ),
            "parcel_qpos_max_abs": _max_abs_difference(
                _flat_tuple(env.parcel.get_qpos()),
                initial["parcel_qpos"],
            ),
            "parcel_dof_velocity_max_abs": _max_abs_difference(
                _flat_tuple(env.parcel.get_dofs_velocity()),
                initial["parcel_dof_velocity"],
            ),
        }
        if max(state_error.values()) > 1e-6:
            raise RuntimeError("dynamic generalized-state reconstruction failed")

        env._last_applied_command = args.replay_mode.replace("-", "_")
        stopped = False
        for source_event in source_events[1:]:
            if args.replay_mode == "recorded-control-inputs":
                _apply_control_inputs(env, source_event)
            else:
                env.robot.control_dofs_force(
                    env.np.asarray(source_event["robot_dof_control_force_n"])
                )
            env.scene.step()
            env.control_step = int(source_event["control_step"])
            env._record_contact_branch(int(source_event["physics_substep"]))
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
            "source_event": {
                "control_step": int(initial["control_step"]),
                "physics_substep": int(initial["physics_substep"]),
            },
            "state_error": state_error,
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

    contract = {
        "simulator": "Genesis 1.2.3",
        "genesis_revision": "ec0efcc0daf9b9932920e6b73f5f810961330997",
        "profile": PROFILE,
        "episode": EPISODE,
        "candidate_id": CANDIDATE_ID,
        "source_capture_sha256": _sha256(source_path),
        "source_start": [196, 0],
        "source_end": [
            int(source_events[-1]["control_step"]),
            int(source_events[-1]["physics_substep"]),
        ],
        "initial_state": "exact generalized qpos/qvel from source event 196/0",
        "command_replay": (
            "recorded nine-DOF control mode and raw mode-specific targets "
            "from the next source event"
            if args.replay_mode == "recorded-control-inputs"
            else "recorded nine-DOF control-force sequence from the next source event"
        ),
        "replay_mode": args.replay_mode,
        "adapter_extension_m": 0.030,
        "adapter_density_kg_m3": 1240.0,
        "physics_hz": 240,
        "force_abort_n": FORCE_ABORT_N,
        "penetration_limit_m": PENETRATION_LIMIT_M,
        "force_difference_n": 1.0,
        "finger_position_difference_m": 0.0001,
        "finger_velocity_difference_m_s": 0.01,
        "finger_force_difference_n": 1.0,
        "stop_on_force_or_penetration_gate": True,
        "controller_or_state_machine_used": False,
    }
    summary = summarize_finger_constraint_repro(
        events,
        force_abort_n=FORCE_ABORT_N,
        penetration_limit_m=PENETRATION_LIMIT_M,
    )
    return {
        "schema_version": "1.0",
        "status": "safety_stopped" if stopped else "complete",
        "study_type": (
            "genesis_panda_finger_constraint_control_input_replay"
            if args.replay_mode == "recorded-control-inputs"
            else "genesis_panda_finger_constraint_dynamic_state_replay"
        ),
        "variant": (
            "combined_rigid_body" if mass_aware else "stock_explicit_inertia_ablation"
        ),
        "contract": contract,
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
