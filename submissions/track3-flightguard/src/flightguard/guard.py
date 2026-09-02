"""Stateful VIO sanity gate and short-horizon dead reckoning."""

from __future__ import annotations

from dataclasses import dataclass

import torch


@dataclass(frozen=True)
class GuardOutput:
    """State estimate exposed to the controller and evaluation-only labels."""

    position: torch.Tensor
    velocity: torch.Tensor
    fault: torch.Tensor
    position_innovation: torch.Tensor
    velocity_innovation: torch.Tensor
    dropout_steps: torch.Tensor


class VioGuard:
    """Reject impossible VIO updates and bridge them with a decaying-velocity model.

    The guard intentionally consumes only the same position/velocity measurement
    available to the controller. Simulator truth is never passed to ``apply``.
    """

    def __init__(
        self,
        num_envs: int,
        *,
        dt: float,
        position_jump_threshold: float = 0.75,
        velocity_jump_threshold: float = 4.0,
        velocity_decay: float = 0.98,
        device: torch.device | str = "cpu",
    ) -> None:
        if num_envs <= 0:
            raise ValueError("num_envs must be positive")
        if dt <= 0:
            raise ValueError("dt must be positive")
        if position_jump_threshold <= 0 or velocity_jump_threshold <= 0:
            raise ValueError("innovation thresholds must be positive")
        if not 0.0 <= velocity_decay <= 1.0:
            raise ValueError("velocity_decay must be in [0, 1]")

        self.num_envs = num_envs
        self.dt = float(dt)
        self.position_jump_threshold = float(position_jump_threshold)
        self.velocity_jump_threshold = float(velocity_jump_threshold)
        self.velocity_decay = float(velocity_decay)
        self.device = torch.device(device)
        self._position = torch.zeros(num_envs, 3, device=self.device)
        self._velocity = torch.zeros(num_envs, 3, device=self.device)
        self._initialized = torch.zeros(num_envs, dtype=torch.bool, device=self.device)
        self._dropout_steps = torch.zeros(
            num_envs, dtype=torch.long, device=self.device
        )

    def reset(
        self,
        position: torch.Tensor,
        velocity: torch.Tensor,
        envs_idx: torch.Tensor | None = None,
    ) -> None:
        """Seed all or selected filters with a known valid measurement."""

        if envs_idx is None:
            envs_idx = torch.arange(self.num_envs, device=self.device)
        else:
            envs_idx = envs_idx.to(device=self.device, dtype=torch.long)
        expected = (envs_idx.numel(), 3)
        if position.shape != expected or velocity.shape != expected:
            raise ValueError(
                f"position and velocity must both have selected shape {expected}"
            )
        if position.device != self.device or velocity.device != self.device:
            raise ValueError("reset tensors must be on the guard device")
        if not torch.isfinite(position).all() or not torch.isfinite(velocity).all():
            raise ValueError("reset state must be finite")

        self._position[envs_idx] = position
        self._velocity[envs_idx] = velocity
        self._initialized[envs_idx] = True
        self._dropout_steps[envs_idx] = 0

    def apply(
        self,
        measured_position: torch.Tensor,
        measured_velocity: torch.Tensor,
        reported_invalid: torch.Tensor | None = None,
    ) -> GuardOutput:
        """Return a finite controller state and a per-environment fault decision."""

        expected = (self.num_envs, 3)
        if measured_position.shape != expected or measured_velocity.shape != expected:
            raise ValueError(
                f"measured position and velocity must both have shape {expected}"
            )
        if (
            measured_position.device != self.device
            or measured_velocity.device != self.device
        ):
            raise ValueError("measurement tensors must be on the guard device")
        if reported_invalid is None:
            reported_invalid = torch.zeros(
                self.num_envs, dtype=torch.bool, device=self.device
            )
        if reported_invalid.shape != (self.num_envs,):
            raise ValueError(f"reported_invalid must have shape {(self.num_envs,)}")
        reported_invalid = reported_invalid.to(device=self.device, dtype=torch.bool)

        predicted_position = self._position + self.dt * self._velocity
        predicted_velocity = self.velocity_decay * self._velocity
        finite = torch.isfinite(measured_position).all(dim=1) & torch.isfinite(
            measured_velocity
        ).all(dim=1)
        safe_position = torch.nan_to_num(measured_position)
        safe_velocity = torch.nan_to_num(measured_velocity)
        position_innovation = torch.linalg.vector_norm(
            safe_position - predicted_position, dim=1
        )
        velocity_innovation = torch.linalg.vector_norm(
            safe_velocity - predicted_velocity, dim=1
        )

        impossible = self._initialized & (
            (position_innovation > self.position_jump_threshold)
            | (velocity_innovation > self.velocity_jump_threshold)
        )
        fault = reported_invalid | ~finite | impossible
        accept = ~fault
        first_valid = ~self._initialized & accept

        next_position = torch.where(
            accept[:, None], safe_position, predicted_position
        )
        next_velocity = torch.where(
            accept[:, None], safe_velocity, predicted_velocity
        )
        self._position.copy_(next_position)
        self._velocity.copy_(next_velocity)
        self._initialized |= first_valid
        self._dropout_steps = torch.where(
            fault, self._dropout_steps + 1, torch.zeros_like(self._dropout_steps)
        )

        return GuardOutput(
            self._position,
            self._velocity,
            fault,
            position_innovation,
            velocity_innovation,
            self._dropout_steps,
        )
