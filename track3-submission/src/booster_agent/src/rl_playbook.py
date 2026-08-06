# coding: utf-8
"""RL-enhanced Playbook: uses ONNX policy for chaser, rule-based for others.

Competitors should modify this file to change tactics. The default implementation
uses the trained ONNX chase policy for the chaser role and falls back to
rule-based behavior for supporter and goalkeeper.
"""
from __future__ import annotations

import math
import numpy as np
from typing import TYPE_CHECKING

from .playbook import DefaultPlaybook, RoleAssignment, ROLE_CHASER, ROLE_SUPPORTER, ROLE_GOALKEEPER
from .soccer_framework import PlayContext, RobotCommand, MoveIntent, KickIntent, NoopIntent, Pose2D, BallState

if TYPE_CHECKING:
    from .runtime import SoccerKit


class RLChasePlaybook(DefaultPlaybook):
    """Playbook that uses ONNX RL policy for the chaser role.

    The ONNX model (chase_v6_2048_policy.onnx) takes 19-dim observation:
        - filtered_lin_vel(3), filtered_ang_vel(3), projected_gravity(2)
        - ball_rel_body(2), ball_vel_body(2), dist_to_ball(1)
        - goal_dir(2), goal_dist(1), last_hl_actions(3)

    And outputs 3-dim action: (vx, vy, wz) velocity command.
    """

    # Action clip — MUST match training config (soccer_env_hierarchical: hl_clip_lin=0.8, hl_clip_ang=1.0)
    CLIP_LIN = 0.8   # vx, vy
    CLIP_ANG = 1.0   # wz

    def __init__(self, kit: "SoccerKit", onnx_session=None):
        super().__init__(kit)
        self.onnx_session = onnx_session
        self._last_actions = {}  # player_id -> np.array(3)
        self._prev_ball = {}     # player_id -> (x, y, timestamp)
        self._prev_pose = {}     # player_id -> (x, y, theta, timestamp)
        self._robot_vel = {}     # player_id -> (vx, vy, vyaw) estimated

    def chaser_command(self, player_id: int, ctx: PlayContext) -> RobotCommand:
        """Generate velocity command for the chaser using ONNX policy."""
        if self.onnx_session is None:
            return super().chaser_command(player_id, ctx)

        # Get robot and ball state
        robot = ctx.robots.get(player_id)
        ball = ctx.ball
        if robot is None or robot.pose is None or not ball.is_recent(ctx.now):
            return RobotCommand(intent=NoopIntent(), reason="no_data")

        pose = robot.pose  # Pose2D(x, y, theta)
        now = ctx.now

        # Build 19-dim observation
        obs = self._build_observation(player_id, pose, ball, ctx, now)

        # ONNX inference
        action = self.onnx_session.run(
            ["action"], {"obs": obs[None, :].astype(np.float32)}
        )[0][0]

        # Clip to training range
        vx = float(np.clip(action[0], -self.CLIP_LIN, self.CLIP_LIN))
        vy = float(np.clip(action[1], -self.CLIP_LIN, self.CLIP_LIN))
        vyaw = float(np.clip(action[2], -self.CLIP_ANG, self.CLIP_ANG))

        # Store last action
        self._last_actions[player_id] = np.array([vx, vy, vyaw], dtype=np.float32)

        # Check if close enough to kick
        ball_dist = math.hypot(ball.x - pose.x, ball.y - pose.y)
        if ball_dist < 0.3:
            # Kick toward opponent goal
            goal_x = ctx.field.length / 2 if ctx.team_id == 0 else -ctx.field.length / 2
            kick_dir = math.atan2(0.0 - pose.y, goal_x - pose.x) - pose.theta
            return RobotCommand(
                intent=KickIntent(
                    direction=kick_dir,
                    power=1.0,
                    ball_x=ball.x - pose.x,
                    ball_y=ball.y - pose.y,
                ),
                reason="rl_kick",
            )

        return RobotCommand(
            intent=MoveIntent(vx=vx, vy=vy, vyaw=vyaw),
            reason="rl_chase",
        )

    def _build_observation(self, player_id: int, pose: Pose2D,
                          ball: BallState, ctx: PlayContext, now: float) -> np.ndarray:
        """Build 19-dim observation vector matching training environment.

        Training obs layout:
            [0:3]   filtered_lin_vel (body frame) — estimated from position delta
            [3:6]   filtered_ang_vel (body frame) — estimated from theta delta
            [6:8]   projected_gravity (xy) — approximated from theta
            [8:10]  ball_rel_body (xy) — ball position in robot body frame
            [10:12] ball_vel_body (xy) — ball velocity in body frame
            [12]    dist_to_ball
            [13:15] goal_dir (xy, normalized) — goal direction in body frame
            [15]    goal_dist
            [16:19] last_hl_actions (vx, vy, wz)
        """
        # Goal position (opponent goal)
        goal_x = ctx.field.length / 2 if ctx.team_id == 0 else -ctx.field.length / 2
        goal_y = 0.0

        # World-frame relative positions
        ball_rel_world = np.array([ball.x - pose.x, ball.y - pose.y])
        goal_rel_world = np.array([goal_x - pose.x, goal_y - pose.y])

        # Transform to body frame (rotate by -theta)
        c, s = math.cos(-pose.theta), math.sin(-pose.theta)
        R = np.array([[c, -s], [s, c]])

        ball_rel_body = R @ ball_rel_world
        goal_rel_body = R @ goal_rel_world

        goal_dist = float(np.linalg.norm(goal_rel_body))
        goal_dir = goal_rel_body / (goal_dist + 1e-6)
        dist_to_ball = float(np.linalg.norm(ball_rel_body))

        # Estimate ball velocity
        ball_vel_body = np.zeros(2, dtype=np.float32)
        prev = self._prev_ball.get(player_id)
        if prev and now - prev[2] > 0:
            dt = now - prev[2]
            ball_vel_world = np.array([(ball.x - prev[0]) / dt, (ball.y - prev[1]) / dt])
            ball_vel_body = (R @ ball_vel_world).astype(np.float32)
        self._prev_ball[player_id] = (ball.x, ball.y, now)

        # Estimate robot body-frame velocity from pose deltas (finite difference).
        # Training feeds real filtered_lin_vel / filtered_ang_vel — zeros here would
        # be a major obs mismatch. If the framework later exposes IMU/odometry,
        # prefer that over this estimate.
        lin_vel = np.zeros(3, dtype=np.float32)
        ang_vel = np.zeros(3, dtype=np.float32)
        prev_p = self._prev_pose.get(player_id)
        if prev_p and now - prev_p[3] > 0:
            dt = now - prev_p[3]
            # world-frame linear velocity, then rotate into body frame (same R as ball_vel)
            lin_world = np.array([(pose.x - prev_p[0]) / dt,
                                  (pose.y - prev_p[1]) / dt], dtype=np.float32)
            lin_body = R @ lin_world
            lin_vel = np.array([lin_body[0], lin_body[1], 0.0], dtype=np.float32)
            # yaw rate as body-frame angular velocity z
            dtheta = math.atan2(math.sin(pose.theta - prev_p[2]),
                                math.cos(pose.theta - prev_p[2]))
            ang_vel = np.array([0.0, 0.0, dtheta / dt], dtype=np.float32)
        self._prev_pose[player_id] = (pose.x, pose.y, pose.theta, now)

        # Projected gravity (simplified from theta)
        grav = np.array([-math.sin(pose.theta), math.cos(pose.theta)], dtype=np.float32)

        # Last action
        last_act = self._last_actions.get(player_id, np.zeros(3, dtype=np.float32))

        obs = np.concatenate([
            lin_vel,                          # 3
            ang_vel,                          # 3
            grav,                             # 2
            ball_rel_body.astype(np.float32), # 2
            ball_vel_body,                    # 2
            np.array([dist_to_ball], dtype=np.float32),  # 1
            goal_dir.astype(np.float32),      # 2
            np.array([goal_dist], dtype=np.float32),     # 1
            last_act,                         # 3
        ]).astype(np.float32)

        assert obs.shape == (19,), f"Obs shape mismatch: {obs.shape}"
        return obs
