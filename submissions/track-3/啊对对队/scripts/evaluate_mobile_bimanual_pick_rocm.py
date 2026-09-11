"""Evaluate bilateral contact and cooperative lift with the mobile Bi-Franka."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time

from parcel_sorter.genesis_env import initialize_genesis
from parcel_sorter.mobile_bimanual import (
    ARM_JOINT_NAMES,
    BASE_JOINT_NAMES,
    END_EFFECTOR_LINK_NAMES,
    FINGER_JOINT_NAMES,
    build_mobile_bimanual_mjcf,
    joint_dof_indices,
)
from parcel_sorter.provenance import runtime_report
from parcel_sorter.suction import quaternion_multiply, rotate_vector


def _flat(values: object) -> list[float]:
    if hasattr(values, "detach"):
        values = values.detach().cpu()  # type: ignore[union-attr]
    if hasattr(values, "reshape"):
        values = values.reshape(-1)  # type: ignore[union-attr]
    return [float(value) for value in values]  # type: ignore[union-attr]


def _normalized(values: list[float]) -> tuple[float, float, float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 1e-8:
        raise RuntimeError("tool axis has zero length")
    return tuple(value / norm for value in values)  # type: ignore[return-value]


def _contact_snapshot(robot: object, parcel: object, finger_links: dict[str, set[int]], torch: object) -> dict[str, object]:
    contacts = robot.get_contacts(with_entity=parcel)  # type: ignore[attr-defined]
    forces = contacts["force_a"]
    if int(forces.numel()) == 0:
        return {"left": False, "right": False, "max_force_n": 0.0, "count": 0}
    magnitudes = torch.linalg.vector_norm(forces, dim=-1)
    valid = contacts.get("valid_mask")
    if valid is None:
        valid = magnitudes > 0
    else:
        valid = valid & (magnitudes > 0)
    link_a = contacts["link_a"]
    link_b = contacts["link_b"]
    result: dict[str, object] = {"count": int(valid.sum().item())}
    for arm in ("left", "right"):
        mask = torch.zeros_like(valid, dtype=torch.bool)
        for link_id in finger_links[arm]:
            mask |= (link_a == link_id) | (link_b == link_id)
        result[arm] = bool((mask & valid).any().item())
    result["max_force_n"] = float(magnitudes[valid].max().item()) if bool(valid.any().item()) else 0.0
    return result


def _solve_and_move(
    *,
    robot: object,
    scene: object,
    links: tuple[object, object],
    positions: tuple[object, object],
    quaternions: tuple[object, object],
    arm_dofs: object,
    np: object,
    steps: int,
) -> tuple[list[list[float]], list[float]]:
    qpos = np.asarray(_flat(robot.get_qpos()))
    solution, error = robot.inverse_kinematics_multilink(
        links=links,
        poss=positions,
        quats=quaternions,
        init_qpos=qpos,
        respect_joint_limit=True,
        max_samples=16,
        max_solver_iters=60,
        damping=0.02,
        max_step_size=0.20,
        dofs_idx_local=arm_dofs,
        return_error=True,
    )
    solution_values = np.asarray(_flat(solution))
    error_values = np.asarray(_flat(error)).reshape(2, 6)
    if not np.isfinite(solution_values).all() or not np.isfinite(error_values).all():
        raise RuntimeError("dual-arm IK returned non-finite values")
    start_arm_qpos = qpos[arm_dofs].copy()
    target_arm_qpos = solution_values[arm_dofs]
    for step in range(steps):
        alpha = min(1.0, (step + 1) / max(1, int(steps * 0.75)))
        robot.control_dofs_position(
            start_arm_qpos + alpha * (target_arm_qpos - start_arm_qpos),
            arm_dofs,
        )
        scene.step()
    actual = [
        math.dist(_flat(link.get_pos()), _flat(target))
        for link, target in zip(links, positions)
    ]
    return error_values.tolist(), actual


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("rocm", "cuda"), default="rocm")
    parser.add_argument("--output", type=Path, default=Path("outputs/mobile-bimanual-pick-v1"))
    parser.add_argument("--force-limit-n", type=float, default=10.0)
    args = parser.parse_args()
    if not 1.0 <= args.force_limit_n <= 20.0:
        parser.error("force-limit-n must be in [1, 20]")

    gs, torch, np = initialize_genesis(args.backend)
    source = Path(gs.__file__).resolve().parent / "assets/xml/franka_sim/bi-franka_panda.xml"
    asset = build_mobile_bimanual_mjcf(source, args.output / "mobile_bi_franka.xml")
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=1.0 / 240.0, substeps=1),
        rigid_options=gs.options.RigidOptions(enable_collision=True),
        show_viewer=False,
    )
    scene.add_entity(gs.morphs.Plane())
    scene.add_entity(gs.morphs.Box(size=(1.20, 0.70, 0.10), pos=(0.0, 0.36, 1.00), fixed=True))
    parcel_size = (0.50, 0.06, 0.06)
    parcel_initial = (0.0, 0.36, 1.08)
    parcel = scene.add_entity(gs.morphs.Box(size=parcel_size, pos=parcel_initial))
    robot = scene.add_entity(gs.morphs.MJCF(file=str(asset)))
    scene.build()

    base_dofs = np.asarray(joint_dof_indices(robot, BASE_JOINT_NAMES))
    left_arm = joint_dof_indices(robot, ARM_JOINT_NAMES["left"])
    right_arm = joint_dof_indices(robot, ARM_JOINT_NAMES["right"])
    arm_dofs = np.asarray((*left_arm, *right_arm))
    finger_dofs_by_arm = {
        arm: joint_dof_indices(robot, FINGER_JOINT_NAMES[arm]) for arm in ("left", "right")
    }
    finger_dofs = np.asarray((*finger_dofs_by_arm["left"], *finger_dofs_by_arm["right"]))
    finger_links = {
        "left": {int(robot.get_link("panda0_leftfinger").idx), int(robot.get_link("panda0_rightfinger").idx)},
        "right": {int(robot.get_link("panda1_leftfinger").idx), int(robot.get_link("panda1_rightfinger").idx)},
    }
    links = (
        robot.get_link(END_EFFECTOR_LINK_NAMES["left"]),
        robot.get_link(END_EFFECTOR_LINK_NAMES["right"]),
    )

    robot.set_dofs_kp(np.zeros(3), base_dofs)
    robot.set_dofs_kv(np.asarray((600.0, 600.0, 300.0)), base_dofs)
    robot.set_dofs_kp(np.asarray((4500.0, 4500.0, 3500.0, 3500.0, 2000.0, 2000.0, 2000.0) * 2), arm_dofs)
    robot.set_dofs_kv(np.asarray((450.0, 450.0, 350.0, 350.0, 200.0, 200.0, 200.0) * 2), arm_dofs)
    robot.set_dofs_force_range(-np.ones(14) * 90.0, np.ones(14) * 90.0, arm_dofs)
    robot.set_dofs_kp(np.ones(4) * 100.0, finger_dofs)
    robot.set_dofs_kv(np.ones(4) * 10.0, finger_dofs)
    robot.set_dofs_force_range(-np.ones(4) * 20.0, np.ones(4) * 20.0, finger_dofs)

    neutral = np.asarray((0.0, -0.35, 0.0, -2.10, 0.0, 1.75, 0.785))
    qpos = np.asarray(_flat(robot.get_qpos()))
    qpos[arm_dofs] = np.tile(neutral, 2)
    qpos[finger_dofs] = 0.04
    robot.set_qpos(qpos)
    robot.control_dofs_position(np.tile(neutral, 2), arm_dofs)
    robot.control_dofs_position(np.ones(4) * 0.04, finger_dofs)
    for _ in range(90):
        scene.step()

    initial_quaternions = tuple(tuple(_flat(link.get_quat())) for link in links)
    half_turn = math.sqrt(0.5)
    world_rotations = (
        (half_turn, 0.0, 0.0, -half_turn),
        (half_turn, 0.0, 0.0, half_turn),
    )
    quaternions = tuple(
        np.asarray(quaternion_multiply(rotation, quaternion))
        for rotation, quaternion in zip(world_rotations, initial_quaternions)
    )
    axes = tuple(
        _normalized(list(rotate_vector(tuple(quat.tolist()), (0.0, 0.0, 1.0))))
        for quat in quaternions
    )
    center = np.asarray(parcel_initial)
    half_x = parcel_size[0] / 2.0
    surfaces = (center + np.asarray((-half_x, 0.0, 0.0)), center + np.asarray((half_x, 0.0, 0.0)))
    # The upstream gripper link origin trails the effective finger contact zone.
    # A 0.10 m command offset compensates the measured loaded-PD tracking lag.
    tip_offset = 0.10
    contact_targets = tuple(surface - np.asarray(axis) * tip_offset for surface, axis in zip(surfaces, axes))
    pregrasp_targets = tuple(target - np.asarray(axis) * 0.08 for target, axis in zip(contact_targets, axes))

    trace: list[dict[str, object]] = []
    started = time.perf_counter()
    pregrasp_ik, pregrasp_error = _solve_and_move(
        robot=robot, scene=scene, links=links, positions=pregrasp_targets,
        quaternions=quaternions, arm_dofs=arm_dofs, np=np, steps=240,
    )
    trace.append({"stage": "pregrasp", "ik_error": pregrasp_ik, "tracking_error_m": pregrasp_error})
    approach_ik, approach_error = _solve_and_move(
        robot=robot, scene=scene, links=links, positions=contact_targets,
        quaternions=quaternions, arm_dofs=arm_dofs, np=np, steps=180,
    )
    trace.append({"stage": "approach", "ik_error": approach_ik, "tracking_error_m": approach_error})

    max_force = 0.0
    contact = _contact_snapshot(robot, parcel, finger_links, torch)
    for force_step in range(1, int(args.force_limit_n) + 1):
        robot.control_dofs_force(np.ones(4) * -float(force_step), finger_dofs)
        for _ in range(12):
            scene.step()
        contact = _contact_snapshot(robot, parcel, finger_links, torch)
        max_force = max(max_force, float(contact["max_force_n"]))
        if bool(contact["left"]) and bool(contact["right"]):
            break
    trace.append({"stage": "grasp", "contact": contact, "command_force_n": float(force_step)})

    bilateral = bool(contact["left"]) and bool(contact["right"])
    lift_errors: list[float] | None = None
    if bilateral and max_force <= 35.0:
        lift_targets = tuple(target + np.asarray((0.0, 0.0, 0.12)) for target in contact_targets)
        lift_ik, lift_errors = _solve_and_move(
            robot=robot, scene=scene, links=links, positions=lift_targets,
            quaternions=quaternions, arm_dofs=arm_dofs, np=np, steps=240,
        )
        trace.append({"stage": "lift", "ik_error": lift_ik, "tracking_error_m": lift_errors})
        contact = _contact_snapshot(robot, parcel, finger_links, torch)
        max_force = max(max_force, float(contact["max_force_n"]))

    final_parcel = _flat(parcel.get_pos())
    lift_delta = final_parcel[2] - parcel_initial[2]
    success = bilateral and lift_delta >= 0.06 and max_force <= 35.0
    payload = {
        "runtime": runtime_report(),
        "task": "Cooperatively grasp and lift a long rigid parcel with both Panda arms.",
        "parcel_size_m": parcel_size,
        "parcel_initial_position_m": parcel_initial,
        "tool_axes_world": axes,
        "pregrasp_targets_m": [value.tolist() for value in pregrasp_targets],
        "contact_targets_m": [value.tolist() for value in contact_targets],
        "bilateral_contact": bilateral,
        "max_contact_force_n": max_force,
        "final_contact": contact,
        "final_parcel_position_m": final_parcel,
        "parcel_lift_delta_m": lift_delta,
        "elapsed_seconds": time.perf_counter() - started,
        "trace": trace,
        "success": success,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload))
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
