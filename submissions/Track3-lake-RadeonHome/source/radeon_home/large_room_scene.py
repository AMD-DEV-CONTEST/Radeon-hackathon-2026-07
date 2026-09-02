"""Step 3: execute a two-leg semantic transport route in a 6 x 6 metre room."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import imageio.v2 as imageio
import numpy as np

import genesis as gs

from .mobile_scene import _joint_dof_index, _prepare_mobile_urdf
from .spatial_tasks import (
    SEMANTIC_DOCKS,
    build_room_grid,
    generate_task,
    plan_transport,
)


ARM_POSE = np.array([0.0, -0.3, 0.0, -2.0, 0.0, 1.7, 0.79])


def _add_box(scene, *, size, pos, color, fixed=True, friction=1.0):
    return scene.add_entity(
        morph=gs.morphs.Box(size=size, pos=pos, fixed=fixed),
        material=gs.materials.Rigid(rho=300.0, friction=friction),
        surface=gs.surfaces.Default(color=color),
    )


def _build_large_room(
    *,
    start_xy: tuple[float, float],
    generated_asset_dir: Path,
    pick_zone: str | None = None,
):
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=0.01, substeps=2),
        rigid_options=gs.options.RigidOptions(
            dt=0.01,
            constraint_solver=gs.constraint_solver.Newton,
            enable_collision=True,
            enable_joint_limit=True,
        ),
        show_viewer=False,
        profiling_options=gs.options.ProfilingOptions(show_FPS=False),
    )
    scene.add_entity(gs.morphs.Plane())

    wall_color = (0.72, 0.77, 0.82, 1.0)
    for size, pos in (
        ((6.2, 0.08, 0.45), (0.0, -3.06, 0.225)),
        ((6.2, 0.08, 0.45), (0.0, 3.06, 0.225)),
        ((0.08, 6.2, 0.45), (-3.06, 0.0, 0.225)),
        ((0.08, 6.2, 0.45), (3.06, 0.0, 0.225)),
    ):
        _add_box(scene, size=size, pos=pos, color=wall_color)

    obstacle_color = (0.35, 0.42, 0.50, 1.0)
    _add_box(
        scene,
        size=(1.40, 0.70, 0.65),
        pos=(0.0, 0.0, 0.325),
        color=obstacle_color,
    )
    _add_box(
        scene,
        size=(0.50, 0.50, 0.75),
        pos=(-1.55, 0.25, 0.375),
        color=obstacle_color,
    )
    _add_box(
        scene,
        size=(0.50, 0.50, 0.75),
        pos=(1.55, 0.25, 0.375),
        color=obstacle_color,
    )

    # Furniture is placed behind its free docking pose, toward the nearest wall.
    furniture_colors = {
        "desk": (0.62, 0.46, 0.30, 1.0),
        "coffee_table": (0.70, 0.52, 0.34, 1.0),
        "bedside_table": (0.55, 0.39, 0.26, 1.0),
        "door_tray": (0.46, 0.32, 0.76, 1.0),
        "storage_bin": (0.18, 0.62, 0.36, 1.0),
        "trash_bin": (0.20, 0.48, 0.68, 1.0),
    }
    pick_object = None
    for name, (x, y) in SEMANTIC_DOCKS.items():
        marker_color = furniture_colors[name]
        _add_box(
            scene,
            size=(0.34, 0.34, 0.012),
            pos=(x, y, 0.006),
            color=marker_color,
        )
        # Keep enough clearance for the mobile base to occupy the docking marker.
        # The first GPU run used 0.58 m and physically stopped 0.555 m short at
        # the bedside table, revealing that the visual furniture overlapped the
        # robot footprint even though the planner considered the dock free.
        furniture_y = y + (0.85 if y > 0 else -0.75)
        if y > 0:
            size = (0.78, 0.45, 0.08)
            pos = (x, furniture_y, 0.74)
        else:
            size = (0.48, 0.38, 0.45)
            pos = (x, furniture_y, 0.225)
        _add_box(scene, size=size, pos=pos, color=marker_color)
        if name == pick_zone:
            object_y = y + (0.64 if y > 0 else -0.54)
            pick_object = _add_box(
                scene,
                size=(0.025, 0.055, 0.090),
                pos=(x, object_y, pos[2] + size[2] / 2 + 0.045),
                color=(0.94, 0.36, 0.12, 1.0),
                fixed=False,
                friction=5.0,
            )

    mobile_urdf = _prepare_mobile_urdf(generated_asset_dir)
    robot = scene.add_entity(
        gs.morphs.URDF(
            file=str(mobile_urdf),
            pos=(start_xy[0], start_xy[1], 0.30),
            fixed=True,
        ),
        # Higher contact friction at the finger/object interface reduces
        # payload slip without introducing a kinematic grasp constraint.
        material=gs.materials.Rigid(friction=5.0),
    )
    camera = scene.add_camera(
        res=(1280, 720),
        pos=(6.4, -7.0, 7.5),
        lookat=(0.0, 0.0, 0.25),
        fov=48,
        GUI=False,
    )
    grasp_camera = None
    if pick_zone is not None:
        px, py = SEMANTIC_DOCKS[pick_zone]
        sign = 1.0 if py > 0 else -1.0
        grasp_camera = scene.add_camera(
            res=(1280, 720),
            pos=(px + 1.35, py - 0.55 * sign, 1.65),
            lookat=(px, py + 0.62 * sign, 0.90),
            fov=36,
            GUI=False,
        )
    scene.build()
    return scene, robot, camera, grasp_camera, pick_object


def _configure_robot(robot):
    base_names = ("base_slider_x", "base_slider_y", "base_rotate_z")
    base_indices = [_joint_dof_index(robot, name) for name in base_names]
    arm_indices = [
        _joint_dof_index(robot, f"panda_joint{index}") for index in range(1, 8)
    ]
    finger_indices = [
        _joint_dof_index(robot, name)
        for name in ("panda_finger_joint1", "panda_finger_joint2")
    ]
    qpos = robot.get_qpos().detach().cpu().numpy().reshape(-1)
    qpos[arm_indices] = ARM_POSE
    qpos[finger_indices] = 0.04
    robot.set_qpos(qpos)

    kp = np.full(qpos.shape, 1400.0)
    kv = np.full(qpos.shape, 140.0)
    force_min = np.full(qpos.shape, -600.0)
    force_max = np.full(qpos.shape, 600.0)
    kp[arm_indices] = np.array([4500, 4500, 3500, 3500, 2000, 2000, 2000])
    kv[arm_indices] = np.array([450, 450, 350, 350, 200, 200, 200])
    force_min[arm_indices] = np.array([-87, -87, -87, -87, -12, -12, -12])
    force_max[arm_indices] = np.array([87, 87, 87, 87, 12, 12, 12])
    kp[finger_indices] = 800.0
    kv[finger_indices] = 80.0
    robot.set_dofs_kp(kp)
    robot.set_dofs_kv(kv)
    robot.set_dofs_force_range(force_min, force_max)
    return qpos, base_indices


def _measured_xy(robot) -> np.ndarray:
    return (
        robot.get_link("base")
        .get_pos()
        .detach()
        .cpu()
        .numpy()
        .reshape(-1)[:2]
    )


def run_large_room_task(
    *,
    seed: int,
    output_dir: Path,
    steps_per_cell: int = 25,
) -> dict:
    grid = build_room_grid()
    task = generate_task(seed, grid)
    plan = plan_transport(task, grid)
    scene, robot, camera, _, _ = _build_large_room(
        start_xy=task.start_xy,
        generated_asset_dir=output_dir / "generated_assets",
    )
    qpos, base_indices = _configure_robot(robot)
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = [camera.render(rgb=True)[0]]
    start = np.asarray(task.start_xy)
    trajectory = []
    phase_measurements = {}

    phases = (
        ("pickup", plan.pickup_path, SEMANTIC_DOCKS[task.source_zone]),
        ("delivery", plan.delivery_path, SEMANTIC_DOCKS[task.target_zone]),
    )
    for phase_name, cells, target_xy in phases:
        current_world = grid.cell_to_world(cells[0])
        for cell in cells[1:]:
            next_world = grid.cell_to_world(cell)
            delta = np.asarray(next_world) - np.asarray(current_world)
            yaw = float(np.arctan2(delta[1], delta[0]))
            for alpha in np.linspace(0.0, 1.0, steps_per_cell):
                world_xy = (
                    np.asarray(current_world) * (1.0 - alpha)
                    + np.asarray(next_world) * alpha
                )
                qpos[base_indices[0]] = world_xy[0] - start[0]
                qpos[base_indices[1]] = world_xy[1] - start[1]
                qpos[base_indices[2]] = yaw
                robot.control_dofs_position(qpos)
                scene.step()
                measured = _measured_xy(robot)
                trajectory.append(
                    {
                        "phase": phase_name,
                        "command_x": float(world_xy[0]),
                        "command_y": float(world_xy[1]),
                        "measured_x": float(measured[0]),
                        "measured_y": float(measured[1]),
                    }
                )
                if len(trajectory) % 50 == 0:
                    frames.append(camera.render(rgb=True)[0])
            current_world = next_world

        for _ in range(300):
            robot.control_dofs_position(qpos)
            scene.step()
        measured = _measured_xy(robot)
        target = np.asarray(target_xy)
        phase_measurements[phase_name] = {
            "target_xy": target.tolist(),
            "measured_xy": measured.tolist(),
            "error_m": float(np.linalg.norm(measured - target)),
        }
        frames.extend([camera.render(rgb=True)[0]] * 8)

    imageio.imwrite(output_dir / "large_room_final.png", frames[-1])
    imageio.mimsave(output_dir / "large_room_task.mp4", frames, fps=8)
    result = {
        "backend": "gpu",
        "task": {
            "seed": task.seed,
            "object_id": task.object_id,
            "source_zone": task.source_zone,
            "target_zone": task.target_zone,
            "start_xy": task.start_xy,
        },
        "planned_distance_m": plan.total_distance_m,
        "trajectory_samples": len(trajectory),
        "phase_measurements": phase_measurements,
        "success": all(
            measurement["error_m"] <= 0.10
            for measurement in phase_measurements.values()
        ),
    }
    (output_dir / "large_room_result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one large-room transport route")
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs/large-room")
    )
    parser.add_argument("--steps-per-cell", type=int, default=25)
    args = parser.parse_args()
    gs.init(backend=gs.gpu)
    run_large_room_task(
        seed=args.seed,
        output_dir=args.output_dir,
        steps_per_cell=args.steps_per_cell,
    )


if __name__ == "__main__":
    main()
