"""Causal timestamp-feature corruption used for robustness training."""

from __future__ import annotations

import numpy as np


TRAINING_CONDITIONS = (
    "missing_burst_30pct",
    "camera_clock_drift_3frames",
    "timestamp_jitter_1frame",
    "timestamp_channels_swapped",
    "timestamps_spoofed_clean",
)

STRESS_CALIBRATION_CONDITIONS = (
    "intact",
    "missing_burst_50pct",
    "camera_clock_drift_5frames",
    "timestamp_jitter_2frames",
    "timestamp_channels_swapped",
    "timestamps_spoofed_clean",
)


def timestamp_feature_indices(feature_names: list[str]) -> tuple[int, int, int]:
    required = (
        "camera_age_normalized",
        "lidar_age_normalized",
        "sensor_age_skew",
    )
    missing = [name for name in required if name not in feature_names]
    if missing:
        raise ValueError(f"Timing feature names are missing: {missing}")
    return tuple(feature_names.index(name) for name in required)  # type: ignore[return-value]


def corrupt_timestamp_sequences(
    source: np.ndarray,
    feature_names: list[str],
    condition: str,
    rng: np.random.Generator,
) -> np.ndarray:
    """Apply one timestamp condition independently to every sequence."""

    if source.ndim != 3:
        raise ValueError("Timestamp sequence corruption expects [N, T, F]")
    if condition == "intact":
        return source
    output = source.copy()
    camera_index, lidar_index, skew_index = timestamp_feature_indices(feature_names)
    sequence_count, length, _ = output.shape

    if condition.startswith("missing_burst_"):
        percentage = int(condition.removeprefix("missing_burst_").removesuffix("pct"))
        burst_length = max(1, int(round(length * percentage / 100.0)))
        for sequence in range(sequence_count):
            start = int(rng.integers(0, length - burst_length + 1))
            selected = slice(start, start + burst_length)
            output[sequence, selected, camera_index] = 0.0
            output[sequence, selected, lidar_index] = 0.0
            output[sequence, selected, skew_index] = 0.0
    elif condition.startswith("camera_clock_drift_"):
        frames = float(
            condition.removeprefix("camera_clock_drift_").removesuffix("frames").removesuffix("frame")
        )
        drift = np.linspace(0.0, frames / 5.0, length, dtype=np.float32)
        output[:, :, camera_index] = np.clip(
            output[:, :, camera_index] + drift[None, :], 0.0, 2.0
        )
        output[:, :, skew_index] = np.abs(
            output[:, :, camera_index] - output[:, :, lidar_index]
        )
    elif condition.startswith("timestamp_jitter_"):
        frames = float(
            condition.removeprefix("timestamp_jitter_").removesuffix("frames").removesuffix("frame")
        )
        scale = frames / 5.0
        camera_noise = rng.normal(0.0, scale, size=(sequence_count, length)).astype(np.float32)
        lidar_noise = rng.normal(0.0, scale, size=(sequence_count, length)).astype(np.float32)
        output[:, :, camera_index] = np.clip(
            output[:, :, camera_index] + camera_noise, 0.0, 2.0
        )
        output[:, :, lidar_index] = np.clip(
            output[:, :, lidar_index] + lidar_noise, 0.0, 2.0
        )
        output[:, :, skew_index] = np.abs(
            output[:, :, camera_index] - output[:, :, lidar_index]
        )
    elif condition == "timestamp_channels_swapped":
        camera = output[:, :, camera_index].copy()
        output[:, :, camera_index] = output[:, :, lidar_index]
        output[:, :, lidar_index] = camera
        output[:, :, skew_index] = np.abs(
            output[:, :, camera_index] - output[:, :, lidar_index]
        )
    elif condition == "timestamps_spoofed_clean":
        output[:, :, camera_index] = 0.0
        output[:, :, lidar_index] = 0.0
        output[:, :, skew_index] = 0.0
    else:
        raise ValueError(f"Unknown timestamp corruption condition: {condition}")
    return output


def augment_timestamp_training_sequences(
    source: np.ndarray,
    feature_names: list[str],
    probability: float,
    seed: int,
) -> tuple[np.ndarray, dict[str, int]]:
    if not 0.0 <= probability <= 1.0:
        raise ValueError("Timestamp augmentation probability must be in [0, 1]")
    output = source.copy()
    counts = {"intact": len(output), **{name: 0 for name in TRAINING_CONDITIONS}}
    if probability == 0.0:
        return output, counts
    rng = np.random.default_rng(seed)
    selected = np.flatnonzero(rng.random(len(output)) < probability)
    counts["intact"] -= len(selected)
    assignments = rng.integers(0, len(TRAINING_CONDITIONS), size=len(selected))
    for condition_index, condition in enumerate(TRAINING_CONDITIONS):
        indices = selected[assignments == condition_index]
        counts[condition] = len(indices)
        if len(indices):
            output[indices] = corrupt_timestamp_sequences(
                output[indices], feature_names, condition, rng
            )
    return output, counts
