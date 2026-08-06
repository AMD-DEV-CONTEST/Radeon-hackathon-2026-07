"""
multi-robot Soccer Match Environment for Genesis.

Architecture:
    match_3v3.py       — scene builder, 6 robots + ball + field + goals
    rule_policy.py     — rule-based player behavior (find ball, approach, kick)
    role_assigner.py   — assign attacker/defender/goalkeeper per team
    match_evaluator.py — run N matches, collect stats, save JSON/CSV
    scoreboard.py      — score tracking, match state, reset logic

Layering:
    RuleLayer (who does what) → VelocityCommand → WalkPolicy (t1_walk.pt) → Joints
    KickLayer: rule-based kick action (not RL) when close to ball

First version: rule team vs rule team only.
RL integration comes after rule match loop is verified.
"""

from __future__ import annotations
import math, os, dataclasses, enum
from typing import Optional
import numpy as np
import torch

try:
    import genesis as gs
except Exception:
    gs = None


# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

FIELD_L = 14.0   # field length (x)
FIELD_W = 9.0    # field width  (y)
HALF_L = FIELD_L / 2
HALF_W = FIELD_W / 2
GOAL_W = 2.6
GOAL_H = 1.0
GOAL_HALF = GOAL_W / 2
CIRCLE_R = 1.5
BALL_R = 0.11

LEFT_GOAL_X = -HALF_L   # left team defends this goal, attacks right
RIGHT_GOAL_X = HALF_L   # right team defends this goal, attacks left

MATCH_STEPS_DEFAULT = 1000  # ~20s at dt=0.02
ROBOT_STAND_HEIGHT = 0.72

# Team definitions
class Team(enum.Enum):
    LEFT = 0   # attacks right goal (+x)
    RIGHT = 1  # attacks left goal (-x)

# Roles
class Role(enum.Enum):
    ATTACKER = "attacker"
    DEFENDER = "defender"
    GOALKEEPER = "goalkeeper"

# Starting formations (x, y, z)
# Left team starts on left half, right team on right half
LEFT_FORMATION = {
    Role.ATTACKER:   (-1.0,  0.0, ROBOT_STAND_HEIGHT),
    Role.DEFENDER:   (-3.5,  1.5, ROBOT_STAND_HEIGHT),
    Role.GOALKEEPER: (-6.5,  0.0, ROBOT_STAND_HEIGHT),
}
RIGHT_FORMATION = {
    Role.ATTACKER:   ( 1.0,  0.0, ROBOT_STAND_HEIGHT),
    Role.DEFENDER:   ( 3.5, -1.5, ROBOT_STAND_HEIGHT),
    Role.GOALKEEPER: ( 6.5,  0.0, ROBOT_STAND_HEIGHT),
}


# ═══════════════════════════════════════════════════════════════════
# Player State
# ═══════════════════════════════════════════════════════════════════

@dataclasses.dataclass
class PlayerState:
    """Per-player state tracked during a match."""
    team: Team
    role: Role
    robot_idx: int          # index into scene entities
    pos: np.ndarray = dataclasses.field(default_factory=lambda: np.zeros(3))
    quat: np.ndarray = dataclasses.field(default_factory=lambda: np.array([1,0,0,0]))
    vel: np.ndarray = dataclasses.field(default_factory=lambda: np.zeros(3))
    fallen: bool = False
    fall_count: int = 0
    recovery_count: int = 0
    vel_cmd: np.ndarray = dataclasses.field(default_factory=lambda: np.zeros(3))  # vx, vy, vyaw

    @property
    def attack_goal_x(self) -> float:
        return RIGHT_GOAL_X if self.team == Team.LEFT else LEFT_GOAL_X

    @property
    def defend_goal_x(self) -> float:
        return LEFT_GOAL_X if self.team == Team.LEFT else RIGHT_GOAL_X

    @property
    def yaw(self) -> float:
        """Facing direction in radians (0 = +x)."""
        # Extract yaw from quaternion (w, x, y, z)
        w, x, y, z = self.quat
        return math.atan2(2*(w*z + x*y), 1 - 2*(y*y + z*z))


# ═══════════════════════════════════════════════════════════════════
# Score Board
# ═══════════════════════════════════════════════════════════════════

