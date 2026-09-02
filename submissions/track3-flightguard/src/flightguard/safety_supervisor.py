"""Causal runtime assurance for short VIO blackouts.

The supervisor consumes only the estimated state, known gate geometry, and a
frozen pre-blackout acceleration-residual envelope.  Simulator truth, domain
labels, and realized actuator commands are intentionally absent from its API.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch

from .gate_math import world_to_gate

SAFETY_MODE_CONTINUE = 0
SAFETY_MODE_BRAKE_HOVER = 1

SAFETY_REASON_CONTINUE = 0
SAFETY_REASON_INVALID_CONTEXT = 1
SAFETY_REASON_NONFINITE_INPUT = 2
SAFETY_REASON_CLEARANCE_EXHAUSTED = 3
SAFETY_REASON_ENVELOPE_TOO_LARGE = 4
SAFETY_REASON_LATCHED = 5
SAFETY_REASON_QUALIFICATION_HORIZON_EXHAUSTED = 6


@dataclass(frozen=True)
class SafetyEnvelopeConfig:
    """Geometry and conservatism for the empirical survival envelope."""

    gate_half_width_m: float = 0.60
    gate_half_height_m: float = 0.50
    proxy_radius_m: float = 0.08
    minimum_clearance_m: float = 0.05
    reaction_margin_s: float = 0.50
    qualification_horizon_s: float = 5.0
    uncertainty_scale: float = 1.0
    ground_z_m: float = 0.10
    ceiling_z_m: float = 5.0
    workspace_xy_m: float = 10.0
    forward_speed_epsilon_mps: float = 1.0e-3

    def __post_init__(self) -> None:
        positive = {
            "gate_half_width_m": self.gate_half_width_m,
            "gate_half_height_m": self.gate_half_height_m,
            "proxy_radius_m": self.proxy_radius_m,
            "minimum_clearance_m": self.minimum_clearance_m,
            "reaction_margin_s": self.reaction_margin_s,
            "qualification_horizon_s": self.qualification_horizon_s,
            "uncertainty_scale": self.uncertainty_scale,
            "ceiling_z_m": self.ceiling_z_m,
            "workspace_xy_m": self.workspace_xy_m,
            "forward_speed_epsilon_mps": self.forward_speed_epsilon_mps,
        }
        for name, value in positive.items():
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if not math.isfinite(self.ground_z_m):
            raise ValueError("ground_z_m must be finite")
        if self.gate_half_width_m <= self.proxy_radius_m:
            raise ValueError("gate width must exceed the proxy radius")
        if self.gate_half_height_m <= self.proxy_radius_m:
            raise ValueError("gate height must exceed the proxy radius")
        if self.ceiling_z_m <= self.ground_z_m:
            raise ValueError("ceiling_z_m must exceed ground_z_m")


@dataclass(frozen=True)
class SafetyDecision:
    """One batched runtime-assurance decision."""

    target: torch.Tensor
    mode: torch.Tensor
    reason: torch.Tensor
    continue_mask: torch.Tensor
    brake_hover_mask: torch.Tensor
    newly_intervened: torch.Tensor
    time_to_gate_s: torch.Tensor
    risk_horizon_s: torch.Tensor
    available_clearance_m: torch.Tensor
    position_envelope_radius_m: torch.Tensor
    time_to_failure_s: torch.Tensor


class BatchedSafetySupervisor:
    """Latch a brake-to-hover action before the empirical tube hits clearance."""

    def __init__(
        self,
        batch_size: int,
        *,
        device: torch.device | str,
        dtype: torch.dtype = torch.float32,
        config: SafetyEnvelopeConfig | None = None,
    ) -> None:
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
        if not dtype.is_floating_point:
            raise TypeError("dtype must be floating-point")
        self.batch_size = batch_size
        self.device = torch.device(device)
        self.dtype = dtype
        self.config = config or SafetyEnvelopeConfig()
        self.started = False
        self.abort_latched = torch.zeros(
            batch_size, device=self.device, dtype=torch.bool
        )
        self.anchor_position = torch.zeros(
            (batch_size, 3), device=self.device, dtype=dtype
        )
        self.intervention_step = torch.full(
            (batch_size,), -1, device=self.device, dtype=torch.long
        )
        self.reason = torch.full(
            (batch_size,),
            SAFETY_REASON_CONTINUE,
            device=self.device,
            dtype=torch.long,
        )
        self.minimum_time_to_failure_s = torch.full(
            (batch_size,), float("inf"), device=self.device, dtype=dtype
        )
        self.minimum_clearance_m = torch.full(
            (batch_size,), float("inf"), device=self.device, dtype=dtype
        )
        self.maximum_envelope_radius_m = torch.zeros(
            batch_size, device=self.device, dtype=dtype
        )

    def begin_dropout(self, position: torch.Tensor) -> None:
        self._validate_matrix("position", position, 3)
        if self.started:
            raise RuntimeError("dropout has already started")
        finite = torch.isfinite(position).all(dim=1)
        self.anchor_position.copy_(
            torch.where(finite[:, None], position, torch.zeros_like(position))
        )
        self.started = True

    @torch.no_grad()
    def decide(
        self,
        position: torch.Tensor,
        velocity: torch.Tensor,
        nominal_target: torch.Tensor,
        gate_center: torch.Tensor,
        gate_yaw: torch.Tensor,
        acceleration_error_bound_mps2: torch.Tensor,
        context_trusted: torch.Tensor,
        active_mask: torch.Tensor,
        *,
        dropout_elapsed_s: float,
        step_index: int,
    ) -> SafetyDecision:
        if not self.started:
            raise RuntimeError("begin_dropout must be called before decide")
        for name, values in (
            ("position", position),
            ("velocity", velocity),
            ("nominal_target", nominal_target),
            ("gate_center", gate_center),
        ):
            self._validate_matrix(name, values, 3)
        self._validate_vector("gate_yaw", gate_yaw, self.dtype)
        self._validate_vector(
            "acceleration_error_bound_mps2",
            acceleration_error_bound_mps2,
            self.dtype,
        )
        self._validate_vector("context_trusted", context_trusted, torch.bool)
        self._validate_vector("active_mask", active_mask, torch.bool)
        if isinstance(step_index, bool) or not isinstance(step_index, int) or step_index < 0:
            raise ValueError("step_index must be a non-negative integer")
        if (
            isinstance(dropout_elapsed_s, bool)
            or not math.isfinite(float(dropout_elapsed_s))
            or float(dropout_elapsed_s) < 0.0
        ):
            raise ValueError("dropout_elapsed_s must be finite and non-negative")

        config = self.config
        elapsed_s = float(dropout_elapsed_s)
        within_qualification_horizon = position.new_full(
            (self.batch_size,),
            elapsed_s < config.qualification_horizon_s,
            dtype=torch.bool,
        )
        remaining = position.new_full(
            (self.batch_size,),
            max(config.qualification_horizon_s - elapsed_s, 0.0),
        )
        local_position = world_to_gate(position, gate_center, gate_yaw)
        zeros = torch.zeros_like(velocity[:, 2])
        local_velocity = world_to_gate(
            velocity,
            zeros[:, None].expand(-1, 3),
            gate_yaw,
        )
        forward = local_velocity[:, 0] > config.forward_speed_epsilon_mps
        before_gate = local_position[:, 0] < 0.0
        raw_time_to_gate = -local_position[:, 0] / local_velocity[:, 0].clamp_min(
            config.forward_speed_epsilon_mps
        )
        reaches_gate = (
            forward
            & before_gate
            & (raw_time_to_gate >= 0.0)
            & (raw_time_to_gate <= remaining)
        )
        time_to_gate = torch.where(
            forward & before_gate,
            raw_time_to_gate.clamp_min(0.0),
            torch.full_like(raw_time_to_gate, float("inf")),
        )
        risk_horizon = torch.where(reaches_gate, time_to_gate, remaining)

        crossing_y = local_position[:, 1] + local_velocity[:, 1] * time_to_gate
        crossing_z = local_position[:, 2] + local_velocity[:, 2] * time_to_gate
        gate_clearance = torch.minimum(
            config.gate_half_width_m
            - config.proxy_radius_m
            - crossing_y.abs(),
            config.gate_half_height_m
            - config.proxy_radius_m
            - crossing_z.abs(),
        )
        gate_clearance = torch.where(
            reaches_gate,
            gate_clearance,
            torch.full_like(gate_clearance, float("inf")),
        )

        predicted_position = position + velocity * risk_horizon[:, None]
        current_boundary_clearance = torch.stack(
            (
                position[:, 2] - config.ground_z_m,
                config.ceiling_z_m - position[:, 2],
                config.workspace_xy_m - position[:, 0].abs(),
                config.workspace_xy_m - position[:, 1].abs(),
            ),
            dim=1,
        )
        predicted_boundary_clearance = torch.stack(
            (
                predicted_position[:, 2] - config.ground_z_m,
                config.ceiling_z_m - predicted_position[:, 2],
                config.workspace_xy_m - predicted_position[:, 0].abs(),
                config.workspace_xy_m - predicted_position[:, 1].abs(),
            ),
            dim=1,
        )
        boundary_clearance = torch.minimum(
            current_boundary_clearance,
            predicted_boundary_clearance,
        ).min(dim=1).values
        available_clearance = torch.minimum(gate_clearance, boundary_clearance)

        scaled_error = acceleration_error_bound_mps2 * config.uncertainty_scale
        # The empirical position-error envelope is anchored at blackout
        # onset.  A decision made after ``elapsed_s`` must therefore cover
        # total elapsed time plus its prospective risk horizon.
        expanded_horizon = (
            elapsed_s + risk_horizon + config.reaction_margin_s
        )
        envelope_radius = 0.5 * scaled_error * expanded_horizon.square()
        safe_error = scaled_error.clamp_min(torch.finfo(self.dtype).eps)
        raw_time_to_failure = torch.sqrt(
            (2.0 * available_clearance.clamp_min(0.0)) / safe_error
        )
        raw_time_to_failure = torch.where(
            scaled_error <= torch.finfo(self.dtype).eps,
            torch.full_like(raw_time_to_failure, float("inf")),
            raw_time_to_failure,
        )
        time_to_failure = torch.where(
            torch.isfinite(raw_time_to_failure),
            (
                raw_time_to_failure - config.reaction_margin_s
                - elapsed_s
            ).clamp_min(0.0),
            raw_time_to_failure,
        )

        finite_inputs = (
            torch.isfinite(position).all(dim=1)
            & torch.isfinite(velocity).all(dim=1)
            & torch.isfinite(nominal_target).all(dim=1)
            & torch.isfinite(gate_center).all(dim=1)
            & torch.isfinite(gate_yaw)
            & torch.isfinite(scaled_error)
            & (scaled_error >= 0.0)
        )
        available_clearance = torch.where(
            finite_inputs,
            available_clearance,
            torch.full_like(available_clearance, -float("inf")),
        )
        envelope_radius = torch.where(
            finite_inputs,
            envelope_radius,
            torch.full_like(envelope_radius, float("inf")),
        )
        time_to_failure = torch.where(
            finite_inputs,
            time_to_failure,
            torch.zeros_like(time_to_failure),
        )
        enough_clearance = available_clearance > config.minimum_clearance_m
        envelope_fits = (
            envelope_radius + config.minimum_clearance_m
            <= available_clearance
        )
        safe_to_continue = (
            ~active_mask
            | (
                context_trusted
                & finite_inputs
                & within_qualification_horizon
                & enough_clearance
                & envelope_fits
            )
        )

        reason = torch.full_like(self.reason, SAFETY_REASON_CONTINUE)
        reason = torch.where(
            active_mask & ~context_trusted,
            torch.full_like(reason, SAFETY_REASON_INVALID_CONTEXT),
            reason,
        )
        reason = torch.where(
            active_mask & context_trusted & ~finite_inputs,
            torch.full_like(reason, SAFETY_REASON_NONFINITE_INPUT),
            reason,
        )
        reason = torch.where(
            active_mask
            & context_trusted
            & finite_inputs
            & within_qualification_horizon
            & ~enough_clearance,
            torch.full_like(reason, SAFETY_REASON_CLEARANCE_EXHAUSTED),
            reason,
        )
        reason = torch.where(
            active_mask
            & context_trusted
            & finite_inputs
            & within_qualification_horizon
            & enough_clearance
            & ~envelope_fits,
            torch.full_like(reason, SAFETY_REASON_ENVELOPE_TOO_LARGE),
            reason,
        )
        reason = torch.where(
            active_mask
            & context_trusted
            & finite_inputs
            & ~within_qualification_horizon,
            torch.full_like(
                reason,
                SAFETY_REASON_QUALIFICATION_HORIZON_EXHAUSTED,
            ),
            reason,
        )

        newly_intervened = (
            active_mask & ~self.abort_latched & ~safe_to_continue
        )
        if bool(newly_intervened.any()):
            finite_anchor = newly_intervened & torch.isfinite(position).all(dim=1)
            self.anchor_position[finite_anchor] = position[finite_anchor]
            self.intervention_step[newly_intervened] = step_index
            self.reason[newly_intervened] = reason[newly_intervened]
        already_latched = self.abort_latched.clone()
        self.abort_latched |= ~safe_to_continue
        output_reason = torch.where(
            already_latched,
            torch.full_like(reason, SAFETY_REASON_LATCHED),
            reason,
        )

        finite_ttf = torch.where(
            torch.isfinite(time_to_failure),
            time_to_failure,
            torch.full_like(time_to_failure, float("inf")),
        )
        finite_clearance = torch.nan_to_num(
            available_clearance,
            nan=-float("inf"),
            posinf=float("inf"),
            neginf=-float("inf"),
        )
        finite_radius = torch.nan_to_num(
            envelope_radius,
            nan=float("inf"),
            posinf=float("inf"),
            neginf=float("inf"),
        )
        self.minimum_time_to_failure_s = torch.where(
            active_mask,
            torch.minimum(self.minimum_time_to_failure_s, finite_ttf),
            self.minimum_time_to_failure_s,
        )
        self.minimum_clearance_m = torch.where(
            active_mask,
            torch.minimum(self.minimum_clearance_m, finite_clearance),
            self.minimum_clearance_m,
        )
        self.maximum_envelope_radius_m = torch.where(
            active_mask,
            torch.maximum(self.maximum_envelope_radius_m, finite_radius),
            self.maximum_envelope_radius_m,
        )

        target = torch.where(
            self.abort_latched[:, None],
            self.anchor_position,
            nominal_target,
        )
        mode = torch.where(
            self.abort_latched,
            torch.full_like(self.reason, SAFETY_MODE_BRAKE_HOVER),
            torch.full_like(self.reason, SAFETY_MODE_CONTINUE),
        )
        return SafetyDecision(
            target=target,
            mode=mode,
            reason=output_reason,
            continue_mask=~self.abort_latched,
            brake_hover_mask=self.abort_latched.clone(),
            newly_intervened=newly_intervened,
            time_to_gate_s=time_to_gate,
            risk_horizon_s=risk_horizon,
            available_clearance_m=available_clearance,
            position_envelope_radius_m=envelope_radius,
            time_to_failure_s=time_to_failure,
        )

    def summary(self) -> dict[str, object]:
        if not self.started:
            raise RuntimeError("supervisor has not started")

        def finite_or_none(values: torch.Tensor) -> list[float | None]:
            return [
                float(value) if math.isfinite(float(value)) else None
                for value in values.detach().cpu().tolist()
            ]

        reason_counts = torch.bincount(
            self.reason[self.abort_latched], minlength=7
        )
        return {
            "type": "causal_empirical_survival_envelope",
            "batch_size": self.batch_size,
            "intervention_count": int(self.abort_latched.sum().item()),
            "intervention_rate": float(
                self.abort_latched.float().mean().item()
            ),
            "intervention_step": self.intervention_step.detach().cpu().tolist(),
            "reason_counts": {
                str(index): int(count)
                for index, count in enumerate(reason_counts.detach().cpu().tolist())
                if count
            },
            "minimum_time_to_failure_s": finite_or_none(
                self.minimum_time_to_failure_s
            ),
            "minimum_clearance_m": finite_or_none(self.minimum_clearance_m),
            "maximum_envelope_radius_m": finite_or_none(
                self.maximum_envelope_radius_m
            ),
            "uses_continuous_simulator_state_truth": False,
            "uses_simulator_lifecycle_mask": True,
            "uses_domain_labels": False,
            "uses_last_applied_action": False,
        }

    def _validate_matrix(
        self, name: str, values: torch.Tensor, width: int
    ) -> None:
        if not isinstance(values, torch.Tensor):
            raise TypeError(f"{name} must be a torch.Tensor")
        if values.shape != (self.batch_size, width):
            raise ValueError(
                f"{name} must have shape {(self.batch_size, width)}"
            )
        if values.device != self.device or values.dtype != self.dtype:
            raise ValueError(
                f"{name} dtype and device must match supervisor "
                f"({self.dtype}, {self.device})"
            )

    def _validate_vector(
        self,
        name: str,
        values: torch.Tensor,
        dtype_kind: object,
    ) -> None:
        if not isinstance(values, torch.Tensor) or values.shape != (self.batch_size,):
            raise ValueError(f"{name} must have shape {(self.batch_size,)}")
        if values.device != self.device:
            raise ValueError(f"{name} must be on {self.device}")
        if dtype_kind == torch.bool and values.dtype != torch.bool:
            raise TypeError(f"{name} must use torch.bool")
        if dtype_kind == self.dtype and values.dtype != self.dtype:
            raise TypeError(f"{name} must use {self.dtype}")
