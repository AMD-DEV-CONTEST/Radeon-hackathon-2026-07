"""Genesis scene construction for dual-bowl Franka fruit sorting."""

from __future__ import annotations

import argparse
import colorsys
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from radeonvla.paths import FRAMES_DIR, PROJECT_ROOT
from radeonvla.scene_config import (
    DR_APPEARANCE_PRIORS,
    FRANKA_EULER,
    FRANKA_FORCE_MAX,
    FRANKA_FORCE_MIN,
    FRANKA_KP,
    FRANKA_KV,
    FRANKA_POS,
    FRANKA_QPOS,
    OBJECT_LAYOUT,
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
    assets_root,
    franka_mjcf_path,
    get_mesh_assets,
)
from radeonvla.setup_assets import setup_assets


def _ensure_numba_cache() -> None:
    cache_dir = Path(tempfile.gettempdir()) / "radeonvla-numba-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("NUMBA_CACHE_DIR", str(cache_dir))


@dataclass
class AppearanceDR:
    """Build-time appearance / FOV randomization (requires scene rebuild)."""

    enabled: bool = False
    table_color_jitter: float = 0.0
    randomize_object_color: bool = False
    fov_jitter_deg: float = 0.0
    seed: int | None = None


@dataclass
class SceneBundle:
    """Runtime handles for one built Genesis scene."""

    scene: Any
    franka: Any
    objects: dict[str, Any]
    world_cam: Any = None
    wrist_cam: Any = None
    video_cam: Any = None
    table: list = field(default_factory=list)
    _wrist_link: Any = None

    def update_wrist_cam(self) -> None:
        if self.wrist_cam is not None:
            self.wrist_cam.move_to_attach()

    def render(self, *, rgb: bool = True, depth: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.world_cam is not None:
            out["world"] = self.world_cam.render(rgb=rgb, depth=depth)
        if self.wrist_cam is not None:
            out["wrist"] = self.wrist_cam.render(rgb=rgb, depth=depth)
        if self.video_cam is not None:
            out["video"] = self.video_cam.render(rgb=rgb, depth=depth)
        return out

    def hold_home(self) -> None:
        self.franka.control_dofs_position(np.array(FRANKA_QPOS))


def _jitter_rgb(color, amp: float, rng: np.random.Generator):
    if amp <= 0.0:
        return color
    rgb = np.clip(np.asarray(color[:3], dtype=float) + rng.uniform(-amp, amp, size=3), 0.0, 1.0)
    alpha = color[3] if len(color) > 3 else 1.0
    return (float(rgb[0]), float(rgb[1]), float(rgb[2]), float(alpha))


def _sample_hsv_color(prior: dict, rng: np.random.Generator):
    h = rng.uniform(*prior["hue"]) / 360.0
    s = rng.uniform(*prior["sat"])
    v = rng.uniform(*prior["val"])
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (float(r), float(g), float(b), 1.0)


def _add_table(scene, rng: np.random.Generator, appearance: AppearanceDR | None) -> list:
    import genesis as gs

    cx, cy = TABLE_CENTER
    top_lx, top_ly, top_lz = TABLE_TOP_SIZE
    leg_lx, leg_ly = TABLE_LEG_SIZE
    leg_lz = TABLE_TOP_Z - top_lz
    amp = appearance.table_color_jitter if (appearance and appearance.enabled) else 0.0
    top_color = _jitter_rgb(TABLE_COLOR, amp, rng)
    leg_color = _jitter_rgb(TABLE_LEG_COLOR, amp, rng)
    entities = [
        scene.add_entity(
            morph=gs.morphs.Box(
                size=TABLE_TOP_SIZE,
                pos=(cx, cy, TABLE_TOP_Z - top_lz / 2),
                fixed=True,
            ),
            surface=gs.surfaces.Default(color=top_color),
        )
    ]
    dx = top_lx / 2 - TABLE_LEG_INSET
    dy = top_ly / 2 - TABLE_LEG_INSET
    for sx in (-1, 1):
        for sy in (-1, 1):
            entities.append(
                scene.add_entity(
                    morph=gs.morphs.Box(
                        size=(leg_lx, leg_ly, leg_lz),
                        pos=(cx + sx * dx, cy + sy * dy, leg_lz / 2),
                        fixed=True,
                    ),
                    surface=gs.surfaces.Default(color=leg_color),
                )
            )
    return entities


def configure_franka(franka, *, n_envs: int = 1) -> None:
    qpos = np.array(FRANKA_QPOS)
    if n_envs > 1:
        qpos = np.tile(qpos, (n_envs, 1))
    franka.set_qpos(qpos)
    franka.set_dofs_kp(np.array(FRANKA_KP))
    franka.set_dofs_kv(np.array(FRANKA_KV))
    franka.set_dofs_force_range(np.array(FRANKA_FORCE_MIN), np.array(FRANKA_FORCE_MAX))


def build_scene(
    *,
    show_viewer: bool = False,
    n_envs: int = 1,
    add_world_cam: bool = True,
    add_wrist_cam: bool = True,
    add_video_cam: bool = False,
    appearance: AppearanceDR | None = None,
) -> SceneBundle:
    """Build the dual-bowl Franka scene. Caller must have already called ``gs.init``."""
    import genesis as gs
    from genesis.utils.geom import euler_to_R, trans_R_to_T

    setup_assets()
    meshes = get_mesh_assets()
    rng = np.random.default_rng(appearance.seed if appearance else None)
    dr_on = bool(appearance and appearance.enabled)
    recolor = dr_on and appearance.randomize_object_color

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
            res=(960, 720),
            camera_pos=(cx + 1.0, -1.2, 1.5),
            camera_lookat=(cx, cy, TABLE_TOP_Z),
            camera_fov=45,
        ),
        show_viewer=show_viewer,
        profiling_options=gs.options.ProfilingOptions(show_FPS=False),
    )

    scene.add_entity(gs.morphs.Plane())
    table = _add_table(scene, rng, appearance)

    objects: dict[str, Any] = {}
    for name, layout in OBJECT_LAYOUT.items():
        asset = meshes[name]
        x, y, _ = layout["pos"]
        scale = float(layout.get("scale", 1.0))
        # rest_z is mesh-local; scale it so the bottom still sits on the table.
        z = TABLE_TOP_Z + asset.rest_z_offset * scale
        surface = None
        if recolor and name in DR_APPEARANCE_PRIORS:
            surface = gs.surfaces.Default(color=_sample_hsv_color(DR_APPEARANCE_PRIORS[name], rng))
        elif layout.get("color") is not None:
            surface = gs.surfaces.Default(color=tuple(layout["color"]))
        # Containers are fixed upright place targets so contact cannot tip them over.
        is_container = layout.get("kind") == "container"
        fixed = bool(layout.get("fixed", is_container))
        objects[name] = scene.add_entity(
            morph=gs.morphs.Mesh(
                file=str(asset.mesh_path),
                pos=(x, y, z),
                euler=layout["euler"],
                scale=scale,
                align=False,
                convexify=True,
                decimate_face_num=500,
                fixed=fixed,
            ),
            material=gs.materials.Rigid(
                rho=float(layout.get("rho", 300.0)),
                friction=layout.get("friction"),
            ),
            surface=surface,
        )

    franka = scene.add_entity(
        gs.morphs.MJCF(
            file=str(franka_mjcf_path()),
            pos=FRANKA_POS,
            euler=FRANKA_EULER,
        ),
    )

    fov_amp = appearance.fov_jitter_deg if dr_on else 0.0
    world_fov = WORLD_CAM_FOV + (float(rng.uniform(-fov_amp, fov_amp)) if fov_amp else 0.0)
    wrist_fov = WRIST_CAM_FOV + (float(rng.uniform(-fov_amp, fov_amp)) if fov_amp else 0.0)

    world_cam = None
    if add_world_cam:
        world_cam = scene.add_camera(
            res=WORLD_CAM_RES,
            pos=WORLD_CAM_POS,
            lookat=WORLD_CAM_LOOKAT,
            fov=world_fov,
            GUI=False,
        )

    video_cam = None
    if add_video_cam:
        video_fov = VIDEO_CAM_FOV + (float(rng.uniform(-fov_amp, fov_amp)) if fov_amp else 0.0)
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

    if wrist_cam is not None:
        offset_t = trans_R_to_T(
            np.asarray(WRIST_CAM_OFFSET_POS, dtype=np.float64),
            euler_to_R(np.asarray(WRIST_CAM_OFFSET_EULER, dtype=np.float64)),
        )
        wrist_cam.attach(wrist_link, offset_t)
        wrist_cam.move_to_attach()

    return SceneBundle(
        scene=scene,
        franka=franka,
        objects=objects,
        world_cam=world_cam,
        wrist_cam=wrist_cam,
        video_cam=video_cam,
        table=table,
        _wrist_link=wrist_link,
    )


