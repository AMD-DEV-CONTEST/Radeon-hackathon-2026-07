"""Genesis household tabletop scene for the RadeonHome MVP."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np


REFERENCE_ROOT = Path(
    os.environ.get("RADEONHOME_REFERENCE_ROOT", "/persistent/projects/reference-franka")
)
REFERENCE_PACKAGE = REFERENCE_ROOT / "franka_fruit_pick"
if str(REFERENCE_PACKAGE) not in sys.path:
    sys.path.insert(0, str(REFERENCE_PACKAGE))

import genesis as gs  # noqa: E402
from build_scene import configure_franka  # noqa: E402
from scene_config import (  # noqa: E402
    ASSETS,
    FRANKA_EULER,
    FRANKA_POS,
    FRANKA_QPOS,
    TABLE_CENTER,
    TABLE_TOP_SIZE,
    TABLE_TOP_Z,
)


@dataclass
class HouseholdScene:
    scene: gs.Scene
    franka: gs.RigidEntity
    entities: dict[str, gs.RigidEntity]
    camera: object


def _box(
    scene: gs.Scene,
    *,
    size: tuple[float, float, float],
    pos: tuple[float, float, float],
    color: tuple[float, float, float, float],
    fixed: bool = False,
    friction: float = 1.0,
) -> gs.RigidEntity:
    return scene.add_entity(
        morph=gs.morphs.Box(size=size, pos=pos, fixed=fixed),
        material=gs.materials.Rigid(rho=350.0, friction=friction),
        surface=gs.surfaces.Default(color=color),
    )


def _open_container(
    scene: gs.Scene,
    *,
    center: tuple[float, float],
    inner_size: tuple[float, float],
    color: tuple[float, float, float, float],
    name: str,
    entities: dict[str, gs.RigidEntity],
) -> None:
    x, y = center
    inner_x, inner_y = inner_size
    wall = 0.012
    base_h = 0.012
    wall_h = 0.07
    entities[name] = _box(
        scene,
        size=(inner_x + 2 * wall, inner_y + 2 * wall, base_h),
        pos=(x, y, TABLE_TOP_Z + base_h / 2),
        color=color,
        fixed=True,
    )
    for suffix, size, pos in (
        (
            "front",
            (inner_x + 2 * wall, wall, wall_h),
            (x, y - inner_y / 2 - wall / 2, TABLE_TOP_Z + wall_h / 2),
        ),
        (
            "back",
            (inner_x + 2 * wall, wall, wall_h),
            (x, y + inner_y / 2 + wall / 2, TABLE_TOP_Z + wall_h / 2),
        ),
        (
            "left",
            (wall, inner_y, wall_h),
            (x - inner_x / 2 - wall / 2, y, TABLE_TOP_Z + wall_h / 2),
        ),
        (
            "right",
            (wall, inner_y, wall_h),
            (x + inner_x / 2 + wall / 2, y, TABLE_TOP_Z + wall_h / 2),
        ),
    ):
        entities[f"{name}_{suffix}"] = _box(
            scene, size=size, pos=pos, color=color, fixed=True
        )


def build_household_scene(*, show_viewer: bool = False) -> HouseholdScene:
    """Build one household scene with grasp targets and safety-critical cup."""

    cx, cy = TABLE_CENTER
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=0.01, substeps=2),
        rigid_options=gs.options.RigidOptions(
            dt=0.01,
            constraint_solver=gs.constraint_solver.Newton,
            enable_collision=True,
            enable_joint_limit=True,
        ),
        viewer_options=gs.options.ViewerOptions(
            res=(1280, 720),
            camera_pos=(1.15, -1.25, 1.45),
            camera_lookat=(cx, cy, TABLE_TOP_Z),
            camera_fov=42,
        ),
        show_viewer=show_viewer,
        profiling_options=gs.options.ProfilingOptions(show_FPS=False),
    )

    entities: dict[str, gs.RigidEntity] = {}
    scene.add_entity(gs.morphs.Plane())
    top_x, top_y, top_z = TABLE_TOP_SIZE
    entities["table"] = _box(
        scene,
        size=TABLE_TOP_SIZE,
        pos=(cx, cy, TABLE_TOP_Z - top_z / 2),
        color=(0.64, 0.48, 0.34, 1.0),
        fixed=True,
    )

    # Pick objects use simple stable collision geometry for the first closed loop.
    entities["trash"] = _box(
        scene,
        size=(0.065, 0.045, 0.035),
        pos=(0.31, 0.22, TABLE_TOP_Z + 0.0175),
        color=(0.92, 0.43, 0.12, 1.0),
    )
    entities["keys"] = _box(
        scene,
        size=(0.075, 0.025, 0.012),
        pos=(0.38, 0.08, TABLE_TOP_Z + 0.006),
        color=(0.95, 0.72, 0.12, 1.0),
        friction=1.4,
    )
    entities["medicine"] = _box(
        scene,
        size=(0.055, 0.035, 0.085),
        pos=(0.34, -0.10, TABLE_TOP_Z + 0.0425),
        color=(0.24, 0.58, 0.94, 1.0),
    )

    # The cup is fixed in the MVP: touching it is still a collision failure, while
    # fixing it prevents an accidental early test from destroying the visual layout.
    entities["cup"] = _box(
        scene,
        size=(0.065, 0.065, 0.105),
        pos=(0.47, -0.13, TABLE_TOP_Z + 0.0525),
        color=(0.93, 0.95, 0.98, 1.0),
        fixed=True,
    )

    _open_container(
        scene,
        center=(0.58, 0.22),
        inner_size=(0.15, 0.13),
        color=(0.20, 0.62, 0.33, 1.0),
        name="trash_bin",
        entities=entities,
    )
    _open_container(
        scene,
        center=(0.58, 0.01),
        inner_size=(0.17, 0.12),
        color=(0.48, 0.32, 0.78, 1.0),
        name="tray",
        entities=entities,
    )

    franka = scene.add_entity(
        gs.morphs.MJCF(
            file=str(ASSETS / "robots" / "franka" / "panda.xml"),
            pos=FRANKA_POS,
            euler=FRANKA_EULER,
        )
    )
    camera = scene.add_camera(
        res=(1280, 720),
        pos=(1.08, -1.05, 1.50),
        lookat=(0.34, 0.03, TABLE_TOP_Z + 0.05),
        fov=42,
        GUI=False,
    )

    scene.build()
    configure_franka(franka, n_envs=1)
    return HouseholdScene(scene, franka, entities, camera)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the RadeonHome household scene")
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--viewer", action="store_true")
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/scene-smoke"))
    args = parser.parse_args()

    gs.init(backend=gs.cpu if args.cpu else gs.gpu)
    bundle = build_household_scene(show_viewer=args.viewer)
    hold = np.asarray(FRANKA_QPOS)
    for _ in range(args.steps):
        bundle.franka.control_dofs_position(hold)
        bundle.scene.step()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    frame_path = args.output_dir / "household_scene.png"
    import imageio.v2 as imageio

    imageio.imwrite(frame_path, bundle.camera.render(rgb=True)[0])
    positions = {
        name: entity.get_pos().detach().cpu().numpy().reshape(-1).tolist()
        for name, entity in bundle.entities.items()
        if name in {"trash", "keys", "medicine", "cup", "trash_bin", "tray"}
    }
    metadata = {
        "backend": "cpu" if args.cpu else "gpu",
        "steps": args.steps,
        "frame": str(frame_path),
        "positions": positions,
    }
    (args.output_dir / "scene_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()

