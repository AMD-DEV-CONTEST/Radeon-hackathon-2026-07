"""Learnable action-conditioned translational flight dynamics.

The model consumes Genesis state conventions: world-frame linear and angular
velocity, a ``[w, x, y, z]`` quaternion, and four normalized motor actions.
It predicts world-frame linear acceleration.  Feature and target statistics
are registered buffers, so a normal ``state_dict`` contains the complete
normalization state alongside the network weights.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from torch import nn


@dataclass(frozen=True)
class DynamicsConfig:
    """Architecture and numerical bounds for :class:`FlightDynamicsModel`."""

    hidden_sizes: tuple[int, ...] = (64, 64)
    input_clip: float = 10.0
    normalization_epsilon: float = 1.0e-6
    check_finite_inputs: bool = False

    def __post_init__(self) -> None:
        if any(
            isinstance(width, bool) or not isinstance(width, int) or width <= 0
            for width in self.hidden_sizes
        ):
            raise ValueError("hidden_sizes must contain only positive integers")
        if not math.isfinite(self.input_clip) or self.input_clip <= 0.0:
            raise ValueError("input_clip must be finite and positive")
        if not math.isfinite(self.normalization_epsilon) or self.normalization_epsilon <= 0.0:
            raise ValueError("normalization_epsilon must be finite and positive")
        if not isinstance(self.check_finite_inputs, bool):
            raise TypeError("check_finite_inputs must be a bool")


class FlightDynamicsModel(nn.Module):
    """Compact MLP that predicts world-frame acceleration for a batch.

    Network input order is ``velocity(3), quaternion_wxyz(4),
    angular_velocity(3), action(4)``.  Quaternions are normalized and mapped
    to the non-negative-``w`` hemisphere before feature normalization.
    Normalized inputs are clipped to ``[-config.input_clip,
    config.input_clip]`` to bound extrapolation presented to the MLP.
    """

    input_dim = 14
    output_dim = 3

    def __init__(self, config: DynamicsConfig | None = None) -> None:
        super().__init__()
        self.config = config or DynamicsConfig()

        layers: list[nn.Module] = []
        previous_width = self.input_dim
        for width in self.config.hidden_sizes:
            layers.extend((nn.Linear(previous_width, width), nn.SiLU()))
            previous_width = width
        layers.append(nn.Linear(previous_width, self.output_dim))
        self.network = nn.Sequential(*layers)

        self.register_buffer("input_mean", torch.zeros(self.input_dim))
        self.register_buffer("input_scale", torch.ones(self.input_dim))
        self.register_buffer("target_mean", torch.zeros(self.output_dim))
        self.register_buffer("target_scale", torch.ones(self.output_dim))

    def set_normalization(
        self,
        input_mean: torch.Tensor,
        input_scale: torch.Tensor,
        target_mean: torch.Tensor,
        target_scale: torch.Tensor,
    ) -> None:
        """Set serialized feature/target statistics after validating them.

        Scales are standard deviations or another strictly positive scale in
        the same units as their corresponding values.
        """

        statistics = (
            ("input_mean", input_mean, self.input_dim, False),
            ("input_scale", input_scale, self.input_dim, True),
            ("target_mean", target_mean, self.output_dim, False),
            ("target_scale", target_scale, self.output_dim, True),
        )
        converted: dict[str, torch.Tensor] = {}
        for name, value, width, is_scale in statistics:
            buffer = getattr(self, name)
            tensor = torch.as_tensor(value, device=buffer.device, dtype=buffer.dtype)
            if tensor.shape != (width,):
                raise ValueError(f"{name} must have shape [{width}]")
            if not bool(torch.isfinite(tensor).all()):
                raise ValueError(f"{name} must be finite")
            if is_scale and not bool((tensor >= self.config.normalization_epsilon).all()):
                raise ValueError(f"{name} must be at least {self.config.normalization_epsilon}")
            converted[name] = tensor

        with torch.no_grad():
            for name, tensor in converted.items():
                getattr(self, name).copy_(tensor)

    def normalize_target(self, acceleration: torch.Tensor) -> torch.Tensor:
        """Map physical acceleration targets to the network's target space."""

        self._validate_single_tensor(
            "acceleration", acceleration, self.output_dim, self.target_mean
        )
        return (acceleration - self.target_mean) / self.target_scale

    def forward(
        self,
        velocity: torch.Tensor,
        quaternion: torch.Tensor,
        angular_velocity: torch.Tensor,
        action: torch.Tensor,
    ) -> torch.Tensor:
        """Alias for :meth:`acceleration`, as expected by ``torch.nn.Module``."""

        return self.acceleration(velocity, quaternion, angular_velocity, action)

    def acceleration(
        self,
        velocity: torch.Tensor,
        quaternion: torch.Tensor,
        angular_velocity: torch.Tensor,
        action: torch.Tensor,
    ) -> torch.Tensor:
        """Predict world-frame linear acceleration with shape ``[N, 3]``."""

        self._validate_inputs(velocity, quaternion, angular_velocity, action)
        quaternion_norm = torch.linalg.vector_norm(quaternion, dim=-1, keepdim=True)
        if self.config.check_finite_inputs and not bool(
            (quaternion_norm >= self.config.normalization_epsilon).all()
        ):
            raise ValueError("quaternion norm must be nonzero")
        normalized_quaternion = quaternion / quaternion_norm.clamp_min(
            self.config.normalization_epsilon
        )
        identity_quaternion = torch.zeros_like(normalized_quaternion)
        identity_quaternion[:, 0] = 1.0
        normalized_quaternion = torch.where(
            quaternion_norm >= self.config.normalization_epsilon,
            normalized_quaternion,
            identity_quaternion,
        )
        normalized_quaternion = torch.where(
            normalized_quaternion[:, :1] < 0.0,
            -normalized_quaternion,
            normalized_quaternion,
        )

        features = torch.cat((velocity, normalized_quaternion, angular_velocity, action), dim=-1)
        normalized_features = (features - self.input_mean) / self.input_scale
        bounded_features = normalized_features.clamp(
            -self.config.input_clip, self.config.input_clip
        )
        normalized_acceleration = self.network(bounded_features)
        return normalized_acceleration * self.target_scale + self.target_mean

    def step(
        self,
        position: torch.Tensor,
        velocity: torch.Tensor,
        quaternion: torch.Tensor,
        angular_velocity: torch.Tensor,
        action: torch.Tensor,
        *,
        dt: float,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Advance translation with constant-acceleration integration.

        Acceleration is evaluated once at the current state.  Over ``dt`` the
        method applies ``p₁ = p₀ + v₀·dt + 0.5·a·dt²`` and
        ``v₁ = v₀ + a·dt``.  Attitude integration is deliberately outside this
        translational model.
        """

        if isinstance(dt, bool):
            raise TypeError("dt must be a finite positive number")
        try:
            time_step = float(dt)
        except (TypeError, ValueError) as error:
            raise ValueError("dt must be finite and positive") from error
        if not math.isfinite(time_step) or time_step <= 0.0:
            raise ValueError("dt must be finite and positive")

        self._validate_single_tensor("position", position, 3, self.input_mean)
        if position.shape[0] != velocity.shape[0]:
            raise ValueError("position and velocity must have the same batch size")
        predicted_acceleration = self.acceleration(velocity, quaternion, angular_velocity, action)
        next_position = (
            position + velocity * time_step + 0.5 * predicted_acceleration * time_step * time_step
        )
        next_velocity = velocity + predicted_acceleration * time_step
        return next_position, next_velocity

    def _validate_inputs(
        self,
        velocity: torch.Tensor,
        quaternion: torch.Tensor,
        angular_velocity: torch.Tensor,
        action: torch.Tensor,
    ) -> None:
        batch = velocity.shape[0] if isinstance(velocity, torch.Tensor) else -1
        expected = (
            ("velocity", velocity, 3),
            ("quaternion", quaternion, 4),
            ("angular_velocity", angular_velocity, 3),
            ("action", action, 4),
        )
        for name, tensor, width in expected:
            self._validate_single_tensor(name, tensor, width, self.input_mean)
            if tensor.shape[0] != batch:
                raise ValueError("dynamics inputs must have the same batch size")

    def _validate_single_tensor(
        self,
        name: str,
        tensor: torch.Tensor,
        width: int,
        reference: torch.Tensor,
    ) -> None:
        if not isinstance(tensor, torch.Tensor):
            raise TypeError(f"{name} must be a torch.Tensor")
        if tensor.ndim != 2 or tensor.shape[1] != width:
            raise ValueError(f"{name} must have shape [N, {width}]")
        if not tensor.is_floating_point():
            raise TypeError(f"{name} must be floating-point")
        if tensor.device != reference.device or tensor.dtype != reference.dtype:
            raise ValueError(
                f"{name} dtype and device must match the model "
                f"({reference.dtype}, {reference.device})"
            )
        if self.config.check_finite_inputs and not bool(torch.isfinite(tensor).all()):
            raise ValueError(f"{name} must be finite")