@dataclasses.dataclass
class ScoreBoard:
    left_score: int = 0
    right_score: int = 0
    step: int = 0
    match_over: bool = False

    # per-match stats
    left_falls: int = 0
    right_falls: int = 0
    left_recoveries: int = 0
    right_recoveries: int = 0
    left_shots: int = 0
    right_shots: int = 0
    left_shots_on_target: int = 0
    right_shots_on_target: int = 0
    ball_out_of_bounds: int = 0

    def goal_scored(self, team: Team):
        if team == Team.LEFT:
            self.left_score += 1  # left scored in right goal
            return "left"
        else:
            self.right_score += 1
            return "right"

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ═══════════════════════════════════════════════════════════════════
# Ball State
# ═══════════════════════════════════════════════════════════════════

@dataclasses.dataclass
class BallState:
    pos: np.ndarray = dataclasses.field(default_factory=lambda: np.zeros(3))
    vel: np.ndarray = dataclasses.field(default_factory=lambda: np.zeros(3))
    prev_pos: np.ndarray = dataclasses.field(default_factory=lambda: np.zeros(3))

    @property
    def speed(self) -> float:
        return float(np.linalg.norm(self.vel[:2]))


# ═══════════════════════════════════════════════════════════════════
# Role Assigner
# ═══════════════════════════════════════════════════════════════════

class RoleAssigner:
    """Assign roles to 3 players per team based on ball position.

    Simple rules:
    - Closest player to ball → ATTACKER
    - Player closest to own goal (excluding attacker) → GOALKEEPER
    - Remaining player → DEFENDER

    Reassign every N steps to allow role switching.
    """

    def __init__(self, reassign_interval: int = 50):
        self.reassign_interval = reassign_interval

    def assign(self, players: list[PlayerState], ball_pos: np.ndarray, step: int) -> bool:
        """Reassign roles if needed. Returns True if roles changed."""
        if step % self.reassign_interval != 0 and step > 0:
            return False

        # Separate by team
        for team in [Team.LEFT, Team.RIGHT]:
            team_players = [p for p in players if p.team == team]
            if len(team_players) != 3:
                continue

            # Find closest to ball → attacker
            dists = [np.linalg.norm(p.pos[:2] - ball_pos[:2]) for p in team_players]
            attacker_idx = int(np.argmin(dists))

            # Of remaining, closest to own goal → goalkeeper
            remaining = [i for i in range(3) if i != attacker_idx]
            goal_dists = [
                abs(team_players[i].pos[0] - team_players[i].defend_goal_x)
                for i in remaining
            ]
            keeper_local = remaining[int(np.argmin(goal_dists))]
            defender_local = [i for i in remaining if i != keeper_local][0]

            # Assign
            team_players[attacker_idx].role = Role.ATTACKER
            team_players[keeper_local].role = Role.GOALKEEPER
            team_players[defender_local].role = Role.DEFENDER

        return True


# ═══════════════════════════════════════════════════════════════════
# Rule Policy
# ═══════════════════════════════════════════════════════════════════

