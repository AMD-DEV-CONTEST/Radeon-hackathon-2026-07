"""Genesis humanoid-soccer environment (headless, GPU-batched on AMD Radeon).

Written against the verified Genesis RL API (see examples/locomotion/go2_env.py):
    gs.init(backend=gs.gpu, ...)
    gs.Scene(...) + gs.morphs.URDF(...) + scene.build(n_envs=...)
    robot.set_dofs_kp/kv, robot.control_dofs_position, robot.get_dofs_position/velocity
    OnPolicyRunner(env, train_cfg, log_dir, device=gs.device).learn(...)

Design anchored on Booster multi-robot (RoBoLeague): a humanoid must stay upright,
chase, dribble and shoot a ball into a goal on a simplified pitch. The robot
URDF is CONFIG-DRIVEN so any biped (Unitree H1, or a T1-like model later)
works without editing this file. Motor DOFs are auto-discovered from the
loaded robot, so you never hardcode joint names.

Reward terms come from rewards/reward.py (Booster sub-task curriculum):
    balance -> chase -> dribble -> shoot -> coop

Run on the AMD Radeon Linux cloud instance. On macOS this file is import-safe
(genesis/tensordict are optional) so it can be edited, but it will not run.
"""
from __future__ import annotations

import math
import os

import torch

try:
    import genesis as gs
except Exception:  # pragma: no cover - allows editing on macOS
    gs = None

try:
    from tensordict import TensorDict
except Exception:  # pragma: no cover
    TensorDict = None

from genesis.utils.geom import (
    inv_quat,
    quat_to_xyz,
    transform_by_quat,
    transform_quat_by_quat,
)

from rewards.reward import compute_reward


def gs_rand(lower, upper, batch_shape):
    assert lower.shape == upper.shape
    return (upper - lower) * torch.rand(size=(*batch_shape, *lower.shape), dtype=gs.tc_float, device=gs.device) + lower


# asset dir of the installed genesis package (robots like H1 live here)
def _genesis_asset(*parts):
    return os.path.join(os.path.dirname(gs.__file__), "assets", *parts)


