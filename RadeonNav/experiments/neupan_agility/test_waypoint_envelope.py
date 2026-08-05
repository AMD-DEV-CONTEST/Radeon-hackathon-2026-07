from __future__ import annotations

import sys

import numpy as np
import pytest

import math

from bridge import path_to_tsc_waypoints
from run_waypoint_envelope import (
    ARC_LENGTH_M,
    CONDITIONS,
    FREE_SPACE_OBSTACLE_INDEX,
    MAX_ABS_YAW_RAD,
    SAMPLE_SPACING_M,
    condition_paths,
    cross_track_error_m,
    generate_path,
    parse_args,
    remaining_policy_path,
)


def test_condition_table_matches_preregistration() -> None:
    assert set(CONDITIONS) == {
        "K000",
        "K020",
        "K040",
        "K070",
        "K100",
        "YP040",
        "YM040",
        "YP080",
        "YM080",
        "YP120",
        "YM120",
        "A050",
        "A100",
        "S050",
        "S100",
    }
    assert FREE_SPACE_OBSTACLE_INDEX == 1
    assert MAX_ABS_YAW_RAD == pytest.approx(0.60)


def test_arc_path_geometry() -> None:
    straight = generate_path("arc", kappa=0.0)
    assert straight.shape == (80, 2)
    np.testing.assert_allclose(straight[-1], [4.0, 0.0], atol=1e-9)
    segment = np.linalg.norm(np.diff(straight, axis=0), axis=1)
    np.testing.assert_allclose(segment, SAMPLE_SPACING_M, atol=1e-9)

    tight = generate_path("arc", kappa=1.0)
    np.testing.assert_allclose(
        tight[-1], [np.sin(4.0), 1.0 - np.cos(4.0)], atol=1e-9
    )
    chords = np.linalg.norm(np.diff(tight, axis=0), axis=1)
    np.testing.assert_allclose(
        chords, 2.0 * np.sin(SAMPLE_SPACING_M / 2.0), atol=1e-9
    )

    arc = generate_path("arc", kappa=0.4)
    headings = np.arctan2(*np.diff(arc, axis=0).T[::-1])
    turn_rates = np.diff(np.unwrap(headings)) / SAMPLE_SPACING_M
    np.testing.assert_allclose(turn_rates, 0.4, rtol=0.02)


def test_slalom_path_geometry() -> None:
    slalom = generate_path("slalom", amplitude=1.0)
    assert slalom.shape == (80, 2)
    assert np.max(np.abs(slalom[:, 1])) == pytest.approx(1.0, abs=1e-3)
    segments = np.linalg.norm(np.diff(slalom, axis=0), axis=1)
    np.testing.assert_allclose(segments, SAMPLE_SPACING_M, atol=2e-3)
    total = float(np.sum(segments)) + SAMPLE_SPACING_M
    assert total == pytest.approx(ARC_LENGTH_M, abs=0.02)
    # 4.0 m of arc covers the full +A crest and most of the down-swing.
    assert np.max(slalom[:, 1]) == pytest.approx(1.0, abs=1e-3)
    assert np.min(slalom[:, 1]) < -0.85


def test_sparse_spacing_paths() -> None:
    sparse = generate_path("arc", kappa=0.4, spacing=1.0)
    assert sparse.shape == (4, 2)
    radius = 2.5
    for index, distance in enumerate((1.0, 2.0, 3.0, 4.0)):
        angle = distance * 0.4
        np.testing.assert_allclose(
            sparse[index],
            [radius * np.sin(angle), radius * (1.0 - np.cos(angle))],
            atol=1e-9,
        )
    with pytest.raises(ValueError):
        generate_path("arc", kappa=0.4, spacing=0.0)


def test_condition_paths_yaw_and_spacing() -> None:
    policy, dense, initial_yaw = condition_paths("YM120")
    assert initial_yaw == pytest.approx(-1.2)
    assert policy.shape == dense.shape == (80, 2)

    policy, dense, initial_yaw = condition_paths("S100")
    assert initial_yaw == 0.0
    assert policy.shape == (4, 2)
    assert dense.shape == (80, 2)

    # Slalom spawns aligned with the path tangent at the origin.
    _, _, yaw = condition_paths("A100")
    assert yaw == pytest.approx(math.atan2(2.0 * math.pi, 4.0))
    _, _, yaw = condition_paths("A050")
    assert yaw == pytest.approx(math.atan2(math.pi, 4.0))


