"""Verify synchronized dual-arm IK and position control on one Radeon GPU."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time

from parcel_sorter.genesis_env import initialize_genesis
from parcel_sorter.mobile_dataset import (
    MobileBimanualFrame,
    MobileBimanualLeRobotWriter,
)
from parcel_sorter.mobile_bimanual import (
    ARM_JOINT_NAMES,
    BASE_JOINT_NAMES,
    END_EFFECTOR_LINK_NAMES,
    FINGER_JOINT_NAMES,
    build_mobile_bimanual_mjcf,
    joint_dof_indices,
)
from parcel_sorter.provenance import runtime_report


def _flat(values: object) -> list[float]:
    if hasattr(values, "detach"):
        values = values.detach().cpu()  # type: ignore[union-attr]
    if hasattr(values, "reshape"):
        values = values.reshape(-1)  # type: ignore[union-attr]
    return [float(value) for value in values]  # type: ignore[union-attr]


def _collision_pairs(robot: object) -> set[tuple[int, int]]:
    return {
        tuple(sorted((int(left), int(right))))
        for left, right in robot.detect_collision()  # type: ignore[attr-defined]
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("rocm", "cuda"), default="rocm")
    parser.add_argument("--steps", type=int, default=240)
    parser.add_argument("--inward-m", type=float, default=0.08)
    parser.add_argument("--vertical-m", type=float, default=-0.08)
    parser.add_argument("--right-y-offset-m", type=float, default=0.0)
    parser.add_argument(
        "--output", type=Path, default=Path("outputs/mobile-bimanual-arms-v1")
    )
    parser.add_argument(
        "--record-dataset",
        type=Path,
        help="record a 30 Hz RGB-D LeRobot episode under this dataset root",
    )
    parser.add_argument("--hybrid-tools", action="store_true")
    parser.add_argument("--image-size", type=int, default=224)
    args = parser.parse_args()
    if args.steps < 1:
        parser.error("steps must be positive")
    if not 0.0 <= args.inward_m <= 0.60:
        parser.error("inward-m must be in [0, 0.60]")
    if not -0.30 <= args.vertical_m <= 0.30:
        parser.error("vertical-m must be in [-0.30, 0.30]")
    if not -0.20 <= args.right_y_offset_m <= 0.20:
        parser.error("right-y-offset-m must be in [-0.20, 0.20]")

    gs, torch, np = initialize_genesis(args.backend)
    source = Path(gs.__file__).resolve().parent / "assets/xml/franka_sim/bi-franka_panda.xml"
    if args.image_size < 32:
        parser.error("image-size must be at least 32")
    use_hybrid_tools = args.hybrid_tools or args.record_dataset is not None
    asset = build_mobile_bimanual_mjcf(
        source,
        args.output / "mobile_bi_franka.xml",
        left_tri_suction=use_hybrid_tools,
        right_v_cradle=use_hybrid_tools,
    )
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=1.0 / 240.0, substeps=1),
        rigid_options=gs.options.RigidOptions(enable_collision=True),
        show_viewer=False,
    )
    scene.add_entity(gs.morphs.Plane())
    robot = scene.add_entity(gs.morphs.MJCF(file=str(asset)))
    camera = None
    if args.record_dataset is not None:
        camera = scene.add_camera(
            res=(args.image_size, args.image_size),
            pos=(0.0, -2.4, 3.1),
            lookat=(0.0, 0.35, 1.15),
            fov=52,
            GUI=False,
        )
    scene.build()

    base_dofs = np.asarray(joint_dof_indices(robot, BASE_JOINT_NAMES))
    left_arm_dofs = joint_dof_indices(robot, ARM_JOINT_NAMES["left"])
    right_arm_dofs = joint_dof_indices(robot, ARM_JOINT_NAMES["right"])
    arm_dofs = np.asarray((*left_arm_dofs, *right_arm_dofs))
    finger_dofs = np.asarray(
        (
            *joint_dof_indices(robot, FINGER_JOINT_NAMES["left"]),
            *joint_dof_indices(robot, FINGER_JOINT_NAMES["right"]),
        )
    )
    left_ee = robot.get_link(END_EFFECTOR_LINK_NAMES["left"])
    right_ee = robot.get_link(END_EFFECTOR_LINK_NAMES["right"])

    robot.set_dofs_kp(np.zeros(3), base_dofs)
    robot.set_dofs_kv(np.asarray((600.0, 600.0, 300.0)), base_dofs)
    arm_kp = np.asarray((4500.0, 4500.0, 3500.0, 3500.0, 2000.0, 2000.0, 2000.0) * 2)
    arm_kv = np.asarray((450.0, 450.0, 350.0, 350.0, 200.0, 200.0, 200.0) * 2)
    robot.set_dofs_kp(arm_kp, arm_dofs)
    robot.set_dofs_kv(arm_kv, arm_dofs)
    robot.set_dofs_force_range(-np.ones(14) * 90.0, np.ones(14) * 90.0, arm_dofs)
    robot.set_dofs_kp(np.ones(4) * 100.0, finger_dofs)
    robot.set_dofs_kv(np.ones(4) * 10.0, finger_dofs)

    neutral = np.asarray((0.0, -0.35, 0.0, -2.10, 0.0, 1.75, 0.785))
    qpos = np.asarray(_flat(robot.get_qpos()))
    qpos[arm_dofs] = np.tile(neutral, 2)
    qpos[finger_dofs] = 0.04
    robot.set_qpos(qpos)
    robot.control_dofs_position(np.tile(neutral, 2), arm_dofs)
    robot.control_dofs_position(np.ones(4) * 0.04, finger_dofs)
    for _ in range(60):
        scene.step()

    initial_positions = (_flat(left_ee.get_pos()), _flat(right_ee.get_pos()))
    initial_quaternions = (_flat(left_ee.get_quat()), _flat(right_ee.get_quat()))
    center_y = 0.5 * (initial_positions[0][1] + initial_positions[1][1])
    targets = []
    for arm_index, position in enumerate(initial_positions):
        inward_x = args.inward_m if arm_index == 0 else -args.inward_m
        targets.append(
            np.asarray(
                (
                    position[0] + inward_x,
                    position[1]
                    + 0.20 * (center_y - position[1])
                    + (args.right_y_offset_m if arm_index == 1 else 0.0),
                    position[2] + args.vertical_m,
                )
            )
        )

    initial_qpos = np.asarray(_flat(robot.get_qpos()))
    solution, ik_error = robot.inverse_kinematics_multilink(
        links=(left_ee, right_ee),
        poss=tuple(targets),
        quats=tuple(np.asarray(value) for value in initial_quaternions),
        init_qpos=initial_qpos,
        respect_joint_limit=True,
        max_samples=12,
        max_solver_iters=50,
        damping=0.02,
        max_step_size=0.25,
        dofs_idx_local=arm_dofs,
        return_error=True,
    )
    solution_values = np.asarray(_flat(solution))
    ik_error_values = np.asarray(_flat(ik_error)).reshape(2, 6)
    if not np.isfinite(solution_values).all() or not np.isfinite(ik_error_values).all():
        raise RuntimeError("dual-arm IK returned non-finite values")
    initial_collisions = _collision_pairs(robot)
    robot.control_dofs_position(solution_values[arm_dofs], arm_dofs)

    writer = None
    if args.record_dataset is not None:
        writer = MobileBimanualLeRobotWriter(
            args.record_dataset,
            fps=30,
            image_size=(args.image_size, args.image_size),
            include_depth=True,
        )
    physics_per_frame = 8
    task_text = (
        "Move the mobile dual-arm parcel robot to a collision-free synchronized "
        "pregrasp pose while keeping the base stationary."
    )
    action_vector = (
        0.0,
        0.0,
        0.0,
        *targets[0].tolist(),
        *initial_quaternions[0],
        1.0,
        *targets[1].tolist(),
        *initial_quaternions[1],
        1.0,
    )

    max_joint_velocity = 0.0
    torch.cuda.synchronize()
    started = time.perf_counter()
    recorded_frames = 0
    for step_index in range(args.steps):
        scene.step()
        velocity = np.abs(np.asarray(_flat(robot.get_dofs_velocity(arm_dofs))))
        max_joint_velocity = max(max_joint_velocity, float(velocity.max()))
        if writer is not None and (step_index + 1) % physics_per_frame == 0:
            rgb, depth, _, _ = camera.render(rgb=True, depth=True)
            current_qpos = np.asarray(_flat(robot.get_qpos()))
            base_velocity = _flat(robot.get_dofs_velocity(base_dofs))
            left_pose = (*_flat(left_ee.get_pos()), *_flat(left_ee.get_quat()))
            right_pose = (*_flat(right_ee.get_pos()), *_flat(right_ee.get_quat()))
            state_vector = (
                *current_qpos[base_dofs].tolist(),
                *base_velocity,
                *current_qpos[np.asarray(left_arm_dofs)].tolist(),
                *current_qpos[np.asarray(joint_dof_indices(robot, FINGER_JOINT_NAMES["left"]))].tolist(),
                *current_qpos[np.asarray(right_arm_dofs)].tolist(),
                *current_qpos[np.asarray(joint_dof_indices(robot, FINGER_JOINT_NAMES["right"]))].tolist(),
                *left_pose,
                *right_pose,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            )
            writer.add_frame(
                MobileBimanualFrame(
                    frame_index=recorded_frames,
                    timestamp_seconds=recorded_frames / 30.0,
                    stage="pregrasp",
                    state=tuple(float(value) for value in state_vector),
                    action=tuple(float(value) for value in action_vector),
                    privileged_state=(0.0,) * 7,
                    task=task_text,
                    rgb=np.asarray(rgb)[..., :3],
                    depth=np.asarray(depth, dtype=np.float32),
                )
            )
            recorded_frames += 1
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - started

    if writer is not None:
        if recorded_frames < 1:
            raise RuntimeError("recording produced no frames; use at least 8 physics steps")
        writer.save_episode()
        writer.finalize()

    final_positions = (_flat(left_ee.get_pos()), _flat(right_ee.get_pos()))
    position_errors = [math.dist(actual, target) for actual, target in zip(final_positions, targets)]
    final_collisions = _collision_pairs(robot)
    new_collisions = sorted(final_collisions - initial_collisions)
    final_qpos = np.asarray(_flat(robot.get_qpos()))
    max_arm_qpos_error = float(
        np.abs(final_qpos[arm_dofs] - solution_values[arm_dofs]).max()
    )
    base_drift = float(np.linalg.norm(final_qpos[base_dofs] - initial_qpos[base_dofs]))
    success = (
        max(position_errors) <= 0.025
        and base_drift <= 0.02
        and not new_collisions
        and max_joint_velocity <= 4.0
    )
    payload = {
        "runtime": runtime_report(),
        "upstream_asset": "Genesis franka_sim Bi-Franka, Apache-2.0",
        "dof_count": int(robot.n_dofs),
        "arm_dof_count": len(arm_dofs),
        "finger_dof_count": len(finger_dofs),
        "end_effectors": END_EFFECTOR_LINK_NAMES,
        "initial_positions_m": initial_positions,
        "target_positions_m": [target.tolist() for target in targets],
        "requested_inward_m": args.inward_m,
        "requested_vertical_m": args.vertical_m,
        "requested_right_y_offset_m": args.right_y_offset_m,
        "final_positions_m": final_positions,
        "ik_error": ik_error_values.tolist(),
        "final_position_error_m": position_errors,
        "base_drift_norm": base_drift,
        "max_arm_joint_velocity_rad_s": max_joint_velocity,
        "max_arm_qpos_error_rad": max_arm_qpos_error,
        "initial_collision_pairs": sorted(initial_collisions),
        "final_collision_pairs": sorted(final_collisions),
        "new_collision_pairs": new_collisions,
        "steps": args.steps,
        "elapsed_seconds": elapsed,
        "simulation_fps": args.steps / max(elapsed, 1e-12),
        "hybrid_tools": use_hybrid_tools,
        "recorded_frames": recorded_frames,
        "mobile_state_dim": 43,
        "mobile_action_dim": 19,
        "success": success,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload))
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
