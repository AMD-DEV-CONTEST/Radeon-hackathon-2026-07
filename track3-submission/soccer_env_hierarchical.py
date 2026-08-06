"""Hierarchical soccer environment — frozen low-level walking + trainable high-level velocity policy.

Architecture:
    High-level PPO policy (19-dim obs → 3-dim action: vx, vy, wz)
        ↓ velocity commands injected into obs history
    Frozen t1_walk.pt (720-dim proprioception → 21-dim joint actions)
        ↓ PD control
    Genesis physics (AMD Radeon GPU)

The high-level policy can SEE the ball (ball position, velocity, goal direction
in body frame). The low-level frozen model only sees proprioception.

This solves the fundamental problem in v4: the RL policy had no ball info in its
720-dim observation but was rewarded for approaching the ball. With the hierarchical
split, the high-level policy directly observes ball state and outputs velocity
commands, while the frozen walking model handles balance and gait.
"""
from __future__ import annotations
import math, os, torch
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


try:
    import genesis as gs
except Exception:
    gs = None

try:
    from tensordict import TensorDict
except Exception:
    TensorDict = None

from genesis.utils.geom import inv_quat, quat_to_xyz, transform_by_quat, transform_quat_by_quat

# Import parent env (works both locally and on remote)
try:
    from envs.soccer_env import SoccerEnv, POLICY_JOINT_NAMES, DECIMATION, PHYSICS_DT
except ImportError:
    from soccer_env_v4 import SoccerEnv, POLICY_JOINT_NAMES, DECIMATION, PHYSICS_DT

# Import reward (works both locally and on remote)
try:
    from rewards.reward import compute_reward, compute_reward_components
except ImportError:
    from reward import compute_reward, compute_reward_components


