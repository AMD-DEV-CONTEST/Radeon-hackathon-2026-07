"""Build a Franka manipulation scene with a table and YCB objects."""

from __future__ import annotations

import argparse
import colorsys
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
    ASSETS,
    DR_APPEARANCE_PRIORS,
    FRANKA_EULER,
    FRANKA_FORCE_MAX,
    FRANKA_FORCE_MIN,
    FRANKA_KP,
    FRANKA_KV,
    FRANKA_POS,
    FRANKA_QPOS,
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
    YCB_LAYOUT,
    get_ycb_assets,
)
from setup_assets import setup_assets


@dataclass
class SceneBundle:
    """Everything a caller needs to drive and observe the scene."""

    scene: gs.Scene
    franka: gs.RigidEntity
    ycb: dict[str, gs.RigidEntity]
    world_cam: "gs.vis.camera.Camera | None" = None
    wrist_cam: "gs.vis.camera.Camera | None" = None
    # Cosmetic third-person camera used only for saved eval videos (not an observation).
    video_cam: "gs.vis.camera.Camera | None" = None
    # Static tabletop + leg entities. Kept so runtime DR (M4 Layer B) can scale table
    # friction: contact friction is max() over the pair, so the tabletop must be scaled
    # alongside the object for the effective object<->table friction to actually change.
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


@dataclass
class SceneDomainRandomizationConfig:
    """M4 domain randomization -- Layer A: build-time appearance / intrinsics knobs.

    Applied once per ``build_scene`` (i.e. per built scene), *not* per episode: colors,
    textures and camera intrinsics are baked at ``scene.build()`` and cannot be changed at
    runtime with the default rasterizer. To sample a new appearance domain, rebuild the
    scene with a different ``seed``.

    Object recolor is opt-in and constrained to the per-object priors in
    ``scene_config.DR_APPEARANCE_PRIORS`` (see the note there). Table color and camera FOV
    are task-irrelevant nuisances, so they are jittered freely without a plausibility prior.
    """

    enabled: bool = False
    table_color_jitter: float = 0.0  # +/- per-RGB-channel offset on table + legs
    randomize_object_color: bool = False  # recolor YCB objects within DR_APPEARANCE_PRIORS
    fov_jitter_deg: float = 0.0  # +/- deg on both cameras' vertical FOV
    seed: int | None = None


def _dr_jitter_rgb(color, amp: float, dr_rng: np.random.Generator):
    """DR helper: return ``color`` with a uniform +/- ``amp`` offset per RGB channel (alpha kept)."""
    if amp <= 0.0:
        return color
    rgb = np.clip(np.asarray(color[:3], dtype=float) + dr_rng.uniform(-amp, amp, size=3), 0.0, 1.0)
    alpha = color[3] if len(color) > 3 else 1.0
    return (float(rgb[0]), float(rgb[1]), float(rgb[2]), float(alpha))


def _dr_sample_object_color(prior: dict, dr_rng: np.random.Generator):
    """DR helper: sample a plausible ``(r, g, b, a)`` from an object's HSV appearance prior."""
    h = dr_rng.uniform(*prior["hue"]) / 360.0  # colorsys expects hue in [0, 1)
    s = dr_rng.uniform(*prior["sat"])
    v = dr_rng.uniform(*prior["val"])
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (float(r), float(g), float(b), 1.0)


def _ensure_assets() -> Path:
    if not (ASSETS / "robots" / "franka" / "panda.xml").exists():
        setup_assets()
    return ASSETS


def _add_table(
    scene: gs.Scene, dr_rng: np.random.Generator, scene_dr: "SceneDomainRandomizationConfig | None"
) -> list:
    cx, cy = TABLE_CENTER
    top_lx, top_ly, top_lz = TABLE_TOP_SIZE
    leg_lx, leg_ly = TABLE_LEG_SIZE
    leg_lz = TABLE_TOP_Z - top_lz

    dr_table_amp = scene_dr.table_color_jitter if (scene_dr and scene_dr.enabled) else 0.0
    top_color = _dr_jitter_rgb(TABLE_COLOR, dr_table_amp, dr_rng)
    leg_color = _dr_jitter_rgb(TABLE_LEG_COLOR, dr_table_amp, dr_rng)

    table_entities = []

    # Tabletop: its top surface sits exactly at TABLE_TOP_Z. Listed first so callers can
    # rely on table[0] being the surface that objects rest on.
    table_entities.append(
        scene.add_entity(
            morph=gs.morphs.Box(
                size=TABLE_TOP_SIZE,
                pos=(cx, cy, TABLE_TOP_Z - top_lz / 2),
                fixed=True,
            ),
            surface=gs.surfaces.Default(color=top_color),
        )
    )

    # Four legs from the floor up to the underside of the tabletop.
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
                    surface=gs.surfaces.Default(color=leg_color),
                )
            )

    return table_entities


