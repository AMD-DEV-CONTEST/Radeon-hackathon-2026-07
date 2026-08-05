"""Observable health features for RGB/LiDAR temporal diagnosis."""

from __future__ import annotations

import numpy as np


FEATURE_NAMES = (
    "camera_mean",
    "camera_std",
    "camera_sharpness_log",
    "camera_temporal_delta",
    "lidar_mean",
    "lidar_std",
    "lidar_min",
    "lidar_zero_ratio",
    "lidar_temporal_delta",
    "speed_normalized",
)

TIMING_FEATURE_NAMES = FEATURE_NAMES + (
    "camera_age_normalized",
    "lidar_age_normalized",
    "sensor_age_skew",
    "cross_modal_delta_gap",
    "lidar_zero_ratio_delta",
)


class HealthFeatureExtractor:
    """Extract causal features without access to clean/reference sensors."""

    def __init__(self) -> None:
        self.previous_rgb: np.ndarray | None = None
        self.previous_lidar: np.ndarray | None = None

    def reset(self) -> None:
        self.previous_rgb = None
        self.previous_lidar = None

    @staticmethod
    def _sharpness(rgb: np.ndarray) -> float:
        gray = rgb.mean(axis=2)
        dx = np.diff(gray, axis=1)
        dy = np.diff(gray, axis=0)
        energy = float(np.mean(dx * dx) + np.mean(dy * dy))
        return float(np.log1p(10000.0 * energy))

    def extract(self, rgb: np.ndarray, lidar: np.ndarray, speed_km_h: float) -> np.ndarray:
        rgb = np.asarray(rgb, dtype=np.float32)
        lidar = np.asarray(lidar, dtype=np.float32)

        camera_delta = (
            0.0 if self.previous_rgb is None else float(np.mean(np.abs(rgb - self.previous_rgb)))
        )
        lidar_delta = (
            0.0
            if self.previous_lidar is None
            else float(np.mean(np.abs(lidar - self.previous_lidar)))
        )

        features = np.asarray(
            [
                float(rgb.mean()),
                float(rgb.std()),
                self._sharpness(rgb),
                camera_delta,
                float(lidar.mean()),
                float(lidar.std()),
                float(lidar.min()),
                float(np.mean(lidar == 0.0)),
                lidar_delta,
                float(np.clip(speed_km_h / 80.0, 0.0, 2.0)),
            ],
            dtype=np.float32,
        )
        self.previous_rgb = rgb.copy()
        self.previous_lidar = lidar.copy()
        return features


class TimingAwareHealthFeatureExtractor(HealthFeatureExtractor):
    """Add observable packet-timing and temporal consistency indicators.

    Sensor packet timestamps are available to a real autonomy stack and do not
    require access to an uncorrupted reference stream. Ages are expressed in
    frame intervals by the caller and normalized to the five-frame fault range.
    """

    def __init__(self) -> None:
        super().__init__()
        self.previous_zero_ratio: float | None = None

    def reset(self) -> None:
        super().reset()
        self.previous_zero_ratio = None

    def extract(
        self,
        rgb: np.ndarray,
        lidar: np.ndarray,
        speed_km_h: float,
        camera_age_frames: float = 0.0,
        lidar_age_frames: float = 0.0,
    ) -> np.ndarray:
        base = super().extract(rgb, lidar, speed_km_h)
        zero_ratio = float(base[7])
        zero_delta = (
            0.0
            if self.previous_zero_ratio is None
            else abs(zero_ratio - self.previous_zero_ratio)
        )
        self.previous_zero_ratio = zero_ratio
        camera_age = float(np.clip(camera_age_frames / 5.0, 0.0, 2.0))
        lidar_age = float(np.clip(lidar_age_frames / 5.0, 0.0, 2.0))
        timing = np.asarray(
            [
                camera_age,
                lidar_age,
                abs(camera_age - lidar_age),
                abs(float(base[3]) - float(base[8])),
                zero_delta,
            ],
            dtype=np.float32,
        )
        return np.concatenate((base, timing)).astype(np.float32, copy=False)


def fault_risk_target(blur_sigma: float, frozen: bool, dropout: float, delay: int) -> float:
    """Continuous training target representing compound-fault severity."""

    risk = (
        0.25 * np.clip(blur_sigma / 4.0, 0.0, 1.0)
        + 0.30 * float(frozen)
        + 0.35 * np.clip(dropout, 0.0, 1.0)
        + 0.20 * np.clip(delay / 5.0, 0.0, 1.0)
    )
    return float(np.clip(risk, 0.0, 1.0))
