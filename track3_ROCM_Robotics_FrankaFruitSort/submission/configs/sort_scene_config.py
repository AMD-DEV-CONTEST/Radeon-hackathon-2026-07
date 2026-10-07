"""Scene layout for the multi-object intelligent sorting task.

Extends the starter franka_fruit_pick scene to a color-coded sorting task:
  - 3 fruit categories (banana / lemon / plum), one item each, in the pick zone
  - 3 color-coded bowls (yellow / green / purple) in the place zone
  - The scripted policy sorts each fruit into the bowl whose color matches the
    fruit's category (banana->yellow, lemon->green, plum->purple).

Layout keeps every pick and place target inside the empirically verified
reachable workspace (REACH_X / REACH_Y from scene_config) so IK stays reliable.
Bowls reuse the starter 024_bowl mesh, recolored via build_scene's per-item
``color`` field (handled by the sort-task patch to build_scene).
"""

from __future__ import annotations

# Reuse the starter bowl mesh for every container, but give each a stable alias
# so it can be addressed independently in the scene entity dict. The patch to
# scene_config.get_ycb_assets() resolves these aliases back to 024_bowl.
CONTAINER_MESH_ALIAS = "024_bowl"

# Color-coded container definitions (RGB, 0-1). Each color matches the natural
# appearance prior of its target fruit category, so a color-conditioned policy
# has a clean visual cue to learn from.
CONTAINER_COLORS = {
    "024_bowl_yellow": (1.0, 0.85, 0.10, 1.0),  # banana -> yellow bowl
    "024_bowl_green": (0.20, 0.70, 0.25, 1.0),  # lemon  -> green bowl
    "024_bowl_purple": (0.55, 0.20, 0.65, 1.0),  # plum   -> purple bowl
}

# Pick zone (x=0.30) and place zone (x=0.50). Three y-rows (0.20 / 0.10 / -0.20).
# The middle lane is at y=0.10 (not 0.00) because the Franka base sits at
# y=0.00: a pick target directly on the base axis yields an IK solution near
# a kinematic singularity, causing RRTConnect to fail (verified: lemon at
# y=0.00 was launched off the table; y=0.05 still caused RRTConnect planning
# failures due to singularity-adjacent ill-conditioned IK). y=0.10 gives
# sufficient clearance from the base axis for reliable top-down planning.
PICK_X = 0.30
PLACE_X = 0.50
LANE_Y = (0.20, 0.10, -0.20)

# Object -> container mapping. This is the "ground truth" sorting rule the
# scripted policy follows; the learned policy must discover it from pixels.
SORT_MAPPING = {
    "011_banana": "024_bowl_yellow",
    "014_lemon": "024_bowl_green",
    "018_plum": "024_bowl_purple",
}

# Lane assignment per fruit (which y-row the fruit starts on). Aligned with its
# target container's lane so the transport move is a pure +x push (no lateral
# swing), making the scripted policy maximally reliable for data collection.
LANE_ASSIGNMENT = {
    "011_banana": LANE_Y[0],
    "014_lemon": LANE_Y[1],
    "018_plum": LANE_Y[2],
}

# Per-item layout passed to build_scene(layout=...). Each entry matches the
# YCB_LAYOUT schema (pos/euler/friction) plus an optional ``color`` override
# used by the patched build_scene to recolor the bowl mesh.
SORT_LAYOUT: dict[str, dict] = {}

for _fruit, _lane_y in LANE_ASSIGNMENT.items():
    SORT_LAYOUT[_fruit] = {
        "pos": (PICK_X, _lane_y, 0.0),
        "euler": (0.0, 0.0, 35.0 if _fruit == "011_banana" else 0.0),
        "friction": 1.0,
    }

for _container, _color in CONTAINER_COLORS.items():
    _lane_y = {
        "024_bowl_yellow": LANE_Y[0],
        "024_bowl_green": LANE_Y[1],
        "024_bowl_purple": LANE_Y[2],
    }[_container]
    SORT_LAYOUT[_container] = {
        "pos": (PLACE_X, _lane_y, 0.0),
        "euler": (0.0, 0.0, 0.0),
        "color": _color,  # consumed by the patched build_scene
    }


def sort_task_description(fruit: str) -> str:
    """Natural-language task string for the LeRobot dataset."""
    name = {
        "011_banana": "banana",
        "014_lemon": "lemon",
        "018_plum": "plum",
    }.get(fruit, fruit)
    target = {
        "011_banana": "yellow bowl",
        "014_lemon": "green bowl",
        "018_plum": "purple bowl",
    }.get(fruit, "bowl")
    return f"sort the {name} into the {target}"


def pick_order() -> list[str]:
    """Order in which fruits are picked in a scripted episode.

    All three fruits are enabled. The lemon approach was previously blocked
    because its y=0.05 position (now y=0.10) sat too close to the Franka
    base axis, causing RRTConnect failures due to IK singularity. With y=0.10
    and a dedicated grasp profile override, lemon picking is now reliable.
    """
    return ["018_plum", "011_banana", "014_lemon"]
