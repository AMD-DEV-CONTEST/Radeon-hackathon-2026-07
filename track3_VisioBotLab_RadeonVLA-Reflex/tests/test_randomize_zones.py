"""Unit tests for zone-based layout sampling (no Genesis required)."""

from __future__ import annotations

import numpy as np

from radeonvla.randomize import sample_bowl_pair, sample_non_overlapping
from radeonvla.scene_config import (
    BOWL_PACK_RADIUS,
    FRUIT_PACK_RADIUS,
    FRUIT_ZONE_X,
    FRUIT_ZONE_Y,
    LEFT_BOWL_ZONE_X,
    LEFT_BOWL_ZONE_Y,
    MIN_CLEARANCE,
    RIGHT_BOWL_ZONE_X,
    RIGHT_BOWL_ZONE_Y,
)


def _min_sep(points, radii, clearance=MIN_CLEARANCE) -> float:
    best = float("inf")
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            d = float(np.linalg.norm(points[i] - points[j]))
            need = radii[i] + radii[j] + clearance
            best = min(best, d - need)
    return best


def test_sample_bowl_pair_lateral_and_depth() -> None:
    rng = np.random.default_rng(0)
    for arrangement in ("lateral", "depth", "free"):
        pair = sample_bowl_pair(
            rng,
            x_range=LEFT_BOWL_ZONE_X,
            y_range=LEFT_BOWL_ZONE_Y,
            radius=BOWL_PACK_RADIUS,
            arrangement=arrangement,
            max_tries=80,
        )
        assert pair is not None, arrangement
        p0, p1 = pair
        assert LEFT_BOWL_ZONE_X[0] <= p0[0] <= LEFT_BOWL_ZONE_X[1]
        assert LEFT_BOWL_ZONE_Y[0] <= p0[1] <= LEFT_BOWL_ZONE_Y[1]
        assert LEFT_BOWL_ZONE_X[0] <= p1[0] <= LEFT_BOWL_ZONE_X[1]
        assert LEFT_BOWL_ZONE_Y[0] <= p1[1] <= LEFT_BOWL_ZONE_Y[1]
        dist = float(np.linalg.norm(p0 - p1))
        assert dist >= 2 * BOWL_PACK_RADIUS + MIN_CLEARANCE - 1e-6


def test_sample_bowl_pair_right_zone_stays_negative_y() -> None:
    rng = np.random.default_rng(1)
    pair = sample_bowl_pair(
        rng,
        x_range=RIGHT_BOWL_ZONE_X,
        y_range=RIGHT_BOWL_ZONE_Y,
        radius=BOWL_PACK_RADIUS,
        arrangement="free",
    )
    assert pair is not None
    for p in pair:
        assert p[1] < 0.0
        assert RIGHT_BOWL_ZONE_Y[0] <= p[1] <= RIGHT_BOWL_ZONE_Y[1]


def test_fruit_zone_pack_no_overlap() -> None:
    rng = np.random.default_rng(2)
    names = ("banana", "lemon", "plum", "apple", "orange")
    radii = [FRUIT_PACK_RADIUS[n] for n in names]
    pts = sample_non_overlapping(
        rng,
        n=5,
        radii=radii,
        x_range=FRUIT_ZONE_X,
        y_range=FRUIT_ZONE_Y,
        clearance=MIN_CLEARANCE,
        max_tries=120,
    )
    assert pts is not None
    assert len(pts) == 5
    for p in pts:
        assert FRUIT_ZONE_X[0] <= p[0] <= FRUIT_ZONE_X[1]
        assert FRUIT_ZONE_Y[0] <= p[1] <= FRUIT_ZONE_Y[1]
    assert _min_sep(pts, radii) >= -1e-6


def test_fruit_avoids_existing_bowls() -> None:
    rng = np.random.default_rng(3)
    bowls = sample_bowl_pair(
        rng,
        x_range=LEFT_BOWL_ZONE_X,
        y_range=LEFT_BOWL_ZONE_Y,
        radius=BOWL_PACK_RADIUS,
        arrangement="lateral",
    )
    assert bowls is not None
    existing = [(bowls[0], BOWL_PACK_RADIUS), (bowls[1], BOWL_PACK_RADIUS)]
    names = ("banana", "lemon", "plum", "apple", "orange")
    radii = [FRUIT_PACK_RADIUS[n] for n in names]
    pts = sample_non_overlapping(
        rng,
        n=5,
        radii=radii,
        x_range=FRUIT_ZONE_X,
        y_range=FRUIT_ZONE_Y,
        clearance=MIN_CLEARANCE,
        max_tries=120,
        existing=existing,
    )
    assert pts is not None
    for p, r in zip(pts, radii, strict=True):
        for b, br in existing:
            assert float(np.linalg.norm(p - b)) >= r + br + MIN_CLEARANCE - 1e-6


def test_zones_do_not_overlap_in_x() -> None:
    # Fruit zone must stay robot-side of bowl bank.
    assert FRUIT_ZONE_X[1] <= LEFT_BOWL_ZONE_X[0] + 1e-9
    assert FRUIT_ZONE_X[1] <= RIGHT_BOWL_ZONE_X[0] + 1e-9
    # Left / right bowl zones share x but are split on y.
    assert LEFT_BOWL_ZONE_Y[0] > 0
    assert RIGHT_BOWL_ZONE_Y[1] < 0
