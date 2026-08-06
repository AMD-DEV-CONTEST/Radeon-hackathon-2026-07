"""Contract tests for the multi-robot team strategy brain — no Genesis required.

Covers:
    1. world_to_body frame math (forward/left convention).
    2. PossessionTracker control / dwell / steal / loose-ball behaviour.
    3. SmartRoleAssigner hysteresis (no role flapping) + valid distribution.
    4. FormationTargets possession-aware defender positioning (in bounds).
    5. PassPlanner pressure + open-lane pass recommendation.
    6. build_hl_observation shape + ball geometry correctness.
    7. TeamBrain end-to-end: exactly one RL chaser per team.
"""
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
    Team, Role, PlayerState, BallState, DEFAULT_FIELD,
    Possession, PossessionTracker, SmartRoleAssigner, FormationTargets,
    PassPlanner, PassDecision, TeamBrain, build_hl_observation, world_to_body,
)


# ── Helpers ─────────────────────────────────────────────────────────

def make_player(idx, team, x, y, yaw=0.0):
    p = PlayerState(team=team, robot_idx=idx)
    p.pos = np.array([x, y, 0.72])
    # yaw -> quaternion (w, x, y, z), rotation about z
    p.quat = np.array([math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2)])
    return p


def make_ball(x, y, vx=0.0, vy=0.0):
    b = BallState()
    b.pos = np.array([x, y, 0.11])
    b.vel = np.array([vx, vy, 0.0])
    return b


def three_vs_three():
    """Standard 6-player setup."""
    return [
        make_player(0, Team.LEFT, -1.0, 0.0),
        make_player(1, Team.LEFT, -3.5, 1.5),
        make_player(2, Team.LEFT, -6.5, 0.0),
        make_player(3, Team.RIGHT, 1.0, 0.0),
        make_player(4, Team.RIGHT, 3.5, -1.5),
        make_player(5, Team.RIGHT, 6.5, 0.0),
    ]


# ── 1. Frame math ───────────────────────────────────────────────────

class TestWorldToBody:
    def test_facing_px_ball_ahead(self):
        # Robot faces +x, ball 2m ahead on +x -> body frame (2, 0).
        out = world_to_body(np.array([2.0, 0.0]), 0.0)
        assert np.allclose(out, [2.0, 0.0], atol=1e-6)

    def test_facing_px_ball_left(self):
        # Robot faces +x, ball on +y (left) -> body frame (0, +2).
        out = world_to_body(np.array([0.0, 2.0]), 0.0)
        assert np.allclose(out, [0.0, 2.0], atol=1e-6)

    def test_facing_py_ball_ahead(self):
        # Robot faces +y (yaw=pi/2), ball ahead in world +y -> body frame (2, 0).
        out = world_to_body(np.array([0.0, 2.0]), math.pi / 2)
        assert np.allclose(out, [2.0, 0.0], atol=1e-6)

    def test_facing_nx_ball_ahead(self):
        # Robot faces -x (yaw=pi), ball ahead in world -x -> body frame (2, 0).
        out = world_to_body(np.array([-2.0, 0.0]), math.pi)
        assert np.allclose(out, [2.0, 0.0], atol=1e-6)


# ── 2. Possession ───────────────────────────────────────────────────

class TestPossession:
    def test_close_slow_ball_is_controlled(self):
        players = three_vs_three()
        players[0].pos = np.array([0.2, 0.0, 0.72])
        ball = make_ball(0.0, 0.0)  # slow, 0.2m from player 0
        tr = PossessionTracker()
        poss = tr.update(players, ball)
        assert poss.player_idx == 0
        assert poss.team == Team.LEFT

    def test_fast_ball_is_loose(self):
        players = three_vs_three()
        players[0].pos = np.array([0.2, 0.0, 0.72])
        ball = make_ball(0.0, 0.0, vx=5.0)  # fast -> loose even though close
        tr = PossessionTracker()
        poss = tr.update(players, ball)
        assert poss.player_idx is None
        assert poss.contested

    def test_controller_keeps_ball_within_release_radius(self):
        players = three_vs_three()
        players[0].pos = np.array([0.2, 0.0, 0.72])
        tr = PossessionTracker()
        tr.update(players, make_ball(0.0, 0.0))   # player 0 gains control
        # Ball moves away but stays within release_radius (0.70).
        players[0].pos = np.array([0.6, 0.0, 0.72])
        poss = tr.update(players, make_ball(0.0, 0.0))
        assert poss.player_idx == 0

    def test_far_ball_releases_possession(self):
        players = three_vs_three()
        players[0].pos = np.array([0.2, 0.0, 0.72])
        tr = PossessionTracker()
        tr.update(players, make_ball(0.0, 0.0))
        # Ball teleports far away -> possession released.
        players[0].pos = np.array([3.0, 0.0, 0.72])
        poss = tr.update(players, make_ball(0.0, 0.0))
        assert poss.player_idx is None