class RulePolicy:
    """Rule-based player behavior.

    Outputs velocity commands (vx, vy, vyaw) for the walk policy.
    Also outputs a kick flag when close enough to ball and aligned.

    Behavior per role:
    - ATTACKER: move toward ball, then toward attack goal
    - DEFENDER: stay between ball and own goal
    - GOALKEEPER: stay on goal line, track ball y
    """

    KICK_DISTANCE = 0.3       # meters — kick if this close to ball
    KICK_ALIGN_THRESHOLD = 0.5  # radians — must be roughly facing ball
    MAX_SPEED = 0.5            # m/s
    MAX_TURN = 0.5             # rad/s
    APPROACH_SPEED = 0.4       # m/s when approaching ball
    DEFEND_SPEED = 0.3
    KEEPER_SPEED = 0.3
    KEEPER_Y_RANGE = GOAL_HALF * 0.8

    def compute(self, player: PlayerState, ball: BallState) -> tuple[np.ndarray, bool]:
        """Return (velocity_command [vx, vy, vyaw], should_kick)."""
        to_ball = ball.pos[:2] - player.pos[:2]
        dist_to_ball = float(np.linalg.norm(to_ball))
        ball_dir = math.atan2(to_ball[1], to_ball[0]) if dist_to_ball > 0.01 else 0.0

        # Angle difference: how much to turn to face ball
        yaw_diff = ball_dir - player.yaw
        yaw_diff = (yaw_diff + math.pi) % (2 * math.pi) - math.pi  # normalize to [-pi, pi]

        should_kick = False
        vx, vy, vyaw = 0.0, 0.0, 0.0

        if player.role == Role.ATTACKER:
            if dist_to_ball < self.KICK_DISTANCE:
                # Aligned with attack goal? Kick toward it
                goal_dir = player.attack_goal_x - player.pos[0]
                goal_y = 0.0  # center of goal
                to_goal = np.array([goal_dir, goal_y - player.pos[1]])
                goal_angle = math.atan2(to_goal[1], to_goal[0])
                goal_yaw_diff = goal_angle - player.yaw
                goal_yaw_diff = (goal_yaw_diff + math.pi) % (2 * math.pi) - math.pi

                if abs(goal_yaw_diff) < self.KICK_ALIGN_THRESHOLD:
                    should_kick = True
                    vx = self.MAX_SPEED  # rush forward to kick
                else:
                    vyaw = np.clip(goal_yaw_diff, -self.MAX_TURN, self.MAX_TURN)
            else:
                # Approach ball
                vx = math.cos(yaw_diff) * self.APPROACH_SPEED if abs(yaw_diff) < 1.0 else 0.0
                vy = math.sin(yaw_diff) * self.APPROACH_SPEED if abs(yaw_diff) < 1.0 else 0.0
                vyaw = np.clip(yaw_diff, -self.MAX_TURN, self.MAX_TURN)

        elif player.role == Role.DEFENDER:
            # Position between ball and own goal
            goal_x = player.defend_goal_x
            # Target: 2m in front of own goal, aligned with ball y
            target_x = goal_x + (2.0 if team_side_positive(goal_x) else -2.0)
            target_y = np.clip(ball.pos[1], -self.KEEPER_Y_RANGE, self.KEEPER_Y_RANGE)
            to_target = np.array([target_x - player.pos[0], target_y - player.pos[1]])
            target_dist = float(np.linalg.norm(to_target))
            if target_dist > 0.3:
                target_dir = math.atan2(to_target[1], to_target[0])
                td_yaw = target_dir - player.yaw
                td_yaw = (td_yaw + math.pi) % (2 * math.pi) - math.pi
                vx = math.cos(td_yaw) * self.DEFEND_SPEED if abs(td_yaw) < 1.0 else 0.0
                vy = math.sin(td_yaw) * self.DEFEND_SPEED if abs(td_yaw) < 1.0 else 0.0
                vyaw = np.clip(td_yaw, -self.MAX_TURN, self.MAX_TURN)
            else:
                # Face ball
                vyaw = np.clip(yaw_diff, -self.MAX_TURN, self.MAX_TURN)

        elif player.role == Role.GOALKEEPER:
            # Stay on goal line, track ball y
            goal_x = player.defend_goal_x
            target_y = np.clip(ball.pos[1], -self.KEEPER_Y_RANGE, self.KEEPER_Y_RANGE)
            dx = goal_x - player.pos[0]
            dy = target_y - player.pos[1]
            d = math.sqrt(dx*dx + dy*dy)
            if d > 0.2:
                vx = (dx / d) * self.KEEPER_SPEED
                vy = (dy / d) * self.KEEPER_SPEED
            # Always face ball
            vyaw = np.clip(yaw_diff, -self.MAX_TURN, self.MAX_TURN)

        # Clamp
        speed = math.sqrt(vx*vx + vy*vy)
        if speed > self.MAX_SPEED:
            scale = self.MAX_SPEED / speed
            vx *= scale
            vy *= scale

        player.vel_cmd = np.array([vx, vy, vyaw])
        return np.array([vx, vy, vyaw]), should_kick


def team_side_positive(goal_x: float) -> bool:
    return goal_x > 0


# ═══════════════════════════════════════════════════════════════════
# Match Result
# ═══════════════════════════════════════════════════════════════════

@dataclasses.dataclass
class MatchResult:
    match_id: int
    left_method: str = "rule"
    right_method: str = "rule"
    left_score: int = 0
    right_score: int = 0
    left_falls: int = 0
    right_falls: int = 0
    left_recoveries: int = 0
    right_recoveries: int = 0
    left_shots: int = 0
    right_shots: int = 0
    left_shots_on_target: int = 0
    right_shots_on_target: int = 0
    ball_out_count: int = 0
    total_steps: int = 0
    winner: str = "draw"  # "left", "right", "draw"
    seed: int = 0

    @property
    def net_score(self) -> int:
        return self.left_score - self.right_score

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def to_csv_row(self) -> str:
        d = self.to_dict()
        return ",".join(str(v) for v in d.values())

    @staticmethod
    def csv_header() -> str:
        fields = ["match_id","left_method","right_method","left_score","right_score",
                  "left_falls","right_falls","left_recoveries","right_recoveries",
                  "left_shots","right_shots","left_shots_on_target","right_shots_on_target",
                  "ball_out_count","total_steps","winner","seed"]
        return ",".join(fields)
