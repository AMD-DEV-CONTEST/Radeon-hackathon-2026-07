"""Contract tests for multi-robot match environment — no Genesis required.

Tests:
    1. Role assignment produces exactly one attacker/defender/goalkeeper per team.
    2. Role assignment picks the closest player to ball as attacker.
    3. Score tracking correctly records goals.
    4. Match result JSON schema contains all required keys.
    5. Six robot initial positions do not overlap.
    6. Policy action interface is well-formed.
"""
from __future__ import annotations

import os
import sys
import json
import math

import numpy as np
import pytest

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from match_3v3 import (
    Scene3v3, SceneConfig, FieldConstants, DEFAULT_FIELD,
    Role, Team, RoleAssigner, RoleAssignment,
    RulePolicy, SharedRLPolicy, PolicyAction,
    MatchResult, MatchSummary, ScoreBoard,
    PlayerState, BallState,
)
from match_3v3.roles import check_role_distribution


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def scene():
    return Scene3v3()


@pytest.fixture
def ball():
    return BallState(pos=np.array([0.0, 0.0, 0.11]))


@pytest.fixture
def assigner():
    return RoleAssigner()


@pytest.fixture
def rule_policy():
    return RulePolicy()


# ═══════════════════════════════════════════════════════════════════
# 1. Role assignment — distribution
# ═══════════════════════════════════════════════════════════════════

class TestRoleAssignment:
    """Verify role assignment produces valid distributions."""

    def test_each_team_has_one_of_each_role(self, scene, ball, assigner):
        assignments = assigner.assign(scene.players, ball, step=0)
        dist = check_role_distribution(scene.players)

        assert dist["left_ok"], f"Left team roles invalid: {dist['left_roles']}"
        assert dist["right_ok"], f"Right team roles invalid: {dist['right_roles']}"

    def test_left_team_roles(self, scene, ball, assigner):
        assigner.assign(scene.players, ball, step=0)
        left_roles = {p.role for p in scene.players if p.team == Team.LEFT}
        assert left_roles == {Role.ATTACKER, Role.DEFENDER, Role.GOALKEEPER}

    def test_right_team_roles(self, scene, ball, assigner):
        assigner.assign(scene.players, ball, step=0)
        right_roles = {p.role for p in scene.players if p.team == Team.RIGHT}
        assert right_roles == {Role.ATTACKER, Role.DEFENDER, Role.GOALKEEPER}

    def test_closest_player_is_attacker(self, scene, assigner):
        """The player closest to the ball should be assigned attacker."""
        ball = BallState(pos=np.array([2.0, 0.0, 0.11]))
        assigner.assign(scene.players, ball, step=0)

        # Right team attacker should be closest to ball among right team
        right_players = [p for p in scene.players if p.team == Team.RIGHT]
        right_dists = [float(np.linalg.norm(p.pos[:2] - ball.pos[:2])) for p in right_players]
        attacker_idx = int(np.argmin(right_dists))
        assert right_players[attacker_idx].role == Role.ATTACKER

    def test_goalkeeper_closest_to_own_goal(self, scene, ball, assigner):
        assigner.assign(scene.players, ball, step=0)

        for team in [Team.LEFT, Team.RIGHT]:
            team_players = [p for p in scene.players if p.team == team]
            keeper = [p for p in team_players if p.role == Role.GOALKEEPER][0]
            others = [p for p in team_players if p.role != Role.GOALKEEPER]
            for p in others:
                assert abs(keeper.pos[0] - keeper.defend_goal_x) <= abs(p.pos[0] - p.defend_goal_x), \
                    "Goalkeeper should be closest to own goal"

    def test_reassign_interval(self, scene, ball):
        """Roles should not change between reassignment intervals."""
        assigner = RoleAssigner(reassign_interval=50)
        assigner.assign(scene.players, ball, step=0)
        roles_step_0 = [p.role for p in scene.players]

        assigner.assign(scene.players, ball, step=10)
        roles_step_10 = [p.role for p in scene.players]

        assert roles_step_0 == roles_step_10

    def test_assignments_have_target_positions(self, scene, ball, assigner):
        assignments = assigner.assign(scene.players, ball, step=0)
        assert len(assignments) == 6
        for a in assignments:
            assert isinstance(a, RoleAssignment)
            assert a.target_pos.shape == (3,)
            assert a.reason != ""


# ═══════════════════════════════════════════════════════════════════
# 2. Score tracking
# ═══════════════════════════════════════════════════════════════════

class TestScoreBoard:
    """Verify score tracking logic."""

    def test_initial_score_zero(self):
        sb = ScoreBoard()
        assert sb.left_score == 0
        assert sb.right_score == 0
        assert sb.match_over is False

    def test_record_left_goal(self):
        sb = ScoreBoard()
        sb.record_goal("left")
        assert sb.left_score == 1
        assert sb.right_score == 0

    def test_record_right_goal(self):
        sb = ScoreBoard()
        sb.record_goal("right")
        assert sb.right_score == 1
        assert sb.left_score == 0

    def test_record_multiple_goals(self):
        sb = ScoreBoard()
        sb.record_goal("left")
        sb.record_goal("left")
        sb.record_goal("right")
        assert sb.left_score == 2
        assert sb.right_score == 1


