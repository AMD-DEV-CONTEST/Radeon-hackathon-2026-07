"""Build a color-sorting scene: Franka + table + colored objects + per-color containers.

Based on franka_fruit_pick_demo's build_scene.py. Key changes:
- YCB mesh assets → gs.morphs.Box/Cylinder/Sphere with gs.surfaces.Plastic(color=...)
- Single bowl → per-color YCB 024_bowl containers (scaled ~9cm, recolored per sorting color)
- SceneBundle interface preserved (scene/franka/objects/containers/cameras)
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import genesis as gs
from genesis.utils.geom import trans_R_to_T, euler_to_R

from scene_config import (
    BOWL_ASSET_FILE,
    BOWL_REST_Z_OFFSET,
    BOWL_SCALE,
    COLOR_RGB,
    COLORS,
    CONTAINER_LAYOUT,
    FRANKA_EULER,
    FRANKA_FORCE_MAX,
    FRANKA_FORCE_MIN,
    FRANKA_KP,
    FRANKA_KV,
    FRANKA_POS,
    FRANKA_QPOS,
    OBJECT_LAYOUT,
    OBJECT_SIZE,
    REACH_X,
    REACH_Y,
    TABLE_CENTER,
    TABLE_COLOR,
    TABLE_LEG_COLOR,
    TABLE_LEG_INSET,
    TABLE_LEG_SIZE,
    TABLE_TOP_SIZE,
    TABLE_TOP_Z,
    VIDEO_CAM_FOV,
    VIDEO_CAM_LOOKAT,
    VIDEO_CAM_POS,
    VIDEO_CAM_RES,
    WORLD_CAM_FOV,
    WORLD_CAM_LOOKAT,
    WORLD_CAM_POS,
    WORLD_CAM_RES,
    WRIST_CAM_FAR,
    WRIST_CAM_FOV,
    WRIST_CAM_LINK,
    WRIST_CAM_NEAR,
    WRIST_CAM_OFFSET_EULER,
    WRIST_CAM_OFFSET_POS,
    WRIST_CAM_RES,
    get_sort_objects,
    object_rest_z_offset,
)
from paths import OUTPUTS_DIR


@dataclass
class SortSceneBundle:
    """Everything a caller needs to drive and observe the sorting scene."""

    scene: gs.Scene
    franka: gs.RigidEntity
    objects: dict[str, gs.RigidEntity]  # name → entity (e.g. "red_cube")
    containers: dict[str, gs.RigidEntity]  # color → entity (e.g. "red" → red_bin)
    world_cam: "gs.vis.camera.Camera | None" = None
    wrist_cam: "gs.vis.camera.Camera | None" = None
    video_cam: "gs.vis.camera.Camera | None" = None
    table: list = field(default_factory=list)
    _wrist_link: "gs.RigidLink | None" = None

    def update_wrist_cam(self) -> None:
        """Sync the wrist camera to the current hand-link pose. Call each step."""
        if self.wrist_cam is not None:
            self.wrist_cam.move_to_attach()

    def render(self, *, rgb: bool = True, depth: bool = False):
        """Render both cameras (if present). Returns a dict keyed by camera name."""
        out = {}
        if self.world_cam is not None:
            out["world"] = self.world_cam.render(rgb=rgb, depth=depth)
        if self.wrist_cam is not None:
            out["wrist"] = self.wrist_cam.render(rgb=rgb, depth=depth)
        if self.video_cam is not None:
            out["video"] = self.video_cam.render(rgb=rgb, depth=depth)
        return out


def _add_table(scene: gs.Scene) -> list:
    """Build table from box primitives (same as demo)."""
    cx, cy = TABLE_CENTER
    top_lx, top_ly, top_lz = TABLE_TOP_SIZE
    leg_lx, leg_ly = TABLE_LEG_SIZE
    leg_lz = TABLE_TOP_Z - top_lz

    table_entities = []
    table_entities.append(
        scene.add_entity(
            morph=gs.morphs.Box(
                size=TABLE_TOP_SIZE,
                pos=(cx, cy, TABLE_TOP_Z - top_lz / 2),
                fixed=True,
            ),
            surface=gs.surfaces.Default(color=TABLE_COLOR),
        )
    )

    dx = top_lx / 2 - TABLE_LEG_INSET
    dy = top_ly / 2 - TABLE_LEG_INSET
    for sx in (-1, 1):
        for sy in (-1, 1):
            table_entities.append(
                scene.add_entity(
                    morph=gs.morphs.Box(
                        size=(leg_lx, leg_ly, leg_lz),
                        pos=(cx + sx * dx, cy + sy * dy, leg_lz / 2),
                        fixed=True,
                    ),
                    surface=gs.surfaces.Default(color=TABLE_LEG_COLOR),
                )
            )
    return table_entities


def _add_object(scene: gs.Scene, name: str, color: str, geometry: str,
                pos_xy: tuple[float, float], size: float = OBJECT_SIZE) -> gs.RigidEntity:
    """Add a colored geometric object to the scene."""
    x, y = pos_xy
    z = TABLE_TOP_Z + object_rest_z_offset(geometry, size)

    rgb = COLOR_RGB[color]
    surface = gs.surfaces.Plastic(color=rgb)

    if geometry == "cube":
        morph = gs.morphs.Box(size=(size, size, size), pos=(x, y, z))
    elif geometry == "cylinder":
        morph = gs.morphs.Cylinder(radius=size / 2, height=size, pos=(x, y, z))
    elif geometry == "sphere":
        morph = gs.morphs.Sphere(radius=size / 2, pos=(x, y, z))
    else:
        raise ValueError(f"Unknown geometry: {geometry}")

    # Spheres need higher friction to avoid slipping from the gripper
    friction = 2.0 if geometry == "sphere" else 1.0

    return scene.add_entity(
        morph=morph,
        material=gs.materials.Rigid(rho=300.0, friction=friction),
        surface=surface,
    )


def _add_container(scene: gs.Scene, color: str,
                   pos_xy: tuple[float, float]) -> gs.RigidEntity:
    """Add a per-color YCB 024_bowl container (colored, recessed) to the scene.

    The bowl is scaled to ~9cm diameter and colored to match its sorting
    color (the Default surface overrides the mesh's own texture, same
    technique the demo uses for DR recolor). convexify=True lets coacd
    decompose the recess into convex pieces so objects genuinely fall in.
    """
    x, y = pos_xy
    z = TABLE_TOP_Z + BOWL_REST_Z_OFFSET
    rgb = COLOR_RGB[color]

    return scene.add_entity(
        morph=gs.morphs.Mesh(
            file=BOWL_ASSET_FILE,
            pos=(x, y, z),
            scale=BOWL_SCALE,
            fixed=True,
            convexify=True,
            decimate_face_num=500,
        ),
        surface=gs.surfaces.Default(color=rgb),
    )


def build_scene(
    *,
    show_viewer: bool = False,
    n_envs: int = 1,
    add_world_cam: bool = True,
    add_wrist_cam: bool = True,
    add_video_cam: bool = False,
    draw_world_frame: bool = False,
    colors: tuple[str, ...] = COLORS,
) -> SortSceneBundle:
    """Build the color-sorting scene.

    Args:
        colors: which colors to include (default all 5). Use subset for
                train-only or eval-only scenes.
    """
    sort_objects = get_sort_objects(colors)

    cx, cy = TABLE_CENTER
    camera_lookat = (cx, cy, TABLE_TOP_Z)

    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=0.01, substeps=2),
        rigid_options=gs.options.RigidOptions(
            dt=0.01,
            constraint_solver=gs.constraint_solver.Newton,
            enable_collision=True,
            enable_joint_limit=True,
        ),
        viewer_options=gs.options.ViewerOptions(
            res=(1280, 960),
            camera_pos=(cx + 1.0, -1.2, 1.5),
            camera_lookat=camera_lookat,
            camera_fov=45,
        ),
        show_viewer=show_viewer,
        profiling_options=gs.options.ProfilingOptions(show_FPS=False),
    )

    scene.add_entity(gs.morphs.Plane())
    table_entities = _add_table(scene)

    # Add colored objects
    object_entities: dict[str, gs.RigidEntity] = {}
    for obj in sort_objects:
        object_entities[obj.name] = _add_object(
            scene, obj.name, obj.color, obj.geometry, obj.pos
        )

    # Add per-color containers
    container_entities: dict[str, gs.RigidEntity] = {}
    for color in colors:
        container_entities[color] = _add_container(
            scene, color, CONTAINER_LAYOUT[color]
        )

    # Add Franka
    franka = scene.add_entity(
        gs.morphs.MJCF(
            file="xml/franka_emika_panda/panda.xml",
            pos=FRANKA_POS,
            euler=FRANKA_EULER,
        ),
    )

    # Add cameras (before build, same as demo)
    world_cam = None
    if add_world_cam:
        world_cam = scene.add_camera(
            res=WORLD_CAM_RES,
            pos=WORLD_CAM_POS,
            lookat=WORLD_CAM_LOOKAT,
            fov=WORLD_CAM_FOV,
            GUI=False,
        )

    video_cam = None
    if add_video_cam:
        video_cam = scene.add_camera(
            res=VIDEO_CAM_RES,
            pos=VIDEO_CAM_POS,
            lookat=VIDEO_CAM_LOOKAT,
            fov=VIDEO_CAM_FOV,
            GUI=False,
        )

    wrist_cam = None
    wrist_link = None
    if add_wrist_cam:
        wrist_cam = scene.add_camera(
            res=WRIST_CAM_RES,
            fov=WRIST_CAM_FOV,
            near=WRIST_CAM_NEAR,
            far=WRIST_CAM_FAR,
            GUI=False,
        )
        wrist_link = franka.get_link(WRIST_CAM_LINK)

    if n_envs > 1:
        scene.build(n_envs=n_envs, env_spacing=(1.5, 1.5))
    else:
        scene.build()

    configure_franka(franka, n_envs=n_envs)

    # Attach wrist camera after build (needs runtime pose)
    if wrist_cam is not None:
        offset_T = trans_R_to_T(
            np.asarray(WRIST_CAM_OFFSET_POS, dtype=np.float64),
            euler_to_R(np.asarray(WRIST_CAM_OFFSET_EULER, dtype=np.float64)),
        )
        wrist_cam.attach(wrist_link, offset_T)
        wrist_cam.move_to_attach()

    if draw_world_frame:
        scene.draw_debug_frame(T=np.eye(4), axis_length=0.3, origin_size=0.02, axis_radius=0.01)

    return SortSceneBundle(
        scene=scene,
        franka=franka,
        objects=object_entities,
        containers=container_entities,
        world_cam=world_cam,
        wrist_cam=wrist_cam,
        video_cam=video_cam,
        table=table_entities,
        _wrist_link=wrist_link,
    )


def configure_franka(franka: gs.RigidEntity, *, n_envs: int) -> None:
    qpos = np.array(FRANKA_QPOS)
    if n_envs > 1:
        qpos = np.tile(qpos, (n_envs, 1))
    franka.set_qpos(qpos)
    franka.set_dofs_kp(np.array(FRANKA_KP))
    franka.set_dofs_kv(np.array(FRANKA_KV))
    franka.set_dofs_force_range(np.array(FRANKA_FORCE_MIN), np.array(FRANKA_FORCE_MAX))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and run the color-sorting scene.")
    parser.add_argument("-v", "--vis", action="store_true", default=False)
    parser.add_argument("-c", "--cpu", action="store_true", default=False)
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--save-frames", action="store_true")
    parser.add_argument("--debug-frame", action="store_true")
    args = parser.parse_args()

    gs.init(backend=gs.cpu if args.cpu else gs.gpu)
    bundle = build_scene(
        show_viewer=args.vis,
        draw_world_frame=args.debug_frame,
    )

    hold_qpos = np.array(FRANKA_QPOS)
    for _ in range(args.steps):
        bundle.franka.control_dofs_position(hold_qpos)
        bundle.scene.step()
        bundle.update_wrist_cam()

    if args.save_frames:
        import imageio.v2 as imageio
        out_dir = OUTPUTS_DIR / "scene_frames"
        out_dir.mkdir(parents=True, exist_ok=True)
        if bundle.world_cam is not None:
            imageio.imwrite(str(out_dir / "world_cam.png"), bundle.world_cam.render(rgb=True)[0])
            print(f"Saved {out_dir / 'world_cam.png'}")
        if bundle.wrist_cam is not None:
            imageio.imwrite(str(out_dir / "wrist_cam.png"), bundle.wrist_cam.render(rgb=True)[0])
            print(f"Saved {out_dir / 'wrist_cam.png'}")


if __name__ == "__main__":
    main()