"""Batched, deterministic VIO fault replay.

The injector has two deliberate invariants:

* ``mode="off"`` returns the original tensor objects without copying or mutation.
* The guard-facing measurement never contains simulator ground truth in extra
  channels. Ground truth is used only as the measurement being corrupted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import torch

NanPolicy = Literal["propagate", "zero"]
Mode = Literal["off", "replay_scaled"]


@dataclass(frozen=True)
class ReplayTrace:
    """One time-indexed VIO fault trace.

    ``position_error`` and ``velocity_error`` are additive residuals. A row in
    ``invalid`` marks a real sensor dropout/failure sample. The trace can be
    constructed from an aligned T265/mocap artifact or a synthetic kill trace.
    """

    position_error: torch.Tensor
    velocity_error: torch.Tensor
    invalid: torch.Tensor

    def __post_init__(self) -> None:
        if self.position_error.ndim != 2 or self.position_error.shape[1] != 3:
            raise ValueError("position_error must have shape [T, 3]")
        if self.velocity_error.shape != self.position_error.shape:
            raise ValueError("velocity_error must have the same shape as position_error")
        if self.invalid.shape != (self.position_error.shape[0],):
            raise ValueError("invalid must have shape [T]")
        if self.position_error.shape[0] == 0:
            raise ValueError("trace must contain at least one row")
        if self.invalid.dtype != torch.bool:
            raise ValueError("invalid must be bool")

    @property
    def length(self) -> int:
        return self.position_error.shape[0]

    def to(self, device: torch.device | str) -> ReplayTrace:
        return ReplayTrace(
            self.position_error.to(device=device),
            self.velocity_error.to(device=device),
            self.invalid.to(device=device),
        )


@dataclass(frozen=True)
class FaultBatch:
    """Corrupted measurement and evaluation-only fault labels."""

    position: torch.Tensor
    velocity: torch.Tensor
    invalid: torch.Tensor
    magnitude: torch.Tensor
    trace_index: torch.Tensor


class ReplayFaultInjector:
    """Replay one trace across many environments without per-environment loops."""

    def __init__(
        self,
        trace: ReplayTrace,
        num_envs: int,
        *,
        mode: Mode = "off",
        scale: float = 1.0,
        latency_steps: int = 0,
        nan_policy: NanPolicy = "propagate",
        seed: int = 0,
        device: torch.device | str = "cpu",
    ) -> None:
        if num_envs <= 0:
            raise ValueError("num_envs must be positive")
        if mode not in ("off", "replay_scaled"):
            raise ValueError(f"unsupported mode: {mode}")
        if scale < 0:
            raise ValueError("scale must be non-negative")
        if latency_steps < 0:
            raise ValueError("latency_steps must be non-negative")
        if nan_policy not in ("propagate", "zero"):
            raise ValueError(f"unsupported nan_policy: {nan_policy}")

        self.trace = trace.to(device)
        self.num_envs = num_envs
        self.mode = mode
        self.scale = float(scale)
        self.latency_steps = int(latency_steps)
        self.nan_policy = nan_policy
        self.device = torch.device(device)
        self._step = 0
        self._start = torch.zeros(num_envs, dtype=torch.long, device=self.device)
        self.reset(seed=seed)

    def reset(self, *, seed: int, envs_idx: torch.Tensor | None = None) -> None:
        """Reset deterministic trace offsets.

        Using a CPU generator makes the same seed choose the same offsets on CPU
        and ROCm. Only the compact offsets are transferred to the target device.
        """

        if envs_idx is None:
            envs_idx = torch.arange(self.num_envs, device=self.device)
            self._step = 0
        else:
            envs_idx = envs_idx.to(device=self.device, dtype=torch.long)
        generator = torch.Generator(device="cpu")
        generator.manual_seed(int(seed))
        offsets = torch.randint(
            low=0,
            high=self.trace.length,
            size=(envs_idx.numel(),),
            generator=generator,
            device="cpu",
        ).to(self.device)
        self._start[envs_idx] = offsets

    def apply(self, position: torch.Tensor, velocity: torch.Tensor) -> FaultBatch:
        """Corrupt batched position and velocity measurements for the current step."""

        expected = (self.num_envs, 3)
        if position.shape != expected or velocity.shape != expected:
            raise ValueError(f"position and velocity must both have shape {expected}")
        if position.device != self.device or velocity.device != self.device:
            raise ValueError("input tensors must be on the injector device")

        if self.mode == "off":
            index = torch.zeros(self.num_envs, dtype=torch.long, device=self.device)
            labels = torch.zeros(self.num_envs, dtype=torch.bool, device=self.device)
            magnitude = torch.zeros(self.num_envs, dtype=position.dtype, device=self.device)
            self._step += 1
            return FaultBatch(position, velocity, labels, magnitude, index)

        index = (self._start + self._step - self.latency_steps) % self.trace.length
        pos_error = self.trace.position_error[index].to(dtype=position.dtype)
        vel_error = self.trace.velocity_error[index].to(dtype=velocity.dtype)
        invalid = self.trace.invalid[index]

        finite_error = torch.isfinite(pos_error).all(dim=1) & torch.isfinite(vel_error).all(dim=1)
        invalid = invalid | ~finite_error
        if self.nan_policy == "zero":
            pos_error = torch.nan_to_num(pos_error)
            vel_error = torch.nan_to_num(vel_error)

        corrupted_position = position + self.scale * pos_error
        corrupted_velocity = velocity + self.scale * vel_error
        if self.nan_policy == "propagate":
            nan = torch.full_like(corrupted_position, float("nan"))
            corrupted_position = torch.where(invalid[:, None], nan, corrupted_position)
            corrupted_velocity = torch.where(invalid[:, None], nan, corrupted_velocity)

        magnitude = torch.linalg.vector_norm(
            torch.nan_to_num(self.scale * pos_error), dim=1
        )
        self._step += 1
        return FaultBatch(
            corrupted_position,
            corrupted_velocity,
            invalid,
            magnitude,
            index,
        )

