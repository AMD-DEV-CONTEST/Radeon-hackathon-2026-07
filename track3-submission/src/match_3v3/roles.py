"""Role assignment for multi-robot soccer.

Assigns attacker / defender / goalkeeper per team using fixed, explainable rules:
    1. Closest player to ball → ATTACKER
    2. Of remaining players, closest to own goal → GOALKEEPER
    3. Remaining player → DEFENDER

Each assignment includes a target position derived from the role and match state.
Reassignment happens at a configurable interval to allow dynamic role switching.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .scene import Team, Role, PlayerState, BallState, FieldConstants, DEFAULT_FIELD


@dataclass
class RoleAssignment:
    """Result of role assignment for a single player."""
    player_idx: int
    team: Team
    role: Role
    target_pos: np.ndarray  # (3,) — desired position on field
    reason: str             # human-readable explanation


class RoleAssigner:
    """Assign roles to 3 players per team based on ball position.

    Rules (applied independently per team):
        - Closest player to ball → ATTACKER
        - Closest to own goal (excluding attacker) → GOALKEEPER
        - Remaining → DEFENDER

    Target positions:
        ATTACKER    — move toward ball
        DEFENDER    — midpoint between own goal and ball
        GOALKEEPER  — on goal line, track ball y
    """

    def __init__(
        self,
        reassign_interval: int = 50,
        field: Optional[FieldConstants] = None,
        defend_offset: float = 2.0,
        keeper_y_range: float = 1.04,
    ):
        self.reassign_interval = reassign_interval
        self.field = field or DEFAULT_FIELD
        self.defend_offset = defend_offset
        self.keeper_y_range = keeper_y_range

    def assign(
        self,
        players: list[PlayerState],
        ball: BallState,
        step: int,
    ) -> list[RoleAssignment]:
        """Assign roles to all players. Returns one RoleAssignment per player.

        Reassignment only occurs every ``reassign_interval`` steps or at step 0.
        Between reassignments, target positions are still updated.
        """
        do_reassign = (step == 0) or (step % self.reassign_interval == 0)
        assignments: list[RoleAssignment] = []

        for team in [Team.LEFT, Team.RIGHT]:
            team_indices = [i for i, p in enumerate(players) if p.team == team]
            team_players = [players[i] for i in team_indices]
            if len(team_players) != 3:
                continue

            if do_reassign:
                self._reassign_team(team_players, ball.pos)

            for local_i, p in enumerate(team_players):
                target = self._compute_target(p, ball.pos)
                assignments.append(RoleAssignment(
                    player_idx=p.robot_idx,
                    team=p.team,
                    role=p.role,
                    target_pos=target,
                    reason=self._role_reason(p, ball.pos),
                ))

        return assignments

    def _reassign_team(self, team_players: list[PlayerState], ball_pos: np.ndarray):
        """Reassign roles for one team of 3 players."""
        dists = [float(np.linalg.norm(p.pos[:2] - ball_pos[:2])) for p in team_players]
        attacker_local = int(np.argmin(dists))

        remaining = [i for i in range(3) if i != attacker_local]
        goal_dists = [
            abs(team_players[i].pos[0] - team_players[i].defend_goal_x)
            for i in remaining
        ]
        keeper_local = remaining[int(np.argmin(goal_dists))]
        defender_local = [i for i in remaining if i != keeper_local][0]

        team_players[attacker_local].role = Role.ATTACKER
        team_players[keeper_local].role = Role.GOALKEEPER
        team_players[defender_local].role = Role.DEFENDER

    def _compute_target(self, player: PlayerState, ball_pos: np.ndarray) -> np.ndarray:
        """Compute the desired target position for a player based on their role."""
        if player.role == Role.ATTACKER:
            # Move toward ball
            return ball_pos.copy()

        elif player.role == Role.DEFENDER:
            # Midpoint between own goal and ball, offset toward ball
            goal_x = player.defend_goal_x
            direction = 1.0 if goal_x < 0 else -1.0
            target_x = goal_x + direction * self.defend_offset
            target_y = float(np.clip(ball_pos[1], -self.keeper_y_range, self.keeper_y_range))
            return np.array([target_x, target_y, 0.0])

        else:  # GOALKEEPER
            goal_x = player.defend_goal_x
            target_y = float(np.clip(ball_pos[1], -self.keeper_y_range, self.keeper_y_range))
            return np.array([goal_x, target_y, 0.0])

    def _role_reason(self, player: PlayerState, ball_pos: np.ndarray) -> str:
        if player.role == Role.ATTACKER:
            return "closest to ball"
        elif player.role == Role.GOALKEEPER:
            return "closest to own goal"
        else:
            return "remaining player"


def check_role_distribution(players: list[PlayerState]) -> dict:
    """Validate that each team has exactly one of each role.

    Returns a dict with keys: 'left_ok', 'right_ok', 'left_roles', 'right_roles'.
    """
    result = {"left_ok": True, "right_ok": True, "left_roles": [], "right_roles": []}

    for team in [Team.LEFT, Team.RIGHT]:
        roles = [p.role for p in players if p.team == team]
        role_names = [r.value for r in roles]
        team_key = "left" if team == Team.LEFT else "right"
        result[f"{team_key}_roles"] = role_names

        expected = {Role.ATTACKER, Role.DEFENDER, Role.GOALKEEPER}
        if set(roles) != expected or len(roles) != 3:
            result[f"{team_key}_ok"] = False

    return result
