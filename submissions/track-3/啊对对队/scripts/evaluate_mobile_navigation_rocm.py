"""Evaluate closed-loop obstacle detouring for the wheeled Bi-Franka."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from parcel_sorter.genesis_env import initialize_genesis
from parcel_sorter.mobile_bimanual import (
    BASE_JOINT_NAMES,
    PlanarObstacle,
    build_mobile_bimanual_mjcf,
    planar_base_command,
    plan_detour_waypoints,
)
from parcel_sorter.parcel_routing import classify_and_route, routing_task_text
from parcel_sorter.provenance import runtime_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("rocm", "cuda"), default="rocm")
    parser.add_argument("--output", type=Path, default=Path("outputs/mobile-navigation-v1"))
    parser.add_argument("--max-control-steps", type=int, default=900)
    args = parser.parse_args()
    if args.max_control_steps < 1:
        parser.error("max-control-steps must be positive")
    gs, _, np = initialize_genesis(args.backend)
    source = Path(gs.__file__).resolve().parent / "assets/xml/franka_sim/bi-franka_panda.xml"
    asset = build_mobile_bimanual_mjcf(source, args.output / "mobile_bi_franka.xml")
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=1.0 / 240.0, substeps=1),
        rigid_options=gs.options.RigidOptions(enable_collision=True),
        show_viewer=False,
    )
    scene.add_entity(gs.morphs.Plane())
    obstacle = PlanarObstacle((0.65, 0.0), (0.12, 0.22))
    scene.add_entity(
        gs.morphs.Box(size=(0.24, 0.44, 0.60), pos=(0.65, 0.0, 0.30), fixed=True)
    )
    robot = scene.add_entity(gs.morphs.MJCF(file=str(asset)))
    scene.build()
    base_dofs = np.asarray(
        [robot.get_joint(name).dofs_idx_local[0] for name in BASE_JOINT_NAMES]
    )
    robot.set_dofs_kp(np.zeros(3), base_dofs)
    robot.set_dofs_kv(np.asarray((600.0, 600.0, 300.0)), base_dofs)
    robot.set_dofs_force_range(
        np.asarray((-2500.0, -2500.0, -1200.0)),
        np.asarray((2500.0, 2500.0, 1200.0)),
        base_dofs,
    )
    route = classify_and_route(
        profile_id="electronics_box",
        shape="box",
        handling_class="parallel_jaw",
        dimensions_m=(0.20, 0.10, 0.08),
        mass_kg=0.70,
    )
    destination_xy = (1.30, 0.0)
    waypoints = plan_detour_waypoints(
        (0.0, 0.0),
        destination_xy,
        (obstacle,),
        clearance_m=0.38,
    )
    waypoint_index = 0
    trace = []
    for control_step in range(args.max_control_steps):
        qpos = robot.get_qpos()
        pose = tuple(float(qpos[index]) for index in base_dofs)
        command = planar_base_command(
            pose,
            waypoints[waypoint_index],
            max_linear_speed_m_s=0.35,
            max_yaw_rate_rad_s=1.0,
            position_tolerance_m=0.045,
        )
        if command.reached:
            waypoint_index += 1
            if waypoint_index >= len(waypoints):
                break
            continue
        robot.control_dofs_velocity(
            np.asarray(
                (
                    command.velocity_x_m_s,
                    command.velocity_y_m_s,
                    command.yaw_rate_rad_s,
                )
            ),
            base_dofs,
        )
        for _ in range(8):
            scene.step()
        if control_step % 10 == 0:
            trace.append(
                {
                    "control_step": control_step,
                    "pose_xy_yaw": pose,
                    "waypoint_index": waypoint_index,
                    "distance_to_waypoint_m": command.distance_to_goal_m,
                }
            )
    robot.control_dofs_velocity(np.zeros(3), base_dofs)
    final_qpos = robot.get_qpos()
    final_pose = tuple(float(final_qpos[index]) for index in base_dofs)
    final_error = math.dist(final_pose[:2], destination_xy)
    success = waypoint_index >= len(waypoints) and final_error <= 0.06
    payload = {
        "runtime": runtime_report(),
        "task": routing_task_text("electronics_box", route),
        "route": route.__dict__,
        "waypoints_xy_m": waypoints,
        "obstacle": {
            "center_xy_m": obstacle.center_xy_m,
            "half_extent_xy_m": obstacle.half_extent_xy_m,
            "planning_clearance_m": 0.38,
        },
        "success": success,
        "final_pose_xy_yaw": final_pose,
        "final_error_m": final_error,
        "control_steps": control_step + 1,
        "trace": trace,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload))
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
