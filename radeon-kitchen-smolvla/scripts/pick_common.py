"""
Scene-agnostic scene builder for pick tasks.

Loads scene config from ``scenes/<name>.json``, places Franka + cube + cameras.
Used by 02_gen_data_custom_scene.py and 04_eval_custom_scene.py.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

from genesis_scene_utils import load_mesh, load_franka, mesh_aabb
from scene_placement import add_placement_args, compute_workspace

WORKSHOP_DIR = Path(__file__).resolve().parent.parent
SCENES_DIR = WORKSHOP_DIR / "scenes"
DEFAULT_SCENE = "rustic_kitchen"

# ---------------------------------------------------------------------------
# Pick-task constants (scene-agnostic)
# ---------------------------------------------------------------------------
CUBE_SIZE = (0.04, 0.04, 0.04)
GRASP_QUAT = np.array([0, 1, 0, 0], dtype=np.float32)
FINGER_OPEN = 0.04
FINGER_CLOSED = 0.01

FORCE_LOWER = np.array(
    [-87, -87, -87, -87, -12, -12, -12, -100, -100], dtype=np.float32
)
FORCE_UPPER = np.array(
    [87, 87, 87, 87, 12, 12, 12, 100, 100], dtype=np.float32
)

PLACEMENT_DEFAULTS = dict(
    base_x=0.0, base_y=0.0, base_lift=0.0,
    yaw=0.0, surface_z=0.0,
)


# ---------------------------------------------------------------------------
# Scene config loading
# ---------------------------------------------------------------------------
def load_scene_config(scene_name: str) -> dict:
    """Load ``scenes/<name>.json`` and resolve paths relative to workshop root."""
    path = SCENES_DIR / f"{scene_name}.json"
    if not path.exists():
        available = [p.stem for p in SCENES_DIR.glob("*.json")]
        print(f"[error] Scene '{scene_name}' not found at {path}")
        print(f"[error] Available scenes: {available}")
        sys.exit(1)
    with open(path) as f:
        cfg = json.load(f)
    cfg["asset_dir"] = WORKSHOP_DIR / cfg["asset_dir"]
    cfg.setdefault("mesh_file", "*.glb")
    cfg.setdefault("scale", 1.0)
    cfg.setdefault("floor_z", 0.0)
    cfg.setdefault("anchors", {})
    return cfg


def apply_anchor(args, cfg):
    """If ``--anchor`` is set, override placement args from scene config."""
    anchor_name = getattr(args, "anchor", None)
    if not anchor_name:
        return
    anchors = cfg.get("anchors", {})
    if anchor_name not in anchors:
        print(f"[error] Anchor '{anchor_name}' not found in scene config")
        print(f"[error] Available anchors: {list(anchors.keys())}")
        sys.exit(1)
    a = anchors[anchor_name]
    args.base_x = a.get("base_x", args.base_x)
    args.base_y = a.get("base_y", args.base_y)
    args.base_lift = a.get("base_lift", args.base_lift)
    args.yaw = a.get("yaw", args.yaw)
    args.surface_z = a.get("surface_z", args.surface_z)
    if "cube_dx" in a:
        args.cube_dx = a["cube_dx"]
    if "cube_dy" in a:
        args.cube_dy = a["cube_dy"]
    if "cam_up" in a:
        args._cam_up_override = a["cam_up"]
    if "cam_side" in a:
        args._cam_side_override = a["cam_side"]
    desc = a.get("description", "")
    print(f"[anchor] {anchor_name}: base_xy=({args.base_x:.2f}, {args.base_y:.2f}) "
          f"base_lift={args.base_lift:.2f} yaw={args.yaw}° "
          f"surface_z={args.surface_z:.2f}")
    if desc:
        print(f"[anchor] {desc}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def add_pick_args(ap: argparse.ArgumentParser) -> None:
    """Register scene + placement + rendering CLI args."""
    ap.add_argument("--scene", type=str, default=DEFAULT_SCENE,
                    help=f"Scene name (loads scenes/<name>.json, "
                         f"default: {DEFAULT_SCENE})")
    ap.add_argument("--mesh-file", type=str, default=None,
                    help="Override visual mesh file (e.g. rustic_kitchen_hq.glb)")
    ap.add_argument("--collision-mesh", type=str, default=None,
                    help="Override collision mesh file (e.g. rustic_kitchen_collider.glb)")
    ap.add_argument("--no-scene-mesh", action="store_true",
                    help="Do not load custom scene mesh; use a flat plane at z=0")
    ap.add_argument("--scale", type=float, default=None,
                    help="Override scene mesh scale")
    ap.add_argument("--cube-friction", type=float, default=1.5)
    ap.add_argument("--anchor", type=str, default=None,
                    help="Load placement from scene anchor (e.g. left_counter)")
    ap.add_argument("--show-axes", action="store_true",
                    help="Draw RGB axis markers at world origin")
    # Camera layout: up+side (fixed world cams) or up+wrist (eye-in-hand).
    ap.add_argument(
        "--camera-layout", type=str, default="up_side",
        choices=["up_side", "up_wrist"],
        help="Camera layout: up+side (fixed world cams) or up+wrist "
             "(camera attached to Franka hand link). Wrist mirrors "
             "01_gen_data.py R9d D040 defaults.",
    )
    # Wrist-camera hand-link-local pose (R9d D040 defaults, validated on flat).
    ap.add_argument("--wrist-cam-pos-x", type=float, default=0.05)
    ap.add_argument("--wrist-cam-pos-y", type=float, default=0.00)
    ap.add_argument("--wrist-cam-pos-z", type=float, default=-0.08,
                    help="Negative z = above hand")
    ap.add_argument("--wrist-cam-lookat-x", type=float, default=0.00)
    ap.add_argument("--wrist-cam-lookat-y", type=float, default=0.00)
    ap.add_argument("--wrist-cam-lookat-z", type=float, default=0.10,
                    help="Positive z = below hand (toward gripper tip)")
    ap.add_argument("--wrist-cam-up-x", type=float, default=0.0)
    ap.add_argument("--wrist-cam-up-y", type=float, default=0.0)
    ap.add_argument("--wrist-cam-up-z", type=float, default=-1.0)
    ap.add_argument("--wrist-cam-fov", type=float, default=65.0)
    add_placement_args(ap, defaults=PLACEMENT_DEFAULTS)


# ---------------------------------------------------------------------------
# Axis rulers (used by --show-axes)
# ---------------------------------------------------------------------------
RULER_STEP = 0.5
RULER_CUBE = 0.03

def _add_axis_rulers(scene, gs, hq_path, scale):
    """Place ruler cubes along XY(+/-) and Z(+) at 0.5m intervals, clipped to AABB."""
    try:
        bbox_min, bbox_max, _ = mesh_aabb(hq_path, scale=scale, opengl_correct=True)
        x_lo, x_hi = float(bbox_min[0]), float(bbox_max[0])
        y_lo, y_hi = float(bbox_min[1]), float(bbox_max[1])
        z_hi = float(bbox_max[2])
    except Exception:
        x_lo, x_hi, y_lo, y_hi, z_hi = -3.0, 3.0, -3.0, 3.0, 3.0

    # Origin cube + axis arrows
    scene.add_entity(
        morph=gs.morphs.Box(size=(0.04, 0.04, 0.04), pos=(0, 0, 0), fixed=True),
        surface=gs.surfaces.Default(color=(1, 1, 1, 1)),
    )
    arrow_len = 0.5
    arrow_thick = 0.012
    scene.add_entity(
        morph=gs.morphs.Box(size=(arrow_len, arrow_thick, arrow_thick),
                            pos=(arrow_len / 2, 0, 0), fixed=True),
        surface=gs.surfaces.Default(color=(1, 0, 0, 1)),
    )
    scene.add_entity(
        morph=gs.morphs.Box(size=(arrow_thick, arrow_len, arrow_thick),
                            pos=(0, arrow_len / 2, 0), fixed=True),
        surface=gs.surfaces.Default(color=(0, 1, 0, 1)),
    )
    scene.add_entity(
        morph=gs.morphs.Box(size=(arrow_thick, arrow_thick, arrow_len),
                            pos=(0, 0, arrow_len / 2), fixed=True),
        surface=gs.surfaces.Default(color=(0, 0, 1, 1)),
    )

    def _brightness(v, lo, hi):
        span = hi - lo
        return 0.3 + 0.7 * ((v - lo) / span) if span > 0 else 0.65

    x_vals = np.arange(
        math.floor(x_lo / RULER_STEP) * RULER_STEP,
        math.ceil(x_hi / RULER_STEP) * RULER_STEP + RULER_STEP * 0.5,
        RULER_STEP,
    )
    for v in x_vals:
        if abs(v) < 1e-6:
            continue
        b = _brightness(v, x_lo, x_hi)
        scene.add_entity(
            morph=gs.morphs.Box(size=(RULER_CUBE, RULER_CUBE, RULER_CUBE),
                                pos=(v, 0, 0), fixed=True),
            surface=gs.surfaces.Default(color=(b, 0, 0, 1)),
        )

    y_vals = np.arange(
        math.floor(y_lo / RULER_STEP) * RULER_STEP,
        math.ceil(y_hi / RULER_STEP) * RULER_STEP + RULER_STEP * 0.5,
        RULER_STEP,
    )
    for v in y_vals:
        if abs(v) < 1e-6:
            continue
        b = _brightness(v, y_lo, y_hi)
        scene.add_entity(
            morph=gs.morphs.Box(size=(RULER_CUBE, RULER_CUBE, RULER_CUBE),
                                pos=(0, v, 0), fixed=True),
            surface=gs.surfaces.Default(color=(0, b, 0, 1)),
        )

    z_vals = np.arange(RULER_STEP, math.ceil(z_hi / RULER_STEP) * RULER_STEP + RULER_STEP * 0.5, RULER_STEP)
    for v in z_vals:
        b = _brightness(v, 0, z_hi)
        scene.add_entity(
            morph=gs.morphs.Box(size=(RULER_CUBE, RULER_CUBE, RULER_CUBE),
                                pos=(0, 0, v), fixed=True),
            surface=gs.surfaces.Default(color=(0, 0, b, 1)),
        )

    print(f"[axes] rulers: X=[{x_lo:+.1f}, {x_hi:+.1f}] Y=[{y_lo:+.1f}, {y_hi:+.1f}] "
          f"Z=[0, {z_hi:+.1f}]  step={RULER_STEP}m")


# ---------------------------------------------------------------------------
# Scene builder
# ---------------------------------------------------------------------------
def build_scene(args, gs):
    """Build scene + Franka + cube + cameras.

    Returns ``(scene, franka, cube, cam_overview, cam_up, cam_side, info)``.
    """
    cfg = load_scene_config(args.scene)
    s = args.scale if args.scale is not None else cfg["scale"]

    visual_path = None
    collision_path = None
    if not getattr(args, "no_scene_mesh", False):
        asset_dir = cfg["asset_dir"]
        visual_file = args.mesh_file or cfg["mesh_file"]
        visual_path = asset_dir / visual_file
        if not visual_path.exists():
            print(f"[error] Visual mesh not found: {visual_path}")
            sys.exit(1)

        col_file = getattr(args, "collision_mesh", None) or cfg.get("collision_mesh")
        if col_file:
            collision_path = asset_dir / col_file
            if not collision_path.exists():
                print(f"[warn] Collision mesh not found: {collision_path}, skipping")
                collision_path = None

        floor_z = cfg["floor_z"]
    else:
        floor_z = 0.0
        print("[scene] no-scene-mesh=True -> using flat plane at z=0")

    apply_anchor(args, cfg)
    args.base_z = floor_z + getattr(args, "base_lift", 0.0)
    print(f"[placement] floor_z={floor_z:.3f} base_lift={args.base_lift:.3f} "
          f"-> base_z={args.base_z:.3f}")

    base_xy = (args.base_x, args.base_y)
    yaw_rad = math.radians(args.yaw)
    surface_z = args.surface_z

    cube_local_xy = (args.cube_dx, args.cube_dy)
    ws = compute_workspace(base_xy, yaw_rad, surface_z,
                           cube_half_z=CUBE_SIZE[2] / 2.0,
                           cube_local_xy=cube_local_xy)

    scene = gs.Scene(
        sim_options=gs.options.SimOptions(
            dt=1.0 / getattr(args, "fps", 30), substeps=4),
        rigid_options=gs.options.RigidOptions(
            enable_collision=True, enable_joint_limit=True,
            box_box_detection=False),
        vis_options=gs.options.VisOptions(ambient_light=(0.4, 0.4, 0.4)),
        renderer=gs.renderers.Rasterizer(),
        show_viewer=False,
    )

    if visual_path is not None:
        if collision_path is not None:
            load_mesh(scene, gs, collision_path, scale=s, opengl_correct=True,
                      collision=True, visualization=False)
            load_mesh(scene, gs, visual_path, scale=s, opengl_correct=True,
                      collision=False, visualization=True)
        else:
            load_mesh(scene, gs, visual_path, scale=s, opengl_correct=True)
    else:
        scene.add_entity(gs.morphs.Plane())

    if getattr(args, "show_axes", False):
        _add_axis_rulers(scene, gs, visual_path, s)

    cx, cy, cz = ws["cube"]
    plat_thick = 0.02
    scene.add_entity(
        morph=gs.morphs.Box(
            size=(0.40, 0.40, plat_thick),
            pos=(cx, cy, surface_z - plat_thick / 2.0),
            fixed=True,
        ),
        material=gs.materials.Rigid(friction=2.0),
        surface=gs.surfaces.Default(color=(0.3, 0.25, 0.2, 0.0)),
    )

    cube = scene.add_entity(
        morph=gs.morphs.Box(size=CUBE_SIZE, pos=ws["cube"]),
        material=gs.materials.Rigid(friction=args.cube_friction),
        surface=gs.surfaces.Default(color=(1.0, 0.3, 0.3, 1.0)),
    )

    franka = load_franka(
        scene, gs,
        pos=(args.base_x, args.base_y, args.base_z),
        euler=(0, 0, args.yaw),
    )

    bx, by, fz = args.base_x, args.base_y, args.base_z
    cx, cy, cz = ws["cube"]
    cam_overview = scene.add_camera(
        res=(args.res_w, args.res_h),
        pos=(bx, 0.8 * s, 0.65 * s + fz),
        lookat=(bx, -0.6 * s, 0.45 * s + fz),
        fov=65, GUI=False,
    )

    mid_x = (bx + cx) / 2.0
    cam_front = scene.add_camera(
        res=(args.res_w, args.res_h),
        pos=(mid_x + 1.2, by, 0.4 + fz),
        lookat=(mid_x, by, 0.15 + fz),
        fov=55, GUI=False,
    )

    cu, cs = ws["cam_up"], ws["cam_side"]
    cu_ov = getattr(args, "_cam_up_override", None)
    cs_ov = getattr(args, "_cam_side_override", None)
    if cu_ov:
        print(f"[cam_up] override → pos={cu_ov['pos']} lookat={cu_ov['lookat']}")
        cu = dict(pos=tuple(cu_ov["pos"]), lookat=tuple(cu_ov["lookat"]),
                  fov=cu_ov.get("fov", cu["fov"]), res=cu["res"])
    if cs_ov:
        print(f"[cam_side] override → pos={cs_ov['pos']} lookat={cs_ov['lookat']}")
        cs = dict(pos=tuple(cs_ov["pos"]), lookat=tuple(cs_ov["lookat"]),
                  fov=cs_ov.get("fov", cs["fov"]), res=cs["res"])
    cam_up = scene.add_camera(
        res=cu["res"], pos=cu["pos"], lookat=cu["lookat"],
        fov=cu["fov"], GUI=False,
    )

    camera_layout = getattr(args, "camera_layout", "up_side")
    if camera_layout == "up_wrist":
        # Pass hand-link-local pose here; attach_wrist_cam() below binds it to
        # the franka hand after scene.build() (must be called by caller).
        cam_side = scene.add_camera(
            res=cs["res"],
            pos=(args.wrist_cam_pos_x, args.wrist_cam_pos_y, args.wrist_cam_pos_z),
            lookat=(args.wrist_cam_lookat_x, args.wrist_cam_lookat_y, args.wrist_cam_lookat_z),
            fov=args.wrist_cam_fov,
            GUI=False,
        )
        print(f"[cam] layout=up_wrist  pos=({args.wrist_cam_pos_x:.2f},"
              f"{args.wrist_cam_pos_y:.2f},{args.wrist_cam_pos_z:.2f}) "
              f"fov={args.wrist_cam_fov}  (attach after scene.build())")
    else:
        cam_side = scene.add_camera(
            res=cs["res"], pos=cs["pos"], lookat=cs["lookat"],
            fov=cs["fov"], GUI=False,
        )

    info = dict(
        scene_name=args.scene, scene_config=cfg,
        base_xy=base_xy, base_z=args.base_z, yaw=args.yaw,
        surface_z=surface_z, cube_pos=ws["cube"],
        camera_layout=camera_layout,
    )
    return scene, franka, cube, cam_overview, cam_front, cam_up, cam_side, info


def attach_wrist_cam(args, franka, cam_side, gs):
    """If ``camera_layout == up_wrist``, bind ``cam_side`` to the hand link.

    Must be called after ``scene.build()`` so that franka links are resolved.
    Silently no-op for up_side layout so callers can invoke unconditionally.
    """
    if getattr(args, "camera_layout", "up_side") != "up_wrist":
        return
    import torch
    from genesis.utils.geom import pos_lookat_up_to_T

    hand = franka.get_link("hand")
    wrist_pos = torch.tensor(
        [args.wrist_cam_pos_x, args.wrist_cam_pos_y, args.wrist_cam_pos_z],
        dtype=gs.tc_float, device=gs.device,
    )
    wrist_lookat = torch.tensor(
        [args.wrist_cam_lookat_x, args.wrist_cam_lookat_y, args.wrist_cam_lookat_z],
        dtype=gs.tc_float, device=gs.device,
    )
    wrist_up = torch.tensor(
        [args.wrist_cam_up_x, args.wrist_cam_up_y, args.wrist_cam_up_z],
        dtype=gs.tc_float, device=gs.device,
    )
    wrist_offset_T = pos_lookat_up_to_T(wrist_pos, wrist_lookat, wrist_up)
    try:
        cam_side.attach(rigid_link=hand, offset_T=wrist_offset_T)
    except TypeError:
        cam_side.attach(hand, wrist_offset_T)
    print("[cam] wrist camera attached to franka hand link")