class SoccerEnvHierarchical(SoccerEnv):
    """Hierarchical env: frozen t1_walk + trainable high-level velocity policy.

    High-level action: 3 dims [vx, vy, wz] ∈ [-1, 1]
    High-level obs: 19 dims (ball-aware, body frame)

    Low-level: frozen t1_walk.pt (720 → 21), runs at 50 Hz
    High-level: PPO, runs at 5–10 Hz (configurable via decimation)
    """

    def __init__(self, num_envs, env_cfg, obs_cfg, reward_cfg, command_cfg,
                 walk_model_path, high_level_decimation=5, show_viewer=False):
        # Pre-set flag so overridden methods behave correctly during super().__init__
        self._hl_initialized = False
        self.high_level_decimation = high_level_decimation

        # ── Strategy A: rule-walk fallback (bypass mismatched frozen t1_walk.pt) ──
        # When True, low-level actions come from a deterministic gait (static stance
        # when idle, phase-driven leg swing scaled by speed) instead of the frozen
        # walk model. This CANNOT tremble the way the mismatched model does.
        self.use_rule_walk = bool(env_cfg.get("use_rule_walk", False))
        self._rule_phase = 0.0
        self._rule_stride = float(env_cfg.get("rule_stride_period", 1.1))   # s per stride
        self._rule_step_amp = float(env_cfg.get("rule_step_amp", 0.16))     # rad (hip/knee)
        self._rule_lift_amp = float(env_cfg.get("rule_lift_amp", 0.22))     # rad (knee lift)
        self._rule_ankle_amp = float(env_cfg.get("rule_ankle_amp", 0.10))   # rad (ankle)

        # Pre-allocate high-level action buffers (needed by overridden _reset_idx)
        device = gs.device if gs is not None else "cpu"
        self.hl_actions = torch.zeros((num_envs, 3), dtype=gs.tc_float, device=device)
        self.last_hl_actions = torch.zeros((num_envs, 3), dtype=gs.tc_float, device=device)

        # Call parent init — sets up physics, scene, buffers, calls reset()
        super().__init__(num_envs, env_cfg, obs_cfg, reward_cfg, command_cfg, show_viewer)

        # === Override for high-level ===
        self._hl_initialized = True
        self.num_actions = 3                     # vx, vy, wz
        self.hl_clip_lin = env_cfg.get("hl_clip_lin", 0.8)  # Stage 2 default; yaml/CLI overridable
        self.hl_clip_ang = env_cfg.get("hl_clip_ang", 1.0)
        self.high_level_dt = self.dt * high_level_decimation

        # ── Opt-in multi-agent observation (19 → 24 dims) ───────────
        # OFF by default so the v6 checkpoint (19-dim) stays valid. When ON, the
        # multi-robot training harness must populate self.teammate_pos / self.opponent_pos
        # (world-frame xyz) each step before _update_observation(); see
        # _multiagent_extra(). The 5 extra dims are appended *after* the base 19,
        # so an old policy is untouched and a new one can be trained with them.
        self.use_multiagent_obs = bool(env_cfg.get("multiagent_obs", False))
        self.ma_teammate_dim = 2          # other 2 teammates
        self.ma_opponent_dim = 3         # 3 opponents
        self.ma_extra_dim = 5            # tm_rel(2) + opp_rel(2) + possession_flag(1)

        # Resize obs buffer for high-level (19, or 24 with multi-agent on)
        self.hl_obs_dim = 19 + (self.ma_extra_dim if self.use_multiagent_obs else 0)
        self.obs_buf = torch.empty((self.num_envs, self.hl_obs_dim),
                                   dtype=gs.tc_float, device=self.device)
        # Multi-agent position buffers (num_envs x K x 3). Set by the multi-robot harness;
        # start as None and default to zeros inside _multiagent_extra().
        self.teammate_pos = None
        self.opponent_pos = None

        # Load frozen walking model (skipped under Strategy A rule-walk fallback)
        self.walk_model = None
        self._norm_mean = None
        self._norm_std = None
        if self.use_rule_walk:
            print("[hierarchical] Strategy A: rule-walk fallback ENABLED — frozen walk model NOT loaded")
        elif walk_model_path:
            self.walk_model = safe_jit_load(walk_model_path, map_location=self.device)
            self.walk_model.eval()
            try:
                _norm = self.walk_model.obs_normalizer
                self._norm_mean = _norm._mean.to(self.device)
                self._norm_std = torch.clamp(_norm._std, min=1e-8).to(self.device)
                print(f"[hierarchical] Walk model normalizer loaded: mean={self._norm_mean.shape}")
            except Exception as e:
                self._norm_mean = None
                self._norm_std = None
                print(f"[hierarchical] Walk model normalizer not available: {e}")
            print(f"[hierarchical] Frozen walk model loaded from {walk_model_path}")
        else:
            print("[hierarchical] WARNING: no walk_model_path and rule-walk disabled")
        print(f"[hierarchical] HL obs dim={self.hl_obs_dim}, HL action dim={self.num_actions}")
        print(f"[hierarchical] HL dt={self.high_level_dt:.3f}s, decimation={high_level_decimation}")
        print(f"[hierarchical] HL clip: lin={self.hl_clip_lin} m/s, ang={self.hl_clip_ang} rad/s")

        # GPU-accumulated success metrics for tensorboard (flushed in step(), no per-step sync)
        self._m_goals = torch.zeros((), dtype=gs.tc_float, device=self.device)
        self._m_dist = torch.zeros((), dtype=gs.tc_float, device=self.device)
        self._m_steps = 0
    def set_curriculum_stage(self, clip_lin, clip_ang, task=None):
        """Switch curriculum stage: adjust action clip and optionally switch task."""
        self.hl_clip_lin = clip_lin
        self.hl_clip_ang = clip_ang
        if task is not None:
            self.task = task
        print(f"[curriculum] clip_lin={clip_lin}, clip_ang={clip_ang}, task={self.task}")


        # Re-update observation with high-level format
        self._update_observation()

    # ─── Public API ───────────────────────────────────────────────

    def _obs_dim(self):
        return self.hl_obs_dim

    def step(self, hl_actions):
        """High-level step: set velocity commands, run N low-level steps with frozen model.

        Args:
            hl_actions: (num_envs, 3) velocity commands [vx, vy, wz]
        Returns:
            obs, reward, done, extras (same as standard env interface)
        """
        # Clip and store high-level actions
        # Per-dimension clip (no filter)
        self.hl_actions = torch.stack([
            torch.clamp(hl_actions[:, 0], -self.hl_clip_lin, self.hl_clip_lin),
            torch.clamp(hl_actions[:, 1], -self.hl_clip_lin, self.hl_clip_lin),
            torch.clamp(hl_actions[:, 2], -self.hl_clip_ang, self.hl_clip_ang),
        ], dim=1)
        # Deadzone: commands below 0.05 are treated as zero (scaled up with clip range)
        self.hl_actions = torch.where(torch.abs(self.hl_actions) < 0.05, torch.zeros_like(self.hl_actions), self.hl_actions)
        self.commands[:] = self.hl_actions

        # Ensure obs_buf is 720-dim (from parent _update_observation)
        super(SoccerEnvHierarchical, self)._update_observation()

        # Run N low-level steps with frozen walking model
        for _ in range(self.high_level_decimation):
            low_obs = self._build_low_level_obs()      # 720-dim proprioception
            joint_actions = self._run_walk_model(low_obs)  # 21-dim joint targets
            self._low_level_step(joint_actions)

        # ── Compute high-level reward ──
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

        # Use high-level actions for reward (action_rate, energy)
        soccer["last_actions"] = self.last_hl_actions

        # ── Feed team-geometry into the coop (multi-robot) reward terms ──
        # Only when multiagent_obs is on (the multi-robot harness supplies teammate/
        # opponent positions). Harmless no-op otherwise — the coop terms are
        # inert unless these obs keys exist. Possession is computed here (from
        # current post-step positions) so the reward matches this step exactly.
        if self.use_multiagent_obs:
            gx = float(self.goal_x)
            self_xy = self.base_pos[:, :2]
            ball_xy = self.ball_pos[:, :2]
            attack_goal_xy = torch.full_like(self_xy, 0.0)
            attack_goal_xy[:, 0] = gx
            defend_goal_xy = torch.full_like(self_xy, 0.0)
            defend_goal_xy[:, 0] = -gx

            # Possession flag (mirror _multiagent_extra): +1 if I'm the chaser on
            # the controlling team, 0 if a teammate is, -1 if opponents are closer.
            self_ball = torch.norm((self.ball_pos - self.base_pos)[:, :2], dim=-1)
            if self.teammate_pos is not None:
                tm_ball = torch.norm((self.teammate_pos - self.ball_pos[:, None, :])[:, :, :2],
                                     dim=-1).min(dim=-1).values
            else:
                tm_ball = torch.full_like(self_ball, float("inf"))
            if self.opponent_pos is not None:
                op_ball = torch.norm((self.opponent_pos - self.ball_pos[:, None, :])[:, :, :2],
                                     dim=-1).min(dim=-1).values
            else:
                op_ball = torch.full_like(self_ball, float("inf"))
            team_min = torch.minimum(self_ball, tm_ball)
            in_possession = torch.where(
                team_min <= op_ball,
                torch.where(self_ball <= tm_ball, 1.0, 0.0),
                -1.0).unsqueeze(-1)

            soccer["self_xy"] = self_xy
            soccer["ball_xy"] = ball_xy
            soccer["attack_goal_xy"] = attack_goal_xy
            soccer["defend_goal_xy"] = defend_goal_xy
            soccer["in_possession"] = in_possession
            # Goal-credit: a ball in the attack goal is my team's score. The
            # harness may override with scored_my_team when goal-side is known.
            soccer["scored_my_team"] = soccer["scored"].float()

        self.rew_buf = compute_reward(soccer, self.hl_actions, w, self.task)
        reward_components = compute_reward_components(soccer, w, self.task)

        # ── Success metrics → extras["episode"] (rsl_rl logs these to tensorboard) ──
        # Accumulated on GPU, flushed every 10 HL steps — zero per-step sync cost.
        self._m_goals += soccer["scored"].float().sum()
        self._m_dist += soccer["dist_to_ball"].mean()
        self._m_steps += 1
        if self._m_steps >= 10:
            self.extras["episode"] = {
                "goal_per_1k_steps": (self._m_goals / (10.0 * self.num_envs) * 1000.0).item(),
                "mean_dist_to_ball": (self._m_dist / 10.0).item(),
                "goals_total": float(self.goals_scored),
            }
            self._m_goals.zero_()
            self._m_dist.zero_()
            self._m_steps = 0

        # Update prev_dist for next step
        self._resample_ball_if_needed()

        # Termination (episode_length_buf counts low-level steps, max_episode_length too)
        self.reset_buf = self.episode_length_buf > self.max_episode_length
        self.reset_buf |= soccer["scored"]  # episode ends on goal — no goal-camping, clean success stats
        self.reset_buf |= torch.abs(self.base_euler[:, 1]) > self.term_pitch
        self.reset_buf |= torch.abs(self.base_euler[:, 0]) > self.term_roll
        self.reset_buf |= self.scene.rigid_solver.get_error_envs_mask()
        self.extras["time_outs"] = (
            self.episode_length_buf > self.max_episode_length
        ).to(dtype=gs.tc_float)

        # Preserve the post-physics terminal observation before _reset_idx()
        # restores finished environments to their spawn state.  Consumers such
        # as the distributed worker can therefore report the state that caused
        # a fall/goal instead of the freshly reset pose.  Keep the scalar event
        # flags at the top level for compatibility with lightweight evaluators.
        terminal_done = self.reset_buf.detach().clone()
        self.extras["fallen"] = soccer["fallen"].detach().clone()
        self.extras["scored"] = soccer["scored"].detach().clone()
        self.extras["done"] = terminal_done
        self.extras["reward_components"] = {
            name: {field: value.detach().clone() for field, value in component.items()}
            for name, component in reward_components.items()
        }
        terminal_state = {
            "fallen": self.extras["fallen"].clone(),
            "scored": self.extras["scored"].clone(),
            "done": terminal_done.clone(),
            "base_pos": self.base_pos.detach().clone(),
            "base_euler": self.base_euler.detach().clone(),
            "ball_pos": self.ball_pos.detach().clone(),
            "ball_vel": self.ball_vel.detach().clone(),
        }
        self.extras["terminal_state"] = terminal_state
        # Keep the short alias for older local evaluators while making the
        # canonical contract explicit for new telemetry consumers.
        self.extras["terminal"] = terminal_state

        # Reset terminated envs
        self._reset_idx(self.reset_buf)

        # Build high-level observation
        self._update_observation()

        # Save last high-level actions
        self.last_hl_actions.copy_(self.hl_actions)
        self.fallen_prev.copy_(soccer["fallen"])

        return self.get_observations(), self.rew_buf, self.reset_buf, self.extras

    # ─── Low-level inference ──────────────────────────────────────

    def _build_low_level_obs(self):
        return self.obs_buf

    def _run_walk_model(self, obs_720):
        """Run frozen walking model: normalize obs → actor → 21-dim joint actions.

        Under Strategy A (use_rule_walk), the mismatched frozen model is bypassed
        and a deterministic gait is returned instead (no obs needed).
        """
        if self.use_rule_walk:
            return self._rule_walk_actions()
        with torch.no_grad():
            if self._norm_mean is not None:
                obs_normed = (obs_720 - self._norm_mean) / self._norm_std
            else:
                obs_normed = obs_720
            return self.walk_model.actor(obs_normed)

    def _rule_walk_actions(self):
        """Strategy A gait generator. Returns 21-dim joint actions in the SAME space
        as the frozen walk-model output (target = action*0.25 + policy_default_pos).

        - commands == 0 -> static standing stance (all zeros = default pose, rock steady)
        - commands != 0 -> phase-driven leg swing scaled by forward/side speed

        Fully deterministic, so it cannot 'tremble' like the mismatched RL model.
        Balance is preserved by small amplitudes + a double-support bias.
        """
        import math as _m
        actions = torch.zeros((self.num_envs, 21), dtype=gs.tc_float, device=self.device)
        vx = self.commands[:, 0]
        vy = self.commands[:, 1]
        wz = self.commands[:, 2]
        speed = torch.clamp(torch.sqrt(vx * vx + vy * vy), 0.0, 1.0)
        if float(speed.max()) < 0.03:
            return actions  # pure stance
        self._rule_phase = getattr(self, "_rule_phase", 0.0) + self.dt
        stride = getattr(self, "_rule_stride", 1.1)
        step_amp = getattr(self, "_rule_step_amp", 0.16)
        lift_amp = getattr(self, "_rule_lift_amp", 0.22)
        ank_amp = getattr(self, "_rule_ankle_amp", 0.10)
        phi = 2.0 * _m.pi * (self._rule_phase / stride)
        s = torch.sin(torch.tensor(phi, dtype=gs.tc_float, device=self.device))
        A_step = speed * step_amp
        A_lift = speed * lift_amp
        A_ank = speed * ank_amp
        sL = torch.where(s > 0, s, torch.zeros_like(s))
        sR = torch.where(s < 0, -s, torch.zeros_like(s))
        # Hip pitch: thrust swing leg forward, stance leg eases back slightly
        actions[:, 5] = A_step * (sL - 0.3 * sR)    # Left_Hip_Pitch
        actions[:, 6] = A_step * (sR - 0.3 * sL)    # Right_Hip_Pitch
        # Knee: lift the swinging foot
        actions[:, 15] = A_lift * sL                # Left_Knee_Pitch
        actions[:, 16] = A_lift * sR                # Right_Knee_Pitch
        # Ankle pitch: compensate to keep foot ~level
        actions[:, 17] = -A_ank * sL                # Left_Ankle_Pitch
        actions[:, 18] = -A_ank * sR                # Right_Ankle_Pitch
        # Hip/ankle roll: keep feet under CoM (tiny)
        actions[:, 9] = -0.05 * A_step * (sL - sR)  # Left_Hip_Roll
        actions[:, 10] = -0.05 * A_step * (sR - sL)  # Right_Hip_Roll
        actions[:, 19] = 0.05 * A_step * (sL - sR)  # Left_Ankle_Roll
        actions[:, 20] = 0.05 * A_step * (sR - sL)  # Right_Ankle_Roll
        # Turning (wz): gentle weight shift
        actions[:, 13] = 0.1 * wz                   # Left_Hip_Yaw
        actions[:, 14] = -0.1 * wz                  # Right_Hip_Yaw
        return actions

    def _low_level_step(self, joint_actions):
        """Execute one low-level control step (DECIMATION physics substeps)."""
        self.actions = torch.clip(joint_actions, -self.clip_actions, self.clip_actions)
        exec_actions = self.last_actions if self.simulate_action_latency else self.actions

        # Map 21 policy actions → 23 motor targets (head keeps default)
        target_dof_pos = self.default_dof_pos.unsqueeze(0).expand(self.num_envs, -1).clone()
        policy_targets = exec_actions * self.action_scale + self.policy_default_pos.unsqueeze(0)
        target_dof_pos[:, self.policy_joint_indices] = policy_targets

        self.robot.control_dofs_position(
            target_dof_pos[:, self.actions_dof_idx],
            slice(self.base_dof_start, self.base_dof_start + self.num_motors),
        )

        for _ in range(DECIMATION):
            self.scene.step()

        self.episode_length_buf += 1
        self._read_state()

        # Update low-level action history
        self.last_actions.copy_(self.actions)
        self.last_dof_vel.copy_(self.dof_vel)
        super(SoccerEnvHierarchical, self)._update_observation()

    # ─── High-level observation ───────────────────────────────────

    def _update_observation(self):
        """Build high-level observation: ball-aware, body-frame, 19 dims.

        Layout:
            filtered_lin_vel(3)    — robot velocity in body frame
            filtered_ang_vel(3)    — robot angular velocity in body frame
            projected_gravity(2)   — orientation indicator (xy)
            ball_rel_body(2)       — ball position relative to robot, body frame (xy)
            ball_vel_body(2)       — ball velocity in body frame (xy)
            dist_to_ball(1)        — Euclidean distance to ball
            goal_dir(2)            — goal direction in body frame (xy, normalized)
            goal_dist(1)           — distance to goal
            last_hl_actions(3)     — last velocity command [vx, vy, wz]
        """
        if not self._hl_initialized:
            # During parent __init__, use parent's observation
            super()._update_observation()
            return

        inv_bq = inv_quat(self.base_quat)

        # Ball position relative to robot, in body frame
        ball_rel = self.ball_pos - self.base_pos
        ball_rel_body = transform_by_quat(ball_rel, inv_bq)

        # Ball velocity in body frame
        ball_vel_body = transform_by_quat(self.ball_vel, inv_bq)

        # Goal direction in body frame
        goal_pos = torch.zeros_like(self.base_pos)
        goal_pos[:, 0] = self.goal_x
        goal_rel = goal_pos - self.base_pos
        goal_rel_body = transform_by_quat(goal_rel, inv_bq)
        goal_dist = torch.norm(goal_rel_body[:, :2], dim=1, keepdim=True)
        goal_dir = goal_rel_body[:, :2] / (goal_dist + 1e-6)

        # Distance to ball
        dist_to_ball = torch.norm(ball_rel_body[:, :2], dim=1, keepdim=True)

        self.obs_buf = torch.cat([
            self.filtered_lin_vel,              # 3
            self.filtered_ang_vel,             # 3
            self.projected_gravity[:, :2],     # 2
            ball_rel_body[:, :2],              # 2
            ball_vel_body[:, :2],              # 2
            dist_to_ball,                       # 1
            goal_dir,                           # 2
            goal_dist,                          # 1
            self.last_hl_actions,               # 3
        ], dim=-1)  # Total: 19

        # Append multi-agent features (teammates/opponents/possession) in-place
        # of the multi-robot training flag. No-op when multiagent_obs is False.
        if self.use_multiagent_obs:
            extra = self._multiagent_extra(inv_bq)
            self.obs_buf = torch.cat([self.obs_buf, extra], dim=-1)  # 24

    def _multiagent_extra(self, inv_bq):
        """Compute the 5-dim multi-agent extension in body frame.

        Reads ``self.teammate_pos`` (num_envs x 2 x 3) and ``self.opponent_pos``
        (num_envs x 3 x 3) — world-frame xyz of the *other* robots, set by the
        multi-robot training harness each step. Returns a (num_envs x 5) tensor:

            [tm_rel_x, tm_rel_y, opp_rel_x, opp_rel_y, possession_flag]

        where tm/opp rel are the body-frame xy of the *nearest* teammate /
        opponent, and possession_flag is +1 if this robot's team controls the
        ball, -1 if opponents do, 0 if loose. Mirrors
        ``match_3v3.multiagent_obs.compute_multiagent_features`` (numpy) 1:1.
        """
        if self.teammate_pos is None:
            self.teammate_pos = torch.zeros((self.num_envs, self.ma_teammate_dim, 3),
                                            dtype=gs.tc_float, device=self.device)
        if self.opponent_pos is None:
            self.opponent_pos = torch.zeros((self.num_envs, self.ma_opponent_dim, 3),
                                            dtype=gs.tc_float, device=self.device)

        # Nearest teammate relative position (body frame).
        tm_rel = self.teammate_pos - self.base_pos[:, None, :]      # num_envs x 2 x 3
        tm_body = transform_by_quat(tm_rel, inv_bq[:, None, :])     # num_envs x 2 x 3
        tm_dist = torch.norm(tm_body[:, :, :2], dim=-1)             # num_envs x 2
        tm_nearest = tm_body[torch.arange(self.num_envs),
                             torch.argmin(tm_dist, dim=-1), :2]     # num_envs x 2

        # Nearest opponent relative position (body frame).
        op_rel = self.opponent_pos - self.base_pos[:, None, :]
        op_body = transform_by_quat(op_rel, inv_bq[:, None, :])
        op_dist = torch.norm(op_body[:, :, :2], dim=-1)
        op_nearest = op_body[torch.arange(self.num_envs),
                             torch.argmin(op_dist, dim=-1), :2]

        # Possession flag: compare each team's closest robot to the ball.
        self_ball = torch.norm((self.ball_pos - self.base_pos)[:, :2], dim=-1)  # num_envs
        tm_ball = torch.norm((self.teammate_pos - self.ball_pos[:, None, :])[:, :, :2],
                             dim=-1).min(dim=-1).values                        # num_envs
        op_ball = torch.norm((self.opponent_pos - self.ball_pos[:, None, :])[:, :, :2],
                             dim=-1).min(dim=-1).values                        # num_envs
        team_min = torch.minimum(self_ball, tm_ball)
        flag = torch.where(team_min <= op_ball,       # my team closer to ball
                           torch.where(self_ball <= tm_ball, 1.0, 0.0),  # am I the chaser?
                           -1.0)                                         # opponents closer
        flag = flag.unsqueeze(-1)                                            # num_envs x 1

        return torch.cat([tm_nearest, op_nearest, flag], dim=-1)          # num_envs x 5

    # ─── Overrides for hierarchical behavior ──────────────────────

    def _resample_commands(self, envs_idx=None):
        """No-op: high-level policy provides velocity commands, not random sampling."""
        if not self._hl_initialized:
            super()._resample_commands(envs_idx)

    def _reset_idx(self, envs_idx=None):
        """Reset environments, zeroing high-level actions."""
        super()._reset_idx(envs_idx)
        if self._hl_initialized:
            if envs_idx is None:
                self.hl_actions.zero_()
                self.last_hl_actions.zero_()
            else:
                self.hl_actions.masked_fill_(envs_idx[:, None], 0.0)
                self.last_hl_actions.masked_fill_(envs_idx[:, None], 0.0)
