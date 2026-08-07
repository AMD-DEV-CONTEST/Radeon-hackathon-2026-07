"""Connected-component labelling on run-length segments.

Internal primitive, shared by background removal (border connectivity) and
component slicing.  It exists once so those two never grow separate
implementations (BACKEND_CLI_PLAN.md 10.1).

Why run-length rather than the obvious per-pixel approach: the plan asks for a
1024x1024 sheet in under 150 ms without SciPy.  Iterative label propagation
needs roughly as many passes as the shape's diameter, and a per-pixel union-find
in Python is a million-iteration loop.  Compressing each row into runs first
usually cuts the working set by two orders of magnitude, and everything except
the union step stays vectorised.

Ordering is fixed: components come back sorted by ``(top, left, height, width)``
so ties are broken deterministically (BACKEND_CLI_PLAN.md 5.2).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .errors import UsageError
from .model import Rect


@dataclass(frozen=True, slots=True)
class Component:
    """One connected region."""

    label: int
    bounds: Rect
    area: int

    @property
    def sort_key(self) -> tuple[int, int, int, int]:
        return (self.bounds.y, self.bounds.x, self.bounds.height, self.bounds.width)


@dataclass(frozen=True, slots=True)
class LabelResult:
    """Labels are 0 for background and 1..n for components, in sorted order."""

    labels: np.ndarray
    components: tuple[Component, ...]

    @property
    def count(self) -> int:
        return len(self.components)


def _extract_runs(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(rows, starts, ends)`` for every horizontal run of True.

    ``ends`` is exclusive, matching the half-open rectangle convention.
    """

    height, width = mask.shape
    padded = np.zeros((height, width + 2), dtype=np.int8)
    padded[:, 1:-1] = mask
    deltas = np.diff(padded, axis=1)

    start_rows, start_cols = np.nonzero(deltas == 1)
    _end_rows, end_cols = np.nonzero(deltas == -1)
    # np.nonzero walks row-major, so the i-th start pairs with the i-th end.
    return start_rows, start_cols, end_cols


