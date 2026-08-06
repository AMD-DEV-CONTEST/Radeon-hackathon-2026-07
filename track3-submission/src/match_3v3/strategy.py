"""Team strategy brain for multi-robot soccer — pure numpy, no Genesis required.

This module fixes the three gaps that made the trained v6 policy behave like
"three strangers chasing one ball" in a multi-robot match:

    1. Role flapping  — the base RoleAssigner re-picks the attacker by a bare
       argmin every ``reassign_interval`` steps. When two players are nearly
       equidistant to the ball, the attacker role flips back and forth and both
       robots hesitate. ``SmartRoleAssigner`` adds hysteresis + commitment so a
       chaser keeps the ball unless clearly beaten to it (or falls).

    2. No possession / formation — nothing tracked who controlled the ball, so
       there was no "push up when we have it, drop back when they have it".
       ``PossessionTracker`` + ``FormationTargets`` give the team a shape.

    3. No pass coordination — the attacker dribbled into pressure with no outlet.
       ``PassPlanner`` detects pressure and recommends a pass to an open,
       more-advanced teammate.

Everything here is CPU-testable: it operates on ``PlayerState`` / ``BallState``
value objects and returns plain numpy arrays. The Genesis scene step loop calls
into ``TeamBrain``; the trained high-level policy is plugged in via
``build_hl_observation`` (which mirrors ``soccer_env_hierarchical``'s 19-dim
layout) so the attacker uses the learned chaser instead of a rule.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .scene import Team, Role, PlayerState, BallState, FieldConstants, DEFAULT_FIELD


# ═══════════════════════════════════════════════════════════════════
# Frame helpers
# ═══════════════════════════════════════════════════════════════════

def sigmoid(x: np.ndarray) -> np.ndarray:
    """Numerically stable logistic sigmoid."""
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=np.float64)))


def world_to_body(rel_xy: np.ndarray, yaw: float) -> np.ndarray:
    """Rotate a world-frame relative (dx, dy) into the robot body frame.

    Body frame: +x is forward (facing direction ``yaw``), +y is left.
    Matches the convention used by ``transform_by_quat(rel, inv_base_quat)``
    in ``soccer_env_hierarchical`` for a robot whose heading is ``yaw``.
    """
    c, s = math.cos(yaw), math.sin(yaw)
    dx, dy = float(rel_xy[0]), float(rel_xy[1])
    forward = dx * c + dy * s
    left = -dx * s + dy * c
    return np.array([forward, left], dtype=np.float64)


def normalize_angle(a: float) -> float:
    """Wrap an angle to [-pi, pi]."""
    return (a + math.pi) % (2.0 * math.pi) - math.pi


# ═══════════════════════════════════════════════════════════════════
# Possession tracking
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Possession:
    """Which player/team currently controls the ball."""
    player_idx: Optional[int] = None      # robot_idx of controller, or None if loose
    team: Optional[Team] = None

    @property
    def contested(self) -> bool:
        return self.player_idx is None


class PossessionTracker:
    """Track ball control with a small dwell to avoid flicker.

    A player controls the ball when it is within ``control_radius`` of them and
    moving slower than ``control_max_speed`` (a fast ball nearby is a pass or a
    deflection, not control). To stop the controller from flickering between two
    nearby players, the current controller keeps the ball until it leaves
    ``release_radius`` or another player is clearly closer by ``steal_margin``.
    """

    def __init__(
        self,
        control_radius: float = 0.45,
        release_radius: float = 0.70,
        control_max_speed: float = 0.8,
        steal_margin: float = 0.15,
    ):
        self.control_radius = control_radius
        self.release_radius = release_radius
        self.control_max_speed = control_max_speed
        self.steal_margin = steal_margin
        self._controller: Optional[int] = None  # robot_idx

    def reset(self):
        self._controller = None

    def update(self, players: list[PlayerState], ball: BallState) -> Possession:
        # A fast-moving ball is loose regardless of proximity.
        ball_slow = ball.speed < self.control_max_speed

        dists = {p.robot_idx: float(np.linalg.norm(p.pos[:2] - ball.pos[:2]))
                 for p in players}

        # Current controller keeps the ball while it stays within release_radius.
        if self._controller is not None and ball_slow:
            cur_d = dists.get(self._controller, np.inf)
            if cur_d < self.release_radius:
                # Someone clearly closer steals it.
                challenger = min(dists, key=dists.get)
                if challenger != self._controller and dists[challenger] < cur_d - self.steal_margin:
                    self._controller = challenger
                team = next(p.team for p in players if p.robot_idx == self._controller)
                return Possession(self._controller, team)
            # Ball escaped — release.
            self._controller = None

        # No controller: the closest player within control_radius takes it.
        if ball_slow and dists:
            closest = min(dists, key=dists.get)
            if dists[closest] < self.control_radius:
                self._controller = closest
                team = next(p.team for p in players if p.robot_idx == closest)
                return Possession(closest, team)

        return Possession(None, None)


# ═══════════════════════════════════════════════════════════════════
# Smart role assignment (hysteresis — fixes role flapping)
# ═══════════════════════════════════════════════════════════════════

class SmartRoleAssigner:
    """Role assignment with hysteresis + goalkeeper stickiness.

    Compared to the base ``RoleAssigner`` (bare argmin every N steps), this:
        - keeps a *committed* attacker: the chaser stays on the ball until a
          teammate is closer by ``switch_margin`` metres, or the chaser falls.
        - keeps the goalkeeper sticky: the keeper only changes if it falls —
          swapping keepers mid-play leaves an open net.
        - still produces exactly one ATTACKER / DEFENDER / GOALKEEPER per team.
    """

    def __init__(
        self,
        field: Optional[FieldConstants] = None,
        switch_margin: float = 0.6,
        defend_offset: float = 2.0,
        keeper_y_range: float = 1.04,
    ):
        self.field = field or DEFAULT_FIELD
        self.switch_margin = switch_margin
        self.defend_offset = defend_offset
        self.keeper_y_range = keeper_y_range
        # Persistent per-team state: {Team: {"attacker": idx, "keeper": idx}}
        self._state: dict = {Team.LEFT: {"attacker": None, "keeper": None},
                             Team.RIGHT: {"attacker": None, "keeper": None}}

    def reset(self):
        for t in (Team.LEFT, Team.RIGHT):
            self._state[t] = {"attacker": None, "keeper": None}

    def assign(self, players: list[PlayerState], ball: BallState) -> list[PlayerState]:
        """(Re)assign roles in place; returns the same player list."""
        for team in (Team.LEFT, Team.RIGHT):
            team_players = [p for p in players if p.team == team]
            if len(team_players) != 3:
                continue
            self._assign_team(team_players, ball)
        return players

    def _assign_team(self, tp: list[PlayerState], ball: BallState):
        st = self._state[tp[0].team]
        dists = {p.robot_idx: float(np.linalg.norm(p.pos[:2] - ball.pos[:2])) for p in tp}
        by_idx = {p.robot_idx: p for p in tp}
        fallen = {i: by_idx[i].fallen for i in dists}

        # Closest *non-fallen* player to the ball (a downed robot cannot chase).
        candidates = [i for i in dists if not fallen[i]] or list(dists)
        closest = min(candidates, key=lambda i: dists[i])

        # ── Attacker with hysteresis ────────────────────────────────
        committed = st["attacker"]
        if committed is None or committed not in by_idx or by_idx[committed].fallen:
            attacker = closest                      # no commitment, or chaser fell
        elif dists[closest] < dists[committed] - self.switch_margin:
            attacker = closest                      # clearly beaten to the ball
        else:
            attacker = committed                    # keep commitment
        st["attacker"] = attacker

        # ── Goalkeeper, sticky ──────────────────────────────────────
        keeper = st["keeper"]
        rest = [i for i in dists if i != attacker]
        if keeper is None or keeper not in by_idx or keeper == attacker or by_idx[keeper].fallen:
            # Choose keeper = closest to own goal among standing non-attackers.
            non_fallen_rest = [i for i in rest if not fallen[i]] or rest
            keeper = min(non_fallen_rest,
                         key=lambda i: abs(by_idx[i].pos[0] - by_idx[i].defend_goal_x))
        st["keeper"] = keeper

        # ── Defender = whoever is left ──────────────────────────────
        defender = next(i for i in dists if i not in (attacker, keeper))

        by_idx[attacker].role = Role.ATTACKER
        by_idx[keeper].role = Role.GOALKEEPER
        by_idx[defender].role = Role.DEFENDER


# ═══════════════════════════════════════════════════════════════════
# Formation targets (possession-aware team shape)
# ═══════════════════════════════════════════════════════════════════

class FormationTargets:
    """Compute the desired field position for each player given possession.

    Shape rules (per team):
        ATTACKER    — go to the ball (the chaser; the RL policy refines this).
        DEFENDER    — if *we* have the ball: push up to a passing outlet halfway
                      between centre and the ball; if *they* have it: drop to a
                      zonal spot between the ball and our goal; if loose: hold
                      central cover.
        GOALKEEPER  — stay on the goal line, track ball y (clamped).
    """

    def __init__(
        self,
        field: Optional[FieldConstants] = None,
        defend_offset: float = 2.2,
        outlet_pushup: float = 0.5,
        keeper_y_range: float = 1.04,
    ):
        self.field = field or DEFAULT_FIELD
        self.defend_offset = defend_offset
        self.outlet_pushup = outlet_pushup
        self.keeper_y_range = keeper_y_range

    def target(self, player: PlayerState, ball: BallState, possession: Possession) -> np.ndarray:
        f = self.field
        if player.role == Role.ATTACKER:
            return np.array([ball.pos[0], ball.pos[1], 0.0])

        if player.role == Role.GOALKEEPER:
            gx = player.defend_goal_x
            ty = float(np.clip(ball.pos[1], -self.keeper_y_range, self.keeper_y_range))
            return np.array([gx, ty, 0.0])

        # DEFENDER — possession-aware.
        gx = player.defend_goal_x
        direction = 1.0 if gx < 0 else -1.0       # +1 pushes toward centre/+x
        we_have_it = (possession.team == player.team)
        they_have_it = (possession.team is not None and possession.team != player.team)

        if we_have_it:
            # Passing outlet: halfway between centre line and the ball, wide of it.
            tx = direction * (abs(ball.pos[0]) * self.outlet_pushup)
            ty = float(np.clip(ball.pos[1] + (1.5 if ball.pos[1] >= 0 else -1.5),
                               -f.half_width + 0.5, f.half_width - 0.5))
        elif they_have_it:
            # Zonal defence: between ball and own goal.
            tx = gx + direction * self.defend_offset
            ty = float(np.clip(ball.pos[1] * 0.7, -self.keeper_y_range, self.keeper_y_range))
        else:
            # Contested: hold central cover in front of goal.
            tx = gx + direction * (self.defend_offset + 1.0)
            ty = float(np.clip(ball.pos[1] * 0.5, -self.keeper_y_range, self.keeper_y_range))

        # Never stand on/behind the goal line or out of bounds.
        tx = float(np.clip(tx, -f.half_length + 0.3, f.half_length - 0.3))
        return np.array([tx, ty, 0.0])


# ═══════════════════════════════════════════════════════════════════
# Pass planning
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PassDecision:
    """Whether the ball-carrier should pass, and where to."""
    should_pass: bool = False
    target_idx: Optional[int] = None
    target_pos: np.ndarray = field(default_factory=lambda: np.zeros(3))
    pass_dir: np.ndarray = field(default_factory=lambda: np.zeros(2))


class PassPlanner:
    """Recommend a pass when the carrier is pressured and a teammate is open.

    A pass is suggested when all of the following hold:
        - ``player`` currently possesses the ball.
        - The nearest opponent is within ``pressure_radius`` (under pressure).
        - A teammate is more advanced toward the attack goal than the carrier by
          at least ``min_advance`` and the passing lane is clear (no opponent
          within ``lane_half_width`` of the carrier→teammate segment).
    """

    def __init__(
        self,
        field: Optional[FieldConstants] = None,
        pressure_radius: float = 1.0,
        min_advance: float = 0.5,
        lane_half_width: float = 0.6,
        max_pass_dist: float = 6.0,
        passer_clear_radius: float = 0.8,
    ):
        self.field = field or DEFAULT_FIELD
        self.pressure_radius = pressure_radius
        self.min_advance = min_advance
        self.lane_half_width = lane_half_width
        self.max_pass_dist = max_pass_dist
        # Opponents within this distance of the passer are already pressing it
        # and cannot intercept a ball travelling away — exclude them from the
        # lane-block test so a pressured carrier can still find an outlet pass.
        self.passer_clear_radius = passer_clear_radius

    def decide(
        self,
        player: PlayerState,
        players: list[PlayerState],
        ball: BallState,
        possession: Possession,
    ) -> PassDecision:
        if possession.player_idx != player.robot_idx:
            return PassDecision()

        teammates = [p for p in players if p.team == player.team and p.robot_idx != player.robot_idx]
        opponents = [p for p in players if p.team != player.team]
        if not teammates:
            return PassDecision()

        # Pressure check.
        if opponents:
            nearest_opp = min(float(np.linalg.norm(o.pos[:2] - player.pos[:2])) for o in opponents)
        else:
            nearest_opp = np.inf
        if nearest_opp > self.pressure_radius:
            return PassDecision()

        # Attack direction (+1 toward +x, -1 toward -x).
        atk_dir = 1.0 if player.attack_goal_x > player.pos[0] else -1.0

        best: Optional[PassDecision] = None
        best_score = -np.inf
        for tm in teammates:
            advance = (tm.pos[0] - player.pos[0]) * atk_dir
            dist = float(np.linalg.norm(tm.pos[:2] - player.pos[:2]))
            if advance < self.min_advance or dist > self.max_pass_dist or dist < 0.3:
                continue
            if not self._lane_clear(player.pos[:2], tm.pos[:2], opponents):
                continue
            # Score: prefer more advanced + more open teammates.
            openness = self._lane_clearance(player.pos[:2], tm.pos[:2], opponents)
            score = advance + 0.5 * openness
            if score > best_score:
                direction = (tm.pos[:2] - player.pos[:2]) / (dist + 1e-6)
                best = PassDecision(True, tm.robot_idx, tm.pos.copy(), direction)
                best_score = score
        return best if best is not None else PassDecision()

    def _lane_clear(self, a: np.ndarray, b: np.ndarray, opponents: list[PlayerState]) -> bool:
        return self._lane_clearance(a, b, opponents) >= self.lane_half_width

    def _lane_clearance(self, a: np.ndarray, b: np.ndarray, opponents: list[PlayerState]) -> float:
        """Minimum distance from any opponent to the a→b segment (inf if none)."""
        if not opponents:
            return np.inf
        ab = b - a
        ab2 = float(np.dot(ab, ab)) + 1e-9
        clear = np.inf
        for o in opponents:
            # Skip opponents already hugging the passer — they press, not block.
            if float(np.linalg.norm(o.pos[:2] - a)) < self.passer_clear_radius:
                continue
            t = float(np.clip(np.dot(o.pos[:2] - a, ab) / ab2, 0.0, 1.0))
            proj = a + t * ab
            d = float(np.linalg.norm(o.pos[:2] - proj))
            clear = min(clear, d)
        return clear


# ═══════════════════════════════════════════════════════════════════
# High-level observation builder (mirrors soccer_env_hierarchical)
# ═══════════════════════════════════════════════════════════════════

def build_hl_observation(
    player: PlayerState,
    ball: BallState,
    last_action: np.ndarray,
    goal_x: Optional[float] = None,
) -> np.ndarray:
    """Build the 19-dim high-level observation for one player.

    This reproduces the exact layout of
    ``SoccerEnvHierarchical._update_observation`` so a checkpoint trained in the
    single-agent env can be dropped into the multi-robot match unchanged:

        [ filtered_lin_vel(3), filtered_ang_vel(3), projected_gravity(2),
          ball_rel_body(2), ball_vel_body(2), dist_to_ball(1),
          goal_dir(2), goal_dist(1), last_hl_actions(3) ]

    The multi-robot scene does not track per-axis body velocities, so lin/ang velocity
    and gravity are approximated from ``player.vel`` and the upright assumption
    (projected_gravity ≈ 0 for a standing robot). This is sufficient for the
    chaser role, whose decisions are dominated by ball/goal geometry.
    """
    yaw = player.yaw
    gx = player.attack_goal_x if goal_x is None else goal_x

    ball_rel_body = world_to_body(ball.pos[:2] - player.pos[:2], yaw)
    ball_vel_body = world_to_body(ball.vel[:2], yaw)
    dist_to_ball = float(np.linalg.norm(ball_rel_body))

    goal_rel_body = world_to_body(np.array([gx - player.pos[0], 0.0 - player.pos[1]]), yaw)
    goal_dist = float(np.linalg.norm(goal_rel_body))
    goal_dir = goal_rel_body / (goal_dist + 1e-6)

    # Approximate body-frame linear velocity from world velocity.
    lin_vel_body = np.zeros(3)
    lin_vel_body[:2] = world_to_body(player.vel[:2], yaw)
    ang_vel_body = np.zeros(3)              # not tracked in match state
    projected_gravity = np.zeros(2)         # upright assumption

    la = np.asarray(last_action, dtype=np.float64).reshape(-1)
    if la.size != 3:
        la = np.zeros(3)

    obs = np.concatenate([
        lin_vel_body,                       # 3
        ang_vel_body,                       # 3
        projected_gravity,                  # 2
        ball_rel_body,                      # 2
        ball_vel_body,                      # 2
        [dist_to_ball],                     # 1
        goal_dir,                           # 2
        [goal_dist],                        # 1
        la,                                 # 3
    ]).astype(np.float32)
    assert obs.shape == (19,), f"HL obs must be 19-dim, got {obs.shape}"
    return obs


# ═══════════════════════════════════════════════════════════════════
# TeamBrain — one orchestrator per match
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PlayerCommand:
    """Per-player output of the team brain."""
    robot_idx: int
    role: Role
    target_pos: np.ndarray
    use_rl: bool                     # True → drive with the trained HL policy
    pass_decision: PassDecision = field(default_factory=PassDecision)


class TeamBrain:
    """Combine possession, roles, formation, and passing into per-player commands.

    Usage (per step)::

        brain = TeamBrain()
        commands = brain.compute(players, ball)
        for cmd in commands:
            if cmd.use_rl:
                obs = build_hl_observation(player, ball, player.vel_cmd)
                action = trained_policy(obs)      # the v6 high-level MLP
            else:
                action = rule_policy.compute(player, ball)   # walk toward target
    """

    def __init__(
        self,
        field: Optional[FieldConstants] = None,
        switch_margin: float = 0.6,
        pressure_radius: float = 1.0,
    ):
        self.field = field or DEFAULT_FIELD
        self.possession = PossessionTracker()
        self.roles = SmartRoleAssigner(field=self.field, switch_margin=switch_margin)
        self.formation = FormationTargets(field=self.field)
        self.passing = PassPlanner(field=self.field, pressure_radius=pressure_radius)

    def reset(self):
        self.possession.reset()
        self.roles.reset()

    def compute(self, players: list[PlayerState], ball: BallState) -> list[PlayerCommand]:
        poss = self.possession.update(players, ball)
        self.roles.assign(players, ball)

        commands: list[PlayerCommand] = []
        for p in players:
            target = self.formation.target(p, ball, poss)
            # The attacker chases the ball — hand it to the trained RL policy.
            use_rl = (p.role == Role.ATTACKER)
            pd = self.passing.decide(p, players, ball, poss) if use_rl else PassDecision()
            commands.append(PlayerCommand(p.robot_idx, p.role, target, use_rl, pd))
        return commands
