"""Large-room semantic task generation and two-leg transport planning."""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from .navigation import (
    GridCell,
    GridMap,
    astar,
    inflate_obstacles,
    path_length_m,
)


ROOM_SIZE_M = 6.0
RESOLUTION_M = 0.25
GRID_SIZE = int(ROOM_SIZE_M / RESOLUTION_M) + 1
ORIGIN_XY = (-ROOM_SIZE_M / 2, -ROOM_SIZE_M / 2)
ROBOT_RADIUS_M = 0.23
SAFETY_MARGIN_M = 0.12
INFLATION_CELLS = math.ceil(
    (ROBOT_RADIUS_M + SAFETY_MARGIN_M) / RESOLUTION_M
)


SEMANTIC_DOCKS: dict[str, tuple[float, float]] = {
    "desk": (-2.00, 1.75),
    "coffee_table": (0.00, 1.75),
    "bedside_table": (2.00, 1.75),
    "door_tray": (-2.00, -2.00),
    "storage_bin": (0.00, -2.00),
    "trash_bin": (2.00, -2.00),
}

OBJECT_ALLOWED_SOURCES: dict[str, tuple[str, ...]] = {
    "medicine": ("desk", "coffee_table"),
    "keys": ("desk", "coffee_table", "bedside_table"),
    "toy": ("coffee_table", "door_tray"),
    "trash": ("desk", "coffee_table", "bedside_table"),
}

OBJECT_ALLOWED_TARGETS: dict[str, tuple[str, ...]] = {
    "medicine": ("bedside_table",),
    "keys": ("door_tray",),
    "toy": ("storage_bin",),
    "trash": ("trash_bin",),
}


def _rectangle_cells(
    *,
    center_xy: tuple[float, float],
    size_xy: tuple[float, float],
) -> set[GridCell]:
    cx = round((center_xy[0] - ORIGIN_XY[0]) / RESOLUTION_M)
    cy = round((center_xy[1] - ORIGIN_XY[1]) / RESOLUTION_M)
    half_x = max(0, round(size_xy[0] / RESOLUTION_M / 2))
    half_y = max(0, round(size_xy[1] / RESOLUTION_M / 2))
    return {
        (x, y)
        for x in range(cx - half_x, cx + half_x + 1)
        for y in range(cy - half_y, cy + half_y + 1)
        if 0 <= x < GRID_SIZE and 0 <= y < GRID_SIZE
    }


def build_room_grid() -> GridMap:
    raw: set[GridCell] = set()
    # Central sofa and two chairs form navigation obstacles.
    raw |= _rectangle_cells(center_xy=(0.0, 0.0), size_xy=(1.40, 0.70))
    raw |= _rectangle_cells(center_xy=(-1.55, 0.25), size_xy=(0.50, 0.50))
    raw |= _rectangle_cells(center_xy=(1.55, 0.25), size_xy=(0.50, 0.50))
    occupied = inflate_obstacles(
        raw,
        radius_cells=INFLATION_CELLS,
        width=GRID_SIZE,
        height=GRID_SIZE,
    )
    return GridMap(
        GRID_SIZE,
        GRID_SIZE,
        RESOLUTION_M,
        ORIGIN_XY,
        occupied,
    )


@dataclass(frozen=True)
class TransportTask:
    seed: int
    object_id: str
    source_zone: str
    target_zone: str
    start_xy: tuple[float, float]


@dataclass
class PlannedTransport:
    task: TransportTask
    pickup_path: list[GridCell]
    delivery_path: list[GridCell]
    pickup_distance_m: float
    delivery_distance_m: float

    @property
    def total_distance_m(self) -> float:
        return self.pickup_distance_m + self.delivery_distance_m

    def to_dict(self) -> dict:
        data = asdict(self)
        data["total_distance_m"] = self.total_distance_m
        return data


def _free_start(grid: GridMap, rng: random.Random) -> GridCell:
    candidates = [
        (x, y)
        for x in range(2, grid.width - 2)
        for y in range(2, grid.height - 2)
        if grid.is_free((x, y))
    ]
    return rng.choice(candidates)


def generate_task(seed: int, grid: GridMap) -> TransportTask:
    rng = random.Random(seed)
    object_id = rng.choice(sorted(OBJECT_ALLOWED_SOURCES))
    source = rng.choice(OBJECT_ALLOWED_SOURCES[object_id])
    target = rng.choice(OBJECT_ALLOWED_TARGETS[object_id])
    start_cell = _free_start(grid, rng)
    return TransportTask(seed, object_id, source, target, grid.cell_to_world(start_cell))


def plan_transport(task: TransportTask, grid: GridMap) -> PlannedTransport:
    start = grid.world_to_cell(task.start_xy)
    pickup = grid.world_to_cell(SEMANTIC_DOCKS[task.source_zone])
    delivery = grid.world_to_cell(SEMANTIC_DOCKS[task.target_zone])
    pickup_path = astar(grid, start, pickup, allow_diagonal=True)
    delivery_path = astar(grid, pickup, delivery, allow_diagonal=True)
    return PlannedTransport(
        task,
        pickup_path,
        delivery_path,
        path_length_m(pickup_path, grid.resolution_m),
        path_length_m(delivery_path, grid.resolution_m),
    )


def evaluate_tasks(*, count: int, seed: int) -> dict:
    grid = build_room_grid()
    successes = []
    failures = []
    for offset in range(count):
        task = generate_task(seed + offset, grid)
        try:
            successes.append(plan_transport(task, grid))
        except ValueError as error:
            failures.append({"task": asdict(task), "error": str(error)})
    distances = [result.total_distance_m for result in successes]
    return {
        "room_size_m": [ROOM_SIZE_M, ROOM_SIZE_M],
        "resolution_m": RESOLUTION_M,
        "robot_radius_m": ROBOT_RADIUS_M,
        "safety_margin_m": SAFETY_MARGIN_M,
        "inflation_cells": INFLATION_CELLS,
        "task_count": count,
        "success_count": len(successes),
        "failure_count": len(failures),
        "planning_success_rate": len(successes) / count if count else 0.0,
        "mean_total_distance_m": sum(distances) / len(distances) if distances else 0.0,
        "max_total_distance_m": max(distances, default=0.0),
        "sample_plans": [result.to_dict() for result in successes[:5]],
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate large-room transport plans")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument(
        "--output", type=Path, default=Path("outputs/spatial-planning.json")
    )
    args = parser.parse_args()
    result = evaluate_tasks(count=args.count, seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "sample_plans"}, indent=2))


if __name__ == "__main__":
    main()
