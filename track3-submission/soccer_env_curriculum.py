"""4-Phase Curriculum Soccer Environment for single-robot RL training.

Fixed 24-dim obs + 4-dim action throughout all phases.
Phase transitions handled by changing reward weights + opponent behavior.

Phases:
  P1 (0-200):    Basic navigation — no opponent, learn to reach ball
  P2 (200-450):  Weak opponent (0.1 m/s) — learn dribble + avoidance
  P3 (450-700):  Kick timing — 4th action dim triggers kick trajectory
  P4 (700-1000): Full confrontation — strong opponent (0.5 m/s), all skills

Obs (24 dims, fixed):
  [0-2]   filtered_lin_vel (body frame)
  [3-5]   filtered_ang_vel (body frame, estimated from yaw delta)
  [6-7]   projected_gravity xy
  [8-9]   ball_rel_body xy
  [10-11] ball_vel_body xy
  [12]    dist_to_ball
  [13-14] goal_dir xy (normalized)
  [15]    goal_dist
  [16-18] last_actions (vx, vy, wz)
  [19-20] opp_rel_body xy (P1: zeros, P2+: active)
  [21-22] opp_vel_body xy (P1: zeros, P2+: active)
  [23]    kick_cooldown (P1-P2: zero, P3+: active)

Action (4 dims, fixed):
  [0-2]   vx, vy, wz (velocity command)
  [3]     kick_trigger (P1-P2: ignored, P3+: when >0.5 and ball<0.3m, execute kick)
"""
from __future__ import annotations
import math, os, torch
try:
    import genesis as gs
except Exception:
    gs = None
from genesis.utils.geom import inv_quat, transform_by_quat
try:
    from envs.soccer_env_hierarchical import SoccerEnvHierarchical
except ImportError:
    from soccer_env_hierarchical import SoccerEnvHierarchical
try:
    from rewards.reward import compute_reward
except ImportError:
    from reward import compute_reward


