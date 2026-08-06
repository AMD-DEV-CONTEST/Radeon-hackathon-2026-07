"""
Disturbance Configuration for Robust Training.

Defines perturbations injected during training to improve robustness:
  - Random push forces (simulating collisions)
  - Friction coefficient randomization
  - Observation noise
  - Ball position perturbation (simulating deflections)

Used by the "complete method" training (PPO + disturbance + recovery).
"""

from __future__ import annotations
import dataclasses
import numpy as np
import torch

try:
    import genesis as gs
except Exception:
    gs = None


@dataclasses.dataclass
class DisturbanceConfig:
    """Configuration for training-time perturbations."""

    # Push force: applied to robot torso at random intervals
    push_enabled: bool = True
    push_interval_s: float = 5.0       # apply push every N seconds
    push_force_range: float = 10.0     # Newtons (0-10N)
    push_torque_range: float = 2.0     # Nm
    push_duration_s: float = 1.0       # duration of push

    # Kick: stronger sudden impulse (simulating collision)
    kick_enabled: bool = True
    kick_interval_s: float = 2.0
    kick_lin_vel_range: float = 0.1    # m/s impulse
    kick_ang_vel_range: float = 0.02   # rad/s impulse

    # Friction randomization
    friction_enabled: bool = True
    friction_range: tuple = (0.1, 2.0)  # friction coefficient range

    # Observation noise (Gaussian)
    obs_noise_enabled: bool = True
    obs_noise_gravity: float = 0.01    # std for projected_gravity
    obs_noise_ang_vel: float = 0.1     # std for angular velocity
    obs_noise_dof_pos: float = 0.01   # std for joint positions
    obs_noise_dof_vel: float = 0.1    # std for joint velocities

    # Ball perturbation (random teleport if ball gets stuck)
    ball_perturb_enabled: bool = True
    ball_stuck_threshold: float = 0.05  # if ball speed < this for N steps
    ball_stuck_steps: int = 50          # steps before perturbing
    ball_perturb_range: float = 3.0     # random new position range (m)

    # Recovery training: don't terminate on fall
    no_fall_termination: bool = True    # episode continues even if robot falls
    recovery_reward_bonus: float = 2.0   # bonus for standing back up
    fall_penalty_scaled: float = -5.0   # penalty per fall step (scaled by dt)

    # Mass randomization
    mass_randomization_enabled: bool = True
    mass_range: tuple = (0.8, 1.2)      # scale factor for robot mass

    # COM randomization
    com_randomization_enabled: bool = True
    com_range: float = 0.1              # meters offset for center of mass