def test_remaining_path_feed_mid_path() -> None:
    policy = generate_path("arc", kappa=0.0)
    dense = policy
    arc = (np.arange(len(policy)) + 1) * SAMPLE_SPACING_M

    remaining, consumed = remaining_policy_path(
        policy, arc, dense, np.array([2.0, 0.0]), 0
    )
    waypoint = path_to_tsc_waypoints(
        remaining, np.array([2.0, 0.0, 0.0]), 0.35, 0.70, MAX_ABS_YAW_RAD
    )
    assert waypoint.delta_yaw == pytest.approx(0.0, abs=1e-9)
    assert waypoint.delta_next_yaw == pytest.approx(0.0, abs=1e-9)
    assert not waypoint.yaw_clipped
    assert waypoint.current_xy[0] >= 2.3

    # Progress is monotone: slipping backward must not rewind the horizon.
    _, consumed_after = remaining_policy_path(
        policy, arc, dense, np.array([1.0, 0.0]), consumed
    )
    assert consumed_after == consumed

    # Beyond the path end: clamps to the final waypoint without raising.
    remaining_end, _ = remaining_policy_path(
        policy, arc, dense, np.array([4.5, 0.0]), consumed
    )
    assert remaining_end.shape[0] >= 1
    np.testing.assert_allclose(remaining_end[-1], [4.0, 0.0])
    overshoot = path_to_tsc_waypoints(
        remaining_end, np.array([4.5, 0.0, 0.0]), 0.35, 0.70, MAX_ABS_YAW_RAD
    )
    assert abs(overshoot.delta_yaw) == pytest.approx(MAX_ABS_YAW_RAD)


def test_remaining_path_feed_sparse() -> None:
    policy = generate_path("arc", kappa=0.4, spacing=1.0)
    dense = generate_path("arc", kappa=0.4)
    arc = (np.arange(len(policy)) + 1) * 1.0

    robot = dense[27]  # arc position 1.4 m along the same curve
    remaining, consumed = remaining_policy_path(policy, arc, dense, robot, 0)
    assert consumed == 1
    np.testing.assert_allclose(remaining[0], policy[1])
    waypoint = path_to_tsc_waypoints(
        remaining,
        np.array([robot[0], robot[1], 1.4 * 0.4]),
        0.35,
        0.70,
        MAX_ABS_YAW_RAD,
    )
    assert abs(waypoint.delta_yaw) < MAX_ABS_YAW_RAD
    assert not waypoint.yaw_clipped


def test_cross_track_error() -> None:
    dense = generate_path("arc", kappa=0.0)
    assert cross_track_error_m(np.array([2.0, 0.0]), dense) == pytest.approx(
        0.0, abs=1e-9
    )
    assert cross_track_error_m(np.array([2.0, 0.3]), dense) == pytest.approx(
        0.3, abs=1e-3
    )


def test_waypoint_feed_contract() -> None:
    path = generate_path("arc", kappa=0.0)
    aligned = path_to_tsc_waypoints(
        path, np.array([0.0, 0.0, 0.0]), 0.35, 0.70, MAX_ABS_YAW_RAD
    )
    assert aligned.delta_yaw == pytest.approx(0.0, abs=1e-9)
    assert aligned.delta_next_yaw == pytest.approx(0.0, abs=1e-9)
    assert not aligned.yaw_clipped

    offset = path_to_tsc_waypoints(
        path, np.array([0.0, 0.0, 0.4]), 0.35, 0.70, MAX_ABS_YAW_RAD
    )
    assert offset.delta_yaw == pytest.approx(-0.4, abs=1e-9)
    assert not offset.yaw_clipped

    saturated = path_to_tsc_waypoints(
        path, np.array([0.0, 0.0, 1.2]), 0.35, 0.70, MAX_ABS_YAW_RAD
    )
    assert saturated.delta_yaw == pytest.approx(-MAX_ABS_YAW_RAD)
    assert saturated.yaw_clipped


def test_envelope_cli_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys, "argv", ["run_waypoint_envelope.py", "--condition", "K040"]
    )
    args = parse_args()
    assert args.run_id == "NAG-251-K040"
    assert args.output_dir.name == "NAG-251-K040"
    assert args.seed == 7
    assert args.friction == pytest.approx(1.0)

    monkeypatch.setattr(
        sys,
        "argv",
        ["run_waypoint_envelope.py", "--condition", "K040", "--friction", "0.3"],
    )
    with pytest.raises(SystemExit):
        parse_args()
