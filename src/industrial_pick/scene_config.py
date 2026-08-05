"""Scene layout and asset configuration for the Franka industrial SORTING scene.

The tabletop holds THREE open-top sorting boxes -- red / green / blue -- placed in a
parallel row on the far side of the tabletop. Each part has a dedicated target box
(an industrial parts-sorting task):

    hex nut -> red box,  bolt -> green box,  gear -> blue box

The pick objects are industrial STL parts scaled UP to fruit-comparable size so the
VLA policy can see and grasp them reliably.

    object  source mesh                          native size (m)        scale  sim size (m)
    gear    assets/industrial/gear.stl           0.038 x 0.041 x 0.008  1.6    0.061 x 0.065 x 0.013
    nut     assets/industrial/nut.stl            0.042 x 0.036 x 0.018  1.5    0.062 x 0.054 x 0.027
    bolt    assets/industrial/bolt.stl           0.042 x 0.036 x 0.043  1.5    0.062 x 0.054 x 0.065

The boxes are built from fixed box primitives (bottom panel + 4 walls) in
``build_scene._add_sorting_boxes`` -- not mesh entities -- so their collision is exact
and they stay put across episodes (only the pick objects are jittered per episode).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import trimesh

# Bundled assets live at the repo root (one level above this package); see paths.py.
ASSETS = Path(__file__).resolve().parent.parent / "assets"

# == Table (built from box primitives) ==
TABLE_TOP_Z = 0.75  # height of the tabletop surface (m)
TABLE_CENTER = (0.35, 0.0)  # (x, y) center of the tabletop
TABLE_TOP_SIZE = (1.20, 0.80, 0.05)  # tabletop (length_x, width_y, thickness_z)
TABLE_LEG_SIZE = (0.06, 0.06)  # leg cross-section (x, y)
TABLE_LEG_INSET = 0.10  # how far legs are inset from the tabletop edges
TABLE_COLOR = (0.62, 0.47, 0.35, 1.0)
TABLE_LEG_COLOR = (0.47, 0.35, 0.24, 1.0)

# == Franka base, mounted on the tabletop near the rear (-x) edge, facing +x ==
FRANKA_POS = (-0.10, 0.0, TABLE_TOP_Z)
FRANKA_EULER = (0.0, 0.0, 0.0)

# == Pick-object xy positions on the tabletop (z filled in at build time) ==
# Slot layout spread apart to reduce grasp-time collisions and give the per-episode
# randomizer position-jitter room. The bolt slot sits 2 cm toward the robot so its
# jitter disk clears the green sorting box at (0.60, 0.0).
# Each entry may set:
#   scale    -- uniform mesh scale (industrial parts are scaled up to fruit size)
#   euler    -- spawn orientation (deg); bolt.stl is z-up (standing) at euler 0
#   friction -- optional per-object contact friction override
YCB_LAYOUT = {
    # gear: flat toothed disk, grasped across its rim (top-down). Banana's old slot.
    "gear": {"pos": (0.31, 0.22, 0.0), "euler": (0.0, 0.0, 0.0), "scale": 1.6, "friction": 1.0},
    # hex nut: flat ring, grasped across its rim (top-down). Lemon's old slot.
    "nut": {"pos": (0.34, -0.08, 0.0), "euler": (0.0, 0.0, 0.0), "scale": 1.5, "friction": 1.0},
    # bolt: standing (z-up), grasped on the shaft below the head. Slot shifted 2 cm
    # toward the robot from (0.44, 0.08) for green-box wall clearance.
    "bolt": {"pos": (0.42, 0.10, 0.0), "euler": (0.0, 0.0, 0.0), "scale": 1.5, "friction": 1.0},
}

# == Sorting boxes: three open-top boxes in a parallel row ==
# Built from fixed box primitives in build_scene (bottom + 4 walls each). Colors are
# TASK-RELEVANT (the sort key), so the boxes are exempt from Layer-A color DR.
#
#   outer footprint 0.14 x 0.14 m, wall height 0.06 m,
#   wall thickness 0.008 m, bottom panel 0.012 m -> inner 0.124 x 0.124 m
#   (all three parts, ~6.5 cm across, drop in easily).
#
# Row sits at x = 0.60 on the far side of the table, boxes 24 cm apart in y. Verified
# clearances: every object slot's jitter disk stays clear of every box wall (the
# tightest is bolt<->green at ~4.6 cm raw clearance).
SORT_BOX_OUTER = (0.14, 0.14)      # (lx, ly) outer footprint (m)
SORT_BOX_WALL_T = 0.008            # wall thickness (m)
SORT_BOX_WALL_H = 0.06             # wall height above the tabletop (m)
SORT_BOX_BOTTOM_T = 0.012          # bottom panel thickness (m)
SORT_BOXES = {
    # name        center (x, y)        color (RGBA)
    "red_box":   {"pos": (0.60, -0.24), "color": (0.78, 0.16, 0.14, 1.0)},
    "green_box": {"pos": (0.60,  0.00), "color": (0.20, 0.62, 0.24, 1.0)},
    "blue_box":  {"pos": (0.60,  0.24), "color": (0.18, 0.32, 0.75, 1.0)},
}

# Which box each part is sorted into (the task mapping).
SORT_TARGET = {
    "nut": "red_box",
    "bolt": "green_box",
    "gear": "blue_box",
}

# Human-readable box names for the natural-language task string.
BOX_DISPLAY_NAMES = {
    "red_box": "red box",
    "green_box": "green box",
    "blue_box": "blue box",
}

# Which layout entries are industrial STL parts (all of them).
INDUSTRIAL_OBJECTS = ("gear", "nut", "bolt")

# == M4 domain randomization: Layer-A per-object appearance priors ==
# Industrial parts are machined metal: keep saturation near zero (neutral steel/zinc gray)
# and randomize only brightness, so recolored parts stay plausible (never colorful).
# The sorting boxes are NOT recolored: their color is the sort key (task-relevant).
DR_APPEARANCE_PRIORS = {
    "gear": {"hue": (0.0, 360.0), "sat": (0.00, 0.12), "val": (0.45, 0.75)},
    "nut": {"hue": (0.0, 360.0), "sat": (0.00, 0.12), "val": (0.50, 0.80)},
    "bolt": {"hue": (0.0, 360.0), "sat": (0.00, 0.15), "val": (0.35, 0.65)},
}

# Base metallic surface colors when DR object recolor is off (STLs carry no texture).
INDUSTRIAL_COLORS = {
    "gear": (0.58, 0.60, 0.63, 1.0),  # machined steel
    "nut": (0.66, 0.68, 0.70, 1.0),   # zinc-plated
    "bolt": (0.45, 0.47, 0.50, 1.0),  # darker steel
}

# == Reachable workspace on the tabletop (empirically verified grasp region) ==
# Objects sampled outside this box tend to be unreachable (IK fails) or drift off the
# tuned grasp region. Used by the M2 randomizer to clamp jittered object poses.
REACH_X = (0.30, 0.50)
REACH_Y = (-0.22, 0.28)

FRANKA_QPOS = (0.0, -0.3, 0.0, -2.0, 0.0, 1.7, 0.79, 0.04, 0.04)
FRANKA_KP = (4500, 4500, 3500, 3500, 2000, 2000, 2000, 100, 100)
FRANKA_KV = (450, 450, 350, 350, 200, 200, 200, 10, 10)
FRANKA_FORCE_MIN = (-87, -87, -87, -87, -12, -12, -12, -100, -100)
FRANKA_FORCE_MAX = (87, 87, 87, 87, 12, 12, 12, 100, 100)

# == Cameras ==
# World camera: a fixed third-person view of the tabletop. Intrinsics are matched to
# the Intel RealSense D435i RGB (color) module, same as the wrist camera: FOV
# 69 deg (H) x 42 deg (V) at native 16:9. Using vfov = 42 deg at 1280x720 gives
# H-FOV ~= 68.6 deg and intrinsics fx = fy ~= 938 px, cx = 640, cy = 360. Only the
# extrinsics (pos / lookat) differ from the wrist camera.
WORLD_CAM_RES = (1280, 720)
# Placed 1 m directly above the table corner closest to the viewer (+x, -y corner).
#   x = 0.35 + 1.20/2 = 0.95,  y = 0.0 - 0.80/2 = -0.40,  z = 0.75 + 1.0 = 1.75
WORLD_CAM_POS = (
    TABLE_CENTER[0] + TABLE_TOP_SIZE[0] / 2,
    TABLE_CENTER[1] - TABLE_TOP_SIZE[1] / 2,
    TABLE_TOP_Z + 1.0,
)
WORLD_CAM_LOOKAT = (TABLE_CENTER[0], TABLE_CENTER[1], TABLE_TOP_Z)
WORLD_CAM_FOV = 42  # vertical FOV in degrees (D435i RGB module)

# Wrist camera: mounted on the Franka hand link (eye-in-hand), looking toward the
# grasp area. Parameters are matched to a real Intel RealSense D435i.
#
# Genesis derives a simple pinhole intrinsic purely from (resolution, vertical FOV):
#     fx = fy = 0.5 * height / tan(vfov / 2),  cx = width / 2,  cy = height / 2
# so matching D435i means picking the right resolution aspect ratio + vertical FOV.
#
# Used as an RGB-only camera (depth channel ignored), matched to the D435i *color*
# module spec: FOV 69 deg (H) x 42 deg (V), native 16:9 sensor.
# Using vfov = 42 deg at 1280x720 reproduces the horizontal FOV automatically:
#     H-FOV = 2 * atan((1280/720) * tan(21 deg)) ~= 68.6 deg  (~= 69 deg).
# Resulting intrinsics @ 1280x720: fx = fy ~= 938 px, cx = 640, cy = 360,
# which closely matches a real D435i color stream at this resolution.
WRIST_CAM_RES = (1280, 720)
WRIST_CAM_FOV = 42  # vertical FOV in degrees (D435i RGB module)
WRIST_CAM_LINK = "hand"
# Camera pose relative to the hand link frame. On the Franka, the hand link +z
# points along the gripper approach direction (toward the fingertips). The camera's
# optical axis is its local -z, so a 180 deg rotation about x makes -z align with
# the hand +z, i.e. the camera looks forward along the approach direction. The
# position offset sits the camera slightly behind the hand origin so the fingers
# stay in view.
WRIST_CAM_OFFSET_POS = (0.05, 0.0, -0.03)
WRIST_CAM_OFFSET_EULER = (180.0, 0.0, 0.0)
# Near clip plane for the wrist (eye-in-hand) camera. Genesis' add_camera defaults to
# near=0.1 m, but a grasped object sits only a few cm in front of this camera, so the
# default clips the object's near surface -- it renders "see-through", revealing the
# table/boxes behind it. A small near plane keeps close-up grasped objects fully visible.
# (Only the wrist camera needs this; the world/video cameras are always >0.1 m away.)
WRIST_CAM_NEAR = 0.01
WRIST_CAM_FAR = 20.0

# Video camera: a purely cosmetic third-person view used only for saved eval videos
# (never part of the policy observation / dataset). Placed off the -y long edge of the
# table at the table's x-center, looking straight across toward the tabletop center: the
# look direction lies in the y-z plane (zero x-component, i.e. perpendicular to the x
# axis), giving a side elevation of the workspace along the table's longer edge.
VIDEO_CAM_RES = (1280, 720)
VIDEO_CAM_POS = (
    TABLE_CENTER[0],
    TABLE_CENTER[1] - 1.0,
    TABLE_TOP_Z + 0.45,
)
VIDEO_CAM_LOOKAT = (TABLE_CENTER[0], TABLE_CENTER[1], TABLE_TOP_Z + 0.05)
VIDEO_CAM_FOV = 42  # vertical FOV in degrees


@dataclass(frozen=True)
class YCBAsset:
    name: str
    mesh_path: Path
    collision_path: Path
    scale: float  # uniform mesh scale applied at spawn (industrial parts: >1)
    rest_z_offset: float  # z distance from (scaled) mesh origin to its lowest point (m)
    radius_xy: float  # circumscribed radius of the (scaled) mesh's xy footprint (m)


def _mesh_geometry(mesh_path: Path, scale: float) -> tuple[float, float]:
    """Return (rest_z_offset, radius_xy) from a mesh's axis-aligned bounds, times ``scale``.

    radius_xy is the circumscribed radius of the xy bounding box (half its diagonal),
    a rotation-safe upper bound on the footprint used for non-overlap spacing.
    """
    mesh = trimesh.load(mesh_path, force="mesh")
    lower, upper = mesh.bounds
    rest_z_offset = float(-lower[2]) * scale
    dx = float(upper[0] - lower[0]) * scale
    dy = float(upper[1] - lower[1]) * scale
    radius_xy = 0.5 * float((dx**2 + dy**2) ** 0.5)
    return rest_z_offset, radius_xy


def get_ycb_assets() -> dict[str, YCBAsset]:
    assets: dict[str, YCBAsset] = {}
    for name, layout in YCB_LAYOUT.items():
        scale = float(layout.get("scale", 1.0))
        if name in INDUSTRIAL_OBJECTS:
            mesh_path = ASSETS / "industrial" / f"{name}.stl"
            collision_path = mesh_path  # convexified at load; no separate collision mesh
        else:
            mesh_path = ASSETS / "ycb" / name / "textured.obj"
            collision_path = ASSETS / "ycb" / name / "collision.ply"
        rest_z_offset, radius_xy = _mesh_geometry(mesh_path, scale)
        assets[name] = YCBAsset(
            name=name,
            mesh_path=mesh_path,
            collision_path=collision_path,
            scale=scale,
            rest_z_offset=rest_z_offset,
            radius_xy=radius_xy,
        )
    return assets
