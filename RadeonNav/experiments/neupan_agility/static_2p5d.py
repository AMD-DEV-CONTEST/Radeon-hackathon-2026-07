"""Static 2.5D map, A* planner, and class scheduler for NAG-401.

Preregistered in EXPERIMENT_PLAN.md M4: a two-channel static map (forbidden +
skill-traversable affordance) is planned with 8-connected A*, resampled to the
0.05 m arc contract, and paired with a path-arc class schedule that feeds the
student-D obstacle one-hot. Traverse-optimality is enforced by map-side virtual
corridor walls (the physical scene contains only the obstacle bodies).
"""

from __future__ import annotations

import heapq
import math
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import numpy as np

PLANNING_RESOLUTION_M = 0.10
PATH_SPACING_M = 0.05
INFLATION_RADIUS_M = 0.40
CLASS_ENTRY_MARGIN_M = 2.0
CLASS_EXIT_MARGIN_M = 0.5
FREE_SPACE_CLASS = 1  # frame(1), validated as flat free-space class in NAG-251
NO_AFFORDANCE = -1


@dataclass(frozen=True)
class Rect:
    """Axis-aligned world-frame rectangle [x0, x1] x [y0, y1]."""

    x0: float
    x1: float
    y0: float
    y1: float

    def contains(self, xy: np.ndarray) -> np.ndarray:
        points = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        return (
            (points[:, 0] >= self.x0)
            & (points[:, 0] <= self.x1)
            & (points[:, 1] >= self.y0)
            & (points[:, 1] <= self.y1)
        )


@dataclass(frozen=True)
class ScenarioSpec:
    name: str
    task_fragment: str | None  # key into source_tasks.TASKS, or None
    wall_position_xy: tuple[float, float] | None
    start_xy: tuple[float, float]
    goal_xy: tuple[float, float]
    duration_sec: float
    map_x: tuple[float, float]
    map_y: tuple[float, float]
    # Physical rects are real collision geometry and get robot-radius inflation;
    # virtual rects are planner-only corridor constraints and are NOT inflated
    # (the corridor they delimit is exactly the source-task passage width).
    physical_rects: tuple[Rect, ...] = field(default=())
    virtual_rects: tuple[Rect, ...] = field(default=())
    affordance_rects: tuple[tuple[Rect, int], ...] = field(default=())
    obstacle_joint: tuple[str, float] | None = None


WALL_HALF_SIZE = (0.1, 0.9, 0.25)  # 0.2 x 1.8 x 0.5 m box


def _wall_rects(center_xy: tuple[float, float]) -> tuple[Rect, ...]:
    cx, cy = center_xy
    return (
        Rect(
            cx - WALL_HALF_SIZE[0],
            cx + WALL_HALF_SIZE[0],
            cy - WALL_HALF_SIZE[1],
            cy + WALL_HALF_SIZE[1],
        ),
    )


def _corridor_rects(half_length: float, flank: float = 1.6) -> tuple[Rect, ...]:
    """Virtual walls flanking a 0.6 m-wide traverse corridor along +x."""
    margin = half_length + 0.2
    return (
        Rect(-margin, margin, 0.3, flank),
        Rect(-margin, margin, -flank, -0.3),
    )