def _neighbour_pairs(
    rows: np.ndarray,
    starts: np.ndarray,
    ends: np.ndarray,
    height: int,
    connectivity: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Pair every run with the runs it touches on the row below.

    Runs within a row are sorted and disjoint, so for one run on the lower row
    the overlapping runs above form a contiguous index range.  Both range ends
    come from a vectorised searchsorted, and the ranges are expanded without a
    Python loop.
    """

    if rows.size == 0:
        empty = np.empty(0, dtype=np.int64)
        return empty, empty

    # Index of the first run of each row, for slicing rows out of the run list.
    row_offsets = np.searchsorted(rows, np.arange(height + 1), side="left")

    # 8-connectivity also joins runs that only meet at a corner, which is the
    # same as widening the overlap test by one pixel on each side.
    slack = 1 if connectivity == 8 else 0

    left_parts: list[np.ndarray] = []
    right_parts: list[np.ndarray] = []

    for row in range(height - 1):
        upper_lo, upper_hi = int(row_offsets[row]), int(row_offsets[row + 1])
        lower_lo, lower_hi = int(row_offsets[row + 1]), int(row_offsets[row + 2])
        if upper_lo == upper_hi or lower_lo == lower_hi:
            continue

        upper_starts = starts[upper_lo:upper_hi]
        upper_ends = ends[upper_lo:upper_hi]
        lower_starts = starts[lower_lo:lower_hi]
        lower_ends = ends[lower_lo:lower_hi]

        # First upper run whose end reaches past this lower run's start.
        lo = np.searchsorted(upper_ends, lower_starts - slack, side="right")
        # One past the last upper run that begins before this lower run ends.
        hi = np.searchsorted(upper_starts, lower_ends + slack, side="left")
        counts = np.maximum(hi - lo, 0)
        total = int(counts.sum())
        if total == 0:
            continue

        # Expand [lo, hi) ranges into flat index pairs without looping.
        lower_index = np.repeat(np.arange(lower_lo, lower_hi), counts)
        offsets = np.arange(total) - np.repeat(
            np.concatenate(([0], np.cumsum(counts)[:-1])), counts
        )
        upper_index = np.repeat(lo, counts) + offsets + upper_lo

        left_parts.append(upper_index)
        right_parts.append(lower_index)

    if not left_parts:
        empty = np.empty(0, dtype=np.int64)
        return empty, empty
    return np.concatenate(left_parts), np.concatenate(right_parts)


def _union_runs(count: int, left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Union-find over runs, returning each run's root."""

    parent = np.arange(count, dtype=np.int64)

    def find(node: int) -> int:
        root = node
        while parent[root] != root:
            root = parent[root]
        # Path compression keeps repeated lookups near O(1).
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    for a, b in zip(left.tolist(), right.tolist()):
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            if root_a < root_b:
                parent[root_b] = root_a
            else:
                parent[root_a] = root_b

    return np.array([find(i) for i in range(count)], dtype=np.int64)


def label_mask(mask: np.ndarray, *, connectivity: int = 4) -> LabelResult:
    """Label connected True regions of a 2-D boolean mask."""

    if connectivity not in (4, 8):
        raise UsageError("connectivity must be 4 or 8", connectivity=connectivity)
    if mask.ndim != 2:
        raise UsageError("mask must be 2-D", shape=tuple(mask.shape))

    mask = np.asarray(mask, dtype=bool)
    height, width = mask.shape
    labels = np.zeros((height, width), dtype=np.int32)
    if not mask.any():
        return LabelResult(labels=labels, components=())

    rows, starts, ends = _extract_runs(mask)
    left, right = _neighbour_pairs(rows, starts, ends, height, connectivity)
    roots = _union_runs(len(rows), left, right)

    # Compact roots into dense component ids.
    unique_roots, dense = np.unique(roots, return_inverse=True)
    component_count = len(unique_roots)
    lengths = ends - starts

    areas = np.zeros(component_count, dtype=np.int64)
    np.add.at(areas, dense, lengths)
    min_row = np.full(component_count, height, dtype=np.int64)
    max_row = np.full(component_count, -1, dtype=np.int64)
    min_col = np.full(component_count, width, dtype=np.int64)
    max_col = np.full(component_count, -1, dtype=np.int64)
    np.minimum.at(min_row, dense, rows)
    np.maximum.at(max_row, dense, rows)
    np.minimum.at(min_col, dense, starts)
    np.maximum.at(max_col, dense, ends)

    provisional = [
        Component(
            label=index,
            bounds=Rect(
                int(min_col[index]),
                int(min_row[index]),
                int(max_col[index] - min_col[index]),
                int(max_row[index] - min_row[index] + 1),
            ),
            area=int(areas[index]),
        )
        for index in range(component_count)
    ]

    order = sorted(range(component_count), key=lambda i: provisional[i].sort_key)
    rank = np.empty(component_count, dtype=np.int32)
    for new_index, old_index in enumerate(order):
        rank[old_index] = new_index + 1  # 0 stays reserved for background

    run_labels = rank[dense]
    _paint_runs(labels, rows, starts, lengths, run_labels, width)

    components = tuple(
        Component(
            label=int(rank[old_index]),
            bounds=provisional[old_index].bounds,
            area=provisional[old_index].area,
        )
        for old_index in order
    )
    return LabelResult(labels=labels, components=components)


def _paint_runs(
    labels: np.ndarray,
    rows: np.ndarray,
    starts: np.ndarray,
    lengths: np.ndarray,
    run_labels: np.ndarray,
    width: int,
) -> None:
    """Write run labels into the pixel grid in one vectorised scatter."""

    total = int(lengths.sum())
    if total == 0:
        return
    flat_starts = rows.astype(np.int64) * width + starts
    offsets = np.arange(total) - np.repeat(
        np.concatenate(([0], np.cumsum(lengths)[:-1])), lengths
    )
    indices = np.repeat(flat_starts, lengths) + offsets
    labels.reshape(-1)[indices] = np.repeat(run_labels, lengths)


def border_connected(mask: np.ndarray, *, connectivity: int = 4) -> np.ndarray:
    """Return the subset of ``mask`` that touches the image border.

    This is the operation that stops background removal from punching holes in
    a character that happens to share the background colour
    (BACKEND_CLI_PLAN.md 8.2).
    """

    result = label_mask(mask, connectivity=connectivity)
    labels = result.labels
    if result.count == 0:
        return np.zeros_like(mask, dtype=bool)

    touching = np.unique(
        np.concatenate([labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]])
    )
    touching = touching[touching > 0]
    if touching.size == 0:
        return np.zeros_like(mask, dtype=bool)
    return np.isin(labels, touching)
