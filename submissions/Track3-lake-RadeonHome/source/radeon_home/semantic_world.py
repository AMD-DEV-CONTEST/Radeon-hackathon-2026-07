"""Simulator-independent semantic observations for the RadeonHome room.

The first dashboard uses this deterministic scene inventory as its perception
adapter.  It is deliberately named a *simulated semantic observation*: it is
not presented as a trained RGB-D detector.  A later RGB-D model only needs to
emit the same JSON schema.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .spatial_tasks import SEMANTIC_DOCKS, build_room_grid


@dataclass(frozen=True)
class SemanticObject:
    object_id: str
    category: str
    zone: str
    xy_m: tuple[float, float]
    depth_m: float
    confidence: float
    movable: bool

    def to_dict(self) -> dict:
        return asdict(self)


def observe_room() -> dict:
    """Return one reproducible virtual RGB-D/semantic observation.

    ``depth_m`` is the target range from the current virtual camera origin,
    and ``confidence`` is a simulator observation confidence.  Keeping those
    fields makes the interface compatible with an eventual RGB-D detector,
    without claiming that a detector has already been trained.
    """

    objects = (
        SemanticObject("trash", "waste", "bedside_table", (2.0, 2.39), 2.72, 0.99, True),
        SemanticObject("keys", "keys", "desk", (-2.0, 2.39), 3.18, 0.98, True),
        SemanticObject("medicine", "medicine_box", "coffee_table", (0.0, 2.39), 2.46, 0.99, True),
        SemanticObject("cup", "cup", "coffee_table", (0.32, 2.39), 2.49, 0.97, True),
        SemanticObject("trash_bin", "container", "trash_bin", SEMANTIC_DOCKS["trash_bin"], 3.08, 1.0, False),
        SemanticObject("tray", "container", "door_tray", SEMANTIC_DOCKS["door_tray"], 3.67, 1.0, False),
        SemanticObject("bedside_table", "furniture", "bedside_table", SEMANTIC_DOCKS["bedside_table"], 2.56, 1.0, False),
    )
    grid = build_room_grid()
    return {
        "source": "simulator_ground_truth_adapter",
        "camera": {"type": "virtual_rgbd", "resolution": [1280, 720]},
        "objects": [item.to_dict() for item in objects],
        "semantic_docks": {name: list(xy) for name, xy in SEMANTIC_DOCKS.items()},
        "occupied_cells": [list(cell) for cell in sorted(grid.occupied)],
        "grid": {
            "origin_xy_m": list(grid.origin_xy),
            "resolution_m": grid.resolution_m,
            "width": grid.width,
            "height": grid.height,
        },
    }