SCENARIOS: dict[str, ScenarioSpec] = {
    "TF": ScenarioSpec(
        name="TF",
        task_fragment="frame",
        wall_position_xy=None,
        start_xy=(-2.15, 0.0),
        goal_xy=(1.45, 0.0),
        duration_sec=10.0,
        map_x=(-4.0, 3.5),
        map_y=(-3.0, 3.0),
        virtual_rects=_corridor_rects(1.5),
        affordance_rects=((Rect(-1.5, 1.5, -0.3, 0.3), 1),),
    ),
    "TR": ScenarioSpec(
        name="TR",
        task_fragment="tire_jump",
        wall_position_xy=None,
        start_xy=(-3.5, 0.0),
        goal_xy=(0.9, 0.0),
        duration_sec=10.0,
        map_x=(-5.0, 3.0),
        map_y=(-3.0, 3.0),
        virtual_rects=(
            Rect(-0.5, 0.5, 0.35, 1.6),
            Rect(-0.5, 0.5, -1.6, -0.35),
        ),
        affordance_rects=((Rect(-0.3, 0.3, -0.35, 0.35), 4),),
        obstacle_joint=("source_tire_joint", 0.475),
    ),
    "TS": ScenarioSpec(
        name="TS",
        task_fragment="seesaw",
        wall_position_xy=None,
        start_xy=(-3.5, 0.0),
        goal_xy=(1.5, 0.0),
        duration_sec=10.0,
        map_x=(-5.0, 3.5),
        map_y=(-3.0, 3.0),
        virtual_rects=_corridor_rects(1.6),
        affordance_rects=((Rect(-1.6, 1.6, -0.3, 0.3), 3),),
        obstacle_joint=("source_seesaw_joint", -float(np.arcsin(0.25 / 1.5))),
    ),
    # Diagnostic probe (not part of the preregistered 5): TR geometry with the
    # M2f-style 1.8 m start, so the tire class is active from step 1. Splits
    # "planner-feed machinery degrades tire" from "long-approach context".
    "TR_SHORT": ScenarioSpec(
        name="TR_SHORT",
        task_fragment="tire_jump",
        wall_position_xy=None,
        start_xy=(-1.8, 0.0),
        goal_xy=(0.9, 0.0),
        duration_sec=10.0,
        map_x=(-5.0, 3.0),
        map_y=(-3.0, 3.0),
        virtual_rects=(
            Rect(-0.5, 0.5, 0.35, 1.6),
            Rect(-0.5, 0.5, -1.6, -0.35),
        ),
        affordance_rects=((Rect(-0.3, 0.3, -0.35, 0.35), 4),),
        obstacle_joint=("source_tire_joint", 0.475),
    ),
    "DW": ScenarioSpec(
        name="DW",
        task_fragment=None,
        wall_position_xy=(0.0, 0.0),
        start_xy=(-2.0, 0.0),
        goal_xy=(2.0, 0.0),
        duration_sec=10.0,
        map_x=(-3.5, 3.5),
        map_y=(-3.5, 3.5),
        physical_rects=_wall_rects((0.0, 0.0)),
    ),
    # Route-v0.1 probes (2026-08-01): bar-jump feasibility at two heights with
    # the proven jump contract (7.5 m straight runup, clear landing corridor),
    # combo ramp+elevated-tunnel+ramp, and tire approached travelling -x (the
    # collision geometry is x-symmetric; this probes the reversed-travel
    # composition, incl. any visual-mesh depth asymmetry).
    "BJ200": ScenarioSpec(
        name="BJ200",
        task_fragment="bar_jump",
        wall_position_xy=None,
        start_xy=(-7.5, 0.0),
        goal_xy=(3.0, 0.0),
        duration_sec=20.0,
        map_x=(-9.0, 4.5),
        map_y=(-3.0, 3.0),
        virtual_rects=(
            Rect(-0.6, 0.6, 0.35, 2.2),
            Rect(-0.6, 0.6, -2.2, -0.35),
        ),
        affordance_rects=((Rect(-0.3, 0.3, -0.6, 0.6), 0),),
        obstacle_joint=("source_bar_joint", 0.20),
    ),
    "BJ125": ScenarioSpec(
        name="BJ125",
        task_fragment="bar_jump",
        wall_position_xy=None,
        start_xy=(-7.5, 0.0),
        goal_xy=(3.0, 0.0),
        duration_sec=20.0,
        map_x=(-9.0, 4.5),
        map_y=(-3.0, 3.0),
        virtual_rects=(
            Rect(-0.6, 0.6, 0.35, 2.2),
            Rect(-0.6, 0.6, -2.2, -0.35),
        ),
        affordance_rects=((Rect(-0.3, 0.3, -0.6, 0.6), 0),),
        obstacle_joint=("source_bar_joint", 0.125),
    ),
    "CT": ScenarioSpec(
        name="CT",
        task_fragment="combo_tunnel",
        wall_position_xy=None,
        start_xy=(-5.5, 0.0),
        goal_xy=(4.5, 0.0),
        duration_sec=20.0,
        map_x=(-7.0, 6.0),
        map_y=(-3.0, 3.0),
        virtual_rects=(
            Rect(-3.0, 3.0, 0.4, 2.0),
            Rect(-3.0, 3.0, -2.0, -0.4),
        ),
        affordance_rects=((Rect(-1.0, 1.0, -0.4, 0.4), 5),),
    ),
    # TE (default asset, -x travel) FAILED: from the east the ring sits
    # recessed in the 0.6 m-deep post pocket, so the depth signature never
    # matches the jump trigger. TE2 bakes a 180-deg rotation so the mesh
    # mouth faces the reversed approach.
    "TE2": ScenarioSpec(
        name="TE2",
        task_fragment="tire_jump_east",
        wall_position_xy=None,
        start_xy=(7.5, 0.0),
        goal_xy=(-3.0, 0.0),
        duration_sec=20.0,
        map_x=(-4.5, 9.0),
        map_y=(-3.0, 3.0),
        virtual_rects=(
            Rect(-0.5, 0.5, 0.35, 1.6),
            Rect(-0.5, 0.5, -1.6, -0.35),
        ),
        affordance_rects=((Rect(-0.3, 0.3, -0.35, 0.35), 4),),
        obstacle_joint=("source_tire_joint", 0.475),
    ),
    # Controls to de-confound travel direction vs runup length in THIS
    # harness: TR75 = passing TR geometry with the runup stretched to 7.5 m
    # (+x travel); TE35 = exact mirror of passing TR (-x travel, 3.5 m).
    "TR75": ScenarioSpec(
        name="TR75",
        task_fragment="tire_jump",
        wall_position_xy=None,
        start_xy=(-7.5, 0.0),
        goal_xy=(0.9, 0.0),
        duration_sec=20.0,
        map_x=(-9.0, 3.0),
        map_y=(-3.0, 3.0),
        virtual_rects=(
            Rect(-0.5, 0.5, 0.35, 1.6),
            Rect(-0.5, 0.5, -1.6, -0.35),
        ),
        affordance_rects=((Rect(-0.3, 0.3, -0.35, 0.35), 4),),
        obstacle_joint=("source_tire_joint", 0.475),
    ),
    "TE35": ScenarioSpec(
        name="TE35",
        task_fragment="tire_jump_east",
        wall_position_xy=None,
        start_xy=(3.5, 0.0),
        goal_xy=(-0.9, 0.0),
        duration_sec=20.0,
        map_x=(-3.0, 5.0),
        map_y=(-3.0, 3.0),
        virtual_rects=(
            Rect(-0.5, 0.5, 0.35, 1.6),
            Rect(-0.5, 0.5, -1.6, -0.35),
        ),
        affordance_rects=((Rect(-0.3, 0.3, -0.35, 0.35), 4),),
        obstacle_joint=("source_tire_joint", 0.475),
    ),
    "TE": ScenarioSpec(
        name="TE",
        task_fragment="tire_jump",
        wall_position_xy=None,
        start_xy=(7.5, 0.0),
        goal_xy=(-3.0, 0.0),
        duration_sec=20.0,
        map_x=(-4.5, 9.0),
        map_y=(-3.0, 3.0),
        virtual_rects=(
            Rect(-0.5, 0.5, 0.35, 1.6),
            Rect(-0.5, 0.5, -1.6, -0.35),
        ),
        affordance_rects=((Rect(-0.3, 0.3, -0.35, 0.35), 4),),
        obstacle_joint=("source_tire_joint", 0.475),
    ),
    "MWT": ScenarioSpec(
        name="MWT",
        task_fragment="tire_jump",
        wall_position_xy=(-2.8, 0.0),
        start_xy=(-5.0, 0.0),
        goal_xy=(1.2, 0.0),
        duration_sec=15.0,
        map_x=(-6.5, 3.0),
        map_y=(-3.5, 3.5),
        physical_rects=_wall_rects((-2.8, 0.0)),
        virtual_rects=(
            Rect(-0.5, 0.5, 0.35, 1.6),
            Rect(-0.5, 0.5, -1.6, -0.35),
        ),
        affordance_rects=((Rect(-0.3, 0.3, -0.35, 0.35), 4),),
        obstacle_joint=("source_tire_joint", 0.475),
    ),
    # Diagnostic probe: MWT with the physical tire removed. Map, A* path, and
    # class schedule stay identical, so the only change is what the depth
    # camera sees beyond the wall. PASSED isolates the composite-scene OOD
    # depth context as the wall-stage failure driver.
    "MWT_NOTIRE": ScenarioSpec(
        name="MWT_NOTIRE",
        task_fragment=None,
        wall_position_xy=(-2.8, 0.0),
        start_xy=(-5.0, 0.0),
        goal_xy=(1.2, 0.0),
        duration_sec=15.0,
        map_x=(-6.5, 3.0),
        map_y=(-3.5, 3.5),
        physical_rects=_wall_rects((-2.8, 0.0)),
        virtual_rects=(
            Rect(-0.5, 0.5, 0.35, 1.6),
            Rect(-0.5, 0.5, -1.6, -0.35),
        ),
        affordance_rects=((Rect(-0.3, 0.3, -0.35, 0.35), 4),),
    ),
}


