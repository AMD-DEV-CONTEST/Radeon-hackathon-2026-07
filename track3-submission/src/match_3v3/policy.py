"""Policy interface for multi-robot soccer — rule-based and RL-based.

Action interface (PolicyAction):
    velocity_cmd  — (vx, vy, vyaw) fed to the walk policy (t1_walk.pt)
    should_kick   — bool: trigger rule-based kick (not RL)
    should_shoot   — bool: trigger shoot checkpoint (if loaded)
    shoot_dir      — (2,) desired ball direction when shooting

Key design decisions:
    - t1_walk.pt handles locomotion only (velocity → joint targets).
    - shoot checkpoint handles kicking skill only.
    - t1_walk.pt does NOT automatically kick the ball.
    - RulePolicy uses geometric rules, no checkpoints needed.
    - SharedRLPolicy loads walk + optional shoot checkpoints.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .scene import Team, Role, PlayerState, BallState, FieldConstants, DEFAULT_FIELD

try:
    import torch
except Exception:
    torch = None

try:
    from safe_load import safe_jit_load
except ImportError:
    import sys as _sys
    _dir = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        _cand = os.path.join(_dir, "scripts")
        if os.path.isfile(os.path.join(_cand, "safe_load.py")):
            _sys.path.insert(0, _cand)
            break
        _dir = os.path.dirname(_dir)
    from safe_load import safe_jit_load


# ═══════════════════════════════════════════════════════════════════
# Action interface
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PolicyAction:
    """Unified output of all policy implementations.

    Attributes:
        velocity_cmd: (vx, vy, vyaw) in robot frame — fed to walk policy.
        should_kick:  Trigger a rule-based kick motion (no RL needed).
        should_shoot: Trigger the shoot checkpoint (requires loaded model).
        shoot_dir:    (dx, dy) desired ball direction when shooting.
    """
    velocity_cmd: np.ndarray = field(default_factory=lambda: np.zeros(3))
    should_kick: bool = False
    should_shoot: bool = False
    shoot_dir: np.ndarray = field(default_factory=lambda: np.zeros(2))


# ═══════════════════════════════════════════════════════════════════
# Rule Policy
# ═══════════════════════════════════════════════════════════════════

class RulePolicy:
    """Rule-based player behavior — no checkpoints, no GPU.

    Behavior per role:
        ATTACKER    — approach ball, align with goal, kick
        DEFENDER    — hold position between ball and own goal
        GOALKEEPER  — stay on goal line, track ball y
    """

    KICK_DISTANCE = 0.3
    KICK_ALIGN_THRESHOLD = 0.5        # radians
    MAX_SPEED = 0.5                   # m/s
    MAX_TURN = 0.5                    # rad/s
    APPROACH_SPEED = 0.4
    DEFEND_SPEED = 0.3
    KEEPER_SPEED = 0.3

    def __init__(self, field: Optional[FieldConstants] = None):
        self.field = field or DEFAULT_FIELD

    @property
    def keeper_y_range(self) -> float:
        return self.field.goal_half * 0.8

    def compute(self, player: PlayerState, ball: BallState) -> PolicyAction:
        """Compute the action for a single player given match state."""
        to_ball = ball.pos[:2] - player.pos[:2]
        dist_to_ball = float(np.linalg.norm(to_ball))

        if dist_to_ball > 0.01:
            ball_dir = math.atan2(to_ball[1], to_ball[0])
        else:
            ball_dir = 0.0

        yaw_diff = ball_dir - player.yaw
        yaw_diff = (yaw_diff + math.pi) % (2 * math.pi) - math.pi

        vx, vy, vyaw = 0.0, 0.0, 0.0
        should_kick = False
        should_shoot = False
        shoot_dir = np.zeros(2)

        if player.role == Role.ATTACKER:
            if dist_to_ball < self.KICK_DISTANCE:
                goal_dx = player.attack_goal_x - player.pos[0]
                goal_dy = 0.0 - player.pos[1]
                to_goal = np.array([goal_dx, goal_dy])
                goal_angle = math.atan2(to_goal[1], to_goal[0])
                goal_yaw_diff = goal_angle - player.yaw
                goal_yaw_diff = (goal_yaw_diff + math.pi) % (2 * math.pi) - math.pi

                if abs(goal_yaw_diff) < self.KICK_ALIGN_THRESHOLD:
                    should_kick = True
                    should_shoot = True
                    shoot_dir = to_goal / (np.linalg.norm(to_goal) + 1e-6)
                    vx = self.MAX_SPEED
                else:
                    vyaw = float(np.clip(goal_yaw_diff, -self.MAX_TURN, self.MAX_TURN))
            else:
                if abs(yaw_diff) < 1.0:
                    vx = math.cos(yaw_diff) * self.APPROACH_SPEED
                    vy = math.sin(yaw_diff) * self.APPROACH_SPEED
                vyaw = float(np.clip(yaw_diff, -self.MAX_TURN, self.MAX_TURN))

        elif player.role == Role.DEFENDER:
            goal_x = player.defend_goal_x
            direction = 1.0 if goal_x < 0 else -1.0
            target_x = goal_x + direction * 2.0
            target_y = float(np.clip(ball.pos[1], -self.keeper_y_range, self.keeper_y_range))
            to_target = np.array([target_x - player.pos[0], target_y - player.pos[1]])
            target_dist = float(np.linalg.norm(to_target))

            if target_dist > 0.3:
                target_dir = math.atan2(to_target[1], to_target[0])
                td_yaw = target_dir - player.yaw
                td_yaw = (td_yaw + math.pi) % (2 * math.pi) - math.pi
                if abs(td_yaw) < 1.0:
                    vx = math.cos(td_yaw) * self.DEFEND_SPEED
                    vy = math.sin(td_yaw) * self.DEFEND_SPEED
                vyaw = float(np.clip(td_yaw, -self.MAX_TURN, self.MAX_TURN))
            else:
                vyaw = float(np.clip(yaw_diff, -self.MAX_TURN, self.MAX_TURN))

        elif player.role == Role.GOALKEEPER:
            goal_x = player.defend_goal_x
            target_y = float(np.clip(ball.pos[1], -self.keeper_y_range, self.keeper_y_range))
            dx = goal_x - player.pos[0]
            dy = target_y - player.pos[1]
            d = math.sqrt(dx * dx + dy * dy)
            if d > 0.2:
                vx = (dx / d) * self.KEEPER_SPEED
                vy = (dy / d) * self.KEEPER_SPEED
            vyaw = float(np.clip(yaw_diff, -self.MAX_TURN, self.MAX_TURN))

        # Clamp speed
        speed = math.sqrt(vx * vx + vy * vy)
        if speed > self.MAX_SPEED:
            scale = self.MAX_SPEED / speed
            vx *= scale
            vy *= scale

        player.vel_cmd = np.array([vx, vy, vyaw])
        return PolicyAction(
            velocity_cmd=np.array([vx, vy, vyaw]),
            should_kick=should_kick,
            should_shoot=should_shoot,
            shoot_dir=shoot_dir,
        )


# ═══════════════════════════════════════════════════════════════════
# Shared RL Policy
# ═══════════════════════════════════════════════════════════════════

class SharedRLPolicy:
    """RL policy using ONNX Runtime for real inference — no more stub.

    Replaces the previous stub that always fell back to RulePolicy.
    Now loads a trained ONNX model and performs real-time inference to
    produce velocity commands (vx, vy, wz) for the walk policy.

    Architecture:
        _load_onnx(model_path)        — init ORT inference session
        _preprocess_obs(player, ball) — raw state → 19-dim network input
        _infer(obs_tensor)            — ONNX Runtime forward pass → 3-dim raw action
        _postprocess(action_raw)      — clip, deadzone, map to velocity command

    The 19-dim observation MUST match the training env's observation space
    exactly (body-frame transforms, normalization, ordering). This is the
    "observation wrapper = bridge between training and deployment" principle.

    When ONNX model is not available, falls back to RulePolicy.
    """

    def __init__(
        self,
        onnx_path: Optional[str] = None,
        walk_checkpoint: Optional[str] = None,
        shoot_checkpoint: Optional[str] = None,
        field: Optional[FieldConstants] = None,
        action_scale: float = 0.25,
        obs_history_length: int = 10,
        clip_lin: float = 0.6,
        clip_ang: float = 0.6,
    ):
        self.field = field or DEFAULT_FIELD
        self.action_scale = action_scale
        self.obs_history_length = obs_history_length
        self.clip_lin = clip_lin
        self.clip_ang = clip_ang
        self.torch_available = torch is not None
        self.rule_fallback = RulePolicy(field=self.field)

        # ONNX Runtime session (primary inference path)
        self.session = None
        self.last_actions = np.zeros(3, dtype=np.float32)

        # Legacy walk/shoot models (for joint-level control)
        self.walk_model = None
        self.shoot_model = None

        if onnx_path:
            self._load_onnx(onnx_path)
        self._load_checkpoints(walk_checkpoint, shoot_checkpoint)

    def _load_onnx(self, onnx_path: str):
        """Initialize ONNX Runtime inference session."""
        try:
            import onnxruntime as ort
            if os.path.exists(onnx_path):
                self.session = ort.InferenceSession(
                    onnx_path, providers=["CPUExecutionProvider"])
                print(f"[SharedRLPolicy] ONNX loaded: {onnx_path}")
            else:
                print(f"[SharedRLPolicy] ONNX not found: {onnx_path}")
        except ImportError:
            print("[SharedRLPolicy] onnxruntime not installed, rule fallback")

    def _load_checkpoints(self, walk_path: Optional[str], shoot_path: Optional[str]):
        """Load TorchScript checkpoints (legacy, for joint-level control)."""
        if not self.torch_available:
            return
        if walk_path and os.path.exists(walk_path):
            try:
                self.walk_model = safe_jit_load(walk_path, map_location="cpu")
            except Exception as e:
                print(f"[SharedRLPolicy] walk checkpoint load failed: {e}")
                self.walk_model = None
        if shoot_path and os.path.exists(shoot_path):
            try:
                self.shoot_model = safe_jit_load(shoot_path, map_location="cpu")
            except Exception as e:
                print(f"[SharedRLPolicy] shoot checkpoint load failed: {e}")
                self.shoot_model = None

    @property
    def onnx_loaded(self) -> bool:
        return self.session is not None

    @property
    def walk_loaded(self) -> bool:
        return self.walk_model is not None

    @property
    def shoot_loaded(self) -> bool:
        return self.shoot_model is not None

    @property
    def mode(self) -> str:
        if self.onnx_loaded:
            return "onnx_vs_rule"
        elif self.walk_loaded:
            return "rl_vs_rule"
        else:
            return "rule_vs_rule"

    def _preprocess_obs(self, player: PlayerState, ball: BallState,
                        teammates: list = None, opponents: list = None) -> np.ndarray:
        """Build observation vector. 19-dim base + optional 5-dim multi-agent extension."""
        cos_yaw = math.cos(player.yaw)
        sin_yaw = math.sin(player.yaw)

        # 0-2: lin_vel in body frame
        lin_vel_body = np.array([
            cos_yaw * player.vel[0] + sin_yaw * player.vel[1],
            -sin_yaw * player.vel[0] + cos_yaw * player.vel[1],
            player.vel[2],
        ], dtype=np.float32)

        # 3-5: ang_vel in body frame (approximate)
        ang_vel_body = np.zeros(3, dtype=np.float32)

        # 6-7: projected_gravity xy from quaternion
        w, x, y, z = player.quat
        grav_xy = np.array([
            2.0 * (x * z - w * y),
            2.0 * (y * z + w * x),
        ], dtype=np.float32)

        # 8-9: ball position relative to robot, body frame
        ball_rel = ball.pos[:2] - player.pos[:2]
        ball_rel_body = np.array([
            cos_yaw * ball_rel[0] + sin_yaw * ball_rel[1],
            -sin_yaw * ball_rel[0] + cos_yaw * ball_rel[1],
        ], dtype=np.float32)

        # 10-11: ball velocity in body frame
        ball_vel_body = np.array([
            cos_yaw * ball.vel[0] + sin_yaw * ball.vel[1],
            -sin_yaw * ball.vel[0] + cos_yaw * ball.vel[1],
        ], dtype=np.float32)

        # 12: distance to ball
        dist_to_ball = np.array([float(np.linalg.norm(ball_rel))], dtype=np.float32)

        # 13-14: goal direction in body frame (normalized)
        goal_pos = np.array([player.attack_goal_x, 0.0])
        goal_rel = goal_pos - player.pos[:2]
        goal_rel_body = np.array([
            cos_yaw * goal_rel[0] + sin_yaw * goal_rel[1],
            -sin_yaw * goal_rel[0] + cos_yaw * goal_rel[1],
        ], dtype=np.float32)
        goal_dist_val = float(np.linalg.norm(goal_rel_body))
        goal_dir = goal_rel_body / (goal_dist_val + 1e-6)

        # 15: goal distance
        goal_dist = np.array([goal_dist_val], dtype=np.float32)

        # 16-18: last high-level actions
        base_obs = np.concatenate([
            lin_vel_body, ang_vel_body, grav_xy,
            ball_rel_body, ball_vel_body, dist_to_ball,
            goal_dir, goal_dist, self.last_actions,
        ]).astype(np.float32)

        # If no teammates/opponents given (None or empty), return 19-dim
        if not teammates or not opponents:
            return base_obs

        # 19-23: multi-agent extension (nearest teammate, nearest opponent, possession)
        tm_rels = []
        for tm_pos in teammates:
            tm_rel = np.array(tm_pos[:2]) - player.pos[:2]
            tm_body = np.array([
                cos_yaw * tm_rel[0] + sin_yaw * tm_rel[1],
                -sin_yaw * tm_rel[0] + cos_yaw * tm_rel[1],
            ])
            tm_rels.append((np.linalg.norm(tm_body), tm_body))
        tm_rels.sort(key=lambda t: t[0])
        tm_nearest = tm_rels[0][1].astype(np.float32)

        opp_rels = []
        for opp_pos in opponents:
            opp_rel = np.array(opp_pos[:2]) - player.pos[:2]
            opp_body = np.array([
                cos_yaw * opp_rel[0] + sin_yaw * opp_rel[1],
                -sin_yaw * opp_rel[0] + cos_yaw * opp_rel[1],
            ])
            opp_rels.append((np.linalg.norm(opp_body), opp_body))
        opp_rels.sort(key=lambda t: t[0])
        opp_nearest = opp_rels[0][1].astype(np.float32)

        # Possession flag
        self_ball_dist = float(np.linalg.norm(ball_rel))
        tm_min_dist = min((np.linalg.norm(np.array(tm[:2]) - ball.pos[:2])
                          for tm in teammates), default=float('inf'))
        opp_min_dist = min((np.linalg.norm(np.array(opp[:2]) - ball.pos[:2])
                           for opp in opponents), default=float('inf'))
        team_min = min(self_ball_dist, tm_min_dist)
        if team_min <= opp_min_dist:
            possession = 1.0 if self_ball_dist <= tm_min_dist else 0.0
        else:
            possession = -1.0
        possession_flag = np.array([possession], dtype=np.float32)

        return np.concatenate([base_obs, tm_nearest, opp_nearest, possession_flag]).astype(np.float32)

    def _infer(self, obs: np.ndarray) -> Optional[np.ndarray]:
        """Run ONNX Runtime forward pass: 19-dim obs → 3-dim raw action."""
        if self.session is None:
            return None
        input_name = self.session.get_inputs()[0].name
        result = self.session.run(None, {input_name: obs.reshape(1, -1)})
        return result[0].squeeze(0)

    def _postprocess(self, action_raw: np.ndarray) -> np.ndarray:
        """Clip, deadzone, and map raw action to velocity command."""
        vx = float(np.clip(action_raw[0], -self.clip_lin, self.clip_lin))
        vy = float(np.clip(action_raw[1], -self.clip_lin, self.clip_lin))
        wz = float(np.clip(action_raw[2], -self.clip_ang, self.clip_ang))
        cmd = np.array([vx, vy, wz], dtype=np.float32)
        cmd[np.abs(cmd) < 0.05] = 0.0
        return cmd

    def compute(self, player: PlayerState, ball: BallState,
                teammates: list = None, opponents: list = None) -> PolicyAction:
        """Compute action using ONNX model, with rule fallback."""
        if self.session is None:
            return self.rule_fallback.compute(player, ball)

        obs = self._preprocess_obs(player, ball, teammates, opponents)
        action_raw = self._infer(obs)
        if action_raw is None:
            return self.rule_fallback.compute(player, ball)

        vel_cmd = self._postprocess(action_raw)
        self.last_actions = vel_cmd.copy()
        player.vel_cmd = vel_cmd
        return PolicyAction(velocity_cmd=vel_cmd)

    def get_walk_joint_targets(
        self, velocity_cmd: np.ndarray,
        obs_history: Optional[np.ndarray] = None,
    ) -> Optional[np.ndarray]:
        """Convert velocity command to joint targets via walk checkpoint."""
        if not self.walk_loaded or not self.torch_available:
            return None
        obs = torch.from_numpy(obs_history).float().unsqueeze(0) if obs_history is not None else torch.zeros(1, 720)
        with torch.no_grad():
            return self.walk_model(obs).squeeze(0).cpu().numpy()

    def get_shoot_joint_targets(
        self, shoot_dir: np.ndarray,
        obs_history: Optional[np.ndarray] = None,
    ) -> Optional[np.ndarray]:
        """Get kick motion joint targets from shoot checkpoint."""
        if not self.shoot_loaded or not self.torch_available:
            return None
        obs = torch.from_numpy(obs_history).float().unsqueeze(0) if obs_history is not None else torch.zeros(1, 720)
        with torch.no_grad():
            return self.shoot_model(obs).squeeze(0).cpu().numpy()

    def close(self):
        """Release ONNX Runtime session and model resources."""
        if self.session is not None:
            del self.session
            self.session = None
        if self.walk_model is not None:
            del self.walk_model
            self.walk_model = None
        if self.shoot_model is not None:
            del self.shoot_model
            self.shoot_model = None


def team_side_positive(goal_x: float) -> bool:
    """Helper: returns True if goal is on positive x side."""
    return goal_x > 0
