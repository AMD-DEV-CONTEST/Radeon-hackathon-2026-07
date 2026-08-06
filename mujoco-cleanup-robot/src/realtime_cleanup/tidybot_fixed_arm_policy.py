"""Small phase/progress-conditioned policies for fixed-scene TidyBot manipulation."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from realtime_cleanup.types import (
    TIDYBOT_ARM_ACTION_NAMES,
    TIDYBOT_TASK_PHASES,
    TidyBotArmPolicyOutput,
)


OBJECT_NAMES = ("can", "bottle", "cup", "banana")
PHASE_NAMES = tuple(TIDYBOT_TASK_PHASES)
ACTION_LIMITS = (0.08, 0.08, 0.08, 0.08, 0.10, 0.10, 0.10, 8.0)
CHECKPOINT_SCHEMA_VERSION = "tidybot_fixed_arm_policy_v1"
MODEL_ARCHITECTURE = "fourier_progress_mlp_classified_delta"


def _finite_vector(value: Any, length: int, name: str) -> np.ndarray:
    result = np.asarray(value, dtype=np.float32)
    if result.shape != (length,):
        raise ValueError(f"{name} must have shape ({length},)")
    if not np.isfinite(result).all():
        raise ValueError(f"{name} contains NaN or infinity")
    return result


def _one_hot(name: str, names: tuple[str, ...]) -> np.ndarray:
    if name not in names:
        raise ValueError(f"{name!r} is not one of {names}")
    result = np.zeros(len(names), dtype=np.float32)
    result[names.index(name)] = 1.0
    return result


def object_one_hot(object_name: str) -> np.ndarray:
    return _one_hot(object_name, OBJECT_NAMES)


def phase_one_hot(phase: str) -> np.ndarray:
    return _one_hot(phase, PHASE_NAMES)


def normalized_progress(step: int, length: int) -> float:
    if isinstance(step, bool) or not isinstance(step, int) or step < 0:
        raise ValueError("step must be a non-negative integer")
    if isinstance(length, bool) or not isinstance(length, int) or length <= 0:
        raise ValueError("length must be a positive integer")
    return min(1.0, float(step) / float(max(1, length - 1)))


@dataclass(frozen=True)
class FixedArmPolicyConfig:
    """Serializable architecture configuration shared by all four object models."""

    hidden_dims: tuple[int, ...] = (256, 256, 128)
    fourier_frequencies: int = 256
    arm_dimension: int = len(TIDYBOT_ARM_ACTION_NAMES)
    object_dimension: int = len(OBJECT_NAMES)
    phase_dimension: int = len(PHASE_NAMES)
    output_dimension: int = len(TIDYBOT_ARM_ACTION_NAMES)
    architecture: str = MODEL_ARCHITECTURE

    def __post_init__(self) -> None:
        if self.architecture != MODEL_ARCHITECTURE:
            raise ValueError(f"unsupported architecture {self.architecture!r}")
        if not self.hidden_dims or any(
            isinstance(width, bool) or not isinstance(width, int) or width <= 0
            for width in self.hidden_dims
        ):
            raise ValueError("hidden_dims must contain positive integers")
        if (
            isinstance(self.fourier_frequencies, bool)
            or not isinstance(self.fourier_frequencies, int)
            or self.fourier_frequencies <= 0
        ):
            raise ValueError("fourier_frequencies must be positive")
        expected = len(TIDYBOT_ARM_ACTION_NAMES)
        if self.arm_dimension != expected or self.output_dimension != expected:
            raise ValueError("fixed arm input/output dimensions must both be eight")
        if self.object_dimension != len(OBJECT_NAMES):
            raise ValueError("object_dimension does not match the fixed object vocabulary")
        if self.phase_dimension != len(PHASE_NAMES):
            raise ValueError("phase_dimension does not match the phase vocabulary")

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["hidden_dims"] = list(self.hidden_dims)
        return result

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> FixedArmPolicyConfig:
        values = dict(payload)
        values["hidden_dims"] = tuple(int(value) for value in values["hidden_dims"])
        return cls(**values)


class FourierProgressMLP(nn.Module):
    """A real MLP with classified action direction and regressed magnitude.

    Progress is represented with deterministic Fourier features. There is no
    embedding, trajectory buffer, or frame-indexed action parameter.
    """

    def __init__(
        self,
        config: FixedArmPolicyConfig,
        *,
        arm_mean: np.ndarray | torch.Tensor,
        arm_scale: np.ndarray | torch.Tensor,
        gripper_bounds: tuple[float, float],
        action_limits: np.ndarray | torch.Tensor = np.asarray(ACTION_LIMITS),
    ) -> None:
        super().__init__()
        self.config = config
        mean = torch.as_tensor(arm_mean, dtype=torch.float32)
        scale = torch.as_tensor(arm_scale, dtype=torch.float32)
        limits = torch.as_tensor(action_limits, dtype=torch.float32)
        if mean.shape != (config.arm_dimension,) or scale.shape != (config.arm_dimension,):
            raise ValueError("arm normalization vectors must be eight-dimensional")
        if limits.shape != (config.output_dimension,):
            raise ValueError("action_limits must be eight-dimensional")
        if not torch.isfinite(mean).all() or not torch.isfinite(scale).all():
            raise ValueError("arm normalization contains NaN or infinity")
        if torch.any(scale <= 0.0):
            raise ValueError("arm_scale must be positive")
        if not torch.isfinite(limits).all() or torch.any(limits <= 0.0):
            raise ValueError("action_limits must be finite and positive")
        gripper_low, gripper_high = (float(value) for value in gripper_bounds)
        if not math.isfinite(gripper_low) or not math.isfinite(gripper_high):
            raise ValueError("gripper bounds must be finite")
        if gripper_high <= gripper_low:
            raise ValueError("gripper upper bound must exceed its lower bound")

        self.register_buffer("arm_mean", mean)
        self.register_buffer("arm_scale", scale)
        self.register_buffer("action_limits", limits)
        self.register_buffer(
            "gripper_bounds",
            torch.tensor([gripper_low, gripper_high], dtype=torch.float32),
        )
        self.register_buffer(
            "fourier_bands",
            torch.arange(1, config.fourier_frequencies + 1, dtype=torch.float32)
            * (2.0 * math.pi),
        )

        feature_dimension = (
            config.arm_dimension
            + config.object_dimension
            + config.phase_dimension
            + 2
            + 1
            + 4 * config.fourier_frequencies
        )
        layers: list[nn.Module] = []
        previous = feature_dimension
        for width in config.hidden_dims:
            layers.extend((nn.Linear(previous, width), nn.SiLU()))
            previous = width
        self.trunk = nn.Sequential(*layers)
        self.direction_head = nn.Linear(previous, config.output_dimension * 3)
        self.magnitude_head = nn.Linear(previous, config.output_dimension)

    def encode(
        self,
        arm_position: torch.Tensor,
        object_bits: torch.Tensor,
        phase_bits: torch.Tensor,
        phase_progress: torch.Tensor,
        episode_progress: torch.Tensor,
        gripper_state: torch.Tensor,
    ) -> torch.Tensor:
        batch = arm_position.shape[0]
        expected = {
            "arm_position": (batch, self.config.arm_dimension),
            "object_bits": (batch, self.config.object_dimension),
            "phase_bits": (batch, self.config.phase_dimension),
            "phase_progress": (batch, 1),
            "episode_progress": (batch, 1),
            "gripper_state": (batch, 1),
        }
        actual = {
            "arm_position": tuple(arm_position.shape),
            "object_bits": tuple(object_bits.shape),
            "phase_bits": tuple(phase_bits.shape),
            "phase_progress": tuple(phase_progress.shape),
            "episode_progress": tuple(episode_progress.shape),
            "gripper_state": tuple(gripper_state.shape),
        }
        mismatches = {
            name: (actual[name], shape)
            for name, shape in expected.items()
            if actual[name] != shape
        }
        if mismatches:
            raise ValueError(f"fixed arm model input shape mismatch: {mismatches}")

        normalized_arm = (arm_position - self.arm_mean) / self.arm_scale
        progresses = torch.cat((phase_progress, episode_progress), dim=1)
        angles = progresses.unsqueeze(-1) * self.fourier_bands
        fourier = torch.cat((torch.sin(angles), torch.cos(angles)), dim=2).flatten(1)
        return torch.cat(
            (
                normalized_arm,
                object_bits,
                phase_bits,
                progresses,
                gripper_state,
                fourier,
            ),
            dim=1,
        )

    def components(
        self,
        arm_position: torch.Tensor,
        object_bits: torch.Tensor,
        phase_bits: torch.Tensor,
        phase_progress: torch.Tensor,
        episode_progress: torch.Tensor,
        gripper_state: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        encoded = self.encode(
            arm_position,
            object_bits,
            phase_bits,
            phase_progress,
            episode_progress,
            gripper_state,
        )
        hidden = self.trunk(encoded)
        direction = self.direction_head(hidden).reshape(
            -1,
            self.config.output_dimension,
            3,
        )
        magnitude = self.magnitude_head(hidden)
        return direction, magnitude

    def forward(
        self,
        arm_position: torch.Tensor,
        object_bits: torch.Tensor,
        phase_bits: torch.Tensor,
        phase_progress: torch.Tensor,
        episode_progress: torch.Tensor,
        gripper_state: torch.Tensor,
        *,
        hard: bool = False,
    ) -> torch.Tensor:
        direction, magnitude = self.components(
            arm_position,
            object_bits,
            phase_bits,
            phase_progress,
            episode_progress,
            gripper_state,
        )
        if hard:
            signed_direction = direction.argmax(dim=-1).to(magnitude.dtype) - 1.0
        else:
            probabilities = torch.softmax(direction, dim=-1)
            signed_direction = probabilities[..., 2] - probabilities[..., 0]
        return signed_direction * magnitude.clamp(0.0, 1.0) * self.action_limits

    def normalized_gripper_state(self, arm_position: torch.Tensor) -> torch.Tensor:
        low, high = self.gripper_bounds
        return ((arm_position[..., 7:8] - low) / (high - low)).clamp(0.0, 1.0)


def _validate_phase_lengths(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict) or set(payload) != set(PHASE_NAMES):
        raise ValueError(f"phase_lengths must contain exactly {PHASE_NAMES}")
    result: dict[str, int] = {}
    for phase in PHASE_NAMES:
        value = payload[phase]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"phase length for {phase} must be positive")
        result[phase] = value
    return result


def load_fixed_arm_checkpoint(
    checkpoint: str | Path,
    *,
    device: str | torch.device = "cpu",
) -> tuple[dict[str, Any], FourierProgressMLP]:
    path = Path(checkpoint)
    try:
        payload = torch.load(path, map_location="cpu", weights_only=True)
    except FileNotFoundError:
        raise
    if not isinstance(payload, dict):
        raise ValueError("fixed arm checkpoint must contain a dictionary")
    if payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        raise ValueError("unsupported fixed arm checkpoint schema")
    if payload.get("architecture") != MODEL_ARCHITECTURE:
        raise ValueError("fixed arm checkpoint architecture mismatch")
    if any(key in payload for key in ("actions", "action_table", "trajectory", "embedding")):
        raise ValueError("frame-indexed actions are forbidden in fixed arm checkpoints")
    object_name = payload.get("object_name")
    if object_name not in OBJECT_NAMES:
        raise ValueError("checkpoint has an invalid object_name")
    _validate_phase_lengths(payload.get("phase_lengths"))
    reference = payload.get("reference_relative_target_pose")
    if not isinstance(reference, dict):
        raise ValueError("checkpoint is missing reference_relative_target_pose")
    _finite_vector(reference.get("position_xyz_m"), 3, "relative target position")
    _finite_vector(reference.get("quaternion_wxyz"), 4, "relative target quaternion")
    if not isinstance(payload.get("sha256"), dict) or not isinstance(
        payload.get("provenance"),
        dict,
    ):
        raise ValueError("checkpoint must contain SHA and provenance dictionaries")

    config_payload = payload.get("config")
    normalization = payload.get("normalization")
    state_dict = payload.get("model_state_dict")
    if not isinstance(config_payload, dict) or not isinstance(normalization, dict):
        raise ValueError("checkpoint is missing model configuration or normalization")
    if not isinstance(state_dict, dict):
        raise ValueError("checkpoint is missing model_state_dict")
    config = FixedArmPolicyConfig.from_dict(config_payload)
    model = FourierProgressMLP(
        config,
        arm_mean=_finite_vector(
            normalization.get("arm_mean"),
            config.arm_dimension,
            "arm_mean",
        ),
        arm_scale=_finite_vector(
            normalization.get("arm_scale"),
            config.arm_dimension,
            "arm_scale",
        ),
        gripper_bounds=tuple(
            _finite_vector(normalization.get("gripper_bounds"), 2, "gripper_bounds")
        ),
        action_limits=_finite_vector(
            normalization.get("action_limits"),
            config.output_dimension,
            "action_limits",
        ),
    )
    model.load_state_dict(state_dict, strict=True)
    model.to(device).eval()
    return payload, model


class TidyBotFixedArmPolicy:
    """Runtime wrapper whose only varying inputs are robot state and progress."""

    def __init__(
        self,
        checkpoint: str | Path,
        *,
        device: str | torch.device = "cpu",
    ) -> None:
        self.checkpoint = Path(checkpoint)
        self.device = torch.device(device)
        self.metadata, self.model = load_fixed_arm_checkpoint(
            self.checkpoint,
            device=self.device,
        )
        self.object_name = str(self.metadata["object_name"])
        self.phase_lengths = _validate_phase_lengths(self.metadata["phase_lengths"])
        self.total_frames = sum(self.phase_lengths.values())
        self.model_calls = 0

    def reset(self) -> None:
        self.model_calls = 0

    def infer(
        self,
        arm_position: np.ndarray,
        *,
        phase: str,
        phase_step: int,
        episode_step: int,
    ) -> TidyBotArmPolicyOutput:
        arm = _finite_vector(
            arm_position,
            len(TIDYBOT_ARM_ACTION_NAMES),
            "arm_position",
        )
        if phase not in PHASE_NAMES:
            raise ValueError(f"invalid fixed arm phase {phase!r}")
        if episode_step < 0 or episode_step >= self.total_frames:
            raise ValueError("episode_step is outside the checkpoint schedule")
        phase_length = self.phase_lengths[phase]
        if phase_step < 0 or phase_step >= phase_length:
            raise ValueError("phase_step is outside the checkpoint phase schedule")

        arm_tensor = torch.from_numpy(arm).to(self.device).unsqueeze(0)
        object_tensor = (
            torch.from_numpy(object_one_hot(self.object_name)).to(self.device).unsqueeze(0)
        )
        phase_tensor = torch.from_numpy(phase_one_hot(phase)).to(self.device).unsqueeze(0)
        phase_progress = torch.tensor(
            [[normalized_progress(phase_step, phase_length)]],
            dtype=torch.float32,
            device=self.device,
        )
        episode_progress = torch.tensor(
            [[normalized_progress(episode_step, self.total_frames)]],
            dtype=torch.float32,
            device=self.device,
        )
        gripper_state = self.model.normalized_gripper_state(arm_tensor)
        with torch.inference_mode():
            action = self.model(
                arm_tensor,
                object_tensor,
                phase_tensor,
                phase_progress,
                episode_progress,
                gripper_state,
                hard=True,
            )[0]
        action_numpy = action.cpu().numpy().astype(np.float32, copy=False)
        self.model_calls += 1
        return TidyBotArmPolicyOutput(
            action_chunk=action_numpy[None],
            phase=phase,
            trace_id=f"fixed-mlp-{self.object_name}-{episode_step:06d}",
        )


def phase_schedule(phase_lengths: dict[str, int]) -> list[tuple[str, int]]:
    lengths = _validate_phase_lengths(phase_lengths)
    return [
        (phase, phase_step)
        for phase in PHASE_NAMES
        for phase_step in range(lengths[phase])
    ]


__all__ = [
    "ACTION_LIMITS",
    "CHECKPOINT_SCHEMA_VERSION",
    "MODEL_ARCHITECTURE",
    "OBJECT_NAMES",
    "PHASE_NAMES",
    "FixedArmPolicyConfig",
    "FourierProgressMLP",
    "TidyBotFixedArmPolicy",
    "load_fixed_arm_checkpoint",
    "normalized_progress",
    "object_one_hot",
    "phase_one_hot",
    "phase_schedule",
]