@dataclass(frozen=True)
class GridMap:
    origin_xy: tuple[float, float]
    resolution: float
    forbidden: np.ndarray  # (nx, ny) bool, inflated
    raw_forbidden: np.ndarray  # (nx, ny) bool, uninflated
    affordance: np.ndarray  # (nx, ny) int, NO_AFFORDANCE where none
    # Per-cell traversal cost multiplier (>=1). None keeps the historical
    # uniform-cost behaviour bit-for-bit (NAG-401 archives).
    cost: np.ndarray | None = None

    def world_to_cell(self, xy: tuple[float, float]) -> tuple[int, int]:
        ix = int(round((xy[0] - self.origin_xy[0]) / self.resolution))
        iy = int(round((xy[1] - self.origin_xy[1]) / self.resolution))
        return ix, iy

    def cell_to_world(self, cell: tuple[int, int]) -> tuple[float, float]:
        return (
            self.origin_xy[0] + cell[0] * self.resolution,
            self.origin_xy[1] + cell[1] * self.resolution,
        )


def _mark(rect: Rect, grid: GridMap, target: np.ndarray, value) -> None:
    x0, y0 = grid.world_to_cell((rect.x0, rect.y0))
    x1, y1 = grid.world_to_cell((rect.x1, rect.y1))
    x0, x1 = max(x0, 0), min(x1, target.shape[0] - 1)
    y0, y1 = max(y0, 0), min(y1, target.shape[1] - 1)
    target[x0 : x1 + 1, y0 : y1 + 1] = value


