"""Tests for multi-agent observation features — no Genesis required."""
from __future__ import annotations

import os
import sys
import math

import numpy as np
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from match_3v3 import (
    Team, Role, PlayerState, Possession,
    compute_multiagent_features, build_full_observation, N_EXTRA,
)
from match_3v3.strategy import build_hl_observation


def make_player(idx, team, x, y, yaw=0.0):
    p = PlayerState(team=team, robot_idx=idx)
    p.pos = np.array([x, y, 0.72])
    p.quat = np.array([math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2)])
    return p


def squad():
    return [
        make_player(0, Team.LEFT, 0.0, 0.0),
        make_player(1, Team.LEFT, 2.0, 1.0),
        make_player(2, Team.LEFT, -6.5, 0.0),
        make_player(3, Team.RIGHT, 3.0, -1.0),
        make_player(4, Team.RIGHT, 5.0, 2.0),
        make_player(5, Team.RIGHT, 6.5, 0.0),
    ]


class TestMultiAgentFeatures:
    def test_shape_and_dtype(self):
        players = squad()
        feats = compute_multiagent_features(players[0], players, Possession(None, None))
        assert feats.shape == (N_EXTRA,)
        assert feats.dtype == np.float32

    def test_nearest_teammate_selected(self):
        players = squad()
        # Player 0 faces +x. Player 1 at (2,1) is the nearest teammate.
        feats = compute_multiagent_features(players[0], players, Possession(None, None))
        tm_rel = feats[0:2]
        # body frame (facing +x): teammate (2,1) -> (2, 1)
        assert np.allclose(tm_rel, [2.0, 1.0], atol=1e-5)

    def test_nearest_opponent_selected(self):
        players = squad()
        # Player 0 faces +x. Nearest opponent is player 3 at (3,-1).
        feats = compute_multiagent_features(players[0], players, Possession(None, None))
        opp_rel = feats[2:4]
        assert np.allclose(opp_rel, [3.0, -1.0], atol=1e-5)

    def test_possession_flag_values(self):
        players = squad()
        f_we = compute_multiagent_features(players[0], players, Possession(1, Team.LEFT))
        f_they = compute_multiagent_features(players[0], players, Possession(3, Team.RIGHT))
        f_loose = compute_multiagent_features(players[0], players, Possession(None, None))
        assert f_we[4] == 1.0
        assert f_they[4] == -1.0
        assert f_loose[4] == 0.0

    def test_body_frame_rotation_applied(self):
        players = squad()
        # Player 0 now faces +y (yaw=pi/2). Teammate player 1 at world (2,1)
        # relative (2,1). Facing +y, body-forward = world +y component.
        players[0].quat = np.array([math.cos(math.pi / 4), 0.0, 0.0, math.sin(math.pi / 4)])
        feats = compute_multiagent_features(players[0], players, Possession(None, None))
        tm_rel = feats[0:2]
        # world_to_body((2,1), pi/2): fwd = 2*cos+1*sin = 1 ; left = -2*sin+1*cos = -2
        assert np.allclose(tm_rel, [1.0, -2.0], atol=1e-5)


class TestFullObservation:
    def test_full_obs_is_24_dim(self):
        players = squad()
        base = build_hl_observation(players[0], _ball_at(1.0, 0.0), np.zeros(3))
        full = build_full_observation(base, players[0], players, Possession(None, None))
        assert full.shape == (24,)

    def test_base_unchanged_in_first_19(self):
        players = squad()
        base = build_hl_observation(players[0], _ball_at(1.0, 0.0), np.zeros(3))
        full = build_full_observation(base, players[0], players, Possession(None, None))
        assert np.allclose(full[:19], base, atol=1e-6)

    def test_rejects_wrong_base_dim(self):
        players = squad()
        with pytest.raises(AssertionError):
            build_full_observation(np.zeros(18), players[0], players, Possession(None, None))


def _ball_at(x, y):
    from match_3v3 import BallState
    b = BallState()
    b.pos = np.array([x, y, 0.11])
    b.vel = np.zeros(3)
    return b


# ── Mirror of soccer_env_hierarchical._multiagent_extra possession rule ──
# The training env computes possession *in-env* from ball distances (no tracker
# needed). This numpy port pins that rule so a torch mismatch is caught early.
def env_possession_flag(self_xy, teammates_xy, opponents_xy, ball_xy):
    self_ball = float(np.linalg.norm(self_xy - ball_xy))
    tm_ball = min(float(np.linalg.norm(t[:2] - ball_xy)) for t in teammates_xy)
    op_ball = min(float(np.linalg.norm(o[:2] - ball_xy)) for o in opponents_xy)
    team_min = min(self_ball, tm_ball)
    if team_min <= op_ball:
        return 1.0 if self_ball <= tm_ball else 0.0   # my team has it; am I the chaser?
    return -1.0                                        # opponents closer


class TestEnvPossessionRule:
    def test_i_am_chaser_on_my_team(self):
        flag = env_possession_flag(
            np.array([0.0, 0.0]),                       # self
            [np.array([2.0, 1.0]), np.array([-6.5, 0.0])],   # teammates far
            [np.array([3.0, -1.0]), np.array([5.0, 2.0]), np.array([6.5, 0.0])],
            np.array([0.5, 0.0]),                       # ball right next to me
        )
        assert flag == 1.0

    def test_teammate_is_chaser_not_me(self):
        flag = env_possession_flag(
            np.array([0.0, 0.0]),
            [np.array([0.3, 0.1]), np.array([-6.5, 0.0])],   # teammate much closer to ball
            [np.array([3.0, -1.0]), np.array([5.0, 2.0]), np.array([6.5, 0.0])],
            np.array([0.2, 0.1]),                       # ball near teammate
        )
        assert flag == 0.0

    def test_opponents_closer(self):
        flag = env_possession_flag(
            np.array([0.0, 0.0]),
            [np.array([2.0, 1.0]), np.array([-6.5, 0.0])],   # my team far
            [np.array([0.4, 0.2]), np.array([5.0, 2.0]), np.array([6.5, 0.0])],  # opp near ball
            np.array([0.3, 0.2]),
        )
        assert flag == -1.0

