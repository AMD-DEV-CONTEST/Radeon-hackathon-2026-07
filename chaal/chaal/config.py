"""Every number that shapes a run, in one place.

Split into three dataclasses because they have three different lifetimes: the
robot description is fixed by the URDF, the task is what we are asking the robot
to do, and the run config is what we sweep when measuring the GPU.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: Joint order as Genesis reports it for the bundled Go2 URDF: free root joint
#: takes local DOFs 0-5, then each leg in turn. Confirmed by introspection, not
#: assumed, because the URDF orders legs FL, FR, RL, RR rather than the more
#: common FR-first convention.
JOINT_NAMES = (
    "FL_hip_joint", "FL_thigh_joint", "FL_calf_joint",
    "FR_hip_joint", "FR_thigh_joint", "FR_calf_joint",
    "RL_hip_joint", "RL_thigh_joint", "RL_calf_joint",
    "RR_hip_joint", "RR_thigh_joint", "RR_calf_joint",
)

#: Standing pose. The URDF's own neutral pose is outside the joint limits, which
#: is what Genesis warns about on load, so a stance has to be supplied.
DEFAULT_ANGLES = {
    "FL_hip_joint": 0.0, "FR_hip_joint": 0.0, "RL_hip_joint": 0.0, "RR_hip_joint": 0.0,
    "FL_thigh_joint": 0.8, "FR_thigh_joint": 0.8, "RL_thigh_joint": 1.0, "RR_thigh_joint": 1.0,
    "FL_calf_joint": -1.5, "FR_calf_joint": -1.5, "RL_calf_joint": -1.5, "RR_calf_joint": -1.5,
}


@dataclass
class RobotConfig:
    urdf: str = "urdf/go2/urdf/go2.urdf"
    base_init_pos: tuple[float, float, float] = (0.0, 0.0, 0.42)
    base_init_quat: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)
    kp: float = 20.0
    kv: float = 0.5


@dataclass
class TaskConfig:
    """Velocity tracking: follow a commanded body-frame velocity without falling."""

    dt: float = 0.02
    episode_length_s: float = 20.0
    action_scale: float = 0.25
    #: Commands are resampled mid-episode so a policy cannot memorise one gait.
    resample_s: float = 4.0
    lin_vel_x: tuple[float, float] = (-1.0, 1.0)
    lin_vel_y: tuple[float, float] = (-1.0, 1.0)
    ang_vel_z: tuple[float, float] = (-1.0, 1.0)
    target_height: float = 0.30
    #: Terminate when the body tips past this, in degrees, on either axis.
    fall_angle_deg: float = 10.0

    obs_scales: dict[str, float] = field(default_factory=lambda: {
        "ang_vel": 0.25, "dof_pos": 1.0, "dof_vel": 0.05, "lin_vel": 2.0,
    })
    reward_scales: dict[str, float] = field(default_factory=lambda: {
        "tracking_lin_vel": 1.0,
        "tracking_ang_vel": 0.2,
        "lin_vel_z": -1.0,
        "action_rate": -0.005,
        "similar_to_default": -0.1,
        "base_height": -50.0,
    })
    tracking_sigma: float = 0.25

    @property
    def max_episode_length(self) -> int:
        return int(self.episode_length_s / self.dt)

    @property
    def num_obs(self) -> int:
        # ang vel 3, projected gravity 3, commands 3, dof pos 12, dof vel 12,
        # previous actions 12.
        return 45


@dataclass
class RunConfig:
    num_envs: int = 4096
    max_iterations: int = 300
    seed: int = 1
    backend: str = "amdgpu"