def _inflate(mask: np.ndarray, radius_cells: int) -> np.ndarray:
    inflated = mask.copy()
    for dx in range(-radius_cells, radius_cells + 1):
        for dy in range(-radius_cells, radius_cells + 1):
            if dx * dx + dy * dy > radius_cells * radius_cells:
                continue
            shifted = np.zeros_like(mask)
            sx = slice(max(dx, 0), mask.shape[0] + min(dx, 0))
            dxs = slice(max(-dx, 0), mask.shape[0] + min(-dx, 0))
            sy = slice(max(dy, 0), mask.shape[1] + min(dy, 0))
            dys = slice(max(-dy, 0), mask.shape[1] + min(-dy, 0))
            shifted[sx, sy] = mask[dxs, dys]
            inflated |= shifted
    return inflated


def build_map(spec: ScenarioSpec, profile=None) -> GridMap:
    nx = int(round((spec.map_x[1] - spec.map_x[0]) / PLANNING_RESOLUTION_M)) + 1
    ny = int(round((spec.map_y[1] - spec.map_y[0]) / PLANNING_RESOLUTION_M)) + 1
    physical = np.zeros((nx, ny), dtype=bool)
    virtual = np.zeros((nx, ny), dtype=bool)
    affordance = np.full((nx, ny), NO_AFFORDANCE, dtype=np.int64)
    grid = GridMap(
        origin_xy=(spec.map_x[0], spec.map_y[0]),
        resolution=PLANNING_RESOLUTION_M,
        forbidden=np.zeros((nx, ny), dtype=bool),
        raw_forbidden=physical,
        affordance=affordance,
    )
    for rect in spec.physical_rects:
        _mark(rect, grid, physical, True)
    for rect in spec.virtual_rects:
        _mark(rect, grid, virtual, True)
    for rect, label in spec.affordance_rects:
        if profile is not None and profile.is_impassable(label):
            # Capability routing: a class the policy cannot traverse is a
            # solid obstacle (inflated, no affordance exemption).
            _mark(rect, grid, physical, True)
        else:
            _mark(rect, grid, affordance, label)
    radius_cells = int(round(INFLATION_RADIUS_M / PLANNING_RESOLUTION_M))
    # Only physical geometry is inflated by the robot radius; virtual corridor
    # walls are planner-side constraints delimiting the exact source passage.
    inflated = _inflate(physical, radius_cells) | virtual
    # Affordance corridors stay plannable: inflation must not seal the corridor.
    inflated &= affordance == NO_AFFORDANCE
    cost = None
    if profile is not None:
        cost = np.ones((nx, ny), dtype=np.float64)
        for rect, label in spec.affordance_rects:
            if not profile.is_impassable(label):
                _mark(rect, grid, cost, profile.cost_multiplier(label))
    return GridMap(
        origin_xy=grid.origin_xy,
        resolution=grid.resolution,
        forbidden=inflated,
        raw_forbidden=physical | virtual,
        affordance=affordance,
        cost=cost,
    )


