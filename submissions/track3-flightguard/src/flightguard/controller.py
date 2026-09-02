"""Batched waypoint controller for the Genesis RACE quadrotor.

The motor order and mixer are tied to Genesis v1.2.3's ``racer.urdf``:

* motor 0: (+x, +y), motor 1: (-x, +y)
* motor 2: (-x, -y), motor 3: (+x, -y)
* configured spins are (-1, +1, -1, +1), and ``DroneEntity`` reverses
  reaction torque for the ``RACE`` model.

Consequently positive body roll uses motors (0, 1), positive pitch uses
motors (1, 2), and positive yaw uses motors (0, 2).  Outputs are normalized
actions for ``FlightGuardGenesisEnv.step`` rather than raw RPM.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch

CONTROLLER_PROFILE_NAMES = ("nominal", "robust_z")


@dataclass(frozen=True)
class WaypointControllerConfig:
    """Physical constants and conservative starting gains for RACE.

    The inertia, arm offsets, mass, ``kf``, and ``km`` values come from
    Genesis v1.2.3's ``assets/urdf/drones/racer.urdf``.  Attitude gains map
    rotation error to angular acceleration; cloud simulation is still
    required to tune them against the Genesis integrator.
    """

    gravity: float = 9.81
    mass: float = 0.830
    inertia_x: float = 0.003113
    inertia_y: float = 0.003113
    inertia_z: float = 0.003113
    arm_x: float = 0.085
    arm_y: float = 0.0675
    thrust_coefficient: float = 8.47e-9
    moment_coefficient: float = 2.13e-11
    position_kp_xy: float = 1.5
    position_kp_z: float = 2.5
    velocity_kd_xy: float = 1.8
    velocity_kd_z: float = 2.0
    attitude_kp_roll_pitch: float = 12.0
    attitude_kp_yaw: float = 0.5
    angular_rate_kd_roll_pitch: float = 4.0
    angular_rate_kd_yaw: float = 0.2
    max_lateral_acceleration: float = 4.0
    max_vertical_acceleration: float = 3.0
    max_upward_vertical_acceleration: float | None = None
    max_downward_vertical_acceleration: float | None = None
    desired_yaw: float = 0.0
    rpm_action_scale: float = 0.8

    def __post_init__(self) -> None:
        positive = {
            "gravity": self.gravity,
            "mass": self.mass,
            "inertia_x": self.inertia_x,
            "inertia_y": self.inertia_y,
            "inertia_z": self.inertia_z,
            "arm_x": self.arm_x,
            "arm_y": self.arm_y,
            "thrust_coefficient": self.thrust_coefficient,
            "moment_coefficient": self.moment_coefficient,
            "rpm_action_scale": self.rpm_action_scale,
        }
        invalid = [name for name, value in positive.items() if value <= 0.0]
        if invalid:
            raise ValueError(f"controller constants must be positive: {', '.join(invalid)}")
        if self.rpm_action_scale >= 1.0:
            raise ValueError("rpm_action_scale must be less than 1")
        if self.max_lateral_acceleration <= 0.0:
            raise ValueError("max_lateral_acceleration must be positive")
        vertical_limits = {
            "max_vertical_acceleration": self.max_vertical_acceleration,
            "max_upward_vertical_acceleration": (self.effective_max_upward_vertical_acceleration),
            "max_downward_vertical_acceleration": (
                self.effective_max_downward_vertical_acceleration
            ),
        }
        invalid_vertical = [
            name for name, value in vertical_limits.items() if not 0.0 < value < self.gravity
        ]
        if invalid_vertical:
            raise ValueError(
                "vertical acceleration limits must lie in (0, gravity): "
                + ", ".join(invalid_vertical)
            )

    @property
    def effective_max_upward_vertical_acceleration(self) -> float:
        return (
            self.max_vertical_acceleration
            if self.max_upward_vertical_acceleration is None
            else self.max_upward_vertical_acceleration
        )

    @property
    def effective_max_downward_vertical_acceleration(self) -> float:
        return (
            self.max_vertical_acceleration
            if self.max_downward_vertical_acceleration is None
            else self.max_downward_vertical_acceleration
        )


def controller_config_for_profile(profile: str) -> WaypointControllerConfig:
    """Return an auditable controller profile without changing nominal defaults."""

    if profile == "nominal":
        return WaypointControllerConfig()
    if profile == "robust_z":
        return WaypointControllerConfig(
            position_kp_z=8.0,
            velocity_kd_z=3.6,
        )
    raise ValueError(f"unsupported controller profile: {profile}")


def _quaternion_to_rotation_matrix(quaternion: torch.Tensor) -> torch.Tensor:
    """Convert normalized-or-near-normalized ``[w, x, y, z]`` to rotation matrices."""

    eps = torch.finfo(quaternion.dtype).eps
    norm = torch.linalg.vector_norm(quaternion, dim=-1, keepdim=True)
    normalized = quaternion / norm.clamp_min(eps)
    identity_quaternion = torch.zeros_like(normalized)
    identity_quaternion[..., 0] = 1.0
    normalized = torch.where(norm > eps, normalized, identity_quaternion)
    w, x, y, z = normalized.unbind(dim=-1)

    return torch.stack(
        (
            1.0 - 2.0 * (y * y + z * z),
            2.0 * (x * y - w * z),
            2.0 * (x * z + w * y),
            2.0 * (x * y + w * z),
            1.0 - 2.0 * (x * x + z * z),
            2.0 * (y * z - w * x),
            2.0 * (x * z - w * y),
            2.0 * (y * z + w * x),
            1.0 - 2.0 * (x * x + y * y),
        ),
        dim=-1,
    ).reshape(*quaternion.shape[:-1], 3, 3)


class BatchedWaypointController:
    """Stateless, vectorized geometric-PD waypoint controller.

    Inputs use world-frame position, velocity, and angular velocity, with
    Genesis ``[w, x, y, z]`` quaternions.  ``target`` may be one waypoint
    shared by the batch or one waypoint per environment.
    """

    def __init__(self, config: WaypointControllerConfig | None = None) -> None:
        self.config = config or WaypointControllerConfig()

    def __call__(
        self,
        position: torch.Tensor,
        quaternion: torch.Tensor,
        velocity: torch.Tensor,
        angular_velocity: torch.Tensor,
        target: torch.Tensor,
    ) -> torch.Tensor:
        return self.compute(position, quaternion, velocity, angular_velocity, target)

    def compute(
        self,
        position: torch.Tensor,
        quaternion: torch.Tensor,
        velocity: torch.Tensor,
        angular_velocity: torch.Tensor,
        target: torch.Tensor,
    ) -> torch.Tensor:
        """Return normalized motor actions with shape ``[N, 4]``."""

        self._validate_shapes(position, quaternion, velocity, angular_velocity, target)
        device, dtype = position.device, position.dtype
        quaternion = quaternion.to(device=device, dtype=dtype)
        velocity = velocity.to(device=device, dtype=dtype)
        angular_velocity = angular_velocity.to(device=device, dtype=dtype)
        target = target.to(device=device, dtype=dtype)
        if target.ndim == 1:
            target = target.unsqueeze(0).expand(position.shape[0], -1)

        config = self.config
        error = target - position
        lateral_acceleration = (
            config.position_kp_xy * error[:, :2] - config.velocity_kd_xy * velocity[:, :2]
        )
        lateral_norm = torch.linalg.vector_norm(lateral_acceleration, dim=-1, keepdim=True)
        lateral_scale = (
            config.max_lateral_acceleration / lateral_norm.clamp_min(torch.finfo(dtype).eps)
        ).clamp_max(1.0)
        lateral_acceleration = lateral_acceleration * lateral_scale

        vertical_acceleration = (
            config.position_kp_z * error[:, 2] - config.velocity_kd_z * velocity[:, 2]
        ).clamp(
            -config.effective_max_downward_vertical_acceleration,
            config.effective_max_upward_vertical_acceleration,
        )
        desired_acceleration = torch.cat(
            (
                lateral_acceleration,
                (config.gravity + vertical_acceleration).unsqueeze(-1),
            ),
            dim=-1,
        )

        rotation = _quaternion_to_rotation_matrix(quaternion)
        desired_rotation = self._desired_rotation(desired_acceleration)
        attitude_skew = (
            desired_rotation.transpose(-1, -2) @ rotation
            - rotation.transpose(-1, -2) @ desired_rotation
        )
        attitude_error = 0.5 * torch.stack(
            (
                attitude_skew[:, 2, 1],
                attitude_skew[:, 0, 2],
                attitude_skew[:, 1, 0],
            ),
            dim=-1,
        )
        body_angular_velocity = (
            rotation.transpose(-1, -2) @ angular_velocity.unsqueeze(-1)
        ).squeeze(-1)

        attitude_kp = position.new_tensor(
            (
                config.attitude_kp_roll_pitch,
                config.attitude_kp_roll_pitch,
                config.attitude_kp_yaw,
            )
        )
        rate_kd = position.new_tensor(
            (
                config.angular_rate_kd_roll_pitch,
                config.angular_rate_kd_roll_pitch,
                config.angular_rate_kd_yaw,
            )
        )
        inertia = position.new_tensor((config.inertia_x, config.inertia_y, config.inertia_z))
        desired_torque = inertia * (-attitude_kp * attitude_error - rate_kd * body_angular_velocity)

        current_body_z = rotation[:, :, 2]
        collective_thrust_ratio = (desired_acceleration * current_body_z).sum(
            dim=-1
        ) / config.gravity
        thrust_ratio = self._mix_motor_thrust_ratios(collective_thrust_ratio, desired_torque)
        minimum_ratio = (1.0 - config.rpm_action_scale) ** 2
        maximum_ratio = (1.0 + config.rpm_action_scale) ** 2
        thrust_ratio = thrust_ratio.clamp(minimum_ratio, maximum_ratio)
        action = (torch.sqrt(thrust_ratio) - 1.0) / config.rpm_action_scale
        return action.clamp(-1.0, 1.0)

    def _desired_rotation(self, desired_acceleration: torch.Tensor) -> torch.Tensor:
        eps = torch.finfo(desired_acceleration.dtype).eps
        body_z = desired_acceleration / torch.linalg.vector_norm(
            desired_acceleration, dim=-1, keepdim=True
        ).clamp_min(eps)
        heading = desired_acceleration.new_tensor(
            (
                math.cos(self.config.desired_yaw),
                math.sin(self.config.desired_yaw),
                0.0,
            )
        ).expand_as(body_z)
        body_y = torch.cross(body_z, heading, dim=-1)
        body_y = body_y / torch.linalg.vector_norm(body_y, dim=-1, keepdim=True).clamp_min(eps)
        body_x = torch.cross(body_y, body_z, dim=-1)
        return torch.stack((body_x, body_y, body_z), dim=-1)

    def _mix_motor_thrust_ratios(
        self,
        collective: torch.Tensor,
        desired_torque: torch.Tensor,
    ) -> torch.Tensor:
        config = self.config
        roll = desired_torque[:, 0] / (config.mass * config.gravity * config.arm_y)
        pitch = desired_torque[:, 1] / (config.mass * config.gravity * config.arm_x)
        reaction_arm = config.moment_coefficient / config.thrust_coefficient
        yaw = desired_torque[:, 2] / (config.mass * config.gravity * reaction_arm)
        return torch.stack(
            (
                collective + roll - pitch + yaw,
                collective + roll + pitch - yaw,
                collective - roll + pitch + yaw,
                collective - roll - pitch - yaw,
            ),
            dim=-1,
        )

    @staticmethod
    def _validate_shapes(
        position: torch.Tensor,
        quaternion: torch.Tensor,
        velocity: torch.Tensor,
        angular_velocity: torch.Tensor,
        target: torch.Tensor,
    ) -> None:
        if position.ndim != 2 or position.shape[1] != 3:
            raise ValueError("position must have shape [N, 3]")
        batch = position.shape[0]
        if quaternion.shape != (batch, 4):
            raise ValueError("quaternion must have shape [N, 4]")
        if velocity.shape != (batch, 3):
            raise ValueError("velocity must have shape [N, 3]")
        if angular_velocity.shape != (batch, 3):
            raise ValueError("angular_velocity must have shape [N, 3]")
        if target.shape not in ((3,), (batch, 3)):
            raise ValueError("target must have shape [3] or [N, 3]")
        if not position.is_floating_point():
            raise TypeError("controller inputs must be floating-point tensors")
