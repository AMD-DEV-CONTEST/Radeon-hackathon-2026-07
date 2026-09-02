"""Frozen causal inertial state propagation.

The estimator combines a one-step world-frame acceleration prior with native
body-frame specific force and angular-rate measurements.  Initialization is a
single explicit freeze boundary.  After that boundary, the only mutable inputs
are the acceleration prior and inertial measurements for the current
transition.

This module defines a narrow data boundary, not a provenance proof.  The caller
is responsible for constructing the prior from the deployed model and for
passing only observations available to the deployed policy.  Simulator wiring,
sensor reads, and evaluation-arm selection deliberately live outside this
CPU-testable core.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from torch import nn

from flightguard.imu import quaternion_multiply, rotation_vector_to_quaternion


@dataclass(frozen=True)
class FrozenCausalIMUConfig:
    """Numerical settings for :class:`FrozenCausalIMUState`."""

    correction_gain: float = 1.0
    innovation_clip_mps2: float | None = 5.0
    prior_quarantine_enabled: bool = False
    gravity_world_mps2: tuple[float, float, float] = (0.0, 0.0, -9.81)
    accelerometer_bias_body_mps2: tuple[float, float, float] = (0.0, 0.0, 0.0)
    quaternion_epsilon: float = 1.0e-8

    def __post_init__(self) -> None:
        if not math.isfinite(self.correction_gain) or not 0.0 <= self.correction_gain <= 1.0:
            raise ValueError("correction_gain must be finite and lie in [0, 1]")
        if self.innovation_clip_mps2 is not None and (
            not math.isfinite(self.innovation_clip_mps2) or self.innovation_clip_mps2 <= 0.0
        ):
            raise ValueError("innovation_clip_mps2 must be None or finite and positive")
        if not isinstance(self.prior_quarantine_enabled, bool):
            raise TypeError("prior_quarantine_enabled must be bool")
        for name, values in (
            ("gravity_world_mps2", self.gravity_world_mps2),
            ("accelerometer_bias_body_mps2", self.accelerometer_bias_body_mps2),
        ):
            if len(values) != 3 or not all(math.isfinite(float(value)) for value in values):
                raise ValueError(f"{name} must contain three finite values")
        if not math.isfinite(self.quaternion_epsilon) or self.quaternion_epsilon <= 0.0:
            raise ValueError("quaternion_epsilon must be finite and positive")


@dataclass(frozen=True)
class CausalIMUPolicyState:
    """Immutable container of cloned policy inputs and their terminal mask."""

    position: torch.Tensor
    quaternion: torch.Tensor
    velocity: torch.Tensor
    angular_velocity_world: torch.Tensor
    dead: torch.Tensor


def _quaternion_to_rotation_matrix(quaternion: torch.Tensor) -> torch.Tensor:
    """Return body-to-world rotation matrices for normalized ``[w, x, y, z]``."""

    w, x, y, z = quaternion.unbind(dim=1)
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
        dim=1,
    ).reshape(-1, 3, 3)


class FrozenCausalIMUState(nn.Module):
    """Batched causal inertial state with no learned parameters.

    The call order for each transition is ``prepare_transition`` followed by
    ``commit_measurement``.  ``policy_state`` exposes cloned tensors and a
    cloned dead mask in an immutable :class:`CausalIMUPolicyState` container.
    A dead lane retains its last finite state for every subsequent call.

    ``correction_gain == 0`` is a strict disabled arm.  A committed transition
    returns the cached acceleration prior bit-for-bit, does not inspect the
    numerical contents of either inertial measurement, and leaves every field
    returned by ``policy_state`` bit-for-bit unchanged.  This arm is intended
    for structural no-op tests; it is a held snapshot rather than a propagating
    inertial baseline.

    ``correction_gain == 1`` with ``innovation_clip_mps2 is None`` is the raw
    trapezoidal strapdown arm.  A finite clip selects the bounded-innovation
    arm, including when the gain is one.
    """

    def __init__(
        self,
        batch_size: int,
        *,
        device: torch.device | str,
        dtype: torch.dtype = torch.float32,
        config: FrozenCausalIMUConfig | None = None,
    ) -> None:
        super().__init__()
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
        if not dtype.is_floating_point:
            raise TypeError("dtype must be floating-point")
        self.batch_size = batch_size
        self.config = config or FrozenCausalIMUConfig()
        resolved_device = torch.device(device)

        def zeros(*shape: int, tensor_dtype: torch.dtype = dtype) -> torch.Tensor:
            return torch.zeros(shape, device=resolved_device, dtype=tensor_dtype)

        self.register_buffer(
            "gravity_world",
            torch.tensor(
                self.config.gravity_world_mps2,
                device=resolved_device,
                dtype=dtype,
            ),
        )
        self.register_buffer("position", zeros(batch_size, 3))
        self.register_buffer("velocity", zeros(batch_size, 3))
        self.register_buffer("quaternion", zeros(batch_size, 4))
        self.quaternion[:, 0] = 1.0
        self.register_buffer("angular_velocity_world", zeros(batch_size, 3))
        self.register_buffer("previous_specific_force_body", zeros(batch_size, 3))
        self.register_buffer("previous_angular_velocity_body", zeros(batch_size, 3))
        self.register_buffer(
            "accelerometer_bias_body",
            torch.tensor(
                self.config.accelerometer_bias_body_mps2,
                device=resolved_device,
                dtype=dtype,
            )
            .view(1, 3)
            .expand(batch_size, -1)
            .clone(),
        )
        self.register_buffer(
            "correction_gain",
            torch.full(
                (batch_size, 1),
                self.config.correction_gain,
                device=resolved_device,
                dtype=dtype,
            ),
        )
        self.register_buffer("innovation_norm", zeros(batch_size))
        self.register_buffer("prior_quarantine_bound", zeros(batch_size))
        self.register_buffer(
            "newly_prior_quarantined",
            zeros(batch_size, tensor_dtype=torch.bool),
        )
        self.register_buffer(
            "prior_quarantined",
            zeros(batch_size, tensor_dtype=torch.bool),
        )
        self.register_buffer(
            "prior_quarantine_count",
            zeros(batch_size, tensor_dtype=torch.long),
        )
        self.register_buffer("last_acceleration_world", zeros(batch_size, 3))
        self.register_buffer("pending_prior_acceleration", zeros(batch_size, 3))
        self.register_buffer(
            "pending_prior_finite",
            zeros(batch_size, tensor_dtype=torch.bool),
        )
        self.register_buffer("dead", zeros(batch_size, tensor_dtype=torch.bool))
        self.register_buffer(
            "frozen",
            torch.tensor(False, device=resolved_device, dtype=torch.bool),
        )
        self.register_buffer(
            "transition_pending",
            torch.tensor(False, device=resolved_device, dtype=torch.bool),
        )
        self.register_buffer(
            "transition_count",
            torch.tensor(0, device=resolved_device, dtype=torch.long),
        )
        self.register_buffer(
            "invalid_measurement_count",
            torch.tensor(0, device=resolved_device, dtype=torch.long),
        )
        self.register_buffer(
            "post_freeze_update_attempts",
            torch.tensor(0, device=resolved_device, dtype=torch.long),
        )
        self.register_buffer(
            "post_freeze_quarantine_bound_update_attempts",
            torch.tensor(0, device=resolved_device, dtype=torch.long),
        )

    @property
    def device(self) -> torch.device:
        return self.gravity_world.device

    @property
    def dtype(self) -> torch.dtype:
        return self.gravity_world.dtype

    @torch.no_grad()
    def freeze(
        self,
        position: torch.Tensor,
        velocity: torch.Tensor,
        quaternion: torch.Tensor,
        specific_force_body: torch.Tensor,
        angular_velocity_body: torch.Tensor,
        *,
        accelerometer_bias_body: torch.Tensor | None = None,
        correction_gain: torch.Tensor | float | None = None,
        frozen_residual_quantile_mps2: torch.Tensor | None = None,
    ) -> None:
        """Initialize the last visible state and close the initialization boundary."""

        if bool(self.frozen.item()):
            self.post_freeze_update_attempts.add_(1)
            if frozen_residual_quantile_mps2 is not None:
                self.post_freeze_quarantine_bound_update_attempts.add_(1)
            raise RuntimeError("causal IMU state is already frozen")
        self._validate_matrix("position", position, 3)
        self._validate_matrix("velocity", velocity, 3)
        self._validate_matrix("quaternion", quaternion, 4)
        self._validate_matrix("specific_force_body", specific_force_body, 3)
        self._validate_matrix("angular_velocity_body", angular_velocity_body, 3)
        bias = self._resolve_bias(accelerometer_bias_body)
        gain = self._resolve_gain(correction_gain)
        quarantine_bound = self._resolve_quarantine_bound(frozen_residual_quantile_mps2)

        normalized_quaternion, quaternion_valid = self._normalize_quaternion(quaternion)
        disabled = gain[:, 0] == 0.0
        inertial_finite = torch.isfinite(specific_force_body).all(dim=1) & torch.isfinite(
            angular_velocity_body
        ).all(dim=1)
        finite = (
            torch.isfinite(position).all(dim=1)
            & torch.isfinite(velocity).all(dim=1)
            & quaternion_valid
            & torch.isfinite(bias).all(dim=1)
            & torch.isfinite(gain).all(dim=1)
            & (disabled | inertial_finite)
        )
        identity = torch.zeros_like(quaternion)
        identity[:, 0] = 1.0

        self.position.copy_(torch.where(finite[:, None], position, torch.zeros_like(position)))
        self.velocity.copy_(torch.where(finite[:, None], velocity, torch.zeros_like(velocity)))
        self.quaternion.copy_(torch.where(finite[:, None], normalized_quaternion, identity))
        self.previous_specific_force_body.copy_(
            torch.where(
                (finite & ~disabled)[:, None],
                specific_force_body,
                torch.zeros_like(specific_force_body),
            )
        )
        self.previous_angular_velocity_body.copy_(
            torch.where(
                (finite & ~disabled)[:, None],
                angular_velocity_body,
                torch.zeros_like(angular_velocity_body),
            )
        )
        self.accelerometer_bias_body.copy_(
            torch.where(finite[:, None], bias, torch.zeros_like(bias))
        )
        self.correction_gain.copy_(torch.where(finite[:, None], gain, torch.zeros_like(gain)))
        self.prior_quarantine_bound.copy_(quarantine_bound)
        rotation = _quaternion_to_rotation_matrix(self.quaternion)
        initial_world_rate = (rotation @ self.previous_angular_velocity_body.unsqueeze(2)).squeeze(
            2
        )
        self.angular_velocity_world.copy_(
            torch.where(
                (finite & ~disabled)[:, None],
                initial_world_rate,
                torch.zeros_like(initial_world_rate),
            )
        )
        self.dead.copy_(~finite)
        self.invalid_measurement_count.copy_((~finite).sum())
        self.frozen.fill_(True)

    @torch.no_grad()
    def prepare_transition(self, prior_acceleration: torch.Tensor) -> None:
        """Cache the one-step world-frame acceleration prior."""

        if not bool(self.frozen.item()):
            raise RuntimeError("causal IMU state must be frozen before propagation")
        if bool(self.transition_pending.item()):
            raise RuntimeError("the previous transition has not been committed")
        self._validate_matrix("prior_acceleration", prior_acceleration, 3)
        finite = torch.isfinite(prior_acceleration).all(dim=1)
        self.pending_prior_acceleration.copy_(
            torch.where(finite[:, None], prior_acceleration, torch.zeros_like(prior_acceleration))
        )
        self.pending_prior_finite.copy_(finite)
        self.transition_pending.fill_(True)

    @torch.no_grad()
    def commit_measurement(
        self,
        specific_force_body: torch.Tensor,
        angular_velocity_body: torch.Tensor,
        *,
        dt: float,
        mask: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """Commit one inertial sample and return the corrected world acceleration.

        Tensor metadata, ``dt``, and ``mask`` are validated in every arm.  The
        disabled arm deliberately ignores inertial tensor values after that
        structural validation.
        """

        if not bool(self.frozen.item()):
            raise RuntimeError("causal IMU state must be frozen before propagation")
        if not bool(self.transition_pending.item()):
            raise RuntimeError("prepare_transition must precede commit_measurement")
        self._validate_matrix("specific_force_body", specific_force_body, 3)
        self._validate_matrix("angular_velocity_body", angular_velocity_body, 3)
        time_step = self._validate_dt(dt)
        active = self._resolve_mask(mask)
        self.innovation_norm.zero_()
        self.newly_prior_quarantined.zero_()
        requested = active & ~self.dead
        disabled = self.correction_gain[:, 0] == 0.0
        _, stored_quaternion_valid = self._normalize_quaternion(self.quaternion)
        stored_state_finite = (
            torch.isfinite(self.position).all(dim=1)
            & torch.isfinite(self.velocity).all(dim=1)
            & stored_quaternion_valid
            & torch.isfinite(self.angular_velocity_world).all(dim=1)
            & torch.isfinite(self.last_acceleration_world).all(dim=1)
            & torch.isfinite(self.correction_gain).all(dim=1)
        )
        disabled_valid = requested & disabled & self.pending_prior_finite & stored_state_finite
        enabled_finite = (
            self.pending_prior_finite
            & torch.isfinite(specific_force_body).all(dim=1)
            & torch.isfinite(angular_velocity_body).all(dim=1)
            & stored_state_finite
            & torch.isfinite(self.previous_specific_force_body).all(dim=1)
            & torch.isfinite(self.previous_angular_velocity_body).all(dim=1)
            & torch.isfinite(self.accelerometer_bias_body).all(dim=1)
        )
        enabled_valid = requested & ~disabled & enabled_finite
        valid = disabled_valid | enabled_valid
        invalid = requested & ~valid
        self.dead.logical_or_(invalid)
        self.invalid_measurement_count.add_(invalid.sum())

        if bool(disabled_valid.any()):
            disabled_index = torch.nonzero(disabled_valid, as_tuple=False)[:, 0]
            self.last_acceleration_world[disabled_index] = self.pending_prior_acceleration[
                disabled_index
            ]

        if bool(enabled_valid.any()):
            index = torch.nonzero(enabled_valid, as_tuple=False)[:, 0]
            old_quaternion = self.quaternion[index]
            old_velocity = self.velocity[index]
            old_position = self.position[index]
            old_specific_force = self.previous_specific_force_body[index]
            old_angular_velocity = self.previous_angular_velocity_body[index]
            new_specific_force = specific_force_body[index]
            new_angular_velocity = angular_velocity_body[index]
            bias = self.accelerometer_bias_body[index]
            prior = self.pending_prior_acceleration[index]
            gain = self.correction_gain[index]

            mean_angular_velocity = 0.5 * (old_angular_velocity + new_angular_velocity)
            delta_quaternion = rotation_vector_to_quaternion(mean_angular_velocity * time_step)
            raw_next_quaternion = quaternion_multiply(old_quaternion, delta_quaternion)
            next_quaternion, next_finite = self._normalize_quaternion(raw_next_quaternion)
            same_hemisphere = (next_quaternion * old_quaternion).sum(dim=1, keepdim=True) >= 0.0
            next_quaternion = torch.where(
                same_hemisphere,
                next_quaternion,
                -next_quaternion,
            )

            old_rotation = _quaternion_to_rotation_matrix(old_quaternion)
            next_rotation = _quaternion_to_rotation_matrix(next_quaternion)
            old_inertial_acceleration = (
                old_rotation @ (old_specific_force - bias).unsqueeze(2)
            ).squeeze(2) + self.gravity_world
            next_inertial_acceleration = (
                next_rotation @ (new_specific_force - bias).unsqueeze(2)
            ).squeeze(2) + self.gravity_world
            inertial_acceleration = 0.5 * (old_inertial_acceleration + next_inertial_acceleration)
            numerical_finite = next_finite & torch.isfinite(inertial_acceleration).all(dim=1)

            innovation = inertial_acceleration - prior
            innovation_norm = torch.linalg.vector_norm(
                innovation,
                dim=1,
                keepdim=True,
            )
            finite_innovation_norm = torch.isfinite(innovation_norm[:, 0])
            self.innovation_norm[index] = innovation_norm[:, 0]
            if self.config.prior_quarantine_enabled:
                quarantine_candidate = (
                    ~self.prior_quarantined[index]
                    & finite_innovation_norm
                    & (innovation_norm[:, 0] > self.prior_quarantine_bound[index])
                )
                quarantine_for_commit = (
                    self.prior_quarantined[index] | quarantine_candidate
                )
            else:
                quarantine_candidate = torch.zeros_like(finite_innovation_norm)
                quarantine_for_commit = torch.zeros_like(finite_innovation_norm)
            if self.config.prior_quarantine_enabled:
                numerical_finite &= finite_innovation_norm
            if self.config.innovation_clip_mps2 is None:
                clipped_innovation = innovation
                exact_strapdown = gain[:, 0] == 1.0
            else:
                scale = (
                    self.config.innovation_clip_mps2
                    / innovation_norm.clamp_min(torch.finfo(self.dtype).tiny)
                ).clamp_max(1.0)
                clipped_innovation = innovation * scale
                exact_strapdown = (gain[:, 0] == 1.0) & (
                    innovation_norm[:, 0] <= self.config.innovation_clip_mps2
                )
            corrected_fused = prior + gain * clipped_innovation
            corrected_acceleration = torch.where(
                exact_strapdown[:, None],
                inertial_acceleration,
                corrected_fused,
            )
            corrected_acceleration = torch.where(
                quarantine_for_commit[:, None],
                inertial_acceleration,
                corrected_acceleration,
            )

            next_velocity = old_velocity + corrected_acceleration * time_step
            next_position = (
                old_position
                + old_velocity * time_step
                + 0.5 * corrected_acceleration * time_step * time_step
            )
            next_world_rate = (next_rotation @ new_angular_velocity.unsqueeze(2)).squeeze(2)
            numerical_finite &= (
                torch.isfinite(corrected_acceleration).all(dim=1)
                & torch.isfinite(next_velocity).all(dim=1)
                & torch.isfinite(next_position).all(dim=1)
                & torch.isfinite(next_world_rate).all(dim=1)
            )
            accepted_index = index[numerical_finite]
            rejected_index = index[~numerical_finite]
            if rejected_index.numel():
                self.dead[rejected_index] = True
                self.invalid_measurement_count.add_(rejected_index.numel())
            if accepted_index.numel():
                accepted = numerical_finite
                accepted_quarantine_candidate = quarantine_candidate[accepted]
                self.newly_prior_quarantined[accepted_index] = accepted_quarantine_candidate
                self.prior_quarantined[accepted_index] |= accepted_quarantine_candidate
                self.prior_quarantine_count[accepted_index] += (
                    accepted_quarantine_candidate.to(torch.long)
                )
                self.position[accepted_index] = next_position[accepted]
                self.velocity[accepted_index] = next_velocity[accepted]
                self.quaternion[accepted_index] = next_quaternion[accepted]
                self.angular_velocity_world[accepted_index] = next_world_rate[accepted]
                self.previous_specific_force_body[accepted_index] = new_specific_force[accepted]
                self.previous_angular_velocity_body[accepted_index] = new_angular_velocity[accepted]
                self.last_acceleration_world[accepted_index] = corrected_acceleration[accepted]

        self.pending_prior_acceleration.zero_()
        self.pending_prior_finite.zero_()
        self.transition_pending.fill_(False)
        self.transition_count.add_(1)
        return self.last_acceleration_world.clone()

    def policy_state(self) -> CausalIMUPolicyState:
        """Return cloned finite policy inputs and a cloned terminal mask."""

        if not bool(self.frozen.item()):
            raise RuntimeError("causal IMU state must be frozen before policy access")
        return CausalIMUPolicyState(
            position=self.position.clone(),
            quaternion=self.quaternion.clone(),
            velocity=self.velocity.clone(),
            angular_velocity_world=self.angular_velocity_world.clone(),
            dead=self.dead.clone(),
        )

    def _resolve_bias(self, value: torch.Tensor | None) -> torch.Tensor:
        if value is None:
            return self.accelerometer_bias_body.clone()
        if not isinstance(value, torch.Tensor):
            raise TypeError("accelerometer_bias_body must be a torch.Tensor")
        if value.shape == (3,):
            value = value.unsqueeze(0).expand(self.batch_size, -1)
        self._validate_matrix("accelerometer_bias_body", value, 3)
        return value

    def _resolve_gain(self, value: torch.Tensor | float | None) -> torch.Tensor:
        if value is None:
            return self.correction_gain.clone()
        if isinstance(value, bool):
            raise TypeError("correction_gain must be numeric or a torch.Tensor")
        if isinstance(value, (int, float)):
            value = torch.full(
                (self.batch_size, 1),
                float(value),
                device=self.device,
                dtype=self.dtype,
            )
        elif isinstance(value, torch.Tensor):
            if value.shape == (self.batch_size,):
                value = value[:, None]
            if value.shape != (self.batch_size, 1):
                raise ValueError("correction_gain must have shape [B] or [B, 1]")
            if value.device != self.device or value.dtype != self.dtype:
                raise ValueError("correction_gain dtype and device must match the causal IMU state")
        else:
            raise TypeError("correction_gain must be numeric or a torch.Tensor")
        if not bool(torch.isfinite(value).all()) or not bool(
            ((value >= 0.0) & (value <= 1.0)).all()
        ):
            raise ValueError("correction_gain must be finite and lie in [0, 1]")
        return value

    def _resolve_quarantine_bound(self, value: torch.Tensor | None) -> torch.Tensor:
        if value is None:
            if self.config.prior_quarantine_enabled:
                raise ValueError(
                    "frozen_residual_quantile_mps2 is required when prior quarantine is enabled"
                )
            return torch.zeros(self.batch_size, device=self.device, dtype=self.dtype)
        if not isinstance(value, torch.Tensor):
            raise TypeError("frozen_residual_quantile_mps2 must be a torch.Tensor")
        if value.shape == (self.batch_size, 1):
            value = value[:, 0]
        if value.shape != (self.batch_size,):
            raise ValueError("frozen_residual_quantile_mps2 must have shape [B] or [B, 1]")
        if value.device != self.device or value.dtype != self.dtype:
            raise ValueError(
                "frozen_residual_quantile_mps2 dtype and device must match the causal IMU state"
            )
        if not bool(torch.isfinite(value).all()) or not bool((value >= 0.0).all()):
            raise ValueError("frozen_residual_quantile_mps2 must be finite and nonnegative")
        return value

    def _resolve_mask(self, mask: torch.Tensor | None) -> torch.Tensor:
        if mask is None:
            return torch.ones(self.batch_size, device=self.device, dtype=torch.bool)
        if (
            not isinstance(mask, torch.Tensor)
            or mask.shape != (self.batch_size,)
            or mask.dtype != torch.bool
            or mask.device != self.device
        ):
            raise ValueError("mask must be a bool tensor with shape [B] on state device")
        return mask

    def _normalize_quaternion(
        self,
        quaternion: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Normalize finite rows and return an explicit per-row validity mask."""

        raw_norm = torch.linalg.vector_norm(quaternion, dim=1, keepdim=True)
        raw_valid = (
            torch.isfinite(quaternion).all(dim=1)
            & torch.isfinite(raw_norm[:, 0])
            & (raw_norm[:, 0] >= self.config.quaternion_epsilon)
        )
        safe_norm = torch.where(
            raw_valid[:, None],
            raw_norm,
            torch.ones_like(raw_norm),
        )
        normalized = quaternion / safe_norm
        normalized_norm = torch.linalg.vector_norm(normalized, dim=1)
        tolerance = 64.0 * torch.finfo(self.dtype).eps
        normalized_valid = (
            raw_valid
            & torch.isfinite(normalized).all(dim=1)
            & torch.isfinite(normalized_norm)
            & ((normalized_norm - 1.0).abs() <= tolerance)
        )
        identity = torch.zeros_like(quaternion)
        identity[:, 0] = 1.0
        return torch.where(normalized_valid[:, None], normalized, identity), normalized_valid

    def _validate_matrix(self, name: str, value: torch.Tensor, width: int) -> None:
        if not isinstance(value, torch.Tensor):
            raise TypeError(f"{name} must be a torch.Tensor")
        if value.shape != (self.batch_size, width):
            raise ValueError(f"{name} must have shape [B, {width}]")
        if not value.is_floating_point():
            raise TypeError(f"{name} must be floating-point")
        if value.device != self.device or value.dtype != self.dtype:
            raise ValueError(
                f"{name} dtype and device must match the causal IMU state "
                f"({self.dtype}, {self.device})"
            )

    @staticmethod
    def _validate_dt(dt: float) -> float:
        if isinstance(dt, bool):
            raise TypeError("dt must be a finite positive number")
        try:
            time_step = float(dt)
        except (TypeError, ValueError) as error:
            raise ValueError("dt must be finite and positive") from error
        if not math.isfinite(time_step) or time_step <= 0.0:
            raise ValueError("dt must be finite and positive")
        return time_step