_NEIGHBOURS = tuple(
    (dx, dy)
    for dx in (-1, 0, 1)
    for dy in (-1, 0, 1)
    if (dx, dy) != (0, 0)
)


def astar(grid: GridMap, start_xy: tuple[float, float], goal_xy: tuple[float, float]) -> np.ndarray:
    """8-connected deterministic A*; returns a world-frame polyline (N, 2)."""
    start = grid.world_to_cell(start_xy)
    goal = grid.world_to_cell(goal_xy)
    shape = grid.forbidden.shape
    for name, cell in (("start", start), ("goal", goal)):
        if not (0 <= cell[0] < shape[0] and 0 <= cell[1] < shape[1]):
            raise ValueError(f"{name} cell {cell} outside the map")
        if grid.forbidden[cell]:
            raise ValueError(f"{name} cell {cell} is forbidden")

    def heuristic(cell: tuple[int, int]) -> float:
        return math.hypot(cell[0] - goal[0], cell[1] - goal[1]) * grid.resolution

    counter = 0
    open_heap = [(heuristic(start), 0.0, counter, start)]
    g_cost = {start: 0.0}
    parent: dict[tuple[int, int], tuple[int, int]] = {}
    closed: set[tuple[int, int]] = set()
    while open_heap:
        _, g, _, cell = heapq.heappop(open_heap)
        if cell in closed:
            continue
        closed.add(cell)
        if cell == goal:
            cells = [cell]
            while cells[-1] in parent:
                cells.append(parent[cells[-1]])
            cells.reverse()
            polyline = np.asarray(
                [grid.cell_to_world(item) for item in cells], dtype=np.float64
            )
            polyline[0] = start_xy
            polyline[-1] = goal_xy
            return polyline
        for dx, dy in _NEIGHBOURS:
            neighbour = (cell[0] + dx, cell[1] + dy)
            if not (0 <= neighbour[0] < shape[0] and 0 <= neighbour[1] < shape[1]):
                continue
            if grid.forbidden[neighbour] or neighbour in closed:
                continue
            # Forbid squeezing diagonally between two blocked orthogonal cells.
            if (
                dx != 0
                and dy != 0
                and grid.forbidden[cell[0] + dx, cell[1]]
                and grid.forbidden[cell[0], cell[1] + dy]
            ):
                continue
            step = grid.resolution * math.hypot(dx, dy)
            if grid.cost is not None:
                step *= float(grid.cost[neighbour])
            candidate = g + step
            if candidate < g_cost.get(neighbour, float("inf")) - 1e-12:
                g_cost[neighbour] = candidate
                parent[neighbour] = cell
                counter += 1
                heapq.heappush(
                    open_heap,
                    (candidate + heuristic(neighbour), candidate, counter, neighbour),
                )
    raise RuntimeError("A* found no path")


def resample_polyline(polyline: np.ndarray, spacing: float = PATH_SPACING_M) -> np.ndarray:
    points = np.asarray(polyline, dtype=np.float64)
    segments = np.linalg.norm(np.diff(points, axis=0), axis=1)
    keep = np.concatenate(([True], segments > 1e-12))
    points = points[keep]
    segments = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(segments)))
    total = float(cumulative[-1])
    targets = np.arange(spacing, total + 1e-9, spacing)
    if len(targets) == 0 or total - targets[-1] > 1e-6:
        targets = np.append(targets, total)
    indices = np.searchsorted(cumulative, targets, side="left")
    indices = np.clip(indices, 1, len(points) - 1)
    upper = cumulative[indices]
    lower = cumulative[indices - 1]
    weight = np.where(upper > lower, (targets - lower) / (upper - lower), 1.0)
    resampled = (
        points[indices - 1] * (1.0 - weight[:, None])
        + points[indices] * weight[:, None]
    )
    return resampled


