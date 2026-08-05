from __future__ import annotations

import numpy as np
import pytest

from static_2p5d import (
    CLASS_ENTRY_MARGIN_M,
    FREE_SPACE_CLASS,
    PATH_SPACING_M,
    SCENARIOS,
    WALL_HALF_SIZE,
    Rect,
    build_map,
    class_at_arc,
    path_heading_changes,
    plan_scenario,
    resample_polyline,
    wall_fragment,
)


def test_scenario_table_matches_preregistration() -> None:
    # 5 preregistered scenarios plus the TR_SHORT / MWT_NOTIRE diagnostic probes.
    assert set(SCENARIOS) == {
        "TF",
        "TR",
        "TS",
        "DW",
        "MWT",
        "TR_SHORT",
        "MWT_NOTIRE",
    }
    assert SCENARIOS["TR_SHORT"].start_xy == (-1.8, 0.0)
    # MWT_NOTIRE differs from MWT only in physical content (no tire fragment).
    assert SCENARIOS["MWT_NOTIRE"].task_fragment is None
    assert SCENARIOS["MWT_NOTIRE"].obstacle_joint is None
    for field in ("start_xy", "goal_xy", "map_x", "map_y", "physical_rects",
                  "virtual_rects", "affordance_rects", "duration_sec"):
        assert getattr(SCENARIOS["MWT_NOTIRE"], field) == getattr(
            SCENARIOS["MWT"], field
        ), field
    assert SCENARIOS["MWT"].duration_sec == 15.0
    for name in ("TF", "TR", "TS", "DW"):
        assert SCENARIOS[name].duration_sec == 10.0
    assert SCENARIOS["TR"].obstacle_joint == ("source_tire_joint", 0.475)
    assert SCENARIOS["DW"].task_fragment is None
    assert SCENARIOS["DW"].wall_position_xy == (0.0, 0.0)
    assert WALL_HALF_SIZE == (0.1, 0.9, 0.25)


def test_map_corridor_stays_plannable() -> None:
    grid = build_map(SCENARIOS["TF"])
    # Centre line through the corridor and its approach is never forbidden.
    for x in np.arange(-2.1, 1.5, 0.1):
        cell = grid.world_to_cell((float(x), 0.0))
        assert not grid.forbidden[cell], f"centre line sealed at x={x:.1f}"
    # Virtual walls forbid routing around the frame.
    assert grid.forbidden[grid.world_to_cell((0.0, 0.8))]
    assert grid.forbidden[grid.world_to_cell((0.0, -0.8))]
    # Affordance labelled inside the corridor.
    assert grid.affordance[grid.world_to_cell((0.0, 0.0))] == 1


def test_traverse_path_goes_through_affordance() -> None:
    for name, label in (("TF", 1), ("TR", 4), ("TS", 3)):
        plan = plan_scenario(SCENARIOS[name])
        dense = plan["dense_path"]
        rect, expected = SCENARIOS[name].affordance_rects[0]
        assert expected == label
        assert np.any(rect.contains(dense)), f"{name} path skips the affordance"
        assert np.max(np.abs(dense[:, 1])) < 0.5, f"{name} path leaves the corridor"
        changes = path_heading_changes(dense)
        assert np.max(changes, initial=0.0) <= 0.79


def test_detour_path_avoids_wall() -> None:
    plan = plan_scenario(SCENARIOS["DW"])
    dense = plan["dense_path"]
    wall = Rect(-0.1, 0.1, -0.9, 0.9)
    assert not np.any(wall.contains(dense))
    near_wall = dense[np.abs(dense[:, 0]) < 0.1]
    assert len(near_wall) > 0
    # Inflated clearance: the path crosses the wall line beyond y = 0.9 + 0.4.
    assert np.min(np.abs(near_wall[:, 1])) >= 1.25
    assert np.max(np.abs(dense[:, 1])) < 2.5
    changes = path_heading_changes(dense)
    assert np.max(changes) <= 0.79


def test_mixed_path_detours_then_traverses() -> None:
    plan = plan_scenario(SCENARIOS["MWT"])
    dense = plan["dense_path"]
    wall = Rect(-2.9, -2.7, -0.9, 0.9)
    assert not np.any(wall.contains(dense))
    rect, label = SCENARIOS["MWT"].affordance_rects[0]
    assert label == 4
    assert np.any(rect.contains(dense))
    intervals = plan["intervals"]
    assert len(intervals) == 1
    assert intervals[0].label == 4


def test_resample_and_schedule_contract() -> None:
    plan = plan_scenario(SCENARIOS["TR"])
    dense = plan["dense_path"]
    segments = np.linalg.norm(np.diff(dense, axis=0), axis=1)
    assert np.all(segments <= PATH_SPACING_M + 1e-6)
    assert np.all(segments > 1e-6)

    intervals = plan["intervals"]
    assert len(intervals) == 1
    interval = intervals[0]
    assert interval.label == 4
    arc = (np.arange(len(dense)) + 1) * PATH_SPACING_M
    s_centre = float(arc[np.argmin(np.linalg.norm(dense, axis=1))])
    assert interval.s_start_m == pytest.approx(
        max(s_centre - CLASS_ENTRY_MARGIN_M, 0.0)
    )
    # Free space before entry, obstacle class inside, free space after exit.
    assert class_at_arc(intervals, max(interval.s_start_m - 0.1, 0.0)) == (
        FREE_SPACE_CLASS
    )
    assert class_at_arc(intervals, interval.s_start_m + 0.1) == 4
    assert class_at_arc(intervals, interval.s_end_m + 0.1) == FREE_SPACE_CLASS