class SoccerEnvCurriculum(SoccerEnvHierarchical):
    """4-phase curriculum environment with virtual opponent + kick mechanism."""

    def __init__(self, num_envs, env_cfg, obs_cfg, reward_cfg, command_cfg,
                 walk_model_path, high_level_decimation=5, show_viewer=False,
                 phase=0, opponent_speed=0.0, opponent_init_pos=(-3.0, 0.0)):
        self._is_curriculum = False
        self.phase = phase
        self.opponent_speed = opponent_speed
        self.opponent_init_xy = opponent_init_pos
        self._prev_yaw = None
        self.opp_prev_pos = None
        self.kick_cooldown = torch.zeros(num_envs, dtype=gs.tc_float, device="cpu")
        super().__init__(num_envs, env_cfg, obs_cfg, reward_cfg, command_cfg,
                         walk_model_path, high_level_decimation, show_viewer)
        self._is_curriculum = True
        self.hl_obs_dim = 24
        self.num_actions = 4
        self.obs_buf = torch.empty((self.num_envs, 24), dtype=gs.tc_float, device=self.device)
        self.opp_pos = torch.zeros((self.num_envs, 3), dtype=gs.tc_float, device=self.device)
        self.opp_pos[:, 0] = opponent_init_pos[0]
        self.opp_pos[:, 1] = opponent_init_pos[1]
        self.opp_pos[:, 2] = 0.7
        self.opp_vel = torch.zeros((self.num_envs, 3), dtype=gs.tc_float, device=self.device)
        self.kick_cooldown = torch.zeros(self.num_envs, dtype=gs.tc_float, device=self.device)
        print(f"[curriculum] Phase {phase}, opponent_speed={opponent_speed}, obs=24, action=4")

    def set_phase(self, phase, opponent_speed):
        """Switch curriculum phase at runtime."""
        self.phase = phase
        self.opponent_speed = opponent_speed
        print(f"[curriculum] Phase switched to {phase}, opponent_speed={opponent_speed}")

    def _obs_dim(self):
        return 24

    def _update_virtual_opponent(self):
        """Kinematic opponent: move toward ball at phase-dependent speed."""
        if self.opponent_speed < 0.01:
            self.opp_vel.zero_()
            return
        self.opp_prev_pos = self.opp_pos.clone()
        ball_rel = self.ball_pos[:, :2] - self.opp_pos[:, :2]
        dist = torch.norm(ball_rel, dim=1, keepdim=True) + 1e-6
        direction = ball_rel / dist
        move = torch.clamp(dist, max=self.opponent_speed * self.high_level_dt)
        self.opp_pos[:, 0] += direction[:, 0] * move.squeeze(-1)
        self.opp_pos[:, 1] += direction[:, 1] * move.squeeze(-1)
        self.opp_pos[:, 0] = torch.clamp(self.opp_pos[:, 0], -self.field_x/2+0.5, self.field_x/2-0.5)
        self.opp_pos[:, 1] = torch.clamp(self.opp_pos[:, 1], -self.field_y/2+0.5, self.field_y/2-0.5)
        if self.opp_prev_pos is not None:
            self.opp_vel[:, :2] = (self.opp_pos[:, :2] - self.opp_prev_pos[:, :2]) / self.high_level_dt

    def _execute_kick(self, kick_trigger, hl_actions):
        """If kick triggered and ball close, apply impulse to ball via physics engine."""
        if self.phase < 2:
            return
        kick_active = (kick_trigger > 0.5) & (self.kick_cooldown < 0.01)
        ball_close = torch.norm(self.ball_pos[:, :2] - self.base_pos[:, :2], dim=1) < 0.3
        can_kick = kick_active & ball_close
        if can_kick.any():
            # Apply impulse in the direction robot is facing (toward goal)
            goal_dir = torch.stack([self.goal_x - self.base_pos[:, 0],
                                    -self.base_pos[:, 1]], dim=1)
            goal_dir_norm = goal_dir / (torch.norm(goal_dir, dim=1, keepdim=True) + 1e-6)
            impulse = goal_dir_norm * 3.0  # 3 m/s kick impulse
            # Set ball velocity in PHYSICS ENGINE via set_dofs_velocity
            ball_qvel = self.ball.get_dofs_velocity()  # [N, 6] = [vx, vy, vz, wx, wy, wz]
            kick_qvel = ball_qvel.clone()
            kick_qvel[can_kick, 0] = impulse[can_kick, 0]
            kick_qvel[can_kick, 1] = impulse[can_kick, 1]
            kick_qvel[can_kick, 2] = 0.0
            self.ball.set_dofs_velocity(kick_qvel)
            self.kick_cooldown[can_kick] = 1.0  # 1 second cooldown
        self.kick_cooldown = torch.clamp(self.kick_cooldown - self.high_level_dt, min=0.0)

    def _soccer_state(self):
        state = super()._soccer_state()
        state["opp_pos"] = self.opp_pos
        state["opp_vel"] = self.opp_vel
        agent_ball_dist = state["dist_to_ball"]
        opp_ball_dist = torch.norm(self.opp_pos[:, :2] - self.ball_pos[:, :2], dim=1)
        state["opp_ball_dist"] = opp_ball_dist
        state["has_possession"] = (agent_ball_dist < opp_ball_dist).float()
        # Dribble: ball in front 0.2-0.5m and moving same direction as robot
        ball_rel = self.ball_pos[:, :2] - self.base_pos[:, :2]
        ball_in_front = (ball_rel[:, 0] > 0.15) & (ball_rel[:, 0] < 0.6)
        robot_vel_dir = self.filtered_lin_vel[:, :2]
        robot_vel_mag = torch.norm(robot_vel_dir, dim=1) + 1e-6
        ball_vel_mag = torch.norm(self.ball_vel[:, :2], dim=1)
        vel_aligned = (torch.sum(robot_vel_dir * self.ball_vel[:, :2], dim=1) /
                       (robot_vel_mag * ball_vel_mag + 1e-6)) > 0.3
        state["dribble_active"] = (ball_in_front & vel_aligned & (ball_vel_mag > 0.1)).float()
        # Kick success: ball velocity spike toward goal after kick
        ball_to_goal_vel = state["ball_vel_to_goal"]
        state["kick_success"] = ((ball_to_goal_vel > 2.0) & (self.kick_cooldown > 0.5)).float()
        return state

    def step(self, hl_actions):
        # Extract kick trigger (4th dim) if present
        if hl_actions.shape[-1] >= 4:
            kick_trigger = hl_actions[:, 3]
            vel_actions = hl_actions[:, :3]
        else:
            kick_trigger = torch.zeros_like(hl_actions[:, 0])
            vel_actions = hl_actions

        # Clip velocity commands
        self.hl_actions = torch.stack([
            torch.clamp(vel_actions[:, 0], -self.hl_clip_lin, self.hl_clip_lin),
            torch.clamp(vel_actions[:, 1], -self.hl_clip_lin, self.hl_clip_lin),
            torch.clamp(vel_actions[:, 2], -self.hl_clip_ang, self.hl_clip_ang),
        ], dim=1)
        self.hl_actions = torch.where(
            torch.abs(self.hl_actions) < 0.05,
            torch.zeros_like(self.hl_actions), self.hl_actions)
        self.commands[:] = self.hl_actions

        super(SoccerEnvHierarchical, self)._update_observation()

        # Execute kick BEFORE physics steps so engine processes the impulse
        self._execute_kick(kick_trigger, self.hl_actions)

        for _ in range(self.high_level_decimation):
            low_obs = self._build_low_level_obs()
            joint_actions = self._run_walk_model(low_obs)
            self._low_level_step(joint_actions)

        # Virtual opponent moves
        self._update_virtual_opponent()

        # Compute reward
        soccer = self._soccer_state()
        w = dict(self.reward_scales)
        w["_ball_radius"] = self.ball_radius
        w["dt"] = self.high_level_dt
        for _k in list(w.keys()):
            if isinstance(w[_k], (int, float)) and _k not in [
                "_ball_radius", "dt", "tracking_sigma", "swing_period",
                "only_positive_rewards", "fall_penalty", "recovery_bonus",
            ]:
                w[_k] *= self.high_level_dt
        soccer["last_actions"] = self.last_hl_actions
        self.rew_buf = compute_reward(soccer, self.hl_actions, w, self.task)

        # Phase-specific rewards
        dt = self.high_level_dt
        if self.phase >= 1:  # P2+: possession + dribble
            self.rew_buf += soccer["has_possession"] * 2.0 * dt
            self.rew_buf += soccer["dribble_active"] * 5.0 * dt
        if self.phase >= 2:  # P3+: kick
            self.rew_buf += soccer["kick_success"] * 15.0 * dt

        # Metrics
        self._m_goals += soccer["scored"].float().sum()
        self._m_dist += soccer["dist_to_ball"].mean()
        self._m_steps += 1
        if self._m_steps >= 10:
            self.extras["episode"] = {
                "goal_per_1k_steps": (self._m_goals / (10.0 * self.num_envs) * 1000.0).item(),
                "mean_dist_to_ball": (self._m_dist / 10.0).item(),
                "goals_total": float(self.goals_scored),
                "possession_rate": soccer["has_possession"].mean().item(),
                "dribble_rate": soccer["dribble_active"].mean().item() if self.phase >= 1 else 0.0,
                "kick_rate": soccer["kick_success"].mean().item() if self.phase >= 2 else 0.0,
                "phase": self.phase,
            }
            self._m_goals.zero_()
            self._m_dist.zero_()
            self._m_steps = 0

        self._resample_ball_if_needed()

        self.reset_buf = self.episode_length_buf > self.max_episode_length
        self.reset_buf |= soccer["scored"]
        self.reset_buf |= torch.abs(self.base_euler[:, 1]) > self.term_pitch
        self.reset_buf |= torch.abs(self.base_euler[:, 0]) > self.term_roll
        self.reset_buf |= self.scene.rigid_solver.get_error_envs_mask()
        self.extras["time_outs"] = (self.episode_length_buf > self.max_episode_length).to(dtype=gs.tc_float)

        self._reset_idx(self.reset_buf)
        self._update_observation()
        self.last_hl_actions.copy_(self.hl_actions)
        self.fallen_prev.copy_(soccer["fallen"])

        return self.get_observations(), self.rew_buf, self.reset_buf, self.extras

    def _update_observation(self):
        """Build 24-dim obs: 19 base + 2 opp pos + 2 opp vel + 1 kick cooldown."""
        if not self._is_curriculum:
            super()._update_observation()
            return

        inv_bq = inv_quat(self.base_quat)

        ball_rel = self.ball_pos - self.base_pos
        ball_rel_body = transform_by_quat(ball_rel, inv_bq)
        ball_vel_body = transform_by_quat(self.ball_vel, inv_bq)
        goal_pos = torch.zeros_like(self.base_pos)
        goal_pos[:, 0] = self.goal_x
        goal_rel = goal_pos - self.base_pos
        goal_rel_body = transform_by_quat(goal_rel, inv_bq)
        goal_dist = torch.norm(goal_rel_body[:, :2], dim=1, keepdim=True)
        goal_dir = goal_rel_body[:, :2] / (goal_dist + 1e-6)
        dist_to_ball = torch.norm(ball_rel_body[:, :2], dim=1, keepdim=True)

        # Opponent relative position (body frame)
        opp_rel = self.opp_pos - self.base_pos
        opp_rel_body = transform_by_quat(opp_rel, inv_bq)
        # Opponent velocity (body frame)
        opp_vel_body = transform_by_quat(self.opp_vel, inv_bq)

        self.obs_buf = torch.cat([
            self.filtered_lin_vel,              # 0-2
            self.filtered_ang_vel,              # 3-5
            self.projected_gravity[:, :2],      # 6-7
            ball_rel_body[:, :2],               # 8-9
            ball_vel_body[:, :2],               # 10-11
            dist_to_ball,                        # 12
            goal_dir,                            # 13-14
            goal_dist,                           # 15
            self.last_hl_actions,                # 16-18
            opp_rel_body[:, :2],                 # 19-20
            opp_vel_body[:, :2],                 # 21-22
            self.kick_cooldown.unsqueeze(-1),    # 23
        ], dim=-1)  # Total: 24

    def _get_yaw(self):
        """Extract yaw from base_quat."""
        w, x, y, z = self.base_quat[:, 0], self.base_quat[:, 1], self.base_quat[:, 2], self.base_quat[:, 3]
        return torch.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))

    def _reset_idx(self, envs_idx=None):
        super()._reset_idx(envs_idx)
        if self._is_curriculum:
            if envs_idx is None:
                self.opp_pos[:, 0] = self.opponent_init_xy[0]
                self.opp_pos[:, 1] = self.opponent_init_xy[1]
                self.opp_pos[:, 2] = 0.7
                self.opp_vel.zero_()
                self.kick_cooldown.zero_()
            else:
                self.opp_pos[envs_idx, 0] = self.opponent_init_xy[0]
                self.opp_pos[envs_idx, 1] = self.opponent_init_xy[1]
                self.opp_pos[envs_idx, 2] = 0.7
                self.opp_vel[envs_idx].zero_()
                self.kick_cooldown[envs_idx].zero_()