# ── 3. Smart role assignment (hysteresis) ───────────────────────────

class TestSmartRoleAssigner:
    def test_exactly_one_of_each_role(self):
        players = three_vs_three()
        ball = make_ball(0.0, 0.0)
        ra = SmartRoleAssigner()
        ra.assign(players, ball)
        for team in (Team.LEFT, Team.RIGHT):
            roles = {p.role for p in players if p.team == team}
            assert roles == {Role.ATTACKER, Role.DEFENDER, Role.GOALKEEPER}

    def test_closest_becomes_attacker_initially(self):
        players = three_vs_three()
        ball = make_ball(-1.2, 0.1)   # closest to LEFT player 0
        ra = SmartRoleAssigner()
        ra.assign(players, ball)
        assert players[0].role == Role.ATTACKER

    def test_no_role_flap_when_distances_close(self):
        # Two LEFT players nearly equidistant; ball nudges so argmin would flip.
        players = three_vs_three()
        players[0].pos = np.array([-1.0, 0.0, 0.72])
        players[1].pos = np.array([-1.4, 0.0, 0.72])   # 0.4m further
        ra = SmartRoleAssigner(switch_margin=0.6)

        ball = make_ball(-1.1, 0.0)   # player 0 closer -> becomes attacker
        ra.assign(players, ball)
        first_attacker = [p for p in players if p.team == Team.LEFT and p.role == Role.ATTACKER][0].robot_idx

        # Ball moves so player 1 is now marginally closer (but < switch_margin).
        ball = make_ball(-1.35, 0.0)
        ra.assign(players, ball)
        second_attacker = [p for p in players if p.team == Team.LEFT and p.role == Role.ATTACKER][0].robot_idx

        # Hysteresis: attacker should NOT have flipped for a 0.25m change.
        assert first_attacker == second_attacker == 0

    def test_role_switches_when_clearly_beaten(self):
        players = three_vs_three()
        players[0].pos = np.array([-1.0, 0.0, 0.72])
        players[1].pos = np.array([-3.0, 0.0, 0.72])
        ra = SmartRoleAssigner(switch_margin=0.6)
        ra.assign(players, make_ball(-1.1, 0.0))   # player 0 attacker
        # Ball now sits next to player 1, far from player 0.
        ra.assign(players, make_ball(-3.0, 0.0))
        assert players[1].role == Role.ATTACKER

    def test_fallen_attacker_releases_role(self):
        players = three_vs_three()
        ra = SmartRoleAssigner()
        ra.assign(players, make_ball(-1.1, 0.0))
        assert players[0].role == Role.ATTACKER
        players[0].fallen = True
        ra.assign(players, make_ball(-1.1, 0.0))
        # Role must move off the fallen player.
        assert players[0].role != Role.ATTACKER
        roles = {p.role for p in players if p.team == Team.LEFT}
        assert roles == {Role.ATTACKER, Role.DEFENDER, Role.GOALKEEPER}


# ── 4. Formation targets ────────────────────────────────────────────

class TestFormationTargets:
    def test_goalkeeper_target_on_goal_line(self):
        players = three_vs_three()
        gk = players[2]  # LEFT goalkeeper
        gk.role = Role.GOALKEEPER
        ft = FormationTargets()
        tgt = ft.target(gk, make_ball(0.0, 0.0), Possession(None, None))
        assert tgt[0] == pytest.approx(DEFAULT_FIELD.left_goal_x)

    def test_defender_pushes_up_when_we_have_ball(self):
        players = three_vs_three()
        d = players[1]  # LEFT defender
        d.role = Role.DEFENDER
        ft = FormationTargets()
        we = Possession(0, Team.LEFT)
        tgt_attack = ft.target(d, make_ball(1.0, 0.0), we)
        neutral = ft.target(d, make_ball(1.0, 0.0), Possession(None, None))
        # Pushing up means larger x (toward +x attack goal) than the neutral cover.
        assert tgt_attack[0] > neutral[0]

    def test_all_targets_within_field(self):
        players = three_vs_three()
        ra = SmartRoleAssigner()
        ball = make_ball(2.0, 1.0)
        ra.assign(players, ball)
        ft = FormationTargets()
        f = DEFAULT_FIELD
        for poss in (Possession(None, None), Possession(0, Team.LEFT), Possession(3, Team.RIGHT)):
            for p in players:
                tgt = ft.target(p, ball, poss)
                assert abs(tgt[0]) <= f.half_length
                assert abs(tgt[1]) <= f.half_width


# ── 5. Pass planning ────────────────────────────────────────────────

