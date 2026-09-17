"""Small, dependency-light helpers for reproducible visual perturbations."""
from __future__ import annotations

import numpy as np


def resolve_domain_randomization(
    enabled: bool,
    image_noise_std: float,
    brightness_range: tuple[float, float] | None,
) -> tuple[float, tuple[float, float] | None]:
    """Resolve CLI defaults while keeping the legacy no-augmentation path."""
    if enabled:
        if image_noise_std == 0.0:
            image_noise_std = 4.0
        if brightness_range is None:
            brightness_range = (0.85, 1.15)
    if image_noise_std < 0.0:
        raise ValueError("image noise standard deviation must be non-negative")
    if brightness_range is not None:
        lo, hi = brightness_range
        if lo <= 0.0 or lo >= hi:
            raise ValueError("brightness range must satisfy 0 < min < max")
        brightness_range = (float(lo), float(hi))
    return float(image_noise_std), brightness_range


def augment_image(
    image: np.ndarray,
    rng: np.random.Generator,
    noise_std: float = 0.0,
    brightness: float = 1.0,
) -> np.ndarray:
    """Apply deterministic illumination and sensor-noise perturbations."""
    arr = image.astype(np.float32) * float(brightness)
    if noise_std > 0.0:
        arr += rng.normal(0.0, noise_std, size=arr.shape)
    return np.clip(arr, 0.0, 255.0).astype(np.uint8)


def ablate_camera(
    image: np.ndarray,
    camera: str,
    ablation: str,
    fill_value: float = 127.5,
) -> np.ndarray:
    """Replace the camera that is not part of an ablation with neutral pixels."""
    if ablation not in ("both", "overhead_only", "wrist_only"):
        raise ValueError(f"unknown camera ablation: {ablation}")
    keep = (
        ablation == "both"
        or (ablation == "overhead_only" and camera == "overhead")
        or (ablation == "wrist_only" and camera == "wrist")
    )
    if keep:
        return image
    value = np.uint8(np.clip(round(fill_value), 0, 255))
    return np.full_like(image, value)


def apply_random_camera_dropout(
    image: np.ndarray,
    camera: str,
    rng: np.random.Generator,
    probability: float = 0.0,
    fill_value: float = 127.5,
) -> tuple[np.ndarray, bool]:
    """Randomly replace one camera with neutral pixels.

    This is deliberately frame-local: a real sensor can be briefly occluded or
    unavailable while the rest of the observation remains usable.  Returning
    the applied flag lets evaluation report how often a dropout occurred.
    """
    if not 0.0 <= probability <= 1.0:
        raise ValueError("camera dropout probability must be in [0, 1]")
    dropped = bool(rng.random() < probability)
    if not dropped:
        return image, False
    value = np.uint8(np.clip(round(fill_value), 0, 255))
    return np.full_like(image, value), True


def apply_occlusion(
    image: np.ndarray,
    rng: np.random.Generator,
    probability: float = 0.0,
    fraction: float = 0.25,
    fill_value: float = 0.0,
) -> tuple[np.ndarray, bool]:
    """Apply a deterministic-per-seed rectangular image occlusion."""
    if not 0.0 <= probability <= 1.0:
        raise ValueError("occlusion probability must be in [0, 1]")
    if not 0.0 < fraction <= 1.0:
        raise ValueError("occlusion fraction must be in (0, 1]")
    if rng.random() >= probability:
        return image, False

    height, width = image.shape[:2]
    occ_h = max(1, int(round(height * fraction)))
    occ_w = max(1, int(round(width * fraction)))
    top = int(rng.integers(0, max(height - occ_h + 1, 1)))
    left = int(rng.integers(0, max(width - occ_w + 1, 1)))
    out = image.copy()
    out[top:top + occ_h, left:left + occ_w] = np.uint8(
        np.clip(round(fill_value), 0, 255)
    )
    return out, True
