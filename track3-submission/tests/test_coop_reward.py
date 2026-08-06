"""Tests for cooperative (multi-robot) reward terms — no Genesis/torch required.

These mirror soccer_env_hierarchical / reward.py's torch implementations with a
numpy port so the geometry logic is pinned even though torch can't run locally.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from match_3v3.strategy import sigmoid  # reused helper (numpy)


# ── numpy ports of reward.r_defensive_position / r_support_position ──
def defensive_position(self_xy, ball_xy, defend_goal_xy, in_possession,
                        spread=2.0, lateral_tol=0.5):
    axis = defend_goal_xy - ball_xy
    axis_len = np.linalg.norm(axis, axis=-1, keepdims=True) + 1e-9
    axis_u = axis / axis_len
    rel = self_xy - ball_xy
    proj = np.sum(rel * axis_u, axis=-1, keepdims=True)
    lateral = np.linalg.norm(rel - proj * axis_u, axis=-1, keepdims=True)
    on_side = sigmoid(proj / spread)
    tight = np.exp(-np.clip(lateral - lateral_tol, a_min=0.0, a_max=None))
    return (on_side * tight).squeeze(-1) * (1.0 - in_possession)


def support_position(self_xy, ball_xy, attack_goal_xy, in_possession,
                     push=1.5, crowd_tol=0.5):
    axis = attack_goal_xy - ball_xy
    axis_len = np.linalg.norm(axis, axis=-1, keepdims=True) + 1e-9
    axis_u = axis / axis_len
    rel = self_xy - ball_xy
    proj = np.sum(rel * axis_u, axis=-1, keepdims=True)
    lateral = np.linalg.norm(rel - proj * axis_u, axis=-1, keepdims=True)
    advanced = sigmoid((proj - push) / 1.0)
    not_crowding = np.exp(-np.clip(crowd_tol - lateral, a_min=0.0, a_max=None) * 2.0)
    return (advanced * not_crowding).squeeze(-1) * in_possession


def coop_goal(scored, scored_my_team):
    return scored.astype(float) * scored_my_team.astype(float)


XY = np.array
GX = 7.0  # half field length


class TestDefensivePosition:
    def test_goal_side_gets_reward(self):
        # Ball at (0,0), own goal at (-7,0). Robot goal-side (x=-3) → high.
        r = defensive_position(XY([-3.0, 0.5]), XY([0.0, 0.0]),
                                XY([-GX, 0.0]), in_possession=0.0)
        assert r > 0.5

    def test_ball_side_gets_little(self):
        # Robot clearly on the ball-side (x=+4, same side as attack goal) → low.
        r = defensive_position(XY([4.0, 0.5]), XY([0.0, 0.0]),
                                XY([-GX, 0.0]), in_possession=0.0)
        assert r < 0.15

    def test_ranks_goal_side_over_ball_side(self):
        goal_side = defensive_position(XY([-3.0, 0.5]), XY([0.0, 0.0]),
                                        XY([-GX, 0.0]), in_possession=0.0)
        ball_side = defensive_position(XY([4.0, 0.5]), XY([0.0, 0.0]),
                                        XY([-GX, 0.0]), in_possession=0.0)
        assert goal_side > ball_side

    def test_disabled_when_in_possession(self):
        r = defensive_position(XY([-3.0, 0.5]), XY([0.0, 0.0]),
                                XY([-GX, 0.0]), in_possession=1.0)
        assert r == 0.0

    def test_drifts_wide_penalized(self):
        on_axis = defensive_position(XY([-3.0, 0.0]), XY([0.0, 0.0]),
                                     XY([-GX, 0.0]), in_possession=0.0)
        wide = defensive_position(XY([-3.0, 4.0]), XY([0.0, 0.0]),
                                  XY([-GX, 0.0]), in_possession=0.0)
        assert wide < on_axis


class TestSupportPosition:
    def test_ahead_when_in_possession_gets_reward(self):
        # Ball at (0,0), attack goal +7. Robot ahead (x=+3) & in possession.
        r = support_position(XY([3.0, 0.5]), XY([0.0, 0.0]),
                             XY([GX, 0.0]), in_possession=1.0)
        assert r > 0.5

    def test_behind_ball_gets_little(self):
        r = support_position(XY([-2.0, 0.5]), XY([0.0, 0.0]),
                             XY([GX, 0.0]), in_possession=1.0)
        assert r < 0.15

    def test_disabled_when_not_in_possession(self):
        r = support_position(XY([3.0, 0.5]), XY([0.0, 0.0]),
                             XY([GX, 0.0]), in_possession=0.0)
        assert r == 0.0

    def test_crowding_carrier_penalized(self):
        open_ = support_position(XY([3.0, 3.0]), XY([0.0, 0.0]),
                                  XY([GX, 0.0]), in_possession=1.0)
        crowding = support_position(XY([0.3, 0.1]), XY([0.0, 0.0]),
                                     XY([GX, 0.0]), in_possession=1.0)
        assert open_ > crowding


class TestCoopGoal:
    def test_team_goal_rewarded(self):
        assert coop_goal(np.array([1.0]), np.array([1.0])) == 1.0

    def test_own_goal_penalized(self):
        assert coop_goal(np.array([1.0]), np.array([-1.0])) == -1.0

    def test_no_goal_zero(self):
        assert coop_goal(np.array([0.0]), np.array([1.0])) == 0.0
