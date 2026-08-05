"""NAG-801 validation scenarios and reroute helpers (numpy-only module).

FORK: a barrier with two openings — north holds a bar (IMPASSABLE in the
capability profile), south holds a tire (TRAVERSABLE). Route choice must
come from the profile, verified by a flip probe with swapped verdicts.

STAIRS_TRAP: the map (profile built on riser-0.05 evidence) declares the
stairs region traversable, but the physical scene uses riser-0.10 stairs —
a known frozen-actor boundary where the robot stalls without falling. The
runner must detect the stall, mark the region impassable, and reroute
around the flank.
"""

from __future__ import annotations

import numpy as np

from static_2p5d import (
    FREE_SPACE_CLASS,
    ClassInterval,
    Rect,
    ScenarioSpec,
    astar,
    build_map,
)

STAIRS_ROUTING_CLASS = 6
# Routing-only labels are mapped to a TSC obstacle class before feeding the
# policy; stairs are scan terrain and keep the free-space class frame(1).
ROUTING_TO_TSC = {STAIRS_ROUTING_CLASS: FREE_SPACE_CLASS}

FORK_SPEC = ScenarioSpec(
    name="FORK",
    task_fragment=None,
    wall_position_xy=None,
    # Start slightly south of centre: the capability-chosen (south/tire)
    # branch then needs only a ~27 deg bend that settles before the CM
    # commit window — the capstone lesson (clean jump run-up) applied.
    start_xy=(-4.5, -1.0),
    goal_xy=(4.0, 0.0),
    duration_sec=15.0,
    map_x=(-5.0, 5.0),
    map_y=(-3.0, 3.0),
    # First three rects are simulated wall boxes; the remaining fills are
    # map-only (they seal the post<->wall slivers for A* while keeping the
    # simulated scene close to the tire/bar training context — walls flush
    # against the obstacle frames put the depth input far out of
    # distribution, NAG-401 MWT lesson).
    physical_rects=(
        Rect(-0.1, 0.1, -3.0, -2.5),   # south wall
        Rect(-0.1, 0.1, -0.5, 0.5),    # centre wall
        Rect(-0.1, 0.1, 2.5, 3.0),     # north wall
        Rect(-0.1, 0.1, -2.5, -2.2),   # south sliver fill (map only)
        Rect(-0.1, 0.1, -0.8, -0.5),   # south sliver fill (map only)
        Rect(-0.1, 0.1, 0.5, 0.8),     # north sliver fill (map only)
        Rect(-0.1, 0.1, 2.2, 2.5),     # north sliver fill (map only)
    ),
    affordance_rects=(
        (Rect(-0.3, 0.3, -1.85, -1.15), 4),  # tire mouth (south)
        (Rect(-0.3, 0.3, 1.15, 1.85), 0),    # bar mouth (north)
    ),
)

# Flanking walls give the stairs a stairwell semantics: the initial detour
# is longer than the (capability-cost weighted) route over the stairs, so
# the profile-rational first plan goes up the stairs; only after the online
# block does the flank detour become optimal.
STAIRS_TRAP_SPEC = ScenarioSpec(
    name="STAIRS_TRAP",
    task_fragment=None,
    wall_position_xy=None,
    start_xy=(-4.0, 0.0),
    goal_xy=(5.5, 0.0),
    duration_sec=32.0,
    map_x=(-5.0, 7.0),
    map_y=(-3.5, 3.5),
    # Walls flank only the upper stairs (x >= 0.4): the initial detour is
    # still longer than the capability-cost route over the stairs, but the
    # post-block escape from the stall point is a forward arc around the
    # open lower flank — the frozen commander has no backward gait, so the
    # escape geometry must never require a U-turn in a closed throat
    # (dry-run 1/2 lesson).
    physical_rects=(
        Rect(0.4, 2.8, 1.0, 2.3),    # north stairwell wall
        Rect(0.4, 2.8, -2.3, -1.0),  # south stairwell wall
    ),
    affordance_rects=(
        (Rect(-0.6, 2.6, -0.7, 0.7), STAIRS_ROUTING_CLASS),
    ),
)