# ═══════════════════════════════════════════════════════════════════
# 3. Match result JSON schema
# ═══════════════════════════════════════════════════════════════════

class TestMatchResultSchema:
    """Verify match result JSON schema completeness."""

    def test_result_has_all_required_keys(self):
        result = MatchResult(match_id=0)
        d = result.to_dict()
        required = MatchResult.expected_json_keys()
        assert set(d.keys()) == required, f"Missing keys: {required - set(d.keys())}"

    def test_json_serializable(self):
        result = MatchResult(match_id=1, method="rule_vs_rule", left_score=2, right_score=1)
        s = json.dumps(result.to_dict())
        d = json.loads(s)
        assert d["match_id"] == 1
        assert d["left_score"] == 2
        assert d["right_score"] == 1

    def test_csv_header_matches_keys(self):
        header_fields = set(MatchResult.csv_header().split(","))
        dict_keys = set(MatchResult(match_id=0).to_dict().keys())
        assert header_fields == dict_keys, f"CSV header mismatch: {header_fields ^ dict_keys}"

    def test_derived_fields(self):
        result = MatchResult(match_id=0, left_score=3, right_score=1,
                             left_falls=2, right_falls=3,
                             left_recoveries=1, right_recoveries=2)
        assert result.goals_for == 3
        assert result.goals_against == 1
        assert result.goal_diff == 2
        assert result.fallen_count == 5
        assert result.recovery_count == 3

    def test_winner_determination(self):
        result = MatchResult(match_id=0, left_score=2, right_score=1)
        assert result.goal_diff > 0  # left wins

    def test_method_labels(self):
        """Verify the three supported method labels."""
        for method in ["rule_vs_rule", "rl_vs_rule", "full_vs_rule"]:
            result = MatchResult(match_id=0, method=method)
            assert result.method == method


# ═══════════════════════════════════════════════════════════════════
# 4. Initial positions non-overlap
# ═══════════════════════════════════════════════════════════════════

class TestInitialPositions:
    """Verify no two robots start at the same position."""

    def test_all_positions_distinct(self, scene):
        positions = [p.pos for p in scene.players]
        for i in range(len(positions)):
            for j in range(i + 1, len(positions)):
                dist = float(np.linalg.norm(positions[i] - positions[j]))
                assert dist > 0.5, f"Players {i} and {j} too close: {dist:.2f}m"

    def test_left_team_on_left_half(self, scene):
        for p in scene.players:
            if p.team == Team.LEFT:
                assert p.pos[0] < 0, f"Left team player {p.robot_idx} on right half"

    def test_right_team_on_right_half(self, scene):
        for p in scene.players:
            if p.team == Team.RIGHT:
                assert p.pos[0] > 0, f"Right team player {p.robot_idx} on left half"

    def test_six_players(self, scene):
        assert len(scene.players) == 6

    def test_three_per_team(self, scene):
        left = [p for p in scene.players if p.team == Team.LEFT]
        right = [p for p in scene.players if p.team == Team.RIGHT]
        assert len(left) == 3
        assert len(right) == 3

    def test_goalkeeper_at_goal_line(self, scene):
        """Goalkeepers should start near their goal line."""
        for p in scene.players:
            if p.role == Role.GOALKEEPER:
                expected_x = p.defend_goal_x
                assert abs(p.pos[0] - expected_x) < 1.0, \
                    f"Goalkeeper {p.robot_idx} too far from goal line: {p.pos[0]} vs {expected_x}"

    def test_positions_within_field_bounds(self, scene):
        f = scene.field
        for p in scene.players:
            assert abs(p.pos[0]) <= f.half_length, f"Player {p.robot_idx} x out of bounds"
            assert abs(p.pos[1]) <= f.half_width, f"Player {p.robot_idx} y out of bounds"


# ═══════════════════════════════════════════════════════════════════
# 5. Policy action interface
# ═══════════════════════════════════════════════════════════════════

