"""A Go2 quadruped learning to follow a velocity command, simulated on the GPU.

The whole point of this file is that `num_envs` copies of the robot step
together in one Genesis scene on one Radeon. Nothing here loops over
environments: every quantity is a `(num_envs, ...)` tensor that never leaves the
GPU between the simulator and the policy. That is what makes the throughput in
`chaal bench` possible, and it is also why the reward terms are written as
whole-tensor expressions rather than per-robot code.

The reward set is the standard velocity-tracking formulation used across legged
locomotion work (exponential tracking terms plus shaping penalties). The
contribution here is not the reward design, it is running the whole loop,
simulation and policy update, on a single AMD Radeon through ROCm.
"""
from __future__ import annotations

import math

import torch

from .config import DEFAULT_ANGLES, JOINT_NAMES, RobotConfig, TaskConfig


def _rand(lo: float, hi: float, shape, device) -> torch.Tensor:
    return torch.rand(shape, device=device) * (hi - lo) + lo


class Go2LocomotionEnv:
    """Velocity-tracking locomotion, vectorised over `num_envs` on one GPU."""

    def __init__(
        self,
        num_envs: int,
        robot_cfg: RobotConfig | None = None,
        task_cfg: TaskConfig | None = None,
        show_viewer: bool = False,
        add_camera: bool = False,
    ):
        import genesis as gs
        from genesis.utils.geom import inv_quat, transform_by_quat, quat_to_xyz

        self._gs = gs
        self._inv_quat = inv_quat
        self._transform_by_quat = transform_by_quat
        self._quat_to_xyz = quat_to_xyz

        self.robot_cfg = robot_cfg or RobotConfig()
        self.task = task_cfg or TaskConfig()
        self.cfg = self.task
        self.num_envs = num_envs
        self.num_actions = len(JOINT_NAMES)
        self.num_obs = self.task.num_obs
        self.max_episode_length = self.task.max_episode_length
        self.device = gs.device

        self.scene = gs.Scene(
            sim_options=gs.options.SimOptions(dt=self.task.dt, substeps=2),
            rigid_options=gs.options.RigidOptions(
                dt=self.task.dt,
                constraint_solver=gs.constraint_solver.Newton,
                enable_collision=True,
                enable_joint_limit=True,
            ),
            show_viewer=show_viewer,
        )
        self.scene.add_entity(gs.morphs.Plane())
        self.robot = self.scene.add_entity(
            gs.morphs.URDF(
                file=self.robot_cfg.urdf,
                pos=self.robot_cfg.base_init_pos,
                quat=self.robot_cfg.base_init_quat,
            )
        )
        self.camera = None
        if add_camera:
            self.camera = self.scene.add_camera(
                res=(1280, 720), pos=(3.0, -2.0, 1.5), lookat=(0.0, 0.0, 0.3), fov=40, GUI=False
            )

        self.scene.build(n_envs=num_envs)

        self.motor_dofs = [self.robot.get_joint(n).dofs_idx_local[0] for n in JOINT_NAMES]
        self.robot.set_dofs_kp([self.robot_cfg.kp] * self.num_actions, self.motor_dofs)
        self.robot.set_dofs_kv([self.robot_cfg.kv] * self.num_actions, self.motor_dofs)

        dev = self.device
        self.default_dof_pos = torch.tensor(
            [DEFAULT_ANGLES[n] for n in JOINT_NAMES], device=dev, dtype=torch.float32
        )
        self.base_init_pos = torch.tensor(self.robot_cfg.base_init_pos, device=dev, dtype=torch.float32)
        self.base_init_quat = torch.tensor(self.robot_cfg.base_init_quat, device=dev, dtype=torch.float32)
        self.global_gravity = torch.tensor([0.0, 0.0, -1.0], device=dev, dtype=torch.float32).repeat(num_envs, 1)

        z = lambda *s: torch.zeros(s, device=dev, dtype=torch.float32)
        self.base_pos = z(num_envs, 3)
        self.base_quat = self.base_init_quat.repeat(num_envs, 1)
        self.base_lin_vel = z(num_envs, 3)
        self.base_ang_vel = z(num_envs, 3)
        self.projected_gravity = z(num_envs, 3)
        self.dof_pos = self.default_dof_pos.repeat(num_envs, 1)
        self.dof_vel = z(num_envs, self.num_actions)
        self.actions = z(num_envs, self.num_actions)
        self.last_actions = z(num_envs, self.num_actions)
        self.commands = z(num_envs, 3)
        self.obs_buf = z(num_envs, self.num_obs)
        self.rew_buf = z(num_envs)
        self.reset_buf = torch.ones(num_envs, device=dev, dtype=torch.bool)
        self.episode_length_buf = torch.zeros(num_envs, device=dev, dtype=torch.int32)

        self.reward_fns = {
            name: getattr(self, f"_reward_{name}")
            for name, scale in self.task.reward_scales.items() if scale != 0.0
        }
        self.episode_sums = {name: z(num_envs) for name in self.reward_fns}
        self.extras: dict = {"observations": {}}

        # Return of each episode that actually finished, averaged over the last
        # `_return_window` of them. Tracked here rather than parsed back out of
        # the trainer's log so that a run's headline number and its checkpoint
        # cannot disagree.
        self.return_buf = z(num_envs)
        self._recent_returns: list[float] = []
        self._return_window = 512

        self.reset()

    # ---- commands -------------------------------------------------------

    def _resample_commands(self, envs_idx: torch.Tensor) -> None:
        if len(envs_idx) == 0:
            return
        n = (len(envs_idx),)
        t = self.task
        self.commands[envs_idx, 0] = _rand(*t.lin_vel_x, n, self.device)
        self.commands[envs_idx, 1] = _rand(*t.lin_vel_y, n, self.device)
        self.commands[envs_idx, 2] = _rand(*t.ang_vel_z, n, self.device)

    # ---- core loop ------------------------------------------------------

    def step(self, actions: torch.Tensor):
        self.actions = torch.clip(actions, -100.0, 100.0)
        target = self.actions * self.task.action_scale + self.default_dof_pos
        self.robot.control_dofs_position(target, self.motor_dofs)
        self.scene.step()

        self.episode_length_buf += 1
        self._refresh_state()

        resample_every = int(self.task.resample_s / self.task.dt)
        due = (self.episode_length_buf % resample_every == 0).nonzero(as_tuple=False).flatten()
        self._resample_commands(due)

        self._check_termination()
        self.rew_buf[:] = 0.0
        for name, fn in self.reward_fns.items():
            r = fn() * self.task.reward_scales[name]
            self.rew_buf += r
            self.episode_sums[name] += r

        self.return_buf += self.rew_buf
        reset_idx = self.reset_buf.nonzero(as_tuple=False).flatten()
        self.reset_idx(reset_idx)

        self._build_obs()
        self.last_actions[:] = self.actions[:]
        return self.get_observations(), self.rew_buf, self.reset_buf, self.extras

    def _refresh_state(self) -> None:
        self.base_pos[:] = self.robot.get_pos()
        self.base_quat[:] = self.robot.get_quat()
        inv_base_quat = self._inv_quat(self.base_quat)
        self.base_lin_vel[:] = self._transform_by_quat(self.robot.get_vel(), inv_base_quat)
        self.base_ang_vel[:] = self._transform_by_quat(self.robot.get_ang(), inv_base_quat)
        self.projected_gravity[:] = self._transform_by_quat(self.global_gravity, inv_base_quat)
        self.dof_pos[:] = self.robot.get_dofs_position(self.motor_dofs)
        self.dof_vel[:] = self.robot.get_dofs_velocity(self.motor_dofs)

    def _check_termination(self) -> None:
        # quat_to_xyz is asked for degrees explicitly: it defaults differently
        # across Genesis versions and a silent radians/degrees mix would make
        # the robot look stable by never terminating.
        euler = self._quat_to_xyz(self.base_quat, rpy=True, degrees=True)
        limit = self.task.fall_angle_deg
        tipped = (euler[:, 0].abs() > limit) | (euler[:, 1].abs() > limit)
        timed_out = self.episode_length_buf >= self.max_episode_length
        self.reset_buf = tipped | timed_out
        # rsl_rl bootstraps value at a time limit but not at a real failure, so
        # the two have to be distinguishable.
        self.extras["time_outs"] = timed_out

    def _build_obs(self) -> None:
        s = self.task.obs_scales
        self.obs_buf = torch.cat(
            [
                self.base_ang_vel * s["ang_vel"],
                self.projected_gravity,
                self.commands * torch.tensor([s["lin_vel"], s["lin_vel"], s["ang_vel"]], device=self.device),
                (self.dof_pos - self.default_dof_pos) * s["dof_pos"],
                self.dof_vel * s["dof_vel"],
                self.actions,
            ],
            dim=-1,
        )

    def get_observations(self):
        from tensordict import TensorDict

        return TensorDict({"policy": self.obs_buf}, batch_size=[self.num_envs])

    # ---- resets ---------------------------------------------------------

    def reset_idx(self, envs_idx: torch.Tensor) -> None:
        if len(envs_idx) == 0:
            return
        self.dof_pos[envs_idx] = self.default_dof_pos
        self.dof_vel[envs_idx] = 0.0
        self.robot.set_dofs_position(
            position=self.dof_pos[envs_idx],
            dofs_idx_local=self.motor_dofs,
            zero_velocity=True,
            envs_idx=envs_idx,
        )
        self.base_pos[envs_idx] = self.base_init_pos
        self.base_quat[envs_idx] = self.base_init_quat
        self.robot.set_pos(self.base_pos[envs_idx], zero_velocity=False, envs_idx=envs_idx)
        self.robot.set_quat(self.base_quat[envs_idx], zero_velocity=False, envs_idx=envs_idx)
        self.robot.zero_all_dofs_velocity(envs_idx)

        self.base_lin_vel[envs_idx] = 0.0
        self.base_ang_vel[envs_idx] = 0.0
        self.last_actions[envs_idx] = 0.0
        self.actions[envs_idx] = 0.0

        log = self.extras.setdefault("log", {})
        for name in self.reward_fns:
            log[f"/rew/{name}"] = (
                self.episode_sums[name][envs_idx].mean() / self.task.episode_length_s
            ).item()
            self.episode_sums[name][envs_idx] = 0.0

        finished = self.return_buf[envs_idx]
        if finished.numel():
            self._recent_returns.extend(finished.tolist())
            del self._recent_returns[: -self._return_window]
        self.return_buf[envs_idx] = 0.0

        self.episode_length_buf[envs_idx] = 0
        self.reset_buf[envs_idx] = True
        self._resample_commands(envs_idx)

    @property
    def mean_episode_return(self) -> float:
        """Mean return over recently completed episodes, 0.0 before any finish."""
        if not self._recent_returns:
            return 0.0
        return sum(self._recent_returns) / len(self._recent_returns)

    def reset(self):
        self.reset_buf[:] = True
        self.reset_idx(torch.arange(self.num_envs, device=self.device))
        self._refresh_state()
        self._build_obs()
        return self.get_observations(), None

    # ---- rewards --------------------------------------------------------

    def _reward_tracking_lin_vel(self) -> torch.Tensor:
        err = torch.sum((self.commands[:, :2] - self.base_lin_vel[:, :2]) ** 2, dim=1)
        return torch.exp(-err / self.task.tracking_sigma)

    def _reward_tracking_ang_vel(self) -> torch.Tensor:
        err = (self.commands[:, 2] - self.base_ang_vel[:, 2]) ** 2
        return torch.exp(-err / self.task.tracking_sigma)

    def _reward_lin_vel_z(self) -> torch.Tensor:
        return self.base_lin_vel[:, 2] ** 2

    def _reward_action_rate(self) -> torch.Tensor:
        return torch.sum((self.last_actions - self.actions) ** 2, dim=1)

    def _reward_similar_to_default(self) -> torch.Tensor:
        return torch.sum(torch.abs(self.dof_pos - self.default_dof_pos), dim=1)

    def _reward_base_height(self) -> torch.Tensor:
        return (self.base_pos[:, 2] - self.task.target_height) ** 2