def init_genesis(*, backend: str = "cpu", seed: int = 0) -> None:
    """Initialize Genesis once per process."""
    import genesis as gs

    _ensure_numba_cache()
    backend_map = {
        "cpu": gs.cpu,
        "gpu": gs.gpu,
        "cuda": gs.gpu,
        "amdgpu": getattr(gs, "amdgpu", gs.gpu),
    }
    if backend not in backend_map:
        raise ValueError(f"Unknown backend {backend!r}; expected one of {sorted(backend_map)}")
    gs.init(backend=backend_map[backend], seed=seed, logging_level="warning")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test the RadeonVLA-Reflex Genesis scene.")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs" / "base.yaml")
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--vis", action="store_true", help="Show the interactive viewer.")
    parser.add_argument("--cpu", action="store_true", help="Force CPU backend.")
    parser.add_argument("--backend", choices=("cpu", "gpu", "amdgpu"), default=None)
    parser.add_argument("--save-frames", action="store_true")
    parser.add_argument("--dr-appearance", action="store_true")
    parser.add_argument("--dr-object-color", action="store_true")
    parser.add_argument("--dr-table-jitter", type=float, default=0.15)
    parser.add_argument("--dr-fov-jitter", type=float, default=0.0)
    parser.add_argument("--dr-seed", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    backend = args.backend or ("cpu" if args.cpu else "gpu")
    init_genesis(backend=backend, seed=args.dr_seed)

    appearance = AppearanceDR(
        enabled=args.dr_appearance,
        table_color_jitter=args.dr_table_jitter,
        randomize_object_color=args.dr_object_color,
        fov_jitter_deg=args.dr_fov_jitter,
        seed=args.dr_seed,
    )
    bundle = build_scene(
        show_viewer=args.vis,
        add_world_cam=True,
        add_wrist_cam=True,
        add_video_cam=args.save_frames,
        appearance=appearance,
    )

    for _ in range(args.steps):
        bundle.hold_home()
        bundle.scene.step()
        bundle.update_wrist_cam()

    if args.save_frames:
        import imageio.v2 as imageio

        FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        rendered = bundle.render(rgb=True)
        for name, payload in rendered.items():
            image = payload[0] if isinstance(payload, (tuple, list)) else payload
            out = FRAMES_DIR / f"scene_{name}.png"
            imageio.imwrite(out, image)
            print(f"[scene] wrote {out}")

    print(f"[scene] smoke test complete ({args.steps} steps, backend={backend})")
    print(f"[scene] objects: {sorted(bundle.objects)}")
    print(f"[scene] assets: {assets_root()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