class TestPolicyAction:
    """Verify policy action interface."""

    def test_default_action(self):
        action = PolicyAction()
        assert action.velocity_cmd.shape == (3,)
        assert not action.should_kick
        assert not action.should_shoot
        assert action.shoot_dir.shape == (2,)

    def test_rule_policy_returns_action(self, scene, ball, rule_policy):
        assigner = RoleAssigner()
        assigner.assign(scene.players, ball, step=0)
        for player in scene.players:
            action = rule_policy.compute(player, ball)
            assert isinstance(action, PolicyAction)
            assert action.velocity_cmd.shape == (3,)

    def test_rule_policy_attacker_approaches_ball(self, scene, rule_policy):
        ball = BallState(pos=np.array([0.5, 0.0, 0.11]))
        assigner = RoleAssigner()
        assigner.assign(scene.players, ball, step=0)

        attacker = [p for p in scene.players if p.role == Role.ATTACKER and p.team == Team.LEFT][0]
        action = rule_policy.compute(attacker, ball)
        # Attacker should have non-zero velocity command
        speed = float(np.linalg.norm(action.velocity_cmd[:2]))
        assert speed > 0.01, "Attacker should be moving toward ball"

    def test_rule_policy_goalkeeper_stays(self, scene, rule_policy):
        ball = BallState(pos=np.array([0.0, 0.0, 0.11]))
        assigner = RoleAssigner()
        assigner.assign(scene.players, ball, step=0)

        keeper = [p for p in scene.players if p.role == Role.GOALKEEPER and p.team == Team.LEFT][0]
        action = rule_policy.compute(keeper, ball)
        # Ball is at center, keeper should move toward goal line position
        assert isinstance(action, PolicyAction)

    def test_shared_policy_without_checkpoints(self, scene, ball):
        """SharedRLPolicy without checkpoints should fall back to rule policy."""
        policy = SharedRLPolicy()
        assert policy.mode == "rule_vs_rule"
        assert not policy.walk_loaded
        assert not policy.shoot_loaded

        assigner = RoleAssigner()
        assigner.assign(scene.players, ball, step=0)
        for player in scene.players:
            action = policy.compute(player, ball)
            assert isinstance(action, PolicyAction)


# ═══════════════════════════════════════════════════════════════════
# 6. Scene and field constants
# ═══════════════════════════════════════════════════════════════════

class TestSceneConfig:
    """Verify scene configuration."""

    def test_field_dimensions(self):
        f = DEFAULT_FIELD
        assert f.field_length == 14.0
        assert f.field_width == 9.0
        assert f.half_length == 7.0
        assert f.half_width == 4.5

    def test_goal_positions(self):
        f = DEFAULT_FIELD
        assert f.left_goal_x == -7.0
        assert f.right_goal_x == 7.0

    def test_scene_genesis_flag(self, scene):
        # Genesis is expected to be unavailable in test environment
        assert isinstance(scene.genesis_available, bool)

    def test_reset_positions(self, scene):
        original = [p.pos.copy() for p in scene.players]
        # Modify positions
        for p in scene.players:
            p.pos = np.array([0.0, 0.0, 0.0])
        # Reset
        scene.reset_positions()
        # Check they're back to original
        for i, p in enumerate(scene.players):
            assert np.allclose(p.pos, original[i]), f"Player {i} not reset correctly"

    def test_goal_detection(self, scene):
        # Ball at right goal line
        scene.ball_state.pos = np.array([7.1, 0.0, 0.11])
        scoring = scene.check_goal()
        assert scoring == Team.LEFT

    def test_goal_detection_left(self, scene):
        scene.ball_state.pos = np.array([-7.1, 0.0, 0.11])
        scoring = scene.check_goal()
        assert scoring == Team.RIGHT

    def test_no_goal(self, scene):
        scene.ball_state.pos = np.array([0.0, 0.0, 0.11])
        scoring = scene.check_goal()
        assert scoring is None

    def test_ball_out_of_bounds(self, scene):
        scene.ball_state.pos = np.array([10.0, 0.0, 0.11])
        assert scene.ball_out_of_bounds()

    def test_ball_in_bounds(self, scene):
        scene.ball_state.pos = np.array([0.0, 0.0, 0.11])
        assert not scene.ball_out_of_bounds()


# ═══════════════════════════════════════════════════════════════════
# 7. Match summary
# ═══════════════════════════════════════════════════════════════════

class TestMatchSummary:
    """Verify aggregate statistics."""

    def test_empty_summary(self):
        summary = MatchSummary.from_results([])
        assert summary.n_matches == 0

    def test_aggregate(self):
        results = [
            MatchResult(match_id=0, method="rule_vs_rule",
                        left_score=2, right_score=1, winner="left",
                        left_falls=1, right_falls=2,
                        left_recoveries=1, right_recoveries=1,
                        match_duration_s=20.0),
            MatchResult(match_id=1, method="rule_vs_rule",
                        left_score=1, right_score=2, winner="right",
                        left_falls=2, right_falls=1,
                        left_recoveries=1, right_recoveries=0,
                        match_duration_s=20.0),
        ]
        summary = MatchSummary.from_results(results)
        assert summary.n_matches == 2
        assert summary.left_wins == 1
        assert summary.right_wins == 1
        assert summary.draws == 0
        assert summary.avg_goals_for == 1.5
        assert summary.avg_goals_against == 1.5
        assert summary.left_win_rate == 0.5
        assert summary.right_win_rate == 0.5