STAIRS_TRAP_WALL_BOXES = tuple(
    ((rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0,
     (rect.x1 - rect.x0) / 2.0, (rect.y1 - rect.y0) / 2.0)
    for rect in STAIRS_TRAP_SPEC.physical_rects
)

# Simulated boxes: the three walls only (sliver fills stay map-only).
FORK_BARRIER_BOXES = tuple(
    ((rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0,
     (rect.x1 - rect.x0) / 2.0, (rect.y1 - rect.y0) / 2.0)
    for rect in FORK_SPEC.physical_rects[:3]
)


ESCAPE_MARGIN_M = 0.8


def spec_with_escape_margin(spec: ScenarioSpec, blocked_labels) -> ScenarioSpec:
    """Expand blocked affordance rects so the replanned escape path turns
    around well clear of the obstacle (frozen commander has no backward
    gait; the U-turn needs open ground)."""
    from dataclasses import replace

    rects = tuple(
        (
            Rect(
                r.x0 - ESCAPE_MARGIN_M,
                r.x1 + ESCAPE_MARGIN_M,
                r.y0 - ESCAPE_MARGIN_M,
                r.y1 + ESCAPE_MARGIN_M,
            )
            if label in blocked_labels
            else r,
            label,
        )
        for r, label in spec.affordance_rects
    )
    return replace(spec, affordance_rects=rects)


class BlockedProfileView:
    """Capability profile with extra labels forced IMPASSABLE (reroute)."""

    def __init__(self, base, blocked_labels):
        self._base = base
        self._blocked = frozenset(blocked_labels)

    def is_impassable(self, label: int) -> bool:
        return label in self._blocked or self._base.is_impassable(label)

    def cost_multiplier(self, label: int) -> float:
        return self._base.cost_multiplier(label)


class FlippedProfileView:
    """FORK flip probe: swap the verdicts of two labels."""

    def __init__(self, base, label_a: int, label_b: int):
        self._base = base
        self._swap = {label_a: label_b, label_b: label_a}

    def is_impassable(self, label: int) -> bool:
        return self._base.is_impassable(self._swap.get(label, label))

    def cost_multiplier(self, label: int) -> float:
        return self._base.cost_multiplier(self._swap.get(label, label))


def nearest_free_xy(grid, xy: tuple[float, float]) -> tuple[float, float]:
    """World position of the closest non-forbidden cell (spiral search)."""
    cx, cy = grid.world_to_cell(xy)
    nx, ny = grid.forbidden.shape
    cx, cy = min(max(cx, 0), nx - 1), min(max(cy, 0), ny - 1)
    if not grid.forbidden[cx, cy]:
        return xy
    for radius in range(1, max(nx, ny)):
        best = None
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) != radius:
                    continue
                ix, iy = cx + dx, cy + dy
                if not (0 <= ix < nx and 0 <= iy < ny) or grid.forbidden[ix, iy]:
                    continue
                dist = dx * dx + dy * dy
                if best is None or dist < best[0]:
                    best = (dist, (ix, iy))
        if best is not None:
            return grid.cell_to_world(best[1])
    raise RuntimeError("no free cell found")


def plan_with_profile(spec: ScenarioSpec, profile, start_xy=None) -> dict:
    """Capability-aware plan; start may be off-path (reroute mid-run)."""
    grid = build_map(spec, profile)
    origin = nearest_free_xy(grid, tuple(start_xy or spec.start_xy))
    polyline = astar(grid, origin, spec.goal_xy)
    return {"grid": grid, "polyline": polyline}


JUMP_ALIGN_APPROACH_M = 3.0
JUMP_ALIGN_EXIT_M = 0.5
JUMP_ENTRY_EXTRA_M = 1.0  # capstone amendment: tire needs a 3.0 m entry margin


def widen_jump_entries(intervals, jump_labels=(0, 4), extra=JUMP_ENTRY_EXTRA_M):
    """Move jump-class interval entries earlier (TSC pacing window)."""
    return tuple(
        ClassInterval(max(i.s_start_m - extra, 0.0), i.s_end_m, i.label)
        if i.label in jump_labels
        else i
        for i in intervals
    )


def straighten_jump_approaches(
    polyline: np.ndarray, spec, jump_labels=(0, 4)
) -> np.ndarray:
    """Align the approach to each jump-class region with the region axis.

    The CM contract freezes the heading 2.0 m before the region centre; an
    A* diagonal there commits a skewed jump. Assumes +x traversal (both
    NAG-801 scenarios) — the spliced segment runs straight through the
    region centreline.
    """
    result = np.asarray(polyline, dtype=np.float64)
    for rect, label in spec.affordance_rects:
        if label not in jump_labels or not np.any(rect.contains(result)):
            continue
        cy = (rect.y0 + rect.y1) / 2.0
        x_entry = rect.x0 - JUMP_ALIGN_APPROACH_M
        x_exit = rect.x1 + JUMP_ALIGN_EXIT_M
        # Cut 0.8 m before the aligned segment so the connector is a gentle
        # diagonal (heading changes stay under the 1.2 rad envelope limit).
        before = int(np.argmax(result[:, 0] >= x_entry - 0.8))
        after_mask = result[:, 0] > x_exit + 0.8
        after = int(np.argmax(after_mask)) if np.any(after_mask) else len(result)
        middle = np.asarray(
            [
                [x_entry, cy],
                [rect.x0, cy],
                [rect.x1, cy],
                [x_exit, cy],
            ]
        )
        result = np.vstack([result[:before], middle, result[after:]])
    return result


def crossing_y(polyline: np.ndarray, x_line: float = 0.0) -> float:
    """Interpolated y where the path first crosses the given x line."""
    xs, ys = polyline[:, 0], polyline[:, 1]
    for i in range(len(xs) - 1):
        if (xs[i] - x_line) * (xs[i + 1] - x_line) <= 0 and xs[i] != xs[i + 1]:
            t = (x_line - xs[i]) / (xs[i + 1] - xs[i])
            return float(ys[i] + t * (ys[i + 1] - ys[i]))
    raise ValueError("path never crosses the line")
