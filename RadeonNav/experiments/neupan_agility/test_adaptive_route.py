"""NAG-801 map-level gates: profile-driven fork choice + reroute detour."""

from __future__ import annotations

import numpy as np
import pytest

from adaptive_scenarios import (
    BlockedProfileView,
    FlippedProfileView,
    FORK_SPEC,
    STAIRS_TRAP_SPEC,
    STAIRS_ROUTING_CLASS,
    crossing_y,
    nearest_free_xy,
    plan_with_profile,
)
from capability_profile import build_profile
from static_2p5d import Rect, build_map


@pytest.fixture(scope="module")
def profile():
    return build_profile()


def test_profile_verdicts(profile):
    assert profile.is_impassable(0)      # bar
    assert profile.is_impassable(2)      # poles (direct feed)
    assert not profile.is_impassable(4)  # tire
    assert not profile.is_impassable(STAIRS_ROUTING_CLASS)
    assert profile.cost_multiplier(STAIRS_ROUTING_CLASS) > 1.0

def test_fork_routes_through_tire(profile):
    plan = plan_with_profile(FORK_SPEC, profile)
    y_cross = crossing_y(plan["polyline"])
    assert y_cross < -0.7, f"expected south (tire) crossing, got y={y_cross}"
    tire_rect = FORK_SPEC.affordance_rects[0][0]
    dense = plan["polyline"]
    assert np.any(tire_rect.contains(dense)), "path must pass the tire mouth"


def test_fork_flip_probe_routes_through_bar(profile):
    flipped = FlippedProfileView(profile, 0, 4)
    plan = plan_with_profile(FORK_SPEC, flipped)
    y_cross = crossing_y(plan["polyline"])
    assert y_cross > 0.7, f"flip probe expected north crossing, got y={y_cross}"


def test_fork_without_profile_is_ambivalent_baseline():
    # Without a profile both mouths stay plannable: the route may use either
    # opening — the capability decision genuinely comes from the profile.
    plan = plan_with_profile(FORK_SPEC, None)
    y_cross = crossing_y(plan["polyline"])
    assert abs(y_cross) > 0.7  # through one of the openings, not the wall


def test_stairs_trap_initial_route_over_stairs(profile):
    plan = plan_with_profile(STAIRS_TRAP_SPEC, profile)
    stairs_rect = STAIRS_TRAP_SPEC.affordance_rects[0][0]
    assert np.any(stairs_rect.contains(plan["polyline"]))


def test_stairs_trap_reroute_detours_flank(profile):
    from adaptive_scenarios import spec_with_escape_margin

    blocked = BlockedProfileView(profile, {STAIRS_ROUTING_CLASS})
    # Robot stalled at the stairs base; replan must start from a free cell
    # and the detour must avoid the whole (inflated) stairs region. Same
    # call shape as the runner: blocked regions get the escape margin.
    escape_spec = spec_with_escape_margin(STAIRS_TRAP_SPEC, {STAIRS_ROUTING_CLASS})
    plan = plan_with_profile(escape_spec, blocked, start_xy=(-0.6, 0.0))
    stairs_rect = STAIRS_TRAP_SPEC.affordance_rects[0][0]
    inflated = Rect(
        stairs_rect.x0 - 0.4, stairs_rect.x1 + 0.4,
        stairs_rect.y0 - 0.4, stairs_rect.y1 + 0.4,
    )
    # Skip the leading points: the replan starts at the robot's stall
    # position, which is inside the region being escaped by construction.
    inside = inflated.contains(plan["polyline"][3:])
    assert not np.any(inside), "reroute must clear the inflated stairs region"
    assert np.linalg.norm(plan["polyline"][-1] - np.asarray([5.5, 0.0])) < 0.2


def test_nearest_free_xy_recovers_from_blocked_cell(profile):
    blocked = BlockedProfileView(profile, {STAIRS_ROUTING_CLASS})
    grid = build_map(STAIRS_TRAP_SPEC, blocked)
    free = nearest_free_xy(grid, (1.0, 0.0))  # deep inside blocked stairs
    ix, iy = grid.world_to_cell(free)
    assert not grid.forbidden[ix, iy]


def test_fork_straightened_approach_is_axis_aligned(profile):
    from adaptive_scenarios import (
        JUMP_ALIGN_APPROACH_M,
        straighten_jump_approaches,
    )

    plan = plan_with_profile(FORK_SPEC, profile)
    poly = straighten_jump_approaches(plan["polyline"], FORK_SPEC)
    x_entry = -0.3 - JUMP_ALIGN_APPROACH_M
    segment = poly[(poly[:, 0] >= x_entry) & (poly[:, 0] <= 0.8)]
    assert len(segment) >= 4
    assert np.all(np.abs(segment[:, 1] + 1.5) < 1e-9)
    # Heading changes along the spliced polyline stay inside the envelope.
    diffs = np.diff(poly, axis=0)
    headings = np.arctan2(diffs[:, 1], diffs[:, 0])
    jumps = np.abs(np.angle(np.exp(1j * np.diff(headings))))
    assert float(jumps.max()) <= 1.2


def test_profile_none_keeps_legacy_map():
    grid = build_map(FORK_SPEC)
    assert grid.cost is None
