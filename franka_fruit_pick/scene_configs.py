"""Multi-scene layout definitions for RationalVLA.

Scene A: Fruit pick (original) -- pick banana/lemon/plum, place in bowl
Scene B: Color sort -- pick colored blocks, place in matching boxes
Scene C: Stacking -- stack one block on top of another
Scene D: Distractor -- pick target object among distractors
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Re-use the original scene constants
from scene_config import (
    ASSETS,
    FRANKA_EULER,
    FRANKA_FORCE_MAX,
    FRANKA_FORCE_MIN,
    FRANKA_KP,
    FRANKA_KV,
    FRANKA_POS,
    FRANKA_QPOS,
    REACH_X,
    REACH_Y,
    TABLE_CENTER,
    TABLE_COLOR,
    TABLE_LEG_COLOR,
    TABLE_LEG_INSET,
    TABLE_LEG_SIZE,
    TABLE_TOP_SIZE,
    TABLE_TOP_Z,
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

# Scene B: colored blocks for sorting
BLOCK_SIZE = 0.04  # 4cm cube
BLOCK_COLORS = {
    "red": (0.9, 0.1, 0.1, 1.0),
    "blue": (0.1, 0.1, 0.9, 1.0),
    "green": (0.1, 0.8, 0.1, 1.0),
}

# Scene B: colored boxes for sorting
BOX_SIZE = (0.08, 0.08, 0.06)  # length, width, height
BOX_COLORS = {
    "red": (0.8, 0.15, 0.15, 1.0),
    "blue": (0.15, 0.15, 0.8, 1.0),
    "green": (0.15, 0.75, 0.15, 1.0),
}


@dataclass
class SceneLayout:
    scene_id: str
    description: str
    ycb_objects: dict[str, Any] = field(default_factory=dict)
    primitive_objects: dict[str, Any] = field(default_factory=dict)
    pick_pool: list[str] = field(default_factory=list)
    place_targets: list[str] = field(default_factory=list)
    tasks: list[dict[str, str]] = field(default_factory=list)


SCENE_LAYOUTS: dict[str, SceneLayout] = {
    # ========== Scene A: Fruit Pick (original) ==========
    "A": SceneLayout(
        scene_id="A",
        description="Fruit pick: pick fruit and place in bowl",
        ycb_objects={
            "011_banana": {"pos": (0.31, 0.22, 0.0), "euler": (0.0, 0.0, 35.0)},
            "014_lemon": {"pos": (0.34, -0.08, 0.0), "euler": (0.0, 0.0, 0.0), "friction": 1.0},
            "018_plum": {"pos": (0.44, 0.08, 0.0), "euler": (0.0, 0.0, 0.0), "friction": 1.0},
            "024_bowl": {"pos": (0.50, -0.10, 0.0), "euler": (0.0, 0.0, 0.0)},
        },
        pick_pool=["011_banana", "014_lemon", "018_plum"],
        place_targets=["024_bowl"],
        tasks=[
            {"pick": "011_banana", "place": "024_bowl", "instruction": "pick the banana and put it in the bowl"},
            {"pick": "014_lemon", "place": "024_bowl", "instruction": "pick the lemon and put it in the bowl"},
            {"pick": "018_plum", "place": "024_bowl", "instruction": "pick the plum and put it in the bowl"},
        ],
    ),

    # ========== Scene B: Color Sort ==========
    "B": SceneLayout(
        scene_id="B",
        description="Color sort: pick colored blocks and place in matching boxes",
        ycb_objects={},
        primitive_objects={
            "red_block": {
                "type": "box",
                "size": (BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE),
                "pos": (0.35, 0.15, TABLE_TOP_Z + BLOCK_SIZE / 2),
                "color": BLOCK_COLORS["red"],
            },
            "blue_block": {
                "type": "box",
                "size": (BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE),
                "pos": (0.35, -0.15, TABLE_TOP_Z + BLOCK_SIZE / 2),
                "color": BLOCK_COLORS["blue"],
            },
            "green_block": {
                "type": "box",
                "size": (BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE),
                "pos": (0.45, 0.0, TABLE_TOP_Z + BLOCK_SIZE / 2),
                "color": BLOCK_COLORS["green"],
            },
            "red_box": {
                "type": "box",
                "size": BOX_SIZE,
                "pos": (0.55, 0.15, TABLE_TOP_Z + BOX_SIZE[2] / 2),
                "color": BOX_COLORS["red"],
                "fixed": False,
                "mass": 0.5,
            },
            "blue_box": {
                "type": "box",
                "size": BOX_SIZE,
                "pos": (0.55, -0.15, TABLE_TOP_Z + BOX_SIZE[2] / 2),
                "color": BOX_COLORS["blue"],
                "fixed": False,
                "mass": 0.5,
            },
        },
        pick_pool=["red_block", "blue_block", "green_block"],
        place_targets=["red_box", "blue_box"],
        tasks=[
            {"pick": "red_block", "place": "red_box", "instruction": "pick the red block and put it in the red box"},
            {"pick": "blue_block", "place": "blue_box", "instruction": "pick the blue block and put it in the blue box"},
            {"pick": "green_block", "place": "red_box", "instruction": "pick the green block and put it in the red box"},
        ],
    ),

    # ========== Scene C: Stacking ==========
    "C": SceneLayout(
        scene_id="C",
        description="Stacking: stack one block on top of another",
        ycb_objects={},
        primitive_objects={
            "red_block": {
                "type": "box",
                "size": (BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE),
                "pos": (0.35, 0.0, TABLE_TOP_Z + BLOCK_SIZE / 2),
                "color": BLOCK_COLORS["red"],
            },
            "blue_block": {
                "type": "box",
                "size": (BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE),
                "pos": (0.45, 0.0, TABLE_TOP_Z + BLOCK_SIZE / 2),
                "color": BLOCK_COLORS["blue"],
            },
        },
        pick_pool=["blue_block"],
        place_targets=["red_block"],  # stack blue on red
        tasks=[
            {"pick": "blue_block", "place": "red_block", "instruction": "stack the blue block on top of the red block"},
        ],
    ),

    # ========== Scene D: Distractor ==========
    "D": SceneLayout(
        scene_id="D",
        description="Distractor: pick target fruit among multiple objects",
        ycb_objects={
            "011_banana": {"pos": (0.31, 0.22, 0.0), "euler": (0.0, 0.0, 35.0)},
            "014_lemon": {"pos": (0.34, -0.08, 0.0), "euler": (0.0, 0.0, 0.0), "friction": 1.0},
            "018_plum": {"pos": (0.44, 0.08, 0.0), "euler": (0.0, 0.0, 0.0), "friction": 1.0},
            "024_bowl": {"pos": (0.50, -0.10, 0.0), "euler": (0.0, 0.0, 0.0)},
        },
        primitive_objects={
            "distractor_red": {
                "type": "box",
                "size": (BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE),
                "pos": (0.38, 0.30, TABLE_TOP_Z + BLOCK_SIZE / 2),
                "color": BLOCK_COLORS["red"],
            },
            "distractor_blue": {
                "type": "box",
                "size": (BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE),
                "pos": (0.42, -0.25, TABLE_TOP_Z + BLOCK_SIZE / 2),
                "color": BLOCK_COLORS["blue"],
            },
        },
        pick_pool=["011_banana", "014_lemon", "018_plum"],
        place_targets=["024_bowl"],
        tasks=[
            {"pick": "011_banana", "place": "024_bowl", "instruction": "ignore the blocks, pick the banana and put it in the bowl"},
            {"pick": "014_lemon", "place": "024_bowl", "instruction": "ignore the blocks, pick the lemon and put it in the bowl"},
            {"pick": "018_plum", "place": "024_bowl", "instruction": "ignore the blocks, pick the plum and put it in the bowl"},
        ],
    ),
}

# All scene IDs
ALL_SCENES = list(SCENE_LAYOUTS.keys())


def get_scene_layout(scene_id: str) -> SceneLayout:
    """Get the layout for a specific scene."""
    if scene_id not in SCENE_LAYOUTS:
        raise ValueError(f"Unknown scene_id: {scene_id}. Available: {ALL_SCENES}")
    return SCENE_LAYOUTS[scene_id]