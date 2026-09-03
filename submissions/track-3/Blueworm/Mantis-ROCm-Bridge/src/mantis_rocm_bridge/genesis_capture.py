"""Policy-clock sampling helpers shared by Genesis-to-LeRobot capture tools."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .contracts import ContractError


@dataclass(frozen=True)
class PolicyTick:
    frame_index: int
    policy_timestamp_s: float
    physics_step: int
    physics_timestamp_s: float
    sampling_skew_s: float


@dataclass(frozen=True)
class PolicyCaptureClock:
    """Map exact policy timestamps to the first non-early physics step."""

    physics_dt_s: float
    policy_hz: float

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.physics_dt_s)
            or self.physics_dt_s <= 0
            or not math.isfinite(self.policy_hz)
            or self.policy_hz <= 0
        ):
            raise ContractError("capture clock rates must be finite and positive")

    def tick(self, frame_index: int) -> PolicyTick:
        if not isinstance(frame_index, int) or frame_index < 0:
            raise ContractError("capture frame_index must be a non-negative integer")
        policy_timestamp = frame_index / self.policy_hz
        physics_step = int(
            math.ceil(policy_timestamp / self.physics_dt_s - 1e-12)
        )
        physics_timestamp = physics_step * self.physics_dt_s
        skew = physics_timestamp - policy_timestamp
        if skew < -1e-12 or skew >= self.physics_dt_s + 1e-12:
            raise ContractError("capture sampling skew is outside one physics step")
        return PolicyTick(
            frame_index=frame_index,
            policy_timestamp_s=policy_timestamp,
            physics_step=physics_step,
            physics_timestamp_s=physics_timestamp,
            sampling_skew_s=max(0.0, skew),
        )


def genesis_rgb_array(rendered: Any) -> Any:
    """Normalize a Genesis RGB render to an HWC uint8 three-channel array."""

    import numpy as np

    if isinstance(rendered, dict):
        rendered = rendered.get("rgb")
    elif isinstance(rendered, (tuple, list)):
        rendered = rendered[0]
    if hasattr(rendered, "detach"):
        rendered = rendered.detach()
    if hasattr(rendered, "cpu"):
        rendered = rendered.cpu()
    if hasattr(rendered, "numpy"):
        rendered = rendered.numpy()
    image = np.asarray(rendered)
    if image.ndim == 4 and image.shape[0] == 1:
        image = image[0]
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ContractError(f"unexpected Genesis RGB shape: {image.shape}")
    if image.dtype.kind == "f":
        image = np.clip(image, 0.0, 1.0) * 255.0
    return image[:, :, :3].astype(np.uint8)