def test_handoff_is_non_degenerate_for_all_traverse_scenarios() -> None:
    # Entry anchor is centre-projection - 2.0 m per preregistration: the
    # class switch must happen mid-run, never at step 0.
    for name, expected_entry in (("TR", 1.5), ("TS", 1.5), ("MWT", 4.05)):
        plan = plan_scenario(SCENARIOS[name])
        intervals = plan["intervals"]
        assert len(intervals) == 1, name
        assert intervals[0].s_start_m > 0.5, f"{name} handoff degenerate"
        assert intervals[0].s_start_m == pytest.approx(expected_entry, abs=0.15), name
        assert class_at_arc(intervals, 0.05) == FREE_SPACE_CLASS, name


def test_dw_schedule_is_free_space_everywhere() -> None:
    plan = plan_scenario(SCENARIOS["DW"])
    assert plan["intervals"] == ()
    assert class_at_arc(plan["intervals"], 1.0) == FREE_SPACE_CLASS


def test_initial_yaw_is_path_tangent() -> None:
    plan = plan_scenario(SCENARIOS["TF"])
    assert plan["initial_yaw"] == pytest.approx(0.0, abs=1e-6)


def test_wall_fragment_contract() -> None:
    import xml.etree.ElementTree as ET

    with wall_fragment((-2.8, 0.0)) as path:
        tree = ET.parse(path)
        body = tree.find(".//body[@name='nag401_wall']")
        assert body is not None
        assert body.get("pos", "").startswith("-2.8")
        geom = tree.find(".//geom[@name='nag401_wall_collision']")
        assert geom is not None
        assert geom.get("size") == "0.1000 0.9000 0.2500"


def test_runner_class_state_over_advancing_robot() -> None:
    """Drive the runner's per-step class bookkeeping along the TR path."""
    from run_static_2p5d import class_switch_event, update_class_state

    plan = plan_scenario(SCENARIOS["TR"])
    dense = plan["dense_path"]
    intervals = plan["intervals"]
    rng = np.random.default_rng(7)
    class_arc = 0.0
    last_class: int | None = None
    events = []
    for step, point in enumerate(dense, start=1):
        noisy = point + rng.uniform(-0.02, 0.02, size=2)
        nearest = int(np.argmin(np.linalg.norm(dense - noisy.reshape(1, 2), axis=1)))
        class_arc, active = update_class_state(intervals, class_arc, nearest)
        if last_class is not None and active != last_class:
            events.append(
                class_switch_event(step, last_class, active, class_arc, 0, [0, 0, 0])
            )
        last_class = active
    assert [(event["from"], event["to"]) for event in events] == [(1, 4), (4, 1)]
    assert events[0]["arc_m"] == pytest.approx(intervals[0].s_start_m, abs=0.11)
    assert events[1]["arc_m"] == pytest.approx(intervals[0].s_end_m, abs=0.11)
    for event in events:
        assert set(event) == {"step", "from", "to", "arc_m", "skill", "base_xyz_m"}
    # Monotone even when the noisy projection slips backward.
    arc_a, _ = update_class_state(intervals, 2.0, 10)
    assert arc_a == 2.0


def test_jump_feed_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from run_static_2p5d import (
        JUMP_CLASSES,
        JUMP_LONGLOOK_M,
        committed_delta_yaw,
        feed_lookaheads,
        parse_args,
    )

    assert JUMP_CLASSES == (0, 4)
    assert JUMP_LONGLOOK_M == (0.90, 1.80)

    # Lookaheads change only for longlook inside a jump interval.
    assert feed_lookaheads("default", True) == (0.35, 0.70)
    assert feed_lookaheads("commit", True) == (0.35, 0.70)
    assert feed_lookaheads("longlook", False) == (0.35, 0.70)
    assert feed_lookaheads("longlook", True) == (0.90, 1.80)

    # Committed absolute headings: hold, wrap, clip.
    yaw, clipped = committed_delta_yaw((0.2, 0.4), 0.0)
    np.testing.assert_allclose(yaw, [[0.2, 0.4]], atol=1e-7)
    assert not clipped
    yaw, clipped = committed_delta_yaw((0.2, 0.4), 0.5)
    np.testing.assert_allclose(yaw, [[-0.3, -0.1]], atol=1e-7)
    assert not clipped
    yaw, clipped = committed_delta_yaw((np.pi - 0.1, np.pi - 0.1), -np.pi + 0.1)
    np.testing.assert_allclose(yaw, [[-0.2, -0.2]], atol=1e-6)
    assert not clipped
    yaw, clipped = committed_delta_yaw((1.0, -1.0), 0.0)
    np.testing.assert_allclose(yaw, [[0.6, -0.6]], atol=1e-7)
    assert clipped
    assert yaw.dtype == np.float32

    # Run-ID derivation per plan table.
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_static_2p5d.py", "--scenario", "TR", "--jump-feed", "commit"],
    )
    assert parse_args().run_id == "NAG-402-TR-CM"
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_static_2p5d.py", "--scenario", "TR_SHORT", "--jump-feed", "longlook"],
    )
    assert parse_args().run_id == "NAG-402-TR_SHORT-LL"
    monkeypatch.setattr(
        sys, "argv", ["run_static_2p5d.py", "--scenario", "TR"]
    )
    assert parse_args().run_id == "NAG-401-TR"


def test_resample_polyline_endpoint() -> None:
    polyline = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])
    resampled = resample_polyline(polyline, 0.3)
    # Arc targets 0.3..1.8 plus the appended endpoint at arc 2.0.
    assert len(resampled) == 7
    np.testing.assert_allclose(resampled[-1], [1.0, 1.0], atol=1e-9)
    np.testing.assert_allclose(resampled[2], [0.9, 0.0], atol=1e-9)
    # Point at arc 1.2 sits 0.2 past the corner, on the second segment.
    np.testing.assert_allclose(resampled[3], [1.0, 0.2], atol=1e-9)