class DisturbanceInjector:
    """Inject perturbations during training step."""

    def __init__(self, cfg: DisturbanceConfig, num_envs: int, device: str, dt: float):
        self.cfg = cfg
        self.num_envs = num_envs
        self.device = device
        self.dt = dt

        # Push scheduling
        self.push_interval = int(cfg.push_interval_s / dt)
        self.push_duration = int(cfg.push_duration_s / dt)
        self.push_step_counter = torch.zeros(num_envs, dtype=torch.int32, device=device)
        self.is_pushing = torch.zeros(num_envs, dtype=torch.bool, device=device)
        self.push_force = torch.zeros(num_envs, 3, device=device)
        self.push_torque = torch.zeros(num_envs, 3, device=device)

        # Kick scheduling
        self.kick_interval = int(cfg.kick_interval_s / dt)
        self.kick_step_counter = torch.zeros(num_envs, dtype=torch.int32, device=device)

        # Ball stuck tracking
        self.ball_stuck_counter = torch.zeros(num_envs, dtype=torch.int32, device=device)

    def get_push_forces(self, step: int) -> tuple[torch.Tensor, torch.Tensor]:
        """Return (force, torque) to apply this step, or zeros."""
        if not self.cfg.push_enabled:
            return (torch.zeros(self.num_envs, 3, device=self.device),
                    torch.zeros(self.num_envs, 3, device=self.device))

        # Check if it's time to start a new push
        self.push_step_counter += 1
        should_push = self.push_step_counter >= self.push_interval

        if should_push.any():
            idx = should_push.nonzero(as_tuple=False).flatten()
            n = len(idx)
            # Random force direction (horizontal only)
            angle = torch.rand(n, device=self.device) * 2 * torch.pi
            magnitude = torch.rand(n, device=self.device) * self.cfg.push_force_range
            self.push_force[idx, 0] = torch.cos(angle) * magnitude
            self.push_force[idx, 1] = torch.sin(angle) * magnitude
            self.push_force[idx, 2] = 0.0

            # Random torque
            self.push_torque[idx, :] = (torch.rand(n, 3, device=self.device) - 0.5) * 2 * self.cfg.push_torque_range

            self.is_pushing[idx] = True
            self.push_step_counter[idx] = 0

        # Check if push duration expired
        pushing_too_long = self.is_pushing & (self.push_step_counter >= self.push_duration)
        if pushing_too_long.any():
            idx = pushing_too_long.nonzero(as_tuple=False).flatten()
            self.is_pushing[idx] = False
            self.push_force[idx] = 0.0
            self.push_torque[idx] = 0.0

        force = torch.where(self.is_pushing.unsqueeze(1), self.push_force, torch.zeros_like(self.push_force))
        torque = torch.where(self.is_pushing.unsqueeze(1), self.push_torque, torch.zeros_like(self.push_torque))

        return force, torque

    def get_kick_impulse(self, step: int) -> tuple[torch.Tensor, torch.Tensor]:
        """Return (lin_vel_impulse, ang_vel_impulse) for kick perturbation."""
        if not self.cfg.kick_enabled:
            return (torch.zeros(self.num_envs, 3, device=self.device),
                    torch.zeros(self.num_envs, 3, device=self.device))

        self.kick_step_counter += 1
        should_kick = self.kick_step_counter >= self.kick_interval

        lin_impulse = torch.zeros(self.num_envs, 3, device=self.device)
        ang_impulse = torch.zeros(self.num_envs, 3, device=self.device)

        if should_kick.any():
            idx = should_kick.nonzero(as_tuple=False).flatten()
            n = len(idx)
            lin_impulse[idx, 0] = (torch.rand(n, device=self.device) - 0.5) * 2 * self.cfg.kick_lin_vel_range
            lin_impulse[idx, 1] = (torch.rand(n, device=self.device) - 0.5) * 2 * self.cfg.kick_lin_vel_range
            ang_impulse[idx, 2] = (torch.rand(n, device=self.device) - 0.5) * 2 * self.cfg.kick_ang_vel_range
            self.kick_step_counter[idx] = 0

        return lin_impulse, ang_impulse

    def add_obs_noise(self, obs_dict: dict) -> dict:
        """Add Gaussian noise to observations."""
        if not self.cfg.obs_noise_enabled:
            return obs_dict

        if "torso_up" in obs_dict:
            pass  # torso_up is derived, not noisy

        # Noise is added at the env level in step(), not here
        # This is a placeholder for documentation
        return obs_dict

    def check_ball_stuck(self, ball_vel: torch.Tensor) -> torch.Tensor:
        """Check if ball is stuck and needs perturbation.

        Returns boolean tensor: True if ball should be perturbed.
        """
        if not self.cfg.ball_perturb_enabled:
            return torch.zeros(self.num_envs, dtype=torch.bool, device=self.device)

        ball_speed = torch.norm(ball_vel[:, :2], dim=1)
        is_slow = ball_speed < self.cfg.ball_stuck_threshold

        self.ball_stuck_counter = torch.where(is_slow, self.ball_stuck_counter + 1,
                                              torch.zeros_like(self.ball_stuck_counter))

        should_perturb = self.ball_stuck_counter >= self.cfg.ball_stuck_steps
        self.ball_stuck_counter[should_perturb] = 0

        return should_perturb

    def get_friction(self) -> float:
        """Sample a random friction coefficient."""
        if not self.cfg.friction_enabled:
            return 1.0
        return float(np.random.uniform(*self.cfg.friction_range))

    def get_mass_scale(self) -> float:
        """Sample a random mass scale factor."""
        if not self.cfg.mass_randomization_enabled:
            return 1.0
        return float(np.random.uniform(*self.cfg.mass_range))


# Default disturbance configs for different training modes
DISTURBANCE_NONE = DisturbanceConfig(
    push_enabled=False, kick_enabled=False, friction_enabled=False,
    obs_noise_enabled=False, ball_perturb_enabled=False,
    no_fall_termination=False, mass_randomization_enabled=False,
    com_randomization_enabled=False,
)

DISTURBANCE_LIGHT = DisturbanceConfig(
    push_force_range=5.0, push_interval_s=8.0,
    kick_lin_vel_range=0.05, kick_interval_s=4.0,
    friction_range=(0.3, 1.5),
    obs_noise_gravity=0.005, obs_noise_ang_vel=0.05,
    no_fall_termination=True,
)

DISTURBANCE_FULL = DisturbanceConfig(
    push_force_range=10.0, push_interval_s=5.0,
    kick_lin_vel_range=0.1, kick_interval_s=2.0,
    friction_range=(0.1, 2.0),
    obs_noise_gravity=0.01, obs_noise_ang_vel=0.1,
    obs_noise_dof_pos=0.01, obs_noise_dof_vel=0.1,
    no_fall_termination=True,
    mass_range=(0.8, 1.2),
    com_randomization_enabled=True,
)
