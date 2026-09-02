"""Causal, frozen online calibration for translational flight dynamics.

The adapter intentionally has no learned parameters.  Before a VIO dropout it
uses only observed velocity transitions, IMU state, and a local history of
issued motor commands to fit one control-authority correction and one
world-frame acceleration bias for every candidate integer actuator delay.
Candidate delays are scored on a later causal holdout window.  The selected
fit-window context is deployed only when it clears validation improvement
thresholds against an explicit causal no-op.  Otherwise the adapter freezes to
the exact ``d=0, gamma=0, bias=0`` fallback.  Neither path can consume
post-dropout truth.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import torch
from torch import nn

if TYPE_CHECKING:
    from flightguard.dynamics import FlightDynamicsModel


@dataclass(frozen=True)
class FrozenAffineDelayConfig:
    """Numerical and identifiability bounds for frozen causal calibration."""

    max_delay_steps: int = 10
    gravity_world_mps2: tuple[float, float, float] = (0.0, 0.0, -9.81)
    ridge: float = 0.05
    gamma_min: float = -0.60
    gamma_max: float = 0.60
    bias_abs_max_mps2: float = 1.50
    min_fit_samples: int = 100
    min_score_samples: int = 50
    min_excitation: float = 0.05
    delay_score_tolerance: float = 1.0e-4
    min_score_improvement_absolute: float = 1.0e-4
    min_score_improvement_relative: float = 0.05
    score_residual_quantile: float = 0.95
    max_score_samples: int = 512

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_delay_steps, bool)
            or not isinstance(self.max_delay_steps, int)
            or self.max_delay_steps < 0
        ):
            raise ValueError("max_delay_steps must be a non-negative integer")
        if len(self.gravity_world_mps2) != 3 or not all(
            math.isfinite(float(value)) for value in self.gravity_world_mps2
        ):
            raise ValueError("gravity_world_mps2 must contain three finite values")
        positive = {
            "ridge": self.ridge,
            "bias_abs_max_mps2": self.bias_abs_max_mps2,
            "min_excitation": self.min_excitation,
            "delay_score_tolerance": self.delay_score_tolerance,
            "min_score_improvement_absolute": (self.min_score_improvement_absolute),
            "min_score_improvement_relative": (self.min_score_improvement_relative),
        }
        for name, value in positive.items():
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if (
            not math.isfinite(self.gamma_min)
            or not math.isfinite(self.gamma_max)
            or self.gamma_min >= self.gamma_max
        ):
            raise ValueError("gamma bounds must be finite and increasing")
        for name, value in (
            ("min_fit_samples", self.min_fit_samples),
            ("min_score_samples", self.min_score_samples),
            ("max_score_samples", self.max_score_samples),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_score_samples < self.min_score_samples:
            raise ValueError("max_score_samples must cover min_score_samples")
        if (
            not math.isfinite(self.score_residual_quantile)
            or not 0.0 < self.score_residual_quantile <= 1.0
        ):
            raise ValueError("score_residual_quantile must lie in (0, 1]")


class FrozenAffineDelayContext(nn.Module):
    """Per-environment causal calibration state with zero learned parameters.

    Call order for transition ``t`` is:

    1. ``push_issued(u_t)``;
    2. before dropout, step the plant and call ``observe_transition``;
    3. call ``begin_scoring`` between the fit and score windows;
    4. call ``freeze`` exactly at the dropout boundary;
    5. during dropout, call ``predict_acceleration`` before stepping the plant.

    No method accepts applied motor commands, domain labels, or latent simulator
    parameters.
    """

    def __init__(
        self,
        batch_size: int,
        *,
        device: torch.device | str,
        dtype: torch.dtype = torch.float32,
        config: FrozenAffineDelayConfig | None = None,
    ) -> None:
        super().__init__()
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
        if not dtype.is_floating_point:
            raise TypeError("dtype must be floating-point")
        self.batch_size = batch_size
        self.config = config or FrozenAffineDelayConfig()
        self.candidate_count = self.config.max_delay_steps + 1
        resolved_device = torch.device(device)

        def zeros(*shape: int, tensor_dtype: torch.dtype = dtype) -> torch.Tensor:
            return torch.zeros(shape, device=resolved_device, dtype=tensor_dtype)

        self.register_buffer(
            "gravity",
            torch.tensor(
                self.config.gravity_world_mps2,
                device=resolved_device,
                dtype=dtype,
            ),
        )
        self.register_buffer(
            "issued_history",
            zeros(self.candidate_count, batch_size, 4),
        )
        self.register_buffer(
            "issued_cursor",
            torch.tensor(-1, device=resolved_device, dtype=torch.long),
        )

        for prefix in ("fit", "all"):
            self.register_buffer(f"{prefix}_count", zeros(batch_size))
            self.register_buffer(
                f"{prefix}_sum_phi",
                zeros(batch_size, self.candidate_count, 3),
            )
            self.register_buffer(
                f"{prefix}_sum_residual",
                zeros(batch_size, self.candidate_count, 3),
            )
            self.register_buffer(
                f"{prefix}_sum_phi2",
                zeros(batch_size, self.candidate_count),
            )
            self.register_buffer(
                f"{prefix}_sum_cross",
                zeros(batch_size, self.candidate_count),
            )

        self.register_buffer(
            "score_gamma",
            zeros(batch_size, self.candidate_count),
        )
        self.register_buffer(
            "score_bias",
            zeros(batch_size, self.candidate_count, 3),
        )
        self.register_buffer(
            "score_excitation",
            zeros(batch_size, self.candidate_count),
        )
        self.register_buffer(
            "score_sse",
            zeros(batch_size, self.candidate_count),
        )
        self.register_buffer("score_noop_sse", zeros(batch_size))
        self.register_buffer("score_count", zeros(batch_size))
        self.register_buffer(
            "score_error_norm_samples",
            torch.full(
                (
                    batch_size,
                    self.candidate_count,
                    self.config.max_score_samples,
                ),
                float("inf"),
                device=resolved_device,
                dtype=dtype,
            ),
        )
        self.register_buffer(
            "score_noop_error_norm_samples",
            torch.full(
                (batch_size, self.config.max_score_samples),
                float("inf"),
                device=resolved_device,
                dtype=dtype,
            ),
        )
        self.register_buffer(
            "score_observation_index",
            torch.tensor(0, device=resolved_device, dtype=torch.long),
        )
        self.register_buffer(
            "scoring_started",
            torch.tensor(False, device=resolved_device, dtype=torch.bool),
        )
        self.register_buffer(
            "frozen",
            torch.tensor(False, device=resolved_device, dtype=torch.bool),
        )
        self.register_buffer(
            "post_freeze_update_attempts",
            torch.tensor(0, device=resolved_device, dtype=torch.long),
        )
        self.register_buffer(
            "invalid_observation",
            zeros(batch_size, tensor_dtype=torch.bool),
        )

        self.register_buffer(
            "selected_delay",
            zeros(batch_size, tensor_dtype=torch.long),
        )
        self.register_buffer("selected_gamma", zeros(batch_size, 1))
        self.register_buffer("selected_bias", zeros(batch_size, 3))
        self.register_buffer(
            "selected_valid",
            zeros(batch_size, tensor_dtype=torch.bool),
        )
        self.register_buffer(
            "selected_score_mse",
            torch.full(
                (batch_size,),
                float("inf"),
                device=resolved_device,
                dtype=dtype,
            ),
        )
        self.register_buffer(
            "selected_score_margin",
            zeros(batch_size),
        )
        self.register_buffer(
            "selected_excitation",
            zeros(batch_size),
        )
        self.register_buffer(
            "selected_corrected_score_mse",
            zeros(batch_size),
        )
        self.register_buffer("noop_score_mse", zeros(batch_size))
        self.register_buffer(
            "score_improvement_absolute",
            zeros(batch_size),
        )
        self.register_buffer(
            "score_improvement_relative",
            zeros(batch_size),
        )
        self.register_buffer(
            "noop_fallback",
            zeros(batch_size, tensor_dtype=torch.bool),
        )
        self.register_buffer(
            "selected_residual_quantile_mps2",
            torch.full(
                (batch_size,),
                float("inf"),
                device=resolved_device,
                dtype=dtype,
            ),
        )

    @property
    def device(self) -> torch.device:
        return self.gravity.device

    @property
    def dtype(self) -> torch.dtype:
        return self.gravity.dtype

    def push_issued(self, action: torch.Tensor) -> None:
        """Append the issued command for the current transition."""

        self._validate_matrix("action", action, 4)
        cursor = (int(self.issued_cursor.item()) + 1) % self.candidate_count
        self.issued_history[cursor].copy_(action)
        self.issued_cursor.fill_(cursor)

    def delayed_actions(self) -> torch.Tensor:
        """Return candidate commands ``u[t-d]`` as ``[B, D, 4]``."""

        cursor = int(self.issued_cursor.item())
        if cursor < 0:
            return torch.zeros(
                (self.batch_size, self.candidate_count, 4),
                device=self.device,
                dtype=self.dtype,
            )
        delays = torch.arange(
            self.candidate_count,
            device=self.device,
            dtype=torch.long,
        )
        indices = (cursor - delays) % self.candidate_count
        return self.issued_history[indices].permute(1, 0, 2)

    def begin_scoring(self) -> None:
        """Freeze fit-window coefficients used only for causal delay scoring."""

        if bool(self.frozen.item()):
            raise RuntimeError("cannot begin scoring after context freeze")
        if bool(self.scoring_started.item()):
            raise RuntimeError("scoring has already started")
        gamma, bias, excitation = self._coefficients("fit")
        self.score_gamma.copy_(gamma)
        self.score_bias.copy_(bias)
        self.score_excitation.copy_(excitation)
        self.scoring_started.fill_(True)

    @torch.no_grad()
    def observe_transition(
        self,
        model: FlightDynamicsModel,
        velocity: torch.Tensor,
        quaternion: torch.Tensor,
        angular_velocity: torch.Tensor,
        next_velocity: torch.Tensor,
        *,
        dt: float,
        phase: Literal["fit", "score"],
        mask: torch.Tensor | None = None,
    ) -> None:
        """Update causal statistics from one visible velocity transition."""

        if bool(self.frozen.item()):
            self.post_freeze_update_attempts.add_(1)
            raise RuntimeError("frozen context cannot consume new observations")
        if phase not in ("fit", "score"):
            raise ValueError("phase must be 'fit' or 'score'")
        if phase == "score" and not bool(self.scoring_started.item()):
            raise RuntimeError("begin_scoring must be called before score updates")
        if phase == "fit" and bool(self.scoring_started.item()):
            raise RuntimeError("fit updates cannot occur after scoring starts")
        time_step = self._validate_dt(dt)
        self._validate_matrix("velocity", velocity, 3)
        self._validate_matrix("quaternion", quaternion, 4)
        self._validate_matrix("angular_velocity", angular_velocity, 3)
        self._validate_matrix("next_velocity", next_velocity, 3)
        if mask is None:
            valid = torch.ones(
                self.batch_size,
                device=self.device,
                dtype=torch.bool,
            )
        else:
            if (
                not isinstance(mask, torch.Tensor)
                or mask.shape != (self.batch_size,)
                or mask.dtype != torch.bool
                or mask.device != self.device
            ):
                raise ValueError("mask must be a bool tensor with shape [B] on context device")
            valid = mask.clone()
        requested = valid.clone()

        finite_inputs = (
            torch.isfinite(velocity).all(dim=1)
            & torch.isfinite(quaternion).all(dim=1)
            & torch.isfinite(angular_velocity).all(dim=1)
            & torch.isfinite(next_velocity).all(dim=1)
        )
        self.invalid_observation.logical_or_(requested & ~finite_inputs)
        valid &= finite_inputs
        safe_velocity = torch.where(
            valid[:, None],
            velocity,
            torch.zeros_like(velocity),
        )
        identity_quaternion = torch.zeros_like(quaternion)
        identity_quaternion[:, 0] = 1.0
        safe_quaternion = torch.where(
            valid[:, None],
            quaternion,
            identity_quaternion,
        )
        safe_angular_velocity = torch.where(
            valid[:, None],
            angular_velocity,
            torch.zeros_like(angular_velocity),
        )
        safe_next_velocity = torch.where(
            valid[:, None],
            next_velocity,
            safe_velocity,
        )
        prediction = self._candidate_predictions(
            model,
            safe_velocity,
            safe_quaternion,
            safe_angular_velocity,
        )
        observed = (safe_next_velocity - safe_velocity) / time_step
        finite_outputs = torch.isfinite(observed).all(dim=1) & torch.isfinite(prediction).all(
            dim=(1, 2)
        )
        self.invalid_observation.logical_or_(requested & ~finite_outputs)
        valid &= finite_outputs
        phi = prediction - self.gravity.view(1, 1, 3)
        residual = observed[:, None, :] - prediction
        phi = torch.where(valid[:, None, None], phi, torch.zeros_like(phi))
        residual = torch.where(
            valid[:, None, None],
            residual,
            torch.zeros_like(residual),
        )

        if phase == "score":
            sample_index = int(self.score_observation_index.item())
            if sample_index >= self.config.max_score_samples:
                raise RuntimeError("score window exceeds configured max_score_samples")
            corrected = prediction + self.score_gamma[:, :, None] * phi + self.score_bias
            squared_error = (corrected - observed[:, None, :]).square().sum(dim=2)
            squared_error = torch.where(
                valid[:, None],
                squared_error,
                torch.zeros_like(squared_error),
            )
            self.score_sse.add_(squared_error)
            noop_squared_error = (prediction[:, 0] - observed).square().sum(dim=1)
            noop_squared_error = torch.where(
                valid,
                noop_squared_error,
                torch.zeros_like(noop_squared_error),
            )
            self.score_noop_sse.add_(noop_squared_error)
            self.score_count.add_(valid.to(self.dtype))
            candidate_error_norm = torch.sqrt(squared_error.clamp_min(0.0))
            noop_error_norm = torch.sqrt(noop_squared_error.clamp_min(0.0))
            infinity_candidate = torch.full_like(candidate_error_norm, float("inf"))
            infinity_noop = torch.full_like(noop_error_norm, float("inf"))
            self.score_error_norm_samples[:, :, sample_index].copy_(
                torch.where(valid[:, None], candidate_error_norm, infinity_candidate)
            )
            self.score_noop_error_norm_samples[:, sample_index].copy_(
                torch.where(valid, noop_error_norm, infinity_noop)
            )
            self.score_observation_index.add_(1)

        self._accumulate("all", phi, residual, valid)
        if phase == "fit":
            self._accumulate("fit", phi, residual, valid)

    @torch.no_grad()
    def freeze(self) -> None:
        """Deploy a validated fit-window correction or an exact causal no-op."""

        if bool(self.frozen.item()):
            raise RuntimeError("context is already frozen")
        if not bool(self.scoring_started.item()):
            raise RuntimeError("begin_scoring must be called before freeze")

        score_denominator = (self.score_count * 3.0).clamp_min(1.0)
        score_mse = self.score_sse / score_denominator[:, None]
        noop_score_mse = self.score_noop_sse / score_denominator
        noop_valid = (
            (self.fit_count >= self.config.min_fit_samples)
            & (self.score_count >= self.config.min_score_samples)
            & torch.isfinite(noop_score_mse)
            & ~self.invalid_observation
        )
        candidate_valid = (
            noop_valid[:, None]
            & (self.score_excitation >= self.config.min_excitation)
            & torch.isfinite(score_mse)
            & torch.isfinite(self.score_gamma)
            & torch.isfinite(self.score_bias).all(dim=2)
        )
        infinity = torch.full_like(score_mse, float("inf"))
        eligible_score = torch.where(candidate_valid, score_mse, infinity)
        best_score = eligible_score.min(dim=1).values
        within_tolerance = eligible_score <= best_score[:, None] + self.config.delay_score_tolerance
        delay_indices = torch.arange(
            self.candidate_count,
            device=self.device,
            dtype=torch.long,
        ).expand(self.batch_size, -1)
        invalid_delay = torch.full_like(delay_indices, self.candidate_count)
        chosen_delay = (
            torch.where(
                within_tolerance,
                delay_indices,
                invalid_delay,
            )
            .min(dim=1)
            .values
        )
        candidate_available = torch.isfinite(best_score) & (chosen_delay < self.candidate_count)
        safe_delay = torch.where(
            candidate_available,
            chosen_delay,
            torch.zeros_like(chosen_delay),
        )
        row = torch.arange(self.batch_size, device=self.device)

        sorted_scores = eligible_score.sort(dim=1).values
        if self.candidate_count > 1:
            margin = sorted_scores[:, 1] - sorted_scores[:, 0]
            margin = torch.where(torch.isfinite(margin), margin, torch.zeros_like(margin))
        else:
            margin = torch.zeros(self.batch_size, device=self.device, dtype=self.dtype)

        corrected_score = score_mse[row, safe_delay]
        corrected_score = torch.where(
            candidate_available,
            corrected_score,
            torch.zeros_like(corrected_score),
        )
        improvement_absolute = torch.where(
            candidate_available,
            noop_score_mse - corrected_score,
            torch.zeros_like(noop_score_mse),
        )
        improvement_relative = improvement_absolute / noop_score_mse.abs().clamp_min(
            torch.finfo(self.dtype).eps
        )
        improvement_relative = torch.nan_to_num(
            improvement_relative,
            nan=0.0,
            posinf=torch.finfo(self.dtype).max,
            neginf=-torch.finfo(self.dtype).max,
        )
        improvement_relative = torch.where(
            candidate_available,
            improvement_relative,
            torch.zeros_like(improvement_relative),
        )
        deploy_corrected = (
            candidate_available
            & (improvement_absolute >= self.config.min_score_improvement_absolute)
            & (improvement_relative >= self.config.min_score_improvement_relative)
        )
        fallback = noop_valid & ~deploy_corrected

        quantile_index = (
            torch.ceil(self.score_count * float(self.config.score_residual_quantile)).to(torch.long)
            - 1
        ).clamp(min=0, max=self.config.max_score_samples - 1)
        sorted_candidate_errors = self.score_error_norm_samples.sort(dim=2).values
        candidate_quantile = sorted_candidate_errors.gather(
            2,
            quantile_index[:, None, None].expand(-1, self.candidate_count, 1),
        ).squeeze(2)
        sorted_noop_errors = self.score_noop_error_norm_samples.sort(dim=1).values
        noop_quantile = sorted_noop_errors.gather(1, quantile_index[:, None]).squeeze(1)

        selected_gamma = self.score_gamma[row, safe_delay]
        selected_bias = self.score_bias[row, safe_delay]
        selected_excitation = self.score_excitation[row, safe_delay]
        applied_delay = torch.where(
            deploy_corrected,
            safe_delay,
            torch.zeros_like(safe_delay),
        )
        self.selected_delay.copy_(applied_delay)
        self.selected_gamma[:, 0].copy_(
            torch.where(
                deploy_corrected,
                selected_gamma,
                torch.zeros_like(selected_gamma),
            )
        )
        self.selected_bias.copy_(
            torch.where(
                deploy_corrected[:, None],
                selected_bias,
                torch.zeros_like(selected_bias),
            )
        )
        self.selected_valid.copy_(noop_valid)
        self.selected_score_mse.copy_(
            torch.where(
                noop_valid,
                torch.where(deploy_corrected, corrected_score, noop_score_mse),
                infinity[:, 0],
            )
        )
        self.selected_score_margin.copy_(
            torch.where(candidate_available, margin, torch.zeros_like(margin))
        )
        self.selected_excitation.copy_(
            torch.where(
                candidate_available,
                selected_excitation,
                torch.zeros_like(selected_excitation),
            )
        )
        self.selected_corrected_score_mse.copy_(corrected_score)
        self.noop_score_mse.copy_(
            torch.where(noop_valid, noop_score_mse, torch.zeros_like(noop_score_mse))
        )
        self.score_improvement_absolute.copy_(improvement_absolute)
        self.score_improvement_relative.copy_(improvement_relative)
        self.noop_fallback.copy_(fallback)
        selected_quantile = torch.where(
            deploy_corrected,
            candidate_quantile[row, safe_delay],
            noop_quantile,
        )
        self.selected_residual_quantile_mps2.copy_(
            torch.where(
                noop_valid,
                selected_quantile,
                torch.full_like(selected_quantile, float("inf")),
            )
        )
        self.frozen.fill_(True)

    @torch.no_grad()
    def predict_acceleration(
        self,
        model: FlightDynamicsModel,
        velocity: torch.Tensor,
        quaternion: torch.Tensor,
        angular_velocity: torch.Tensor,
    ) -> torch.Tensor:
        """Predict from estimated state and frozen causal issued-command context."""

        if not bool(self.frozen.item()):
            raise RuntimeError("context must be frozen before prediction")
        self._validate_matrix("velocity", velocity, 3)
        self._validate_matrix("quaternion", quaternion, 4)
        self._validate_matrix("angular_velocity", angular_velocity, 3)
        candidates = self.delayed_actions()
        row = torch.arange(self.batch_size, device=self.device)
        selected_action = candidates[row, self.selected_delay]
        base = model.acceleration(
            velocity,
            quaternion,
            angular_velocity,
            selected_action,
        )
        thrust_component = base - self.gravity
        return base + self.selected_gamma * thrust_component + self.selected_bias

    @torch.no_grad()
    def reset(self, indices: torch.Tensor | None = None) -> None:
        """Clear selected environments without shifting the shared FIFO cursor."""

        full_reset = indices is None
        if full_reset:
            indices = torch.arange(
                self.batch_size,
                device=self.device,
                dtype=torch.long,
            )
        elif (
            not isinstance(indices, torch.Tensor)
            or indices.ndim != 1
            or indices.dtype != torch.long
            or indices.device != self.device
        ):
            raise ValueError("indices must be a 1-D long tensor on context device")
        if indices.numel() and (
            bool((indices < 0).any()) or bool((indices >= self.batch_size).any())
        ):
            raise IndexError("context reset index is out of range")

        self.issued_history[:, indices] = 0.0
        for prefix in ("fit", "all"):
            getattr(self, f"{prefix}_count")[indices] = 0.0
            getattr(self, f"{prefix}_sum_phi")[indices] = 0.0
            getattr(self, f"{prefix}_sum_residual")[indices] = 0.0
            getattr(self, f"{prefix}_sum_phi2")[indices] = 0.0
            getattr(self, f"{prefix}_sum_cross")[indices] = 0.0
        self.score_gamma[indices] = 0.0
        self.score_bias[indices] = 0.0
        self.score_excitation[indices] = 0.0
        self.score_sse[indices] = 0.0
        self.score_noop_sse[indices] = 0.0
        self.score_count[indices] = 0.0
        self.score_error_norm_samples[indices] = float("inf")
        self.score_noop_error_norm_samples[indices] = float("inf")
        self.selected_delay[indices] = 0
        self.selected_gamma[indices] = 0.0
        self.selected_bias[indices] = 0.0
        self.selected_valid[indices] = False
        self.selected_score_mse[indices] = float("inf")
        self.selected_score_margin[indices] = 0.0
        self.selected_excitation[indices] = 0.0
        self.selected_corrected_score_mse[indices] = 0.0
        self.noop_score_mse[indices] = 0.0
        self.score_improvement_absolute[indices] = 0.0
        self.score_improvement_relative[indices] = 0.0
        self.noop_fallback[indices] = False
        self.selected_residual_quantile_mps2[indices] = float("inf")
        self.invalid_observation[indices] = False
        if full_reset:
            self.issued_cursor.fill_(-1)
            self.scoring_started.fill_(False)
            self.frozen.fill_(False)
            self.post_freeze_update_attempts.zero_()
            self.score_observation_index.zero_()

    def summary(self) -> dict[str, Any]:
        """Return JSON-serializable context state and causal audit counters."""

        delay_counts = torch.bincount(
            self.selected_delay[self.selected_valid],
            minlength=self.candidate_count,
        )
        bias_norm = torch.linalg.vector_norm(self.selected_bias, dim=1)
        valid_count = int(self.selected_valid.sum().item())
        selected_score_mse = self.selected_score_mse.detach().cpu().tolist()
        selected_residual_quantile = self.selected_residual_quantile_mps2.detach().cpu().tolist()
        return {
            "type": "frozen_affine_delay",
            "frozen": bool(self.frozen.item()),
            "batch_size": self.batch_size,
            "valid_count": valid_count,
            "invalid_count": self.batch_size - valid_count,
            "invalid_observation": (self.invalid_observation.detach().cpu().tolist()),
            "selected_valid": self.selected_valid.detach().cpu().tolist(),
            "selected_delay_steps": self.selected_delay.detach().cpu().tolist(),
            "selected_delay_counts": {
                str(delay): int(count)
                for delay, count in enumerate(delay_counts.detach().cpu().tolist())
                if count
            },
            "selected_gamma": self.selected_gamma[:, 0].detach().cpu().tolist(),
            "selected_bias_mps2": self.selected_bias.detach().cpu().tolist(),
            "selected_bias_norm_mps2": bias_norm.detach().cpu().tolist(),
            "selected_score_mse": [
                float(value) if math.isfinite(float(value)) else None
                for value in selected_score_mse
            ],
            "selected_score_margin": (self.selected_score_margin.detach().cpu().tolist()),
            "selected_excitation": self.selected_excitation.detach().cpu().tolist(),
            "selected_corrected_score_mse": (
                self.selected_corrected_score_mse.detach().cpu().tolist()
            ),
            "noop_score_mse": self.noop_score_mse.detach().cpu().tolist(),
            "score_improvement_absolute": (self.score_improvement_absolute.detach().cpu().tolist()),
            "score_improvement_relative": (self.score_improvement_relative.detach().cpu().tolist()),
            "noop_fallback": self.noop_fallback.detach().cpu().tolist(),
            "noop_fallback_count": int(self.noop_fallback.sum().item()),
            "selected_residual_quantile_mps2": [
                float(value) if math.isfinite(float(value)) else None
                for value in selected_residual_quantile
            ],
            "score_residual_quantile": (self.config.score_residual_quantile),
            "applied_coefficient_source": "fit_window_scored",
            "fit_samples": [int(value) for value in self.fit_count.detach().cpu().tolist()],
            "score_samples": [int(value) for value in self.score_count.detach().cpu().tolist()],
            "post_freeze_update_attempts": int(self.post_freeze_update_attempts.item()),
            "uses_last_applied_action": False,
        }

    def _candidate_predictions(
        self,
        model: FlightDynamicsModel,
        velocity: torch.Tensor,
        quaternion: torch.Tensor,
        angular_velocity: torch.Tensor,
    ) -> torch.Tensor:
        actions = self.delayed_actions()
        candidate_count = self.candidate_count

        def repeat(values: torch.Tensor) -> torch.Tensor:
            return (
                values[:, None, :]
                .expand(-1, candidate_count, -1)
                .reshape(self.batch_size * candidate_count, -1)
            )

        return model.acceleration(
            repeat(velocity),
            repeat(quaternion),
            repeat(angular_velocity),
            actions.reshape(self.batch_size * candidate_count, 4),
        ).reshape(self.batch_size, candidate_count, 3)

    def _accumulate(
        self,
        prefix: Literal["fit", "all"],
        phi: torch.Tensor,
        residual: torch.Tensor,
        valid: torch.Tensor,
    ) -> None:
        weight = valid[:, None, None].to(self.dtype)
        scalar_weight = valid[:, None].to(self.dtype)
        getattr(self, f"{prefix}_count").add_(valid.to(self.dtype))
        getattr(self, f"{prefix}_sum_phi").add_(phi * weight)
        getattr(self, f"{prefix}_sum_residual").add_(residual * weight)
        getattr(self, f"{prefix}_sum_phi2").add_(phi.square().sum(dim=2) * scalar_weight)
        getattr(self, f"{prefix}_sum_cross").add_((phi * residual).sum(dim=2) * scalar_weight)

    def _coefficients(
        self,
        prefix: Literal["fit", "all"],
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        count = getattr(self, f"{prefix}_count")[:, None]
        safe_count = count.clamp_min(1.0)
        sum_phi = getattr(self, f"{prefix}_sum_phi")
        sum_residual = getattr(self, f"{prefix}_sum_residual")
        mean_phi = sum_phi / safe_count[:, :, None]
        mean_residual = sum_residual / safe_count[:, :, None]
        excitation = (
            getattr(self, f"{prefix}_sum_phi2") - sum_phi.square().sum(dim=2) / safe_count
        ).clamp_min(0.0)
        centered_cross = (
            getattr(self, f"{prefix}_sum_cross") - (sum_phi * sum_residual).sum(dim=2) / safe_count
        )
        gamma = (centered_cross / (excitation + self.config.ridge)).clamp(
            self.config.gamma_min, self.config.gamma_max
        )
        bias = (mean_residual - gamma[:, :, None] * mean_phi).clamp(
            -self.config.bias_abs_max_mps2,
            self.config.bias_abs_max_mps2,
        )
        enough = count >= 1.0
        gamma = torch.where(enough, gamma, torch.zeros_like(gamma))
        bias = torch.where(
            enough[:, :, None],
            bias,
            torch.zeros_like(bias),
        )
        return gamma, bias, excitation

    def _validate_matrix(
        self,
        name: str,
        tensor: torch.Tensor,
        width: int,
    ) -> None:
        if not isinstance(tensor, torch.Tensor):
            raise TypeError(f"{name} must be a torch.Tensor")
        if tensor.shape != (self.batch_size, width):
            raise ValueError(f"{name} must have shape {(self.batch_size, width)}")
        if tensor.device != self.device or tensor.dtype != self.dtype:
            raise ValueError(
                f"{name} dtype and device must match context ({self.dtype}, {self.device})"
            )

    @staticmethod
    def _validate_dt(dt: float) -> float:
        if isinstance(dt, bool):
            raise TypeError("dt must be a finite positive number")
        try:
            value = float(dt)
        except (TypeError, ValueError) as error:
            raise ValueError("dt must be finite and positive") from error
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError("dt must be finite and positive")
        return value