class TestPassPlanner:
    def test_pass_recommended_under_pressure_to_open_teammate(self):
        players = three_vs_three()
        carrier = players[0]
        carrier.pos = np.array([1.0, 0.0, 0.72])
        # Advanced, open teammate further toward +x (LEFT attacks +x).
        players[1].pos = np.array([3.0, 0.5, 0.72])
        # Opponent pressing the carrier hard.
        players[3].pos = np.array([1.4, 0.2, 0.72])
        players[4].pos = np.array([6.0, -3.0, 0.72])
        players[5].pos = np.array([6.5, 0.0, 0.72])
        ball = make_ball(1.0, 0.0)
        poss = Possession(0, Team.LEFT)

        pp = PassPlanner(pressure_radius=1.0)
        dec = pp.decide(carrier, players, ball, poss)
        assert dec.should_pass
        assert dec.target_idx == 1
        # Pass direction points upfield (+x).
        assert dec.pass_dir[0] > 0

    def test_no_pass_when_not_possessor(self):
        players = three_vs_three()
        pp = PassPlanner()
        dec = pp.decide(players[0], players, make_ball(0, 0), Possession(3, Team.RIGHT))
        assert not dec.should_pass

    def test_no_pass_when_no_pressure(self):
        players = three_vs_three()
        carrier = players[0]
        carrier.pos = np.array([0.0, 0.0, 0.72])
        players[1].pos = np.array([3.0, 0.5, 0.72])
        # All opponents far away.
        for i in (3, 4, 5):
            players[i].pos = np.array([6.0, -3.0 + i, 0.72])
        pp = PassPlanner(pressure_radius=1.0)
        dec = pp.decide(carrier, players, make_ball(0, 0), Possession(0, Team.LEFT))
        assert not dec.should_pass

    def test_no_pass_through_blocked_lane(self):
        players = three_vs_three()
        carrier = players[0]
        carrier.pos = np.array([1.0, 0.0, 0.72])
        players[1].pos = np.array([3.0, 0.0, 0.72])   # straight ahead
        # Opponent pressing AND parked right in the passing lane.
        players[3].pos = np.array([1.3, 0.0, 0.72])   # pressure
        players[4].pos = np.array([2.0, 0.1, 0.72])   # blocking lane to player 1
        players[5].pos = np.array([6.5, 0.0, 0.72])
        pp = PassPlanner(pressure_radius=1.0, lane_half_width=0.6)
        dec = pp.decide(carrier, players, make_ball(1, 0), Possession(0, Team.LEFT))
        assert not dec.should_pass


# ── 6. HL observation builder ───────────────────────────────────────

class TestBuildHLObs:
    def test_shape_is_19(self):
        p = make_player(0, Team.LEFT, -1.0, 0.0)
        obs = build_hl_observation(p, make_ball(0.5, 0.0), np.zeros(3))
        assert obs.shape == (19,)
        assert obs.dtype == np.float32

    def test_ball_geometry_correct(self):
        # LEFT player at origin facing +x; ball 2m ahead. attack goal = +x.
        p = make_player(0, Team.LEFT, 0.0, 0.0, yaw=0.0)
        ball = make_ball(2.0, 0.0)
        obs = build_hl_observation(p, ball, np.zeros(3))
        # Layout: [lin(3) ang(3) grav(2) ball_rel(2) ball_vel(2) dist(1) goal_dir(2) goal_dist(1) last(3)]
        ball_rel = obs[8:10]
        dist = obs[12]
        goal_dir = obs[13:15]
        assert np.allclose(ball_rel, [2.0, 0.0], atol=1e-5)     # ball ahead in body frame
        assert dist == pytest.approx(2.0, abs=1e-5)
        # Goal is far on +x, so goal_dir ~ (1, 0).
        assert goal_dir[0] > 0.99

    def test_last_action_echoed(self):
        p = make_player(0, Team.LEFT, 0.0, 0.0)
        last = np.array([0.3, -0.2, 0.1])
        obs = build_hl_observation(p, make_ball(1, 0), last)
        assert np.allclose(obs[16:19], last, atol=1e-5)


# ── 7. TeamBrain end-to-end ─────────────────────────────────────────

class TestTeamBrain:
    def test_exactly_one_rl_chaser_per_team(self):
        players = three_vs_three()
        ball = make_ball(0.0, 0.0)
        brain = TeamBrain()
        cmds = brain.compute(players, ball)
        assert len(cmds) == 6
        by_idx = {p.robot_idx: p for p in players}
        for team in (Team.LEFT, Team.RIGHT):
            team_rl = [c for c in cmds if by_idx[c.robot_idx].team == team and c.use_rl]
            assert len(team_rl) == 1
            assert team_rl[0].role == Role.ATTACKER

    def test_targets_present_and_finite(self):
        players = three_vs_three()
        brain = TeamBrain()
        cmds = brain.compute(players, make_ball(1.0, 1.0))
        for c in cmds:
            assert c.target_pos.shape == (3,)
            assert np.all(np.isfinite(c.target_pos))

    def test_reset_clears_state(self):
        brain = TeamBrain()
        players = three_vs_three()
        brain.compute(players, make_ball(0, 0))
        brain.reset()
        assert brain.possession._controller is None
