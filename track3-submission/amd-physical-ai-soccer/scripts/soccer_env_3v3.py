"""multi-robot Soccer Environment — 6 robots in a single Genesis scene.

Extends SoccerEnvHierarchical to support 6 robot entities (3 left team + 3 right team)
in a SINGLE scene, not parallel envs. Left team uses RL policy, right team uses
rule-based policy. Each robot has its own walk model inference for locomotion.

Architecture:
    Left Team (RL):  3 robots → shared PPO policy → velocity commands → walk model → joints
    Right Team (Rule): 3 robots → rule-based chase → velocity commands → walk model → joints
    Ball: shared, single ball entity
    Kick: when robot is close to ball (< 0.3m), apply impulse toward goal
"""
from __future__ import annotations
import math, os, torch
import numpy as np
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

# Import parent env
try:
    from envs.soccer_env import SoccerEnv
except ImportError:
    from soccer_env_v4 import SoccerEnv

try:
    from rewards.reward import compute_reward
except ImportError:
    from reward import compute_reward

# Field constants
FIELD_L = 14.0
FIELD_W = 9.0
HALF_L = FIELD_L / 2
HALF_W = FIELD_W / 2
GOAL_W = 2.6
GOAL_HALF = GOAL_W / 2
BALL_R = 0.11
ROBOT_HEIGHT = 0.72

# 6 robot starting positions
# Left team (attacks +x): [attacker, defender, keeper]
LEFT_START = [(-1.0, 0.0), (-3.5, 1.5), (-6.5, 0.0)]
# Right team (attacks -x): [attacker, defender, keeper]
RIGHT_START = [(1.0, 0.0), (3.5, -1.5), (6.5, 0.0)]

DECIMATION = 10  # low-level physics substeps
PHYSICS_DT = 0.002


