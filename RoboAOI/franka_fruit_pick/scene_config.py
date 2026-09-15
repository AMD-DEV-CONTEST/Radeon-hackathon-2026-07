"""Scene layout and asset configuration for the Franka manipulation scene."""

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

# == YCB object xy positions on the tabletop (z filled in at build time) ==
# Minimal pick-and-place set for pipeline development: three reliably reachable pick
# objects plus one place container. Objects that are not reliably graspable by the
# scripted parallel-jaw pick (apple, orange, pear, mug) and the earlier distractors
# (cracker_box, mustard_bottle) are disabled to reduce clutter and grasp-time
# collisions. Re-enable them later (e.g. as M4 distractors) by uncommenting.
YCB_LAYOUT = {
    # -- disabled distractors / hard-to-grasp objects --
    # "003_cracker_box": {"pos": (0.28, -0.18, 0.0), "euler": (0.0, 0.0, 15.0)},
    # "006_mustard_bottle": {"pos": (0.42, 0.04, 0.0), "euler": (0.0, 0.0, -20.0)},
    # apple/orange: large smooth spheres (~7.5 cm) -- only marginally graspable (flaky at
    # realistic friction) and near the gripper's 8 cm limit.
    # "013_apple": {"pos": (0.45, 0.28, 0.0), "euler": (0.0, 0.0, 0.0), "friction": 1.0},
    # "017_orange": {"pos": (0.45, -0.22, 0.0), "euler": (0.0, 0.0, 0.0), "friction": 1.0},
    # pear: round cross-section (~6.6 cm) makes parallel jaws slip on lift -- not reliable.
    # "016_pear": {"pos": (0.35, -0.13, 0.0), "euler": (0.0, 0.0, 90.0), "friction": 1.0},
    # mug: currently fails the scripted grasp (thin walls / handle) -- disabled for now.
    # "025_mug": {"pos": (0.22, 0.10, 0.0), "euler": (0.0, 0.0, 10.0)},
    # -- active pick objects (spread apart to reduce grasp-time collisions and give the
    #    M2 randomizer some position-jitter room) --
    "011_banana": {"pos": (0.31, 0.22, 0.0), "euler": (0.0, 0.0, 35.0)},
    # lemon: small oblate ellipsoid; grasped near its equator. In pickable pool.
    "014_lemon": {"pos": (0.34, -0.08, 0.0), "euler": (0.0, 0.0, 0.0), "friction": 1.0},
    # plum: small near-sphere (~5.3 cm); grasped near its equator. In pickable pool.
    "018_plum": {"pos": (0.44, 0.08, 0.0), "euler": (0.0, 0.0, 0.0), "friction": 1.0},
    # -- place container --
    "024_bowl": {"pos": (0.50, -0.10, 0.0), "euler": (0.0, 0.0, 0.0)},
}

# == M4 domain randomization: Layer-A per-object appearance priors ==
# Domain randomization (DR) of object color is deliberately constrained to each object's
# *real-world* appearance distribution, so recolored objects stay physically plausible
# (a banana may drift yellow <-> yellow-green for ripeness, but never turns black/blue).
#
# Sampling happens in HSV -- hue in degrees [0, 360), saturation/value in [0, 1] -- because
# the natural variation of these objects is a narrow band on the hue axis plus a
# value/saturation range, which is awkward to express in RGB. A value *floor* keeps
# objects from going implausibly dark.
#
# Only objects with an entry here get recolored (and only when object-color DR is turned
# on); everything else keeps its original mesh texture. The bowl is a container, not a
# grasp target, so its color is a task-irrelevant nuisance and its band is left wide.
# Consumed by ``build_scene`` when ``SceneDomainRandomizationConfig.randomize_object_color``.
DR_APPEARANCE_PRIORS = {
    "011_banana": {"hue": (48.0, 68.0), "sat": (0.55, 0.95), "val": (0.60, 0.90)},
    "014_lemon": {"hue": (48.0, 62.0), "sat": (0.60, 1.00), "val": (0.70, 0.95)},
    "018_plum": {"hue": (300.0, 345.0), "sat": (0.35, 0.80), "val": (0.25, 0.55)},
    "024_bowl": {"hue": (0.0, 360.0), "sat": (0.00, 0.70), "val": (0.35, 0.90)},
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
# table/bowl behind it. A small near plane keeps close-up grasped objects fully visible.
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
    rest_z_offset: float  # z distance from mesh origin to its lowest point (m)
    radius_xy: float  # circumscribed radius of the mesh's xy footprint (m)


def _mesh_geometry(mesh_path: Path) -> tuple[float, float]:
    """Return (rest_z_offset, radius_xy) from a mesh's axis-aligned bounds.

    radius_xy is the circumscribed radius of the xy bounding box (half its diagonal),
    a rotation-safe upper bound on the footprint used for non-overlap spacing.
    """
    mesh = trimesh.load(mesh_path, force="mesh")
    lower, upper = mesh.bounds
    rest_z_offset = float(-lower[2])
    dx = float(upper[0] - lower[0])
    dy = float(upper[1] - lower[1])
    radius_xy = 0.5 * float((dx**2 + dy**2) ** 0.5)
    return rest_z_offset, radius_xy


def get_ycb_assets() -> dict[str, YCBAsset]:
    assets: dict[str, YCBAsset] = {}
    for name in YCB_LAYOUT:
        mesh_path = ASSETS / "ycb" / name / "textured.obj"
        collision_path = ASSETS / "ycb" / name / "collision.ply"
        rest_z_offset, radius_xy = _mesh_geometry(mesh_path)
        assets[name] = YCBAsset(
            name=name,
            mesh_path=mesh_path,
            collision_path=collision_path,
            rest_z_offset=rest_z_offset,
            radius_xy=radius_xy,
        )
    return assets
