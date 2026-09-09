"""Deterministic temporal faults for synchronized RGB and LiDAR streams."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class FaultState:
    """Ground-truth fault metadata for one simulation step."""

    name: str
    blur_sigma: float = 0.0
    camera_frozen: bool = False
    lidar_dropout: float = 0.0
    delay_frames: int = 0


class FaultInjector:
    """Inject compound temporal faults while preserving stream history."""

    SCENARIOS = (
        "clean",
        "progressive_blur",
        "camera_freeze",
        "lidar_dropout",
        "dynamic_delay",
        "freeze_plus_dropout",
        "blur_plus_delay",
    )

    def __init__(self, total_steps: int, seed: int = 0, max_delay: int = 5) -> None:
        if total_steps < len(self.SCENARIOS):
            raise ValueError("total_steps must cover every fault scenario")
        self.total_steps = total_steps
        self.max_delay = max_delay
        self.rng = np.random.default_rng(seed)
        self.rgb_history: deque[np.ndarray] = deque(maxlen=max_delay + 1)
        self.lidar_history: deque[np.ndarray] = deque(maxlen=max_delay + 1)
        self.frozen_rgb: np.ndarray | None = None

    def _scenario(self, step: int) -> tuple[str, float]:
        scaled = min(max(step / self.total_steps, 0.0), 0.999999)
        position = scaled * len(self.SCENARIOS)
        index = int(position)
        return self.SCENARIOS[index], position - index

    @staticmethod
    def _blur(rgb: np.ndarray, sigma: float) -> np.ndarray:
        if sigma <= 0:
            return rgb.copy()
        kernel = max(3, int(round(sigma * 4)) | 1)
        return cv2.GaussianBlur(rgb, (kernel, kernel), sigmaX=sigma)

    def apply(
        self, step: int, rgb: np.ndarray, lidar: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, FaultState]:
        rgb = np.asarray(rgb, dtype=np.float32)
        lidar = np.asarray(lidar, dtype=np.float32)
        self.rgb_history.append(rgb.copy())
        self.lidar_history.append(lidar.copy())

        name, progress = self._scenario(step)
        output_rgb = rgb.copy()
        output_lidar = lidar.copy()
        blur_sigma = 0.0
        camera_frozen = False
        lidar_dropout = 0.0
        delay_frames = 0

        if name in {"progressive_blur", "blur_plus_delay"}:
            blur_sigma = 0.5 + 3.5 * progress
            output_rgb = self._blur(output_rgb, blur_sigma)

        if name in {"camera_freeze", "freeze_plus_dropout"}:
            camera_frozen = True
            if self.frozen_rgb is None:
                self.frozen_rgb = output_rgb.copy()
            output_rgb = self.frozen_rgb.copy()
        else:
            self.frozen_rgb = None

        if name in {"lidar_dropout", "freeze_plus_dropout"}:
            lidar_dropout = 0.2 + 0.7 * progress
            mask = self.rng.random(output_lidar.shape) < lidar_dropout
            output_lidar[mask] = 0.0

        if name in {"dynamic_delay", "blur_plus_delay"}:
            delay_frames = 1 + int(progress * self.max_delay)
            available = min(delay_frames, len(self.rgb_history) - 1)
            if available > 0:
                output_rgb = list(self.rgb_history)[-1 - available].copy()
                output_lidar = list(self.lidar_history)[-1 - available].copy()
                if name == "blur_plus_delay":
                    output_rgb = self._blur(output_rgb, blur_sigma)

        state = FaultState(
            name=name,
            blur_sigma=blur_sigma,
            camera_frozen=camera_frozen,
            lidar_dropout=lidar_dropout,
            delay_frames=delay_frames,
        )
        return output_rgb, output_lidar, state
