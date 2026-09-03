#!/usr/bin/env python3
"""Evaluate recorded G3 target/readback configurations with live collision detection.

This is a development-only counterfactual.  It constructs the frozen G3 scene,
places each bowl at its recorded pose, places Mantis first at the recorded
executed readback and then at the corresponding commanded 18D target, and uses
Genesis ``detect_collision``.  That API re-runs collision detection without a
physics step, so the probe does not integrate dynamics or alter the official
closed-loop protocol.

The readback branch is descriptive: contact constraints can separate a shallow
collision before the post-step qpos is recorded, so a static readback need not
retain the most-recent-step contact.  The target branch asks the otherwise
unobserved question needed to distinguish a commanded colliding trajectory
from collision created only by controller dynamics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from mantis_rocm_bridge.act_closedloop_g3 import (
    GenesisClosedLoopRuntime,
    _read_dofs,
)
from mantis_rocm_bridge.contracts import load_json


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SEEDS = (107, 108)
ROBOT_QPOS_TOLERANCE_RAD = 1e-6
# Genesis stores rigid transforms in float32.  v1 measured maxima of
# 1.476705e-5 m and 1.730323e-4 quaternion component after exact recorded-pose
# placement, so v2 admits the next explicit decimal bounds.
BOWL_POSITION_TOLERANCE_M = 2e-5
BOWL_QUATERNION_TOLERANCE = 2e-4


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        1,
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TypeError(f"{path}:{number} is not a JSON object")
        rows.append(value)
    return rows


def _available_vector(
    item: Any,
    *,
    length: int,
    name: str,
) -> list[float]:
    if not isinstance(item, dict) or item.get("available") is not True:
        raise ValueError(f"{name} is unavailable")
    value = item.get("value")
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"{name} must contain {length} values")
    result = [float(component) for component in value]
    if not all(math.isfinite(component) for component in result):
        raise ValueError(f"{name} contains non-finite values")
    return result


def extract_recorded_configuration(row: dict[str, Any]) -> dict[str, Any]:
    command = row.get("command_target_readback", {})
    full = command.get("full_physical_target_readback_18d", {})
    target = _available_vector(
        full.get("target"),
        length=18,
        name="target",
    )
    readback = _available_vector(
        full.get("readback"),
        length=18,
        name="readback",
    )

    bowls: dict[str, dict[str, list[float]]] = {}
    values = row.get("kinematic_state", {}).get("bowls", [])
    if not isinstance(values, list):
        raise ValueError("kinematic_state.bowls must be a list")
    for bowl in values:
        if not isinstance(bowl, dict) or not isinstance(bowl.get("name"), str):
            continue
        bowls[bowl["name"]] = {
            "position_xyz_m": _available_vector(
                bowl.get("position_xyz_m"),
                length=3,
                name=f"{bowl['name']}.position_xyz_m",
            ),
            "quaternion_wxyz": _available_vector(
                bowl.get("quaternion_wxyz"),
                length=4,
                name=f"{bowl['name']}.quaternion_wxyz",
            ),
        }
    if sorted(bowls) != ["bowl1", "bowl2", "bowl3"]:
        raise ValueError(f"expected bowl1/bowl2/bowl3 poses, got {sorted(bowls)}")

    logged_pairs = row.get("contact_state", {}).get(
        "forbidden_collision_pairs",
        [],
    )
    if not isinstance(logged_pairs, list):
        raise ValueError("forbidden_collision_pairs must be a list")
    return {
        "policy_step": int(row["policy_step"]),
        "target_18d": target,
        "readback_18d": readback,
        "bowls": bowls,
        "logged_forbidden_pairs": sorted(str(pair) for pair in logged_pairs),
    }


def canonical_pair(label_a: str, label_b: str) -> str:
    return " <> ".join(sorted((label_a, label_b)))


def classify_collision_pair(
    label_a: str,
    label_b: str,
) -> dict[str, Any]:
    labels = (label_a, label_b)
    robot = next(
        (label for label in labels if label.startswith("mantis:")),
        None,
    )
    bowl = next(
        (label for label in labels if label.startswith("bowl")),
        None,
    )
    table = next(
        (label for label in labels if label.startswith("table:")),
        None,
    )
    if robot is not None and bowl is not None:
        link = robot.split(":", 2)[1]
        allowed = link.startswith("left_clamp") or link.startswith(
            "right_clamp"
        )
        category = "robot_bowl_allowed_clamp" if allowed else (
            "robot_bowl_forbidden"
        )
        return {
            "category": category,
            "forbidden_by_frozen_classifier": not allowed,
        }
    if robot is not None and table is not None:
        return {
            "category": "robot_table",
            "forbidden_by_frozen_classifier": True,
        }
    if all(label.startswith("mantis:") for label in labels):
        return {
            "category": "robot_self_requires_existing_filter",
            "forbidden_by_frozen_classifier": None,
        }
    return {
        "category": "other",
        "forbidden_by_frozen_classifier": None,
    }


def serialize_detected_pairs(
    pairs: Iterable[Sequence[int]],
    labels: dict[int, str],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for raw_pair in pairs:
        if len(raw_pair) < 2:
            continue
        geom_a, geom_b = sorted((int(raw_pair[0]), int(raw_pair[1])))
        if (geom_a, geom_b) in seen:
            continue
        seen.add((geom_a, geom_b))
        label_a = labels.get(geom_a, f"unresolved_geom:{geom_a}")
        label_b = labels.get(geom_b, f"unresolved_geom:{geom_b}")
        result.append(
            {
                "geom_a": geom_a,
                "geom_b": geom_b,
                "label_a": label_a,
                "label_b": label_b,
                "resolved_pair": canonical_pair(label_a, label_b),
                **classify_collision_pair(label_a, label_b),
            }
        )
    return sorted(
        result,
        key=lambda item: (
            item["resolved_pair"],
            item["geom_a"],
            item["geom_b"],
        ),
    )


def forbidden_robot_bowl_pairs(
    serialized: Sequence[dict[str, Any]],
) -> list[str]:
    return sorted(
        {
            str(item["resolved_pair"])
        for item in serialized
        if item.get("category") == "robot_bowl_forbidden"
        }
    )


def robot_bowl_collision_family(pair: str) -> str | None:
    labels = [label.strip() for label in pair.split("<>")]
    bowl = next(
        (label.split(":", 1)[0] for label in labels if label.startswith("bowl")),
        None,
    )
    robot = next(
        (label for label in labels if label.startswith("mantis:")),
        None,
    )
    if bowl is None or robot is None:
        return None
    parts = robot.split(":")
    if len(parts) < 3:
        return None
    link = parts[1]
    suffix = parts[2]
    if not link.startswith(("left_wrist_", "right_wrist_")):
        return None
    side = link.split("_", 1)[0]
    return f"{bowl} <> mantis:{side}_wrist_*:{suffix}"


def _as_vector(value: Any) -> list[float]:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    result = value.tolist() if hasattr(value, "tolist") else list(value)
    if result and isinstance(result[0], list):
        result = result[0]
    return [float(component) for component in result]


def _max_abs_difference(left: Sequence[float], right: Sequence[float]) -> float:
    return max((abs(a - b) for a, b in zip(left, right)), default=0.0)


def _quaternion_sign_invariant_error(
    observed: Sequence[float],
    expected: Sequence[float],
) -> float:
    direct = _max_abs_difference(observed, expected)
    negated = _max_abs_difference(observed, [-value for value in expected])
    return min(direct, negated)


def evaluate_configuration(
    runtime: GenesisClosedLoopRuntime,
    configuration: dict[str, Any],
    qpos: Sequence[float],
) -> dict[str, Any]:
    for name in ("bowl1", "bowl2", "bowl3"):
        entity = runtime._bowls[name]
        pose = configuration["bowls"][name]
        entity.set_pos(
            pose["position_xyz_m"],
            zero_velocity=True,
            relative=True,
        )
        entity.set_quat(
            pose["quaternion_wxyz"],
            zero_velocity=True,
            relative=True,
        )
    runtime._robot.set_dofs_position(
        qpos,
        dofs_idx_local=runtime._all_indices,
        zero_velocity=True,
    )

    qpos_readback = _read_dofs(runtime._robot, runtime._all_indices)
    robot_error = _max_abs_difference(qpos_readback, qpos)
    bowl_pose_errors: dict[str, dict[str, float]] = {}
    for name in ("bowl1", "bowl2", "bowl3"):
        entity = runtime._bowls[name]
        expected = configuration["bowls"][name]
        observed_position = _as_vector(entity.get_pos())
        observed_quaternion = _as_vector(entity.get_quat())
        bowl_pose_errors[name] = {
            "position_max_abs_m": _max_abs_difference(
                observed_position,
                expected["position_xyz_m"],
            ),
            "quaternion_max_abs_sign_invariant": (
                _quaternion_sign_invariant_error(
                    observed_quaternion,
                    expected["quaternion_wxyz"],
                )
            ),
        }

    detected = runtime._robot.detect_collision()
    if hasattr(detected, "tolist"):
        detected = detected.tolist()
    serialized = serialize_detected_pairs(detected, runtime._labels)
    return {
        "robot_qpos_max_abs_readback_error_rad": robot_error,
        "bowl_pose_readback_errors": bowl_pose_errors,
        "detected_pair_count": len(serialized),
        "detected_pairs": serialized,
        "forbidden_robot_bowl_pairs": forbidden_robot_bowl_pairs(serialized),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint_root", type=Path)
    parser.add_argument("--seed", type=int, required=True, choices=ALLOWED_SEEDS)
    parser.add_argument("--diagnostics-jsonl", type=Path, required=True)
    parser.add_argument(
        "--expected-diagnostics-sha256",
        required=True,
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bowl-asset-root", type=Path, required=True)
    parser.add_argument("--mantis-urdf", type=Path, required=True)
    parser.add_argument("--backend", choices=("cuda",), default="cuda")
    parser.add_argument(
        "--history-length",
        type=int,
        default=3,
        choices=range(1, 6),
    )
    parser.add_argument(
        "--gate",
        type=Path,
        default=ROOT / "configs/act-closedloop-g3-v1.json",
    )
    parser.add_argument(
        "--task",
        type=Path,
        default=ROOT / "configs/task-pack-v1.json",
    )
    parser.add_argument(
        "--port-config",
        type=Path,
        default=ROOT / "configs/mantis-port-config.json",
    )
    parser.add_argument(
        "--fixed-plan",
        type=Path,
        default=ROOT / "configs/fixed-base-plan.json",
    )
    parser.add_argument(
        "--scene-contract",
        type=Path,
        default=ROOT / "configs/stack-bowls-genesis-v1.json",
    )
    parser.add_argument(
        "--camera-contract",
        type=Path,
        default=ROOT / "configs/camera-extrinsics-v1.json",
    )
    parser.add_argument(
        "--source-task",
        type=Path,
        default=ROOT / "configs/source-task-stack-bowls-three.json",
    )
    parser.add_argument(
        "--interface",
        type=Path,
        default=ROOT / "configs/mantis-lerobot-interface-v1.json",
    )
    return parser


def _require_absolute_existing(path: Path, *, directory: bool) -> Path:
    if not path.is_absolute():
        raise ValueError(f"path must be absolute: {path}")
    if directory and not path.is_dir():
        raise ValueError(f"directory does not exist: {path}")
    if not directory and not path.is_file():
        raise ValueError(f"file does not exist: {path}")
    return path


def main() -> int:
    arguments = build_parser().parse_args()
    output_dir = arguments.output_dir
    if not output_dir.is_absolute():
        raise ValueError("--output-dir must be absolute")
    if output_dir.exists():
        raise FileExistsError(f"refusing existing output: {output_dir}")

    checkpoint_root = _require_absolute_existing(
        arguments.checkpoint_root,
        directory=True,
    )
    diagnostics_path = _require_absolute_existing(
        arguments.diagnostics_jsonl,
        directory=False,
    )
    mantis_urdf = _require_absolute_existing(
        arguments.mantis_urdf,
        directory=False,
    )
    bowl_root = _require_absolute_existing(
        arguments.bowl_asset_root,
        directory=True,
    )
    observed_diagnostics_sha = sha256_file(diagnostics_path)
    if observed_diagnostics_sha != arguments.expected_diagnostics_sha256:
        raise ValueError(
            "diagnostic source SHA-256 mismatch: "
            f"{observed_diagnostics_sha} != "
            f"{arguments.expected_diagnostics_sha256}"
        )

    config_paths = {
        "gate": arguments.gate.resolve(),
        "task": arguments.task.resolve(),
        "port": arguments.port_config.resolve(),
        "fixed_plan": arguments.fixed_plan.resolve(),
        "scene": arguments.scene_contract.resolve(),
        "camera": arguments.camera_contract.resolve(),
        "source_task": arguments.source_task.resolve(),
        "interface": arguments.interface.resolve(),
    }
    configs = {name: load_json(path) for name, path in config_paths.items()}
    openloop_relative = configs["gate"]["openloop_admission_contract"]
    openloop_path = (ROOT / openloop_relative).resolve()
    openloop_gate = load_json(openloop_path)
    bowl_urdf = bowl_root / "urdf" / "robotwin_002_bowl_model3.urdf"
    _require_absolute_existing(bowl_urdf.resolve(), directory=False)

    rows = read_jsonl(diagnostics_path)
    if not rows:
        raise ValueError("no diagnostic rows")
    selected_rows = rows[-arguments.history_length :]
    configurations = [
        extract_recorded_configuration(row) for row in selected_rows
    ]
    if configurations[-1]["logged_forbidden_pairs"] == []:
        raise ValueError("terminal positive-control row has no logged collision")

    runtime = GenesisClosedLoopRuntime(
        checkpoint_root=checkpoint_root,
        pretrained_model=checkpoint_root / "pretrained_model",
        mantis_urdf=mantis_urdf,
        bowl_urdf=bowl_urdf,
        gate=configs["gate"],
        task=configs["task"],
        port=configs["port"],
        fixed_plan=configs["fixed_plan"],
        scene_contract=configs["scene"],
        camera_contract=configs["camera"],
        source_task=configs["source_task"],
        interface=configs["interface"],
        seed=arguments.seed,
        backend=arguments.backend,
        port_sha256=sha256_file(config_paths["port"]),
        interface_sha256=sha256_file(config_paths["interface"]),
        fixed_plan_sha256=sha256_file(config_paths["fixed_plan"]),
        openloop_admission_gate=openloop_gate,
        openloop_admission_gate_sha256=sha256_file(openloop_path),
        diagnostic_observability=True,
    )

    evaluations: list[dict[str, Any]] = []
    for configuration in configurations:
        readback_result = evaluate_configuration(
            runtime,
            configuration,
            configuration["readback_18d"],
        )
        target_result = evaluate_configuration(
            runtime,
            configuration,
            configuration["target_18d"],
        )
        evaluations.append(
            {
                "policy_step": configuration["policy_step"],
                "logged_forbidden_pairs": configuration[
                    "logged_forbidden_pairs"
                ],
                "readback_configuration": readback_result,
                "target_configuration": target_result,
            }
        )

    terminal = evaluations[-1]
    logged_terminal_families = sorted(
        {
            family
            for pair in terminal["logged_forbidden_pairs"]
            if (family := robot_bowl_collision_family(pair)) is not None
        }
    )
    target_terminal_families = sorted(
        {
            family
            for pair in terminal["target_configuration"][
                "forbidden_robot_bowl_pairs"
            ]
            if (family := robot_bowl_collision_family(pair)) is not None
        }
    )
    target_terminal_family_match = (
        bool(logged_terminal_families)
        and target_terminal_families == logged_terminal_families
    )
    all_pose_admissions_pass = all(
        result[branch]["robot_qpos_max_abs_readback_error_rad"]
        <= ROBOT_QPOS_TOLERANCE_RAD
        and all(
            errors["position_max_abs_m"] <= BOWL_POSITION_TOLERANCE_M
            and errors["quaternion_max_abs_sign_invariant"]
            <= BOWL_QUATERNION_TOLERANCE
            for errors in result[branch][
                "bowl_pose_readback_errors"
            ].values()
        )
        for result in evaluations
        for branch in ("readback_configuration", "target_configuration")
    )
    target_terminal_pairs = terminal["target_configuration"][
        "forbidden_robot_bowl_pairs"
    ]
    target_collision_steps = [
        result["policy_step"]
        for result in evaluations
        if result["target_configuration"]["forbidden_robot_bowl_pairs"]
    ]
    if not all_pose_admissions_pass:
        causal_result = "invalid_counterfactual"
        status = "FAIL"
    elif target_terminal_family_match:
        causal_result = (
            "commanded_target_contains_logged_bowl_right_wrist_"
            "collision_family"
        )
        status = "PASS"
    elif target_terminal_pairs:
        causal_result = (
            "commanded_target_contains_different_forbidden_"
            "robot_bowl_collision"
        )
        status = "PASS"
    else:
        causal_result = "commanded_target_has_no_forbidden_robot_bowl_collision"
        status = "PASS"

    result = {
        "schema_version": 1,
        "probe_id": "mantis_g3_commanded_target_collision_counterfactual_v2",
        "seed": arguments.seed,
        "development_only": True,
        "official_amd_g3_evidence": False,
        "competition_gate_eligible": False,
        "no_scene_step": True,
        "collision_api": "Genesis RigidEntity.detect_collision",
        "history_length": arguments.history_length,
        "diagnostic_source_path": str(diagnostics_path),
        "diagnostic_source_sha256": observed_diagnostics_sha,
        "source_hashes": {
            **{
                name: sha256_file(path)
                for name, path in sorted(config_paths.items())
            },
            "openloop_admission": sha256_file(openloop_path),
            "mantis_urdf": sha256_file(mantis_urdf),
            "bowl_urdf": sha256_file(bowl_urdf),
        },
        "pose_admission_tolerances": {
            "robot_qpos_max_abs_rad": ROBOT_QPOS_TOLERANCE_RAD,
            "bowl_position_max_abs_m": BOWL_POSITION_TOLERANCE_M,
            "bowl_quaternion_component_max_abs_sign_invariant": (
                BOWL_QUATERNION_TOLERANCE
            ),
            "basis": (
                "v1 measured float32 placement maxima rounded upward to "
                "the next explicit decimal bounds"
            ),
        },
        "all_pose_admissions_pass": all_pose_admissions_pass,
        "logged_terminal_collision_families": logged_terminal_families,
        "target_terminal_collision_families": target_terminal_families,
        "target_terminal_family_match": target_terminal_family_match,
        "readback_terminal_static_pairs": terminal[
            "readback_configuration"
        ]["forbidden_robot_bowl_pairs"],
        "target_collision_steps_in_window": target_collision_steps,
        "causal_result": causal_result,
        "evaluations": evaluations,
        "claim_boundary": (
            "This development probe evaluates static collision state at "
            "recorded readback and target configurations. A post-step "
            "readback may be collision-free after constraint resolution even "
            "when the most recent physics step recorded contact. This is not "
            "an official AMD result, does not integrate dynamics, and does "
            "not establish corrected task success or real-robot safety."
        ),
    }

    output_dir.mkdir(parents=True, exist_ok=False)
    result_path = output_dir / "counterfactual.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "status").write_text(status + "\n", encoding="utf-8")
    (output_dir / "finished_at_utc.txt").write_text(
        datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n",
        encoding="utf-8",
    )
    names = ("counterfactual.json", "finished_at_utc.txt", "status")
    (output_dir / "SHA256SUMS").write_text(
        "".join(
            f"{sha256_file(output_dir / name)}  {name}\n"
            for name in names
        ),
        encoding="utf-8",
    )
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