def build_scene(
    *,
    show_viewer: bool = False,
    n_envs: int = 1,
    add_world_cam: bool = True,
    add_wrist_cam: bool = True,
    add_video_cam: bool = False,
    draw_world_frame: bool = False,
    scene_dr: "SceneDomainRandomizationConfig | None" = None,
) -> SceneBundle:
    assets = _ensure_assets()
    ycb_assets = get_ycb_assets()

    # M4 Layer-A: a single RNG stream drives all build-time appearance/intrinsics DR, so a
    # given (scene_dr.seed) fully determines the sampled appearance domain.
    dr_rng = np.random.default_rng(scene_dr.seed if scene_dr else None)
    dr_enabled = bool(scene_dr and scene_dr.enabled)
    dr_recolor_objects = dr_enabled and scene_dr.randomize_object_color

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
    table_entities = _add_table(scene, dr_rng, scene_dr)

    ycb_entities: dict[str, gs.RigidEntity] = {}
    for name, layout in YCB_LAYOUT.items():
        asset = ycb_assets[name]
        x, y, _ = layout["pos"]
        z = TABLE_TOP_Z + asset.rest_z_offset
        # Layer-A object recolor: only for objects with an appearance prior, and only when
        # enabled. Passing surface=None keeps the object's original mesh texture.
        surface = None
        if dr_recolor_objects and name in DR_APPEARANCE_PRIORS:
            surface = gs.surfaces.Default(color=_dr_sample_object_color(DR_APPEARANCE_PRIORS[name], dr_rng))
        ycb_entities[name] = scene.add_entity(
            morph=gs.morphs.Mesh(
                file=str(asset.mesh_path),
                pos=(x, y, z),
                euler=layout["euler"],
                align=False,
                convexify=True,
                decimate_face_num=500,
            ),
            material=gs.materials.Rigid(rho=300.0, friction=layout.get("friction")),
            surface=surface,
        )

    franka = scene.add_entity(
        gs.morphs.MJCF(
            file=str(assets / "robots" / "franka" / "panda.xml"),
            pos=FRANKA_POS,
            euler=FRANKA_EULER,
        ),
    )

    # Cameras must be added before scene.build(). FOV (intrinsics) can only be set here,
    # so Layer-A jitters it at build time; extrinsics are left to Layer B (runtime).
    dr_fov_amp = scene_dr.fov_jitter_deg if dr_enabled else 0.0
    world_fov = WORLD_CAM_FOV + (float(dr_rng.uniform(-dr_fov_amp, dr_fov_amp)) if dr_fov_amp else 0.0)
    wrist_fov = WRIST_CAM_FOV + (float(dr_rng.uniform(-dr_fov_amp, dr_fov_amp)) if dr_fov_amp else 0.0)

    world_cam = None
    if add_world_cam:
        world_cam = scene.add_camera(
            res=WORLD_CAM_RES,
            pos=WORLD_CAM_POS,
            lookat=WORLD_CAM_LOOKAT,
            fov=world_fov,
            GUI=False,
        )

    # Cosmetic recording view: a fixed third-person camera for saved eval videos only.
    # Its FOV is jittered alongside the others under Layer-A DR purely for visual variety.
    video_cam = None
    if add_video_cam:
        video_fov = VIDEO_CAM_FOV + (float(dr_rng.uniform(-dr_fov_amp, dr_fov_amp)) if dr_fov_amp else 0.0)
        video_cam = scene.add_camera(
            res=VIDEO_CAM_RES,
            pos=VIDEO_CAM_POS,
            lookat=VIDEO_CAM_LOOKAT,
            fov=video_fov,
            GUI=False,
        )

    wrist_cam = None
    wrist_link = None
    if add_wrist_cam:
        wrist_cam = scene.add_camera(
            res=WRIST_CAM_RES,
            fov=wrist_fov,
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

    # Attaching needs the link's runtime pose, so it happens after build().
    if wrist_cam is not None:
        offset_T = trans_R_to_T(
            np.asarray(WRIST_CAM_OFFSET_POS, dtype=np.float64),
            euler_to_R(np.asarray(WRIST_CAM_OFFSET_EULER, dtype=np.float64)),
        )
        wrist_cam.attach(wrist_link, offset_T)
        wrist_cam.move_to_attach()

    # Debug world frame at the origin (X=red, Y=green, Z=blue) to help tune layout.
    if draw_world_frame:
        scene.draw_debug_frame(T=np.eye(4), axis_length=0.3, origin_size=0.02, axis_radius=0.01)

    return SceneBundle(
        scene=scene,
        franka=franka,
        ycb=ycb_entities,
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
    parser = argparse.ArgumentParser(description="Build and run the Franka manipulation scene.")
    parser.add_argument("-v", "--vis", action="store_true", default=False)
    parser.add_argument("-c", "--cpu", action="store_true", default=False)
    parser.add_argument("-n", "--n-envs", type=int, default=1)
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument(
        "--setup-assets",
        action="store_true",
        help="Refresh YCB and robot symlinks before building.",
    )
    parser.add_argument("--no-world-cam", action="store_true", help="Disable the fixed world camera.")
    parser.add_argument("--no-wrist-cam", action="store_true", help="Disable the wrist camera.")
    parser.add_argument(
        "--debug-frame",
        action="store_true",
        help="Draw a world coordinate frame at the origin for layout debugging.",
    )
    parser.add_argument(
        "--save-frames",
        action="store_true",
        help="Render and save one frame from each camera at the end of the run.",
    )
    parser.add_argument(
        "--dr-appearance",
        action="store_true",
        help="Enable M4 Layer-A build-time appearance/intrinsics domain randomization.",
    )
    parser.add_argument(
        "--dr-table-jitter",
        type=float,
        default=0.15,
        help="Layer-A: +/- per-RGB-channel jitter on the table/leg color (needs --dr-appearance).",
    )
    parser.add_argument(
        "--dr-object-color",
        action="store_true",
        help="Layer-A: recolor YCB objects within their DR_APPEARANCE_PRIORS (needs --dr-appearance).",
    )
    parser.add_argument(
        "--dr-fov-jitter",
        type=float,
        default=0.0,
        help="Layer-A: +/- deg jitter on both cameras' vertical FOV (needs --dr-appearance).",
    )
    parser.add_argument("--dr-seed", type=int, default=None, help="Seed for the Layer-A appearance RNG.")
    args = parser.parse_args()

    if args.setup_assets:
        setup_assets()

    scene_dr = SceneDomainRandomizationConfig(
        enabled=args.dr_appearance,
        table_color_jitter=args.dr_table_jitter,
        randomize_object_color=args.dr_object_color,
        fov_jitter_deg=args.dr_fov_jitter,
        seed=args.dr_seed,
    )

    gs.init(backend=gs.cpu if args.cpu else gs.gpu)
    bundle = build_scene(
        show_viewer=args.vis,
        n_envs=args.n_envs,
        add_world_cam=not args.no_world_cam,
        add_wrist_cam=not args.no_wrist_cam,
        draw_world_frame=args.debug_frame,
        scene_dr=scene_dr,
    )

    # Keep the arm at its initial pose so it does not droop under gravity.
    hold_qpos = np.array(FRANKA_QPOS)
    if args.n_envs > 1:
        hold_qpos = np.tile(hold_qpos, (args.n_envs, 1))

    for _ in range(args.steps):
        bundle.franka.control_dofs_position(hold_qpos)
        bundle.scene.step()
        bundle.update_wrist_cam()

    if args.save_frames:
        import imageio.v2 as imageio

        if bundle.world_cam is not None:
            imageio.imwrite("world_cam.png", bundle.world_cam.render(rgb=True)[0])
            print("Saved world_cam.png")
        if bundle.wrist_cam is not None:
            imageio.imwrite("wrist_cam.png", bundle.wrist_cam.render(rgb=True)[0])
            print("Saved wrist_cam.png")


if __name__ == "__main__":
    main()
