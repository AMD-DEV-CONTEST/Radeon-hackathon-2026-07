"""Scene layout and asset configuration for color sorting with YCB objects.

Based on franka_fruit_pick_demo's scene_config.py. Key changes:
- Geometric primitives (Box/Cylinder/Sphere) → YCB mesh objects with real textures
- Per-color containers (5-box recessed bins) preserved, enlarged for YCB sizes
- Franka base/table/camera config preserved from demo (D435i-aligned)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh

# == Table (built from box primitives, same as demo) ==
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

# == YCB assets path ==
ASSETS = Path(__file__).resolve().parent.parent / "assets" / "ycb"

# == YCB object layout ==
# Each object: real-world color, position on tabletop, euler rotation.
# Train colors: red, yellow, purple. Eval colors: green, orange.
# Objects excluded per demo findings: pear (round cross-section slips).
YCB_LAYOUT: dict[str, dict] = {
    # Train objects — each placed within ~0.12m of its container so the lateral transport
    # stays short (round YCB objects eject from parallel jaws on long lateral transports).
    # Objects are y-spaced 0.24m so the 20cm banana can rotate freely without hitting neighbors.
    # The banana is elongated and grips well, so it can sit farther from its bin (no overlap).
    "013_apple": {"pos": (0.44, 0.24, 0.0), "euler": (0.0, 0.0, 0.0), "color": "red", "friction": 1.0},
    "011_banana": {"pos": (0.36, 0.0, 0.0), "euler": (0.0, 0.0, 35.0), "color": "yellow", "friction": 1.0},
    "018_plum": {"pos": (0.44, -0.24, 0.0), "euler": (0.0, 0.0, 0.0), "color": "purple", "friction": 1.0},
    # Eval objects (hold-out, not in training data)
    "014_lemon": {"pos": (0.44, 0.0, 0.0), "euler": (0.0, 0.0, 0.0), "color": "yellow", "friction": 1.0},
    "017_orange": {"pos": (0.44, -0.24, 0.0), "euler": (0.0, 0.0, 0.0), "color": "orange", "friction": 1.0},
}

# Train/eval split
TRAIN_YCB_NAMES = ("013_apple", "011_banana", "018_plum")
EVAL_YCB_NAMES = ("014_lemon", "017_orange")

# Color mapping for task descriptions and containers
COLOR_RGB = {
    "red": (0.9, 0.1, 0.1),
    "yellow": (0.95, 0.85, 0.1),
    "purple": (0.6, 0.1, 0.7),
    "green": (0.1, 0.7, 0.2),
    "orange": (0.95, 0.55, 0.1),
}

# YCB object → display name for task descriptions
YCB_DISPLAY_NAMES = {
    "013_apple": "apple",
    "011_banana": "banana",
    "018_plum": "plum",
    "014_lemon": "lemon",
    "017_orange": "orange",
}

# == Per-color containers (5-box recessed bin) ==
# Enlarged to 16cm so the 20cm banana can sit diagonally (20cm < 16*sqrt(2)=22.6cm)
# and dip its bottom below the rim. Round objects (apple/plum/lemon/orange) fit easily.
CONTAINER_BOTTOM_SIZE = (0.16, 0.16, 0.004)  # floor slab (lx, ly, lz)
CONTAINER_WALL_THICKNESS = 0.004
CONTAINER_WALL_HEIGHT = 0.05
CONTAINER_INNER_SIZE = 0.16 - 2 * CONTAINER_WALL_THICKNESS  # 0.152 m
CONTAINER_RIM_Z_OFFSET = CONTAINER_BOTTOM_SIZE[2] + CONTAINER_WALL_HEIGHT  # 0.054 m above table
CONTAINER_RIM_MARGIN = 0.01
CONTAINER_LAYOUT = {
    "red": (0.56, 0.24),
    "yellow": (0.56, 0.00),
    "purple": (0.56, -0.24),
    "green": (0.62, 0.15),
    "orange": (0.62, -0.15),
}

# == Reachable workspace on the tabletop (from demo, empirically verified) ==
REACH_X = (0.28, 0.52)
REACH_Y = (-0.22, 0.22)

# == Franka configuration (preserved from demo) ==
FRANKA_QPOS = (0.0, -0.3, 0.0, -2.0, 0.0, 1.7, 0.79, 0.04, 0.04)
FRANKA_KP = (4500, 4500, 3500, 3500, 2000, 2000, 2000, 100, 100)
FRANKA_KV = (450, 450, 350, 350, 200, 200, 200, 10, 10)
FRANKA_FORCE_MIN = (-87, -87, -87, -87, -12, -12, -12, -100, -100)
FRANKA_FORCE_MAX = (87, 87, 87, 87, 12, 12, 12, 100, 100)

# == Cameras (preserved from demo, D435i-aligned) ==
WORLD_CAM_RES = (1280, 720)
WORLD_CAM_POS = (
    TABLE_CENTER[0] + TABLE_TOP_SIZE[0] / 2,
    TABLE_CENTER[1] - TABLE_TOP_SIZE[1] / 2,
    TABLE_TOP_Z + 1.0,
)
WORLD_CAM_LOOKAT = (TABLE_CENTER[0], TABLE_CENTER[1], TABLE_TOP_Z)
WORLD_CAM_FOV = 42

WRIST_CAM_RES = (1280, 720)
WRIST_CAM_FOV = 42
WRIST_CAM_LINK = "hand"
WRIST_CAM_OFFSET_POS = (0.05, 0.0, -0.03)
WRIST_CAM_OFFSET_EULER = (180.0, 0.0, 0.0)
WRIST_CAM_NEAR = 0.01
WRIST_CAM_FAR = 20.0

VIDEO_CAM_RES = (1280, 720)
VIDEO_CAM_POS = (
    TABLE_CENTER[0],
    TABLE_CENTER[1] - 1.0,
    TABLE_TOP_Z + 0.45,
)
VIDEO_CAM_LOOKAT = (TABLE_CENTER[0], TABLE_CENTER[1], TABLE_TOP_Z + 0.05)
VIDEO_CAM_FOV = 42


@dataclass(frozen=True)
class YCBAsset:
    """A YCB object with precomputed geometry."""
    name: str
    mesh_path: Path
    collision_path: Path
    rest_z_offset: float  # z from mesh origin to lowest point (m)
    radius_xy: float  # circumscribed radius of xy footprint (m)
    color: str  # assigned color category
    friction: float


def _mesh_geometry(mesh_path: Path) -> tuple[float, float]:
    """Return (rest_z_offset, radius_xy) from a mesh's axis-aligned bounds."""
    mesh = trimesh.load(mesh_path, force="mesh")
    lower, upper = mesh.bounds
    rest_z_offset = float(-lower[2])
    dx = float(upper[0] - lower[0])
    dy = float(upper[1] - lower[1])
    radius_xy = 0.5 * float((dx**2 + dy**2) ** 0.5)
    return rest_z_offset, radius_xy


def get_ycb_assets(names: tuple[str, ...]) -> dict[str, YCBAsset]:
    """Return YCBAsset dict for the given YCB object names."""
    assets: dict[str, YCBAsset] = {}
    for name in names:
        layout = YCB_LAYOUT[name]
        mesh_path = ASSETS / name / "textured.obj"
        collision_path = ASSETS / name / "collision.ply"
        rest_z_offset, radius_xy = _mesh_geometry(mesh_path)
        assets[name] = YCBAsset(
            name=name,
            mesh_path=mesh_path,
            collision_path=collision_path,
            rest_z_offset=rest_z_offset,
            radius_xy=radius_xy,
            color=layout["color"],
            friction=layout.get("friction", 1.0),
        )
    return assets


def get_ycb_names_for_split(split: str) -> tuple[str, ...]:
    if split == "train":
        return TRAIN_YCB_NAMES
    elif split == "eval":
        return EVAL_YCB_NAMES
    return tuple(YCB_LAYOUT.keys())
