"""Scene layout and asset configuration for color sorting.

Based on franka_fruit_pick_demo's scene_config.py. Key changes:
- YCB objects replaced with colored Box/Cylinder/Sphere primitives
- Single bowl replaced with per-color containers
- Franka base/table/camera config preserved from demo (D435i-aligned)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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

# == Colored objects layout ==
# Train colors: red, blue, green. Hold-out eval colors: yellow, purple.
# Each color has 3 geometries: Box, Cylinder, Sphere.
# Object size s = 0.04 m (same as RoboPilot grasp_env cubes).
OBJECT_SIZE = 0.04

# Object positions on the tabletop (z filled at build time).
# Spread apart to reduce grasp-time collisions (same approach as demo YCB_LAYOUT).
COLORS = ("red", "blue", "green", "yellow", "purple")
# Pickable geometries: cube + cylinder. Sphere is excluded from the pick pool
# (parallel-jaw gripper cannot reliably hold a smooth sphere — same limitation
# as the demo's exclusion of apple/orange/pear). Spheres remain in the scene
# as visual distractors to increase observation complexity.
GEOMETRIES = ("cube", "cylinder", "sphere")
PICKABLE_GEOMETRIES = ("cube", "cylinder")

# RGB colors for Plastic surface.
COLOR_RGB = {
    "red": (0.9, 0.1, 0.1),
    "blue": (0.1, 0.3, 0.9),
    "green": (0.1, 0.7, 0.2),
    "yellow": (0.95, 0.85, 0.1),
    "purple": (0.6, 0.1, 0.7),
}

# Per-color, per-geometry object positions on the tabletop.
# Format: {color: {geometry: (x, y)}} — z = TABLE_TOP_Z + half_object_height
OBJECT_LAYOUT = {
    "red": {
        "cube": (0.30, 0.15),
        "cylinder": (0.35, -0.10),
        "sphere": (0.40, 0.05),
    },
    "blue": {
        "cube": (0.42, 0.18),
        "cylinder": (0.46, -0.05),  # moved from 0.50 → 0.46 (REACH_X edge → center)
        "sphere": (0.42, -0.18),
    },
    "green": {
        "cube": (0.33, -0.18),
        "cylinder": (0.44, 0.12),  # moved from 0.48 → 0.44 (REACH_X edge → center)
        "sphere": (0.38, 0.00),
    },
    # Hold-out eval colors (not in training data):
    "yellow": {
        "cube": (0.32, 0.10),
        "cylinder": (0.44, -0.12),  # moved from 0.46 → 0.44
        "sphere": (0.40, 0.20),
    },
    "purple": {
        "cube": (0.44, 0.08),
        "cylinder": (0.36, -0.15),
        "sphere": (0.46, 0.00),  # moved from 0.50 → 0.46
    },
}

# == Per-color containers (5-box recessed bin, placed on tabletop) ==
# Each container = bottom slab + 4 walls forming a recessed cavity.
# Inner cavity: 0.072 × 0.072 × 0.026 m (fits 0.04m objects with clearance).
CONTAINER_BOTTOM_SIZE = (0.08, 0.08, 0.004)  # floor slab (lx, ly, lz)
CONTAINER_WALL_THICKNESS = 0.004
CONTAINER_WALL_HEIGHT = 0.03
CONTAINER_INNER_SIZE = 0.08 - 2 * CONTAINER_WALL_THICKNESS  # 0.072 m
CONTAINER_RIM_Z_OFFSET = CONTAINER_BOTTOM_SIZE[2] + CONTAINER_WALL_HEIGHT  # 0.034 m above table
CONTAINER_RIM_MARGIN = 0.01  # how far below the rim the object bottom must dip
CONTAINER_LAYOUT = {
    "red": (0.55, 0.20),
    "blue": (0.55, 0.05),
    "green": (0.55, -0.10),
    "yellow": (0.62, 0.15),
    "purple": (0.62, -0.05),
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
WORLD_CAM_FOV = 42  # vertical FOV (D435i RGB module)

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
class SortObject:
    """A pickable colored geometric object."""

    name: str  # e.g. "red_cube"
    color: str  # e.g. "red"
    geometry: str  # "cube" | "cylinder" | "sphere"
    pos: tuple[float, float]  # (x, y) on tabletop, z filled at build time


@dataclass(frozen=True)
class SortContainer:
    """A per-color place container."""

    name: str  # e.g. "red_bin"
    color: str
    pos: tuple[float, float]  # (x, y) on tabletop


def get_sort_objects(colors: tuple[str, ...] = COLORS) -> list[SortObject]:
    """Return all SortObjects for the given colors."""
    objects = []
    for color in colors:
        for geom in GEOMETRIES:
            x, y = OBJECT_LAYOUT[color][geom]
            objects.append(SortObject(
                name=f"{color}_{geom}",
                color=color,
                geometry=geom,
                pos=(x, y),
            ))
    return objects


def get_sort_containers(colors: tuple[str, ...] = COLORS) -> list[SortContainer]:
    """Return all SortContainers for the given colors."""
    return [
        SortContainer(
            name=f"{color}_bin",
            color=color,
            pos=CONTAINER_LAYOUT[color],
        )
        for color in colors
    ]


def object_rest_z_offset(geometry: str, size: float = OBJECT_SIZE) -> float:
    """Z offset from object origin to its lowest point (for placing on table)."""
    if geometry == "cylinder":
        return size / 2  # cylinder height = size, centered
    elif geometry == "sphere":
        return size / 2  # radius = size/2
    else:  # cube
        return size / 2  # half of height