"""Fixed and risk-aware frame sampling."""

from __future__ import annotations

import threading
from typing import cast

import cv2
import numpy as np
from numpy.typing import NDArray

from buildguard.config import CameraPolicyConfig, RealtimeOptimizationConfig
from buildguard.realtime.schemas import SamplingMode


class FixedFpsSampler:
    def __init__(self, fps: float) -> None:
        if fps <= 0:
            raise ValueError("Sampling FPS must be positive")
        self.fps = fps
        self.interval_seconds = 1.0 / fps
        self._last_sample: float | None = None

    def should_sample(self, timestamp_seconds: float) -> bool:
        if timestamp_seconds < 0:
            raise ValueError("Sampling timestamp must be non-negative")
        if (
            self._last_sample is None
            or timestamp_seconds - self._last_sample + 1e-12 >= self.interval_seconds
        ):
            self._last_sample = timestamp_seconds
            return True
        return False

    def reset(self) -> None:
        self._last_sample = None


class RiskAwareSampler:
    def __init__(
        self,
        *,
        normal_fps: float,
        active_fps: float,
        suspected_fps: float,
    ) -> None:
        if not 0 < normal_fps <= active_fps <= suspected_fps:
            raise ValueError("Sampling FPS must satisfy normal <= active <= suspected")
        self._fps = {
            SamplingMode.NORMAL: normal_fps,
            SamplingMode.ACTIVE: active_fps,
            SamplingMode.SUSPECTED: suspected_fps,
        }
        self._modes: dict[str, SamplingMode] = {}
        self._last_sample: dict[str, float] = {}

    def set_mode(self, camera_id: str, mode: SamplingMode) -> None:
        self._modes[camera_id] = mode

    def mode(self, camera_id: str) -> SamplingMode:
        return self._modes.get(camera_id, SamplingMode.NORMAL)

    def should_sample(self, camera_id: str, timestamp_seconds: float) -> bool:
        if timestamp_seconds < 0:
            raise ValueError("Sampling timestamp must be non-negative")
        interval = 1.0 / self._fps[self.mode(camera_id)]
        previous = self._last_sample.get(camera_id)
        if previous is None or timestamp_seconds - previous + 1e-12 >= interval:
            self._last_sample[camera_id] = timestamp_seconds
            return True
        return False

    def reset(self, camera_id: str) -> None:
        self._last_sample.pop(camera_id, None)
        self._modes.pop(camera_id, None)


class AdaptiveMotionSampler:
    """Motion-driven sampling with consecutive-frame transition hysteresis."""

    def __init__(
        self,
        policy: CameraPolicyConfig,
        optimization: RealtimeOptimizationConfig | None = None,
    ) -> None:
        self.policy = policy
        self.optimization = optimization or RealtimeOptimizationConfig()
        self._mode = SamplingMode.STATIC
        self._candidate = SamplingMode.STATIC
        self._candidate_frames = 0
        self._previous_gray: NDArray[np.uint8] | None = None
        self._last_sample: float | None = None
        self._suspected_risk = False
        self._last_timestamp = 0.0
        self._suspected_until = 0.0
        self._active_until = 0.0
        self._recovery_until = 0.0
        self._risk_score = 0.0
        self._uncertainty_score = 0.0
        self._motion_score = 0.0
        self._lock = threading.RLock()

    @property
    def mode(self) -> SamplingMode:
        with self._lock:
            if not self.optimization.enabled:
                return SamplingMode.SUSPECTED if self._suspected_risk else self._mode
            if self._suspected_risk or (
                self._suspected_until > 0
                and self._last_timestamp <= self._suspected_until
            ):
                return SamplingMode.SUSPECTED
            if self._active_until > 0 and self._last_timestamp <= self._active_until:
                return SamplingMode.ACTIVE
            if self._recovery_until > 0 and self._last_timestamp <= self._recovery_until:
                return SamplingMode.RECOVERY
            return self._mode

    @property
    def motion_score(self) -> float:
        with self._lock:
            return self._motion_score

    @property
    def fps(self) -> float:
        mode = self.mode
        return {
            SamplingMode.STATIC: self.policy.static_fps,
            SamplingMode.LOW_MOTION: self.policy.low_motion_fps,
            SamplingMode.NORMAL: self.policy.low_motion_fps,
            SamplingMode.ACTIVE: self.policy.active_fps,
            SamplingMode.SUSPECTED: self.policy.suspected_fps,
            SamplingMode.RECOVERY: self.policy.active_fps,
        }[mode]

    def set_suspected_risk(
        self,
        suspected: bool,
        timestamp_seconds: float | None = None,
    ) -> None:
        with self._lock:
            timestamp = self._last_timestamp if timestamp_seconds is None else timestamp_seconds
            if timestamp < 0:
                raise ValueError("Sampling timestamp must be non-negative")
            self._last_timestamp = max(self._last_timestamp, timestamp)
            self._suspected_risk = suspected
            if self.optimization.enabled:
                if suspected:
                    self._suspected_until = max(
                        self._suspected_until,
                        timestamp + self.optimization.suspected_hold_seconds,
                    )
                else:
                    self._recovery_until = max(
                        self._recovery_until,
                        timestamp + self.optimization.recovery_hold_seconds,
                    )

    def update_feedback(
        self,
        *,
        timestamp_seconds: float,
        active_tracks: bool,
        risk_score: float,
        uncertainty_score: float,
    ) -> None:
        """Feed detector/tracker state back into sampling without changing models."""
        if timestamp_seconds < 0:
            raise ValueError("Sampling timestamp must be non-negative")
        if not 0 <= risk_score <= 1 or not 0 <= uncertainty_score <= 1:
            raise ValueError("Sampling feedback scores must be within 0..1")
        with self._lock:
            self._last_timestamp = max(self._last_timestamp, timestamp_seconds)
            self._risk_score = risk_score
            self._uncertainty_score = uncertainty_score
            suspected = (
                risk_score > 0
                or uncertainty_score >= self.optimization.uncertainty_threshold
            )
            self._suspected_risk = suspected
            if suspected:
                self._suspected_until = max(
                    self._suspected_until,
                    timestamp_seconds + self.optimization.suspected_hold_seconds,
                )
            elif active_tracks:
                self._active_until = max(
                    self._active_until,
                    timestamp_seconds + self.optimization.recovery_hold_seconds,
                )
            else:
                self._recovery_until = max(
                    self._recovery_until,
                    timestamp_seconds + self.optimization.recovery_hold_seconds,
                )

    def observe(self, image: NDArray[np.uint8]) -> float:
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("Adaptive sampler expects an HxWx3 uint8 BGR frame")
        gray = cast(
            NDArray[np.uint8],
            cv2.cvtColor(image, cv2.COLOR_BGR2GRAY),
        )
        with self._lock:
            if self._previous_gray is None or self._previous_gray.shape != gray.shape:
                score = 0.0
            else:
                score = float(
                    np.mean(np.abs(gray.astype(np.int16) - self._previous_gray.astype(np.int16)))
                )
            self._previous_gray = gray
            self._motion_score = score
            target = (
                SamplingMode.STATIC
                if score <= self.policy.static_motion_threshold
                else (
                    SamplingMode.LOW_MOTION
                    if score <= self.policy.active_motion_threshold
                    else SamplingMode.ACTIVE
                )
            )
            if target == self._mode:
                self._candidate = target
                self._candidate_frames = 0
            elif target == self._candidate:
                self._candidate_frames += 1
                if self._candidate_frames >= self.policy.hysteresis_frames:
                    self._mode = target
                    self._candidate_frames = 0
            else:
                self._candidate = target
                self._candidate_frames = 1
            return score

    def should_sample(self, timestamp_seconds: float) -> bool:
        if timestamp_seconds < 0:
            raise ValueError("Sampling timestamp must be non-negative")
        with self._lock:
            self._last_timestamp = max(self._last_timestamp, timestamp_seconds)
            interval = 1.0 / self.fps
            if (
                self._last_sample is None
                or timestamp_seconds - self._last_sample + 1e-12 >= interval
            ):
                self._last_sample = timestamp_seconds
                return True
            return False

    def reset(self) -> None:
        with self._lock:
            self._mode = SamplingMode.STATIC
            self._candidate = SamplingMode.STATIC
            self._candidate_frames = 0
            self._previous_gray = None
            self._last_sample = None
            self._suspected_risk = False
            self._last_timestamp = 0.0
            self._suspected_until = 0.0
            self._active_until = 0.0
            self._recovery_until = 0.0
            self._risk_score = 0.0
            self._uncertainty_score = 0.0
            self._motion_score = 0.0
