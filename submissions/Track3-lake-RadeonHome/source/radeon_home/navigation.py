"""Deterministic grid navigation used by the first mobile-manipulation MVP."""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass


GridCell = tuple[int, int]


@dataclass(frozen=True)
class GridMap:
    width: int
    height: int
    resolution_m: float
    origin_xy: tuple[float, float]
    occupied: frozenset[GridCell]

    def in_bounds(self, cell: GridCell) -> bool:
        x, y = cell
        return 0 <= x < self.width and 0 <= y < self.height

    def is_free(self, cell: GridCell) -> bool:
        return self.in_bounds(cell) and cell not in self.occupied

    def world_to_cell(self, xy: tuple[float, float]) -> GridCell:
        return (
            round((xy[0] - self.origin_xy[0]) / self.resolution_m),
            round((xy[1] - self.origin_xy[1]) / self.resolution_m),
        )

    def cell_to_world(self, cell: GridCell) -> tuple[float, float]:
        return (
            self.origin_xy[0] + cell[0] * self.resolution_m,
            self.origin_xy[1] + cell[1] * self.resolution_m,
        )


def _heuristic(a: GridCell, b: GridCell, *, allow_diagonal: bool) -> float:
    dx = abs(a[0] - b[0])
    dy = abs(a[1] - b[1])
    if allow_diagonal:
        return dx + dy + (math.sqrt(2.0) - 2.0) * min(dx, dy)
    return float(dx + dy)


def inflate_obstacles(
    occupied: set[GridCell] | frozenset[GridCell],
    *,
    radius_cells: int,
    width: int,
    height: int,
) -> frozenset[GridCell]:
    """Inflate point obstacles by the robot footprint plus safety margin."""

    inflated: set[GridCell] = set()
    for ox, oy in occupied:
        for dx in range(-radius_cells, radius_cells + 1):
            for dy in range(-radius_cells, radius_cells + 1):
                if dx * dx + dy * dy > radius_cells * radius_cells:
                    continue
                cell = (ox + dx, oy + dy)
                if 0 <= cell[0] < width and 0 <= cell[1] < height:
                    inflated.add(cell)
    return frozenset(inflated)


def astar(
    grid: GridMap,
    start: GridCell,
    goal: GridCell,
    *,
    allow_diagonal: bool = False,
) -> list[GridCell]:
    """Return a shortest path including start and goal."""

    if not grid.is_free(start):
        raise ValueError(f"Start cell is occupied or out of bounds: {start}")
    if not grid.is_free(goal):
        raise ValueError(f"Goal cell is occupied or out of bounds: {goal}")

    frontier: list[tuple[int, int, GridCell]] = [(0, 0, start)]
    came_from: dict[GridCell, GridCell | None] = {start: None}
    cost_so_far: dict[GridCell, float] = {start: 0.0}
    sequence = 0

    while frontier:
        _, _, current = heapq.heappop(frontier)
        if current == goal:
            break

        x, y = current
        moves = ((1, 0), (-1, 0), (0, 1), (0, -1))
        if allow_diagonal:
            moves += ((1, 1), (1, -1), (-1, 1), (-1, -1))
        for dx, dy in moves:
            neighbor = (x + dx, y + dy)
            if not grid.is_free(neighbor):
                continue
            if dx and dy:
                # Do not squeeze diagonally through two touching obstacles.
                if not grid.is_free((x + dx, y)) or not grid.is_free((x, y + dy)):
                    continue
                step_cost = math.sqrt(2.0)
            else:
                step_cost = 1.0
            new_cost = cost_so_far[current] + step_cost
            if neighbor not in cost_so_far or new_cost < cost_so_far[neighbor]:
                cost_so_far[neighbor] = new_cost
                priority = new_cost + _heuristic(
                    neighbor, goal, allow_diagonal=allow_diagonal
                )
                sequence += 1
                heapq.heappush(frontier, (priority, sequence, neighbor))
                came_from[neighbor] = current

    if goal not in came_from:
        raise ValueError(f"No route from {start} to {goal}")

    path = []
    current: GridCell | None = goal
    while current is not None:
        path.append(current)
        current = came_from[current]
    path.reverse()
    return path


def path_length_m(path: list[GridCell], resolution_m: float) -> float:
    total_cells = 0.0
    for first, second in zip(path, path[1:]):
        total_cells += math.hypot(second[0] - first[0], second[1] - first[1])
    return total_cells * resolution_m


def simplify_path(path: list[GridCell]) -> list[GridCell]:
    """Remove intermediate cells that do not change travel direction."""

    if len(path) <= 2:
        return path[:]
    simplified = [path[0]]
    previous_direction = (
        path[1][0] - path[0][0],
        path[1][1] - path[0][1],
    )
    for index in range(1, len(path) - 1):
        direction = (
            path[index + 1][0] - path[index][0],
            path[index + 1][1] - path[index][1],
        )
        if direction != previous_direction:
            simplified.append(path[index])
        previous_direction = direction
    simplified.append(path[-1])
    return simplified