class SoccerEnv3v3(SoccerEnv):
    """multi-robot soccer environment with 6 robots in a single scene.

    The RL policy controls the left team (3 robots) with a shared policy.
    The right team uses a rule-based chase-ball policy.
    Each robot uses the frozen t1_walk.pt for locomotion.
    """

    def __init__(self, num_envs, env_cfg, obs_cfg, reward_cfg, command_cfg,
                 walk_model_path, high_level_decimation=5, show_viewer=False):
        self._hl_initialized = False
        self.high_level_decimation = high_level_decimation
        self.num_robots = 6  # 3 left + 3 right
        self.num_rl_robots = 3  # left team

        device = gs.device if gs is not None else "cpu"
        # High-level actions for left team (3 robots × 3 dims)
        self.hl_actions = torch.zeros((num_envs, 3, 3), dtype=gs.tc_float, device=device)
        self.last_hl_actions = torch.zeros((num_envs, 3, 3), dtype=gs.tc_float, device=device)

        # Call parent init — sets up physics, scene, buffers, calls reset()
        super().__init__(num_envs, env_cfg, obs_cfg, reward_cfg, command_cfg, show_viewer)

        self._hl_initialized = True
        self.num_actions = 3  # vx, vy, wz per robot
        self.hl_clip_lin = env_cfg.get("hl_clip_lin", 1.2)
        self.hl_clip_ang = env_cfg.get("hl_clip_ang", 1.2)
        self.high_level_dt = self.dt * high_level_decimation

        # High-level obs: 19 dims per robot, 3 robots = 57 dims
        # But we only run RL policy for 1 robot at a time (attacker),
        # so obs_buf is 19 dims
        self.hl_obs_dim = 19
        self.obs_buf = torch.empty((self.num_envs, 720),  # low-level obs for walk model
                                   dtype=gs.tc_float, device=self.device)

        # Load frozen walking model (shared across all robots)
        self.walk_model = safe_jit_load(walk_model_path, map_location=self.device)
        self.walk_model.eval()
        try:
            _norm = self.walk_model.obs_normalizer
            self._norm_mean = _norm._mean.to(self.device)
            self._norm_std = torch.clamp(_norm._std, min=1e-8).to(self.device)
            print(f"[multi-robot] Walk model normalizer loaded: mean={self._norm_mean.shape}")
        except Exception as e:
            self._norm_mean = None
            self._norm_std = None
            print(f"[multi-robot] Walk model normalizer not available: {e}")

        print(f"[multi-robot] Frozen walk model loaded from {walk_model_path}")
        print(f"[multi-robot] HL obs dim={self.hl_obs_dim}, HL action dim={self.num_actions}")
        print(f"[multi-robot] HL dt={self.high_level_dt:.3f}s, decimation={high_level_decimation}")
        print(f"[multi-robot] 6 robots (3 RL + 3 rule), 1 ball, single scene")

        # Per-robot buffers
        self._init_robot_buffers()

        # Kick cooldown
        self.kick_cooldown = torch.zeros((self.num_envs, self.num_robots),
                                          dtype=gs.tc_float, device=self.device)

        self._update_observation()
        self._m_goals = 0
        self._m_dist = 0.0
        self._m_steps = 0

    def _init_robot_buffers(self):
        """Initialize per-robot state buffers."""
        n = self.num_envs
        dev = self.device
        # Positions for all 6 robots
        self.all_base_pos = torch.zeros((n, self.num_robots, 3), dtype=gs.tc_float, device=dev)
        self.all_base_quat = torch.zeros((n, self.num_robots, 4), dtype=gs.tc_float, device=dev)
        self.all_base_euler = torch.zeros((n, self.num_robots, 3), dtype=gs.tc_float, device=dev)
        self.all_dof_pos = []
        self.all_dof_vel = []
        self.all_last_actions = []
        self.all_default_dof_pos = []

        # Initialize per-robot joint buffers
        for i in range(self.num_robots):
            robot = self.robots[i]
            motor_joints = [j for j in robot.joints[1:] if j.n_dofs > 0]
            motors_dof_idx = torch.tensor([j.dof_start for j in motor_joints],
                                          dtype=gs.tc_int, device=dev)
            base_dof_start = int(motors_dof_idx[0].item())
            num_motors = len(motor_joints)
            default_pos = robot.get_dofs_position(motors_dof_idx)[0].clone()
            actions_dof_idx = torch.argsort(motors_dof_idx)

            self.all_dof_pos.append(torch.zeros((n, num_motors), dtype=gs.tc_float, device=dev))
            self.all_dof_vel.append(torch.zeros((n, num_motors), dtype=gs.tc_float, device=dev))
            self.all_last_actions.append(torch.zeros((n, num_motors), dtype=gs.tc_float, device=dev))
            self.all_default_dof_pos.append(default_pos)

            # Set PD gains
            kp = self.cfg.get("kp", 200.0)
            kd = self.cfg.get("kd", 5.0)
            robot.set_dofs_kp([kp] * num_motors, motors_dof_idx)
            robot.set_dofs_kv([kd] * num_motors, motors_dof_idx)

            # Store per-robot metadata
            if not hasattr(self, '_robot_meta'):
                self._robot_meta = []
            self._robot_meta.append({
                'motor_joints': motor_joints,
                'motors_dof_idx': motors_dof_idx,
                'base_dof_start': base_dof_start,
                'num_motors': num_motors,
                'actions_dof_idx': actions_dof_idx,
            })

        # Filtered velocity for each robot (for observation)
        self.all_filtered_lin_vel = torch.zeros((n, self.num_robots, 3), dtype=gs.tc_float, device=dev)
        self.all_filtered_ang_vel = torch.zeros((n, self.num_robots, 3), dtype=gs.tc_float, device=dev)

        # Low-level obs history (10-frame × 72 dims = 720) for each robot
        self.all_obs_history = []
        for i in range(self.num_robots):
            obs_dim_per_frame = 72  # 3+3+3+21+21+21 (ang_vel, grav, cmd, dof_pos, dof_vel, last_act)
            self.all_obs_history.append(
                torch.zeros((n, 10, obs_dim_per_frame), dtype=gs.tc_float, device=dev)
            )

        # Last HL actions for each robot
        self.all_last_hl_actions = torch.zeros((n, self.num_robots, 3), dtype=gs.tc_float, device=dev)
        # Velocity commands for each robot
        self.all_commands = torch.zeros((n, self.num_robots, 3), dtype=gs.tc_float, device=dev)

    def _build_scene(self, show_viewer):
        """Build scene with 6 robots, ball, field, goals, camera."""
        self.scene = gs.Scene(
            sim_options=gs.options.SimOptions(dt=PHYSICS_DT, substeps=1),
            rigid_options=gs.options.RigidOptions(
                enable_self_collision=False, tolerance=1e-5, max_collision_pairs=256),
            viewer_options=gs.options.ViewerOptions(
                camera_pos=(0, -12, 8), camera_lookat=(0, 0, 0.5), camera_fov=50),
            vis_options=gs.options.VisOptions(
                rendered_envs_idx=[0],
                show_world_frame=False,
                show_link_frame=False,
                show_cameras=False,
                plane_reflection=True,
                ambient_light=(0.7, 0.7, 0.7),
                shadow=True,
            ),
            renderer=gs.renderers.Rasterizer(),
            show_viewer=show_viewer,
        )

        # Ground (single plane, no separate field boxes)
        self.scene.add_entity(
            gs.morphs.URDF(file=_genesis_asset("urdf", "plane", "plane.urdf"), fixed=True))

        # Minimal field: just 2 goal markers (no field line boxes to save GPU memory)
        _gs_s = gs.surfaces.Rough(color=(0.95, 0.95, 0.95), roughness=0.5)
        _pw2 = 0.1
        for gx in [-HALF_L, HALF_L]:
            self.scene.add_entity(morph=gs.morphs.Box(size=(_pw2, GOAL_W + _pw2, _pw2), pos=(gx, 0, 1.0), fixed=True), surface=_gs_s)

        # 6 robots
        robot_path = self.cfg["robot_urdf"]
        if not os.path.isabs(robot_path):
            ga = _genesis_asset(robot_path)
            robot_path = ga if os.path.exists(ga) else os.path.abspath(robot_path)

        self.robots = []
        all_starts = LEFT_START + RIGHT_START
        for i, (x, y) in enumerate(all_starts):
            if robot_path.endswith(".xml") or robot_path.endswith(".mjcf"):
                robot = self.scene.add_entity(
                    gs.morphs.MJCF(file=robot_path, pos=(x, y, ROBOT_HEIGHT)))
            else:
                robot = self.scene.add_entity(
                    gs.morphs.URDF(file=robot_path, pos=(x, y, ROBOT_HEIGHT),
                                  fixed=False, merge_fixed_links=False))
            self.robots.append(robot)

        # Ball
        ball_path = os.path.join(os.path.dirname(__file__), "..", "assets", "ball.urdf")
        if not os.path.exists(ball_path):
            ball_path = "/workspace/radeon-repo/assets/ball.urdf"
        if not os.path.exists(ball_path):
            ball_path = "/workspace/assets/ball.urdf"
        self.ball = self.scene.add_entity(gs.morphs.URDF(file=os.path.abspath(ball_path)))

        # Camera (broadcast angle)
        self.scene.add_camera(
            res=(1280, 720), pos=(0, -12, 8), lookat=(0, 0, 0.5), fov=50, GUI=False)

        self.scene.build(n_envs=self.num_envs)

    def _obs_dim(self):
        return 720  # low-level obs for walk model

    def _read_all_robot_states(self):
        """Read positions, quats, dof states for all 6 robots."""
        for i in range(self.num_robots):
            robot = self.robots[i]
            self.all_base_pos[:, i, :] = robot.get_pos()
            self.all_base_quat[:, i, :] = robot.get_quat()
            self.all_base_euler[:, i, :] = quat_to_xyz(
                transform_quat_by_quat(
                    inv_quat(torch.tensor([1.0, 0, 0, 0], device=self.device)),
                    robot.get_quat()), rpy=True, degrees=True)
            meta = self._robot_meta[i]
            self.all_dof_pos[i] = robot.get_dofs_position(meta['motors_dof_idx'])
            self.all_dof_vel[i] = robot.get_dofs_velocity(meta['motors_dof_idx'])

        # Ball
        self.ball_pos = self.ball.get_pos()
        self.ball_vel = self.ball.get_vel()

    def _compute_rl_obs(self, robot_idx=0):
        """Compute 19-dim high-level observation for RL robot (robot_idx=0 = attacker)."""
        pos = self.all_base_pos[:, robot_idx, :]
        quat = self.all_base_quat[:, robot_idx, :]
        lin_vel = self.all_filtered_lin_vel[:, robot_idx, :]
        ang_vel = self.all_filtered_ang_vel[:, robot_idx, :]
        last_actions = self.all_last_hl_actions[:, robot_idx, :]

        inv_bq = inv_quat(quat)

        # Ball relative to robot, body frame
        ball_rel = self.ball_pos - pos
        ball_rel_body = transform_by_quat(ball_rel, inv_bq)
        ball_vel_body = transform_by_quat(self.ball_vel, inv_bq)

        # Goal direction in body frame
        goal_pos = torch.zeros_like(pos)
        goal_pos[:, 0] = self.goal_x  # left team attacks +x
        goal_rel = goal_pos - pos
        goal_rel_body = transform_by_quat(goal_rel, inv_bq)
        goal_dist = torch.norm(goal_rel_body[:, :2], dim=1, keepdim=True)
        goal_dir = goal_rel_body[:, :2] / (goal_dist + 1e-6)

        dist_to_ball = torch.norm(ball_rel_body[:, :2], dim=1, keepdim=True)

        obs = torch.cat([
            lin_vel,                    # 3
            ang_vel,                    # 3
            transform_by_quat(          # 2 (projected gravity xy)
                torch.tensor([0.0, 0.0, -1.0], device=self.device).expand(self.num_envs, -1),
                inv_bq)[:, :2],
            ball_rel_body[:, :2],       # 2
            ball_vel_body[:, :2],       # 2
            dist_to_ball,               # 1
            goal_dir,                   # 2
            goal_dist,                  # 1
            last_actions,               # 3
        ], dim=-1)
        return obs

    def _compute_rule_actions(self, robot_idx):
        """Rule-based velocity command for right-team robots."""
        pos = self.all_base_pos[:, robot_idx, :].clone()
        ball_pos = self.ball_pos.clone()

        # Direction to ball
        to_ball = ball_pos[:, :2] - pos[:, :2]
        dist = torch.norm(to_ball, dim=1, keepdim=True) + 1e-6
        direction = to_ball / dist

        # Goal direction (right team attacks -x)
        goal_x = -self.goal_x  # negative for right team
        to_goal = torch.tensor([goal_x, 0.0], device=self.device).expand(self.num_envs, -1) - pos[:, :2]

        # Simple: move toward ball, if close move toward goal
        vx = torch.where(dist.squeeze(-1) > 0.3,
                        direction[:, 0] * 0.4,
                        torch.sign(to_goal[:, 0]) * 0.5)
        vy = torch.where(dist.squeeze(-1) > 0.3,
                        direction[:, 1] * 0.4,
                        to_goal[:, 1] * 0.3)
        wz = torch.where(dist.squeeze(-1) > 0.3,
                        torch.clamp(torch.atan2(to_ball[:, 1], to_ball[:, 0]) * 0.3, -0.5, 0.5),
                        torch.zeros_like(vx))

        actions = torch.stack([
            torch.clamp(vx, -self.hl_clip_lin, self.hl_clip_lin),
            torch.clamp(vy, -self.hl_clip_lin, self.hl_clip_lin),
            torch.clamp(wz, -self.hl_clip_ang, self.hl_clip_ang),
        ], dim=1)
        return actions

    def _build_low_level_obs_for_robot(self, robot_idx):
        """Build 720-dim observation for walk model of a specific robot."""
        i = robot_idx
        meta = self._robot_meta[i]
        pos = self.all_base_pos[:, i, :]
        quat = self.all_base_quat[:, i, :]
        dof_pos = self.all_dof_pos[i]
        dof_vel = self.all_dof_vel[i]
        last_act = self.all_last_actions[i]
        cmd = self.all_commands[:, i, :]
        default_pos = self.all_default_dof_pos[i]

        inv_bq = inv_quat(quat)
        lin_vel = self.all_filtered_lin_vel[:, i, :]
        ang_vel = self.all_filtered_ang_vel[:, i, :]
        grav = transform_by_quat(
            torch.tensor([0.0, 0.0, -1.0], device=self.device).expand(self.num_envs, -1), inv_bq)

        # 72-dim per frame: ang_vel(3) + grav(3) + cmd(3) + dof_pos(21) + dof_vel(21) + last_act(21)
        n_motors = meta['num_motors']
        per_frame = torch.cat([
            ang_vel * self.obs_scales["ang_vel"],         # 3
            grav,                                          # 3
            cmd,                                           # 3
            (dof_pos - default_pos) * self.obs_scales["dof_pos"],  # N
            dof_vel * self.obs_scales["dof_vel"],         # N
            last_act,                                     # N
        ], dim=-1)

        # Pad to 72 dims if needed
        if per_frame.shape[-1] < 72:
            pad = torch.zeros(self.num_envs, 72 - per_frame.shape[-1], device=self.device)
            per_frame = torch.cat([per_frame, pad], dim=-1)

        # 10-frame history
        self.all_obs_history[i] = torch.cat([self.all_obs_history[i][:, 1:], per_frame.unsqueeze(1)], dim=1)
        return self.all_obs_history[i].reshape(self.num_envs, -1)  # 720

    def _run_walk_model(self, obs_720):
        """Run frozen walking model."""
        with torch.no_grad():
            if self._norm_mean is not None:
                obs_normed = (obs_720 - self._norm_mean) / self._norm_std
            else:
                obs_normed = obs_720
            return self.walk_model.actor(obs_normed)

    def _low_level_step_robot(self, robot_idx, joint_actions):
        """Execute one low-level control step for a specific robot."""
        i = robot_idx
        robot = self.robots[i]
        meta = self._robot_meta[i]
        n_motors = meta['num_motors']

        actions = torch.clip(joint_actions, -self.clip_actions, self.clip_actions)
        exec_actions = self.all_last_actions[i] if self.simulate_action_latency else actions

        target_dof_pos = self.all_default_dof_pos[i].unsqueeze(0).expand(self.num_envs, -1).clone()
        policy_targets = exec_actions * self.action_scale + self.all_default_dof_pos[i].unsqueeze(0)
        # Only set the policy-controlled joints
        motor_start = meta['base_dof_start']
        robot.control_dofs_position(
            target_dof_pos[:, meta['actions_dof_idx']],
            slice(motor_start, motor_start + n_motors),
        )

        self.all_last_actions[i] = actions

    def _execute_kick(self, robot_idx):
        """Apply kick impulse to ball if robot is close enough."""
        i = robot_idx
        pos = self.all_base_pos[:, i, :]
        ball_pos = self.ball_pos

        dist = torch.norm(ball_pos[:, :2] - pos[:, :2], dim=1)
        can_kick = (dist < 0.3) & (self.kick_cooldown[:, i] < 0.01)

        if can_kick.any():
            # Kick direction: toward opponent goal
            if i < 3:  # left team attacks +x
                goal_x = self.goal_x
            else:  # right team attacks -x
                goal_x = -self.goal_x

            goal_dir = torch.stack([goal_x - pos[:, 0], -pos[:, 1]], dim=1)
            goal_dir_norm = goal_dir / (torch.norm(goal_dir, dim=1, keepdim=True) + 1e-6)
            impulse = goal_dir_norm * 3.0  # 3 m/s kick

            # Apply to ball velocity
            ball_qvel = self.ball.get_dofs_velocity().clone()
            ball_qvel[can_kick, 0] = impulse[can_kick, 0]
            ball_qvel[can_kick, 1] = impulse[can_kick, 1]
            ball_qvel[can_kick, 2] = 0.0
            self.ball.set_dofs_velocity(ball_qvel)
            self.kick_cooldown[can_kick, i] = 1.0

        self.kick_cooldown[:, i] = torch.clamp(
            self.kick_cooldown[:, i] - self.high_level_dt, min=0.0)

    def step(self, hl_actions):
        """High-level step: run all 6 robots for N low-level steps.

        Args:
            hl_actions: (num_envs, 3) velocity commands for RL robot (robot 0)
        """
        # Set RL robot commands (robot 0 = left attacker)
        rl_cmd = torch.stack([
            torch.clamp(hl_actions[:, 0], -self.hl_clip_lin, self.hl_clip_lin),
            torch.clamp(hl_actions[:, 1], -self.hl_clip_lin, self.hl_clip_lin),
            torch.clamp(hl_actions[:, 2], -self.hl_clip_ang, self.hl_clip_ang),
        ], dim=1)
        rl_cmd = torch.where(torch.abs(rl_cmd) < 0.05, torch.zeros_like(rl_cmd), rl_cmd)
        self.all_commands[:, 0, :] = rl_cmd
        self.all_last_hl_actions[:, 0, :] = self.hl_actions[:, 0, :].clone()
        self.hl_actions[:, 0, :] = rl_cmd

        # Left team robots 1,2: simple chase-ball rule
        for i in range(1, 3):
            cmd = self._compute_rule_actions(i)
            self.all_commands[:, i, :] = cmd
            self.all_last_hl_actions[:, i, :] = self.hl_actions[:, i, :].clone()
            self.hl_actions[:, i, :] = cmd

        # Right team: rule-based
        for i in range(3, 6):
            cmd = self._compute_rule_actions(i)
            self.all_commands[:, i, :] = cmd
            self.all_last_hl_actions[:, i, :] = self.hl_actions[:, i, :].clone()
            self.hl_actions[:, i, :] = cmd

        # Run N low-level steps
        for _ in range(self.high_level_decimation):
            for i in range(self.num_robots):
                low_obs = self._build_low_level_obs_for_robot(i)
                joint_actions = self._run_walk_model(low_obs)
                self._low_level_step_robot(i, joint_actions)

            for _ in range(DECIMATION):
                self.scene.step()

            self.episode_length_buf += 1
            self._read_all_robot_states()

            # Update filtered velocities
            fw = 0.3
            for i in range(self.num_robots):
                robot = self.robots[i]
                lin_vel = transform_by_quat(robot.get_vel(),
                    inv_quat(self.all_base_quat[:, i, :]))
                ang_vel = transform_by_quat(robot.get_ang(),
                    inv_quat(self.all_base_quat[:, i, :]))
                self.all_filtered_lin_vel[:, i, :] = lin_vel * fw + self.all_filtered_lin_vel[:, i, :] * (1 - fw)
                self.all_filtered_ang_vel[:, i, :] = ang_vel * fw + self.all_filtered_ang_vel[:, i, :] * (1 - fw)

                self.all_last_actions[i] = joint_actions

        # Kick logic for all robots
        for i in range(self.num_robots):
            self._execute_kick(i)

        # Build high-level observation for RL robot
        self._update_observation()

        # Compute reward (simplified)
        soccer = {
            "torso_up": torch.clamp(-transform_by_quat(
                torch.tensor([0.0, 0.0, -1.0], device=self.device).expand(self.num_envs, -1),
                inv_quat(self.all_base_quat[:, 0, :]))[:, 2], min=-1.0, max=1.0),
            "fallen": self.all_base_pos[:, 0, 2] < self.fall_height,
            "base_lin_vel_x": self.all_filtered_lin_vel[:, 0, 0],
            "ball_x": self.ball_pos[:, 0],
            "dist_to_ball": torch.norm(self.all_base_pos[:, 0, :2] - self.ball_pos[:, :2], dim=1),
            "prev_dist_to_ball": torch.norm(
                (self.all_base_pos[:, 0, :2] - self.ball_pos[:, :2]).clone(), dim=1),
            "ball_vel_to_goal": torch.sum(self.ball_vel[:, :2] *
                torch.stack([self.goal_x - self.ball_pos[:, 0],
                            -self.ball_pos[:, 1]], dim=1) /
                (torch.norm(torch.stack([self.goal_x - self.ball_pos[:, 0],
                            -self.ball_pos[:, 1]], dim=1), dim=1, keepdim=True) + 1e-6), dim=1),
            "scored": (self.ball_pos[:, 0] > self.goal_x) &
                      (torch.abs(self.ball_pos[:, 1]) < self.goal_half),
            "just_recovered": torch.zeros(self.num_envs, dtype=gs.tc_bool, device=self.device),
        }

        w = dict(self.reward_scales) if self.reward_scales else {"upright": 1.0, "alive": 0.1}
        w["_ball_radius"] = self.ball_radius
        w["dt"] = self.high_level_dt
        self.rew_buf = compute_reward(soccer, self.hl_actions[:, 0, :], w, "chase_hl")

        # Termination
        self.reset_buf = self.episode_length_buf > self.max_episode_length
        self.reset_buf |= soccer["scored"]
        for i in range(self.num_robots):
            self.reset_buf |= torch.abs(self.all_base_euler[:, i, 1]) > self.term_pitch
            self.reset_buf |= torch.abs(self.all_base_euler[:, i, 0]) > self.term_roll
        self.reset_buf |= self.scene.rigid_solver.get_error_envs_mask()
        self.extras = {"time_outs": (self.episode_length_buf > self.max_episode_length).to(dtype=gs.tc_float)}

        if self.reset_buf.any():
            self._reset_idx(self.reset_buf)

        obs_dict = TensorDict({"policy": self._compute_rl_obs(0)}, batch_size=[self.num_envs])
        return obs_dict, self.rew_buf, self.reset_buf, self.extras

    def _update_observation(self):
        """Update the observation buffer for RL robot."""
        if not self._hl_initialized:
            super()._update_observation()
            return
        self.obs_buf = self._compute_rl_obs(0)

    def get_observations(self):
        return TensorDict({"policy": self._compute_rl_obs(0)}, batch_size=[self.num_envs])

    def reset(self):
        self._reset_idx()
        self._read_all_robot_states()
        return self.get_observations()

    def _reset_idx(self, envs_idx=None):
        """Reset all robots to starting positions."""
        if envs_idx is None:
            # Reset all
            for i, robot in enumerate(self.robots):
                starts = LEFT_START + RIGHT_START
                x, y = starts[i]
                qpos = robot.get_qpos().clone()
                qpos[0, :3] = torch.tensor([x, y, ROBOT_HEIGHT], device=self.device)
                qpos[0, 3:7] = torch.tensor([1.0, 0, 0, 0], device=self.device)
                # Set default joint positions
                meta = self._robot_meta[i]
                motor_start = meta['base_dof_start']
                n_motors = meta['num_motors']
                qpos[0, motor_start:motor_start + n_motors] = self.all_default_dof_pos[i]
                robot.set_qpos(qpos, zero_velocity=True, skip_forward=True)

            # Reset ball to center
            ball_qpos = self.ball.get_qpos().clone()
            ball_qpos[0, :3] = torch.tensor([0.0, 0.0, BALL_R], device=self.device)
            ball_qpos[0, 3:7] = torch.tensor([1.0, 0, 0, 0], device=self.device)
            self.ball.set_qpos(ball_qpos, zero_velocity=True, skip_forward=True)

            # Reset buffers
            self.episode_length_buf.zero_()
            self.reset_buf.fill_(True)
            self.kick_cooldown.zero_()
            for i in range(self.num_robots):
                self.all_obs_history[i].zero_()
                self.all_last_actions[i].zero_()
                self.all_last_hl_actions[:, i, :].zero_()
                self.all_filtered_lin_vel[:, i, :].zero_()
                self.all_filtered_ang_vel[:, i, :].zero_()
        else:
            pass  # Partial reset not needed for rendering


def _genesis_asset(*parts):
    return os.path.join(os.path.dirname(gs.__file__), "assets", *parts)
