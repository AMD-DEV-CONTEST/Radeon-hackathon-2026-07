"""Step 1: navigate an official Genesis mobile Franka to a docking pose."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import imageio.v2 as imageio
import numpy as np

import genesis as gs

from .navigation import GridMap, astar, simplify_path


START_XY = (-0.50, -0.50)
DOCK_XY = (0.50, 0.00)
GRID = GridMap(
    width=9,
    height=7,
    resolution_m=0.25,
    origin_xy=(-1.0, -0.75),
    # A central chair-shaped obstacle, inflated by one grid cell for clearance.
    occupied=frozenset({(4, 2), (4, 3), (4, 4), (5, 2), (5, 3), (5, 4)}),
)


def _add_box(scene, *, size, pos, color, fixed=True):
    return scene.add_entity(
        morph=gs.morphs.Box(size=size, pos=pos, fixed=fixed),
        surface=gs.surfaces.Default(color=color),
    )


def _prepare_mobile_urdf(output_dir: Path) -> Path:
    """Create a Genesis-1.2-compatible copy of its official mobile Panda URDF.

    The bundled URDF omits ``<dynamics>`` on movable joints. Genesis 1.2.3's
    legacy fallback parser then produces an object-typed friction array and
    fails during scene build. The upstream asset remains untouched.
    """

    genesis_spec = importlib.util.find_spec("genesis")
    if genesis_spec is None or genesis_spec.origin is None:
        raise RuntimeError("Genesis is not installed")
    genesis_root = Path(genesis_spec.origin).resolve().parent
    source = (
        genesis_root / "assets" / "urdf" / "panda_bullet" / "panda_slider_mobile.urdf"
    )
    mesh_root = source.parent / "meshes"
    tree = ET.parse(source)
    root = tree.getroot()
    # The upstream mobile wrapper represents the planar base with empty
    # intermediate links. Genesis' legacy parser otherwise assigns gs.EPS mass
    # to those movable bodies, which makes the constrained chain numerically
    # fragile when the arm accelerates while holding a payload.
    for link_name in ("basex", "basey", "basez", "base"):
        link = root.find(f"./link[@name='{link_name}']")
        if link is None or link.find("inertial") is not None:
            continue
        inertial = ET.SubElement(link, "inertial")
        ET.SubElement(inertial, "origin", {"xyz": "0 0 0", "rpy": "0 0 0"})
        mass = "20.0" if link_name == "base" else "1.0"
        ET.SubElement(inertial, "mass", {"value": mass})
        inertia = "0.25" if link_name == "base" else "0.01"
        ET.SubElement(
            inertial,
            "inertia",
            {
                "ixx": inertia,
                "ixy": "0",
                "ixz": "0",
                "iyy": inertia,
                "iyz": "0",
                "izz": inertia,
            },
        )
    for joint in root.findall("joint"):
        if joint.attrib.get("type") != "fixed":
            dynamics = joint.find("dynamics")
            if dynamics is None:
                dynamics = ET.SubElement(joint, "dynamics")
            dynamics.attrib.setdefault("damping", "0.1")
            dynamics.attrib.setdefault("friction", "0.0")
        if joint.attrib.get("name") in {"base_slider_x", "base_slider_y"}:
            limit = joint.find("limit")
            if limit is not None:
                limit.attrib["lower"] = "-6.0"
                limit.attrib["upper"] = "6.0"
        elif joint.attrib.get("name") == "base_rotate_z":
            limit = joint.find("limit")
            if limit is not None:
                limit.attrib["lower"] = "-3.2"
                limit.attrib["upper"] = "3.2"
    # Port the five fingertip collision pads from Genesis'
    # xml/franka_emika_panda/hand.xml into the mobile URDF. MJCF box sizes are
    # half-extents, so the URDF sizes below are doubled. The official visual
    # meshes remain unchanged.
    official_pad_boxes = (
        ("0 0.0055 0.0445", "0.017 0.008 0.017"),
        ("0.0055 0.002 0.05", "0.006 0.004 0.006"),
        ("-0.0055 0.002 0.05", "0.006 0.004 0.006"),
        ("0.0055 0.002 0.0395", "0.006 0.004 0.007"),
        ("-0.0055 0.002 0.0395", "0.006 0.004 0.007"),
    )
    for link_name, yaw in (
        ("panda_leftfinger", "0"),
        ("panda_rightfinger", "3.14159265359"),
    ):
        link = root.find(f"./link[@name='{link_name}']")
        if link is None:
            continue
        for collision in link.findall("collision"):
            link.remove(collision)
        for xyz, size in official_pad_boxes:
            collision = ET.SubElement(link, "collision")
            ET.SubElement(
                collision,
                "origin",
                {"xyz": xyz, "rpy": f"0 0 {yaw}"},
            )
            geometry = ET.SubElement(collision, "geometry")
            ET.SubElement(geometry, "box", {"size": size})
        inertial = link.find("inertial")
        if inertial is not None:
            mass = inertial.find("mass")
            inertia = inertial.find("inertia")
            if mass is not None:
                mass.attrib["value"] = "0.015"
            if inertia is not None:
                inertia.attrib.update(
                    {
                        "ixx": "2.375e-6",
                        "ixy": "0",
                        "ixz": "0",
                        "iyy": "2.375e-6",
                        "iyz": "0",
                        "izz": "7.5e-7",
                    }
                )
    for mesh in root.findall(".//mesh"):
        filename = mesh.attrib.get("filename", "")
        if filename.startswith("package://meshes/"):
            mesh.attrib["filename"] = str(
                mesh_root / filename.removeprefix("package://meshes/")
            )
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "panda_slider_mobile_official_pads.urdf"
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    return destination


def build_mobile_room(*, generated_asset_dir: Path):
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

    # Room boundary and a central obstacle.
    wall_color = (0.72, 0.77, 0.82, 1.0)
    _add_box(scene, size=(2.5, 0.06, 0.35), pos=(0, -0.88, 0.175), color=wall_color)
    _add_box(scene, size=(2.5, 0.06, 0.35), pos=(0, 0.88, 0.175), color=wall_color)
    _add_box(scene, size=(0.06, 1.82, 0.35), pos=(-1.22, 0, 0.175), color=wall_color)
    _add_box(scene, size=(0.06, 1.82, 0.35), pos=(1.22, 0, 0.175), color=wall_color)
    _add_box(
        scene,
        size=(0.24, 0.42, 0.45),
        pos=(0.0, 0.0, 0.225),
        color=(0.38, 0.44, 0.52, 1.0),
    )

    # Docking marker and the household work table.
    _add_box(
        scene,
        size=(0.32, 0.32, 0.01),
        pos=(DOCK_XY[0], DOCK_XY[1], 0.005),
        color=(0.15, 0.75, 0.38, 1.0),
    )
    _add_box(
        scene,
        size=(0.72, 0.55, 0.06),
        pos=(0.83, 0.48, 0.72),
        color=(0.64, 0.48, 0.34, 1.0),
    )

    mobile_urdf = _prepare_mobile_urdf(generated_asset_dir)
    mobile_franka = scene.add_entity(
        gs.morphs.URDF(
            file=str(mobile_urdf),
            pos=(START_XY[0], START_XY[1], 0.30),
            fixed=True,
        )
    )
    camera = scene.add_camera(
        res=(1280, 720),
        pos=(2.1, -2.3, 2.5),
        lookat=(0.0, 0.0, 0.45),
        fov=48,
        GUI=False,
    )
    scene.build()
    return scene, mobile_franka, camera


def _joint_dof_index(robot, name: str) -> int:
    joint = robot.get_joint(name=name)
    indices = joint.dofs_idx_local
    if len(indices) != 1:
        raise RuntimeError(f"Expected one DoF for {name}, found {indices}")
    return indices[0]


def run_navigation(*, output_dir: Path, steps_per_segment: int = 60) -> dict:
    scene, robot, camera = build_mobile_room(
        generated_asset_dir=output_dir / "generated_assets"
    )
    base_names = ("base_slider_x", "base_slider_y", "base_rotate_z")
    base_indices = [_joint_dof_index(robot, name) for name in base_names]
    arm_names = tuple(f"panda_joint{index}" for index in range(1, 8))
    arm_indices = [_joint_dof_index(robot, name) for name in arm_names]
    finger_names = ("panda_finger_joint1", "panda_finger_joint2")
    finger_indices = [_joint_dof_index(robot, name) for name in finger_names]

    qpos = robot.get_qpos().detach().cpu().numpy().reshape(-1)
    # Stable arm pose while the base moves.
    qpos[arm_indices] = np.array([0.0, -0.3, 0.0, -2.0, 0.0, 1.7, 0.79])
    qpos[finger_indices] = 0.04
    robot.set_qpos(qpos)

    kp = np.full(qpos.shape, 1200.0)
    kv = np.full(qpos.shape, 120.0)
    force_min = np.full(qpos.shape, -500.0)
    force_max = np.full(qpos.shape, 500.0)
    kp[arm_indices] = np.array([4500, 4500, 3500, 3500, 2000, 2000, 2000])
    kv[arm_indices] = np.array([450, 450, 350, 350, 200, 200, 200])
    force_min[arm_indices] = np.array([-87, -87, -87, -87, -12, -12, -12])
    force_max[arm_indices] = np.array([87, 87, 87, 87, 12, 12, 12])
    kp[finger_indices] = 800.0
    kv[finger_indices] = 80.0
    force_min[finger_indices] = -100.0
    force_max[finger_indices] = 100.0
    robot.set_dofs_kp(kp)
    robot.set_dofs_kv(kv)
    robot.set_dofs_force_range(force_min, force_max)

    cells = astar(GRID, GRID.world_to_cell(START_XY), GRID.world_to_cell(DOCK_XY))
    waypoints = [GRID.cell_to_world(cell) for cell in simplify_path(cells)]
    trajectory: list[dict[str, float]] = []

    output_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    current_xy = np.asarray(START_XY, dtype=float)
    for waypoint in waypoints[1:]:
        target_xy = np.asarray(waypoint, dtype=float)
        delta = target_xy - current_xy
        yaw = float(np.arctan2(delta[1], delta[0]))
        for alpha in np.linspace(0.0, 1.0, steps_per_segment, endpoint=True):
            xy = current_xy * (1.0 - alpha) + target_xy * alpha
            qpos[base_indices[0]] = xy[0] - START_XY[0]
            qpos[base_indices[1]] = xy[1] - START_XY[1]
            qpos[base_indices[2]] = yaw
            robot.control_dofs_position(qpos)
            scene.step()
            trajectory.append({"x": float(xy[0]), "y": float(xy[1]), "yaw": yaw})
            if len(trajectory) % 20 == 0:
                frames.append(camera.render(rgb=True)[0])
        current_xy = target_xy

    # Let the physical controller converge before measuring docking accuracy.
    for _ in range(500):
        robot.control_dofs_position(qpos)
        scene.step()

    final_frame = camera.render(rgb=True)[0]
    imageio.imwrite(output_dir / "mobile_docking.png", final_frame)
    if frames:
        imageio.mimsave(output_dir / "mobile_docking.mp4", frames, fps=8)

    measured_base_position = (
        robot.get_link("base").get_pos().detach().cpu().numpy().reshape(-1)
    )
    measured_qpos = robot.get_qpos().detach().cpu().numpy().reshape(-1)
    result = {
        "backend": "gpu",
        "start_xy": START_XY,
        "goal_xy": DOCK_XY,
        "grid_path_cells": cells,
        "waypoints_xy": waypoints,
        "trajectory_samples": len(trajectory),
        "base_dof_indices": base_indices,
        "base_dof_names": base_names,
        "arm_dof_indices": arm_indices,
        "measured_base_xyz": measured_base_position.tolist(),
        "measured_base_qpos": measured_qpos[base_indices].tolist(),
        "commanded_final_error_m": float(
            np.linalg.norm(current_xy - np.asarray(DOCK_XY))
        ),
        "measured_final_error_m": float(
            np.linalg.norm(measured_base_position[:2] - np.asarray(DOCK_XY))
        ),
    }
    (output_dir / "navigation_result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RadeonHome mobile docking step")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs/mobile-docking")
    )
    parser.add_argument("--steps-per-segment", type=int, default=60)
    args = parser.parse_args()
    gs.init(backend=gs.gpu)
    run_navigation(
        output_dir=args.output_dir, steps_per_segment=args.steps_per_segment
    )


if __name__ == "__main__":
    main()