def path_heading_changes(path: np.ndarray) -> np.ndarray:
    headings = np.arctan2(*np.diff(path, axis=0).T[::-1])
    return np.abs(
        (np.diff(headings) + np.pi) % (2.0 * np.pi) - np.pi
    )


@dataclass(frozen=True)
class ClassInterval:
    s_start_m: float
    s_end_m: float
    label: int


def class_schedule(
    spec: ScenarioSpec, dense_path: np.ndarray
) -> tuple[ClassInterval, ...]:
    """Path-arc class intervals per the preregistered anchor.

    Entry = obstacle-centre projection − 2.0 m (the centre is the affordance
    rect centre, which coincides with the fragment origin); exit =
    last-in-region + 0.5 m.
    """
    arc = (np.arange(len(dense_path)) + 1) * PATH_SPACING_M
    intervals = []
    for rect, label in spec.affordance_rects:
        inside = rect.contains(dense_path)
        if not np.any(inside):
            continue
        centre = np.asarray(
            [(rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0],
            dtype=np.float64,
        )
        s_centre = float(
            arc[np.argmin(np.linalg.norm(dense_path - centre.reshape(1, 2), axis=1))]
        )
        s_inside = arc[inside]
        intervals.append(
            ClassInterval(
                max(s_centre - CLASS_ENTRY_MARGIN_M, 0.0),
                float(s_inside.max()) + CLASS_EXIT_MARGIN_M,
                int(label),
            )
        )
    return tuple(sorted(intervals, key=lambda item: item.s_start_m))


def class_at_arc(intervals: tuple[ClassInterval, ...], arc_m: float) -> int:
    for interval in intervals:
        if interval.s_start_m <= arc_m <= interval.s_end_m:
            return interval.label
    return FREE_SPACE_CLASS


@contextmanager
def wall_fragment(position_xy: tuple[float, float]) -> Iterator[Path]:
    """Materialize a static wall fragment at the given world position."""
    content = f"""<mujoco model=\"nag401 wall obstacle\">
  <worldbody>
    <body name=\"nag401_wall\" pos=\"{position_xy[0]:.4f} {position_xy[1]:.4f} 0\">
      <geom name=\"nag401_wall_collision\" type=\"box\"
        pos=\"0 0 {WALL_HALF_SIZE[2]:.4f}\"
        size=\"{WALL_HALF_SIZE[0]:.4f} {WALL_HALF_SIZE[1]:.4f} {WALL_HALF_SIZE[2]:.4f}\"
        friction=\"1 0.005 0.0001\" rgba=\"0.75 0.30 0.25 1\"/>
    </body>
  </worldbody>
</mujoco>
"""
    with tempfile.TemporaryDirectory(prefix="unilab-nag401-wall-") as tmp:
        fragment = Path(tmp) / "wall.xml"
        fragment.write_text(content, encoding="utf-8")
        yield fragment


def plan_scenario(spec: ScenarioSpec) -> dict[str, object]:
    """Build map, plan, resample, and schedule for one frozen scenario."""
    grid = build_map(spec)
    polyline = astar(grid, spec.start_xy, spec.goal_xy)
    dense_path = resample_polyline(polyline, PATH_SPACING_M)
    intervals = class_schedule(spec, dense_path)
    initial_yaw = float(
        np.arctan2(
            dense_path[0][1] - spec.start_xy[1], dense_path[0][0] - spec.start_xy[0]
        )
    )
    return {
        "grid": grid,
        "polyline": polyline,
        "dense_path": dense_path,
        "intervals": intervals,
        "initial_yaw": initial_yaw,
    }


__all__ = [
    "CLASS_ENTRY_MARGIN_M",
    "CLASS_EXIT_MARGIN_M",
    "FREE_SPACE_CLASS",
    "INFLATION_RADIUS_M",
    "NO_AFFORDANCE",
    "PATH_SPACING_M",
    "PLANNING_RESOLUTION_M",
    "SCENARIOS",
    "WALL_HALF_SIZE",
    "ClassInterval",
    "GridMap",
    "Rect",
    "ScenarioSpec",
    "astar",
    "build_map",
    "class_at_arc",
    "class_schedule",
    "path_heading_changes",
    "plan_scenario",
    "resample_polyline",
    "wall_fragment",
]
