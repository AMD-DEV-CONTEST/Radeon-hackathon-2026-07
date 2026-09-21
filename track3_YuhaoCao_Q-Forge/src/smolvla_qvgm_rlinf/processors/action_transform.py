"""Explicit action normalization and LIBERO execution conventions."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ActionTransform:
    """Invertible affine transform for 7D LIBERO actions.

    The released SmolVLA base checkpoint has no LIBERO-specific statistics, so
    Phase 5 uses identity statistics. Fine-tuned checkpoints can supply their
    own offset and scale without changing the rollout interface.
    """

    offset: np.ndarray
    scale: np.ndarray
    clip: bool = True

    def __post_init__(self) -> None:
        offset = np.asarray(self.offset, dtype=np.float32)
        scale = np.asarray(self.scale, dtype=np.float32)
        if offset.shape != (7,) or scale.shape != (7,):
            raise ValueError("offset and scale must both have shape (7,)")
        if not np.all(np.isfinite(offset)) or not np.all(np.isfinite(scale)):
            raise ValueError("action statistics must be finite")
        if np.any(scale <= 0):
            raise ValueError("action scales must be positive")
        object.__setattr__(self, "offset", offset)
        object.__setattr__(self, "scale", scale)

    @classmethod
    def identity(cls, *, clip: bool = True) -> "ActionTransform":
        return cls(np.zeros(7, dtype=np.float32), np.ones(7, dtype=np.float32), clip)

    def normalize(self, action: np.ndarray) -> np.ndarray:
        action = np.asarray(action, dtype=np.float32)
        if action.shape[-1] != 7:
            raise ValueError(f"action last dimension must be 7, got {action.shape}")
        return (action - self.offset) / self.scale

    def unnormalize(self, action: np.ndarray) -> np.ndarray:
        action = np.asarray(action, dtype=np.float32)
        if action.shape[-1] != 7:
            raise ValueError(f"action last dimension must be 7, got {action.shape}")
        result = action * self.scale + self.offset
        return np.clip(result, -1.0, 1.0) if self.clip else result

    @staticmethod
    def binarize_gripper(action: np.ndarray) -> np.ndarray:
        result = np.asarray(action, dtype=np.float32).copy()
        result[..., -1] = np.where(result[..., -1] >= 0, 1.0, -1.0)
        return result