class SoccerEnv:
    def __init__(self, num_envs, env_cfg, obs_cfg, reward_cfg, command_cfg, show_viewer=False):
        if gs is None:
            raise RuntimeError("Genesis not available. Run on the AMD Radeon Linux instance.")
        self.num_envs = num_envs
        self.device = gs.device
        self.cfg = env_cfg
        self.obs_cfg = obs_cfg
        self.reward_cfg = reward_cfg
        self.command_cfg = command_cfg
        self.task = env_cfg.get("task", "chase")
        self.distill_logger = None  # set by train.py to record Booster-distillation observables

        self.dt = env_cfg["dt"]
        self.substeps = env_cfg["substeps"]
        self.max_episode_length = math.ceil(env_cfg["episode_length_s"] / self.dt)
        self.action_scale = env_cfg["action_scale"]
        self.clip_actions = env_cfg["clip_actions"]
        self.simulate_action_latency = env_cfg.get("simulate_action_latency", True)

        # soccer field geometry
        self.ball_radius = env_cfg["ball_radius"]
        self.field_x, self.field_y = env_cfg["field"]
        self.goal_half = env_cfg["goal_width"] / 2.0
        self.goal_x = self.field_x / 2.0
        self.circle_radius = env_cfg.get("circle_radius", 1.5)
        self.fall_height = env_cfg["fall_height"]
        self.term_pitch = math.radians(env_cfg["termination_pitch_deg"])
        self.term_roll = math.radians(env_cfg["termination_roll_deg"])

        self.obs_history_length = env_cfg.get("obs_history_length", 10)
        self.obs_scales = obs_cfg["obs_scales"]
        self.reward_scales = reward_cfg  # weights consumed by rewards/reward.py

        self._build_scene(show_viewer)

        # ---------- auto-discover motor DOFs from loaded robot ----------
        # Genesis: robot.joints[0] is the floating base (6 DOF); the rest are motors.
        self.motor_joints = [j for j in self.robot.joints[1:] if j.n_dofs > 0]
        self.motors_dof_idx = torch.tensor(
            [j.dof_start for j in self.motor_joints], dtype=gs.tc_int, device=self.device
        )
        # base DOF count varies (free base is usually 6, sometimes 7); derive it so the
        # motor control slice is correct for any robot without hardcoding.
        self.base_dof_start = int(self.motors_dof_idx[0].item())
        self.num_actions = len(self.motor_joints)
        # default standing pose = the URDF's default joint angles
        # get_dofs_position returns (num_envs, num_actions); take [0] for init template
        self.default_dof_pos = self.robot.get_dofs_position(self.motors_dof_idx)[0].clone()
        self.actions_dof_idx = torch.argsort(self.motors_dof_idx)

        # PD gains
        kp = env_cfg.get("kp", 35.0)
        kd = env_cfg.get("kd", 0.7)
        self.robot.set_dofs_kp([kp] * self.num_actions, self.motors_dof_idx)
        self.robot.set_dofs_kv([kd] * self.num_actions, self.motors_dof_idx)

        # goal direction command (constant): tells the policy which way to shoot
        self.command = torch.tensor(
            command_cfg.get("goal_dir", [1.0, 0.0, 0.0]), dtype=gs.tc_float, device=self.device
        ).expand(self.num_envs, -1).clone()

        # ---------- buffers ----------
        self.global_gravity = torch.tensor([0.0, 0.0, -1.0], dtype=gs.tc_float, device=self.device)
        self.init_base_pos = torch.tensor(env_cfg["base_init_pos"], dtype=gs.tc_float, device=self.device)
        self.init_base_quat = torch.tensor(env_cfg["base_init_quat"], dtype=gs.tc_float, device=self.device)
        self.inv_base_init_quat = inv_quat(self.init_base_quat)
        base_dof = torch.cat([self.init_base_pos, self.init_base_quat])
        # build init_qpos from robot's actual qpos (handles different base DOF)
        qpos_template = self.robot.get_qpos()[0].clone()
        qpos_template[self.base_dof_start:self.base_dof_start + self.num_actions] = self.default_dof_pos
        self.init_qpos = qpos_template.unsqueeze(0).expand(self.num_envs, -1).clone()
        self.init_projected_gravity = transform_by_quat(self.global_gravity, self.inv_base_init_quat)

        self.base_lin_vel = torch.empty((self.num_envs, 3), dtype=gs.tc_float, device=self.device)
        self.base_ang_vel = torch.empty((self.num_envs, 3), dtype=gs.tc_float, device=self.device)
        self.projected_gravity = torch.empty((self.num_envs, 3), dtype=gs.tc_float, device=self.device)
        self.rew_buf = torch.empty((self.num_envs,), dtype=gs.tc_float, device=self.device)
        self.reset_buf = torch.ones((self.num_envs,), dtype=gs.tc_bool, device=self.device)
        self.episode_length_buf = torch.empty((self.num_envs,), dtype=gs.tc_int, device=self.device)
        self.actions = torch.zeros((self.num_envs, self.num_actions), dtype=gs.tc_float, device=self.device)
        self.last_actions = torch.zeros_like(self.actions)
        self.dof_pos = torch.empty_like(self.actions)
        self.dof_vel = torch.empty_like(self.actions)
        self.last_dof_vel = torch.zeros_like(self.actions)

        # obs history buffer for booster_deploy compatibility (10-frame stacking)
        self.obs_dim = 3 + 3 + 3 + self.num_actions + self.num_actions + self.num_actions  # base obs without ball
        self.obs_history = torch.zeros((self.num_envs, self.obs_history_length, self.obs_dim), dtype=gs.tc_float, device=self.device)
        self.base_pos = torch.empty((self.num_envs, 3), dtype=gs.tc_float, device=self.device)
        self.base_quat = torch.empty((self.num_envs, 4), dtype=gs.tc_float, device=self.device)
        self.base_euler = torch.empty((self.num_envs, 3), dtype=gs.tc_float, device=self.device)
        self.ball_pos = torch.empty((self.num_envs, 3), dtype=gs.tc_float, device=self.device)
        self.ball_vel = torch.empty((self.num_envs, 3), dtype=gs.tc_float, device=self.device)
        self.ball_prev_pos = torch.empty_like(self.ball_pos)
        self.prev_dist_to_ball = torch.empty((self.num_envs,), dtype=gs.tc_float, device=self.device)
        self.fallen_prev = torch.zeros((self.num_envs,), dtype=gs.tc_bool, device=self.device)
        self.scored_buf = torch.zeros((self.num_envs,), dtype=gs.tc_float, device=self.device)
        # 射门统计：射正率 / 进球率
        self.shots_taken = 0
        self.shots_on_target = 0
        self.goals_scored = 0
        self.shot_prev_vel = torch.zeros((self.num_envs,), dtype=gs.tc_float, device=self.device)
        self.obs_buf = torch.empty((self.num_envs, self._obs_dim()), dtype=gs.tc_float, device=self.device)
        self.extras = dict()

        self.reset()

    # ---------------------------------------------------------------- scene
    def _build_scene(self, show_viewer):
        # NOTE: gs.init() is called ONCE by the training/eval entrypoint, not here.
        self.scene = gs.Scene(
            sim_options=gs.options.SimOptions(dt=self.dt, substeps=self.substeps),
            rigid_options=gs.options.RigidOptions(
                enable_self_collision=True,
                tolerance=1e-5,
                max_collision_pairs=512,
            ),
            viewer_options=gs.options.ViewerOptions(
                camera_pos=(6.0, 6.0, 4.0),
                camera_lookat=(0.0, 0.0, 0.5),
                camera_fov=40,
            ),
            vis_options=gs.options.VisOptions(rendered_envs_idx=[0]),
            show_viewer=show_viewer,
        )

        # ground plane (Genesis ships a plane URDF)
        self.scene.add_entity(
            gs.morphs.URDF(file=_genesis_asset("urdf", "plane", "plane.urdf"), fixed=True)
        )

        # humanoid robot (CONFIG-DRIVEN path; auto-detect URDF vs MJCF)
        robot_path = self.cfg["robot_urdf"]
        if not os.path.isabs(robot_path):
            # try genesis assets dir first, then project-relative
            ga = _genesis_asset(robot_path)
            robot_path = ga if os.path.exists(ga) else os.path.abspath(robot_path)
        if robot_path.endswith(".xml") or robot_path.endswith(".mjcf"):
            self.robot = self.scene.add_entity(
                gs.morphs.MJCF(file=robot_path, pos=self.cfg["base_init_pos"], quat=self.cfg["base_init_quat"])
            )
        else:
            self.robot = self.scene.add_entity(
                gs.morphs.URDF(file=robot_path, pos=self.cfg["base_init_pos"], quat=self.cfg["base_init_quat"])
            )

        # ball (sphere URDF shipped in this repo: assets/ball.urdf)
        ball_path = os.path.join(os.path.dirname(__file__), "..", "assets", "ball.urdf")
        self.ball = self.scene.add_entity(gs.morphs.URDF(file=os.path.abspath(ball_path)))

        # goal marker (thin flat box for the demo video legibility)
        goal_path = os.path.join(os.path.dirname(__file__), "..", "assets", "goal.urdf")
        self.scene.add_entity(
            gs.morphs.URDF(
                file=os.path.abspath(goal_path),
                pos=[self.goal_x, 0.0, 0.03],
                fixed=True,
            )
        )

        # Add recording camera (before scene.build)
        self.scene.add_camera(
            res=(960, 540),
            pos=(4.0, -6.0, 3.0),
            lookat=(0.0, 0.0, 0.5),
            fov=60,
            GUI=False,
        )
        self.scene.build(n_envs=self.num_envs)

    def _obs_dim(self):
        n = self.num_actions
        return 3 + 3 + 3 + n + n + 3 + 3 + n  # ang_vel, grav, cmd, dof_pos, dof_vel, ball_rel, ball_relvel, act

    def get_stats(self):
        """返回射门统计：射正率、进球率、总射门数。"""
        on_target_rate = self.shots_on_target / max(self.shots_taken, 1)
        goal_rate = self.goals_scored / max(self.shots_taken, 1)
        return {
            "shots_taken": self.shots_taken,
            "shots_on_target": self.shots_on_target,
            "goals_scored": self.goals_scored,
            "on_target_rate": on_target_rate,
            "goal_rate": goal_rate,
        }

    # ---------------------------------------------------------------- RL API
    def reset(self):
        self._reset_idx()
        self._update_observation()
        return self.get_observations()

    def step(self, actions):
        self.actions = torch.clip(actions, -self.clip_actions, self.clip_actions)
        exec_actions = self.last_actions if self.simulate_action_latency else self.actions
        target_dof_pos = exec_actions * self.action_scale + self.default_dof_pos
        self.robot.control_dofs_position(
            target_dof_pos[:, self.actions_dof_idx],
            slice(self.base_dof_start, self.base_dof_start + self.num_actions),
        )
        self.scene.step()

        self.episode_length_buf += 1
        self._read_state()

        # soccer-specific state for the reward module
        soccer = self._soccer_state()

        # distillation bridge: record observables for Booster heuristic extraction (optional).
        # Guarded so it never affects training; only active when train.py sets env.distill_logger.
        if self.distill_logger is not None:
            try:
                from bridge.genesis_logger import record_step
                record_step(self.distill_logger, self, soccer)
            except Exception:
                pass

        w = dict(self.reward_scales)
        w["_ball_radius"] = self.ball_radius
        self.rew_buf = compute_reward(soccer, self.actions, w, self.task)

        self._resample_ball_if_needed()
        self.reset_buf = self.episode_length_buf > self.max_episode_length
        self.reset_buf |= torch.abs(self.base_euler[:, 1]) > self.term_pitch
        self.reset_buf |= torch.abs(self.base_euler[:, 0]) > self.term_roll
        self.reset_buf |= self.scene.rigid_solver.get_error_envs_mask()
        self.extras["time_outs"] = (self.episode_length_buf > self.max_episode_length).to(dtype=gs.tc_float)

        self._reset_idx(self.reset_buf)
        self._update_observation()
        self.last_actions.copy_(self.actions)
        self.last_dof_vel.copy_(self.dof_vel)
        self.fallen_prev.copy_(soccer["fallen"])
        return self.get_observations(), self.rew_buf, self.reset_buf, self.extras

    def get_observations(self):
        return TensorDict({"policy": self.obs_buf}, batch_size=[self.num_envs])

    # ---------------------------------------------------------------- state
    def _read_state(self):
        self.base_pos = self.robot.get_pos()
        self.base_quat = self.robot.get_quat()
        self.base_euler = quat_to_xyz(
            transform_quat_by_quat(self.inv_base_init_quat, self.base_quat), rpy=True, degrees=True
        )
        inv_base_quat = inv_quat(self.base_quat)
        self.base_lin_vel = transform_by_quat(self.robot.get_vel(), inv_base_quat)
        self.base_ang_vel = transform_by_quat(self.robot.get_ang(), inv_base_quat)
        self.projected_gravity = transform_by_quat(self.global_gravity, inv_base_quat)
        self.dof_pos = self.robot.get_dofs_position(self.motors_dof_idx)
        self.dof_vel = self.robot.get_dofs_velocity(self.motors_dof_idx)
        self.ball_pos = self.ball.get_pos()
        self.ball_vel = self.ball.get_vel()

    def _soccer_state(self):
        torso_up = torch.clamp(-self.projected_gravity[:, 2], min=-1.0, max=1.0)
        fallen = (self.base_pos[:, 2] < self.fall_height) | (torch.abs(self.base_euler[:, 1]) > 45) | (
            torch.abs(self.base_euler[:, 0]) > 45
        )
        dist_to_ball = torch.norm(self.base_pos[:, :2] - self.ball_pos[:, :2], dim=1)
        goal_dir = torch.stack(
            [self.goal_x - self.ball_pos[:, 0], -self.ball_pos[:, 1], torch.zeros_like(self.ball_pos[:, 0])], dim=1
        )
        goal_dir = goal_dir / (torch.norm(goal_dir, dim=1, keepdim=True) + 1e-6)
        ball_vel_to_goal = torch.sum(self.ball_vel[:, :2] * goal_dir[:, :2], dim=1)
        scored = (self.ball_pos[:, 0] > self.goal_x) & (torch.abs(self.ball_pos[:, 1]) < self.goal_half)
        just_recovered = self.fallen_prev & (~fallen)

        # 射门统计：检测射门瞬间（球速突然增大且朝向球门）
        # 射门触发：上一帧没在射门，这帧球速 > 1.0 m/s 且朝向球门
        shooting_now = (ball_vel_to_goal > 1.0) & (self.shot_prev_vel < 1.0)
        for i in range(self.num_envs):
            if shooting_now[i]:
                self.shots_taken += 1
                # 射正：球 y 坐标在门宽内
                if abs(self.ball_pos[i, 1].item()) < self.goal_half:
                    self.shots_on_target += 1
        # 进球
        for i in range(self.num_envs):
            if scored[i] and self.shot_prev_vel[i] > 0.5:
                self.goals_scored += 1
        self.shot_prev_vel.copy_(ball_vel_to_goal)

        return {
            "torso_up": torso_up,
            "fallen": fallen,
            "base_lin_vel_x": self.base_lin_vel[:, 0],
            "ball_x": self.ball_pos[:, 0],
            "dist_to_ball": dist_to_ball,
            "prev_dist_to_ball": self.prev_dist_to_ball,
            "ball_vel_to_goal": ball_vel_to_goal,
            "scored": scored,
            "just_recovered": just_recovered,
        }

    def _resample_ball_if_needed(self):
        # keep the previous distance for the dense approach reward, then update
        self.prev_dist_to_ball = torch.norm(self.base_pos[:, :2] - self.ball_pos[:, :2], dim=1).clone()

    def _reset_idx(self, envs_idx=None):
        # robot
        self.robot.set_qpos(self.init_qpos, envs_idx=envs_idx, zero_velocity=True, skip_forward=True)
        # ball: random start, at least 1.5 m from the robot
        ball_qpos = self._sample_ball_qpos()
        self.ball.set_qpos(ball_qpos, envs_idx=envs_idx, zero_velocity=True, skip_forward=True)

        if envs_idx is None:
            self.base_pos.copy_(self.init_base_pos)
            self.base_quat.copy_(self.init_base_quat)
            self.projected_gravity.copy_(self.init_projected_gravity)
            self.dof_pos.copy_(self.default_dof_pos)
            self.base_lin_vel.zero_()
            self.base_ang_vel.zero_()
            self.dof_vel.zero_()
            self.actions.zero_()
            self.last_actions.zero_()
            self.last_dof_vel.zero_()
            self.obs_history.zero_()
            self.episode_length_buf.zero_()
            self.reset_buf.fill_(True)
            self.fallen_prev.zero_()
            self.scored_buf.zero_()
        else:
            torch.where(envs_idx[:, None], self.init_base_pos, self.base_pos, out=self.base_pos)
            torch.where(envs_idx[:, None], self.init_base_quat, self.base_quat, out=self.base_quat)
            torch.where(envs_idx[:, None], self.init_projected_gravity, self.projected_gravity, out=self.projected_gravity)
            torch.where(envs_idx[:, None], self.default_dof_pos, self.dof_pos, out=self.dof_pos)
            self.base_lin_vel.masked_fill_(envs_idx[:, None], 0.0)
            self.base_ang_vel.masked_fill_(envs_idx[:, None], 0.0)
            self.dof_vel.masked_fill_(envs_idx[:, None], 0.0)
            self.actions.masked_fill_(envs_idx[:, None], 0.0)
            self.last_actions.masked_fill_(envs_idx[:, None], 0.0)
            self.last_dof_vel.masked_fill_(envs_idx[:, None], 0.0)
            self.episode_length_buf.masked_fill_(envs_idx, 0)
            self.reset_buf.masked_fill_(envs_idx, True)
            self.fallen_prev.masked_fill_(envs_idx, False)
            self.scored_buf.masked_fill_(envs_idx, 0.0)

        self._read_state()
        self.prev_dist_to_ball = torch.norm(self.base_pos[:, :2] - self.ball_pos[:, :2], dim=1).clone()
        self._resample_commands(envs_idx)

    def _sample_ball_qpos(self):
        lo = torch.tensor([-self.field_x / 2 + 0.5, -self.goal_half, self.ball_radius], device=self.device)
        hi = torch.tensor([self.goal_x - 1.0, self.goal_half, self.ball_radius], device=self.device)
        pos = gs_rand(lo, hi, (self.num_envs,))
        quat = torch.zeros((self.num_envs, 4), device=self.device)
        quat[:, 0] = 1.0
        return torch.cat([pos, quat], dim=1)

    def _resample_commands(self, envs_idx):
        if envs_idx is None:
            self.commands = self.command.clone()
        else:
            torch.where(envs_idx[:, None], self.command, self.commands, out=self.commands)

    def _update_observation(self):
        # Base observation matching booster_deploy T1 walk contract:
        # [ang_vel(3), projected_gravity(3), commands(3), dof_pos-default(N), dof_vel*scale(N), last_action(N)]
        base_obs = torch.cat(
            (
                self.base_ang_vel * self.obs_scales["ang_vel"],       # 3
                self.projected_gravity,                                # 3
                self.commands,                                        # 3
                (self.dof_pos - self.default_dof_pos) * self.obs_scales["dof_pos"],  # N
                self.dof_vel * self.obs_scales["dof_vel"],             # N
                self.last_actions,                                    # N
            ),
            dim=-1,
        )
        # Update history: shift left, append new obs
        self.obs_history = torch.cat([self.obs_history[:, 1:], base_obs.unsqueeze(1)], dim=1)

        # Policy obs = flattened history + ball info (ball info is soccer-specific, not in booster_deploy)
        self.obs_buf = torch.cat(
            (
                self.obs_history.reshape(self.num_envs, -1),           # base_obs × history_length
                (self.ball_pos - self.base_pos) * 2.0,                 # 3 (ball rel pos)
                self.ball_vel * 2.0,                                   # 3 (ball vel)
            ),
            dim=-1,
        )
