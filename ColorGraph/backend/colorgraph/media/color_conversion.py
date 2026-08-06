from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from PIL import Image

from colorgraph.devices.base import ComputeBackend
from colorgraph.grading.color import (
    SONY_SLOG3_SGAMUT3CINE,
    linear_to_srgb,
    log_to_linear_rec709,
)


def log_rgb_array_for_display(
    array: np.ndarray,
    backend: ComputeBackend,
    source_log_profile: str | None,
) -> np.ndarray:
    if array.dtype == np.uint8:
        normalized = array.astype(np.float32) / 255.0
    else:
        normalized = array.astype(np.float32)
    tensor = torch.from_numpy(normalized).permute(2, 0, 1).unsqueeze(0).to(backend.torch_device)
    with backend.inference_context(mixed_precision=False):
        output = linear_to_srgb(log_to_linear_rec709(tensor, source_log_profile)).clamp(0, 1)
    return output[0].permute(1, 2, 0).mul(255).round().byte().cpu().numpy()


def convert_log_frame_for_display(
    path: str | Path,
    backend: ComputeBackend,
    source_log_profile: str | None,
) -> Path:
    target = Path(path).resolve()
    with Image.open(target) as source:
        array = np.asarray(source.convert("RGB"), dtype=np.float32) / 255.0
    converted = log_rgb_array_for_display(array, backend, source_log_profile)
    Image.fromarray(converted, mode="RGB").save(target, quality=94)
    return target


def slog3_rgb_array_for_display(
    array: np.ndarray,
    backend: ComputeBackend,
) -> np.ndarray:
    """Backward-compatible Sony-specific display conversion."""

    return log_rgb_array_for_display(array, backend, SONY_SLOG3_SGAMUT3CINE)


def convert_slog3_frame_for_display(
    path: str | Path,
    backend: ComputeBackend,
) -> Path:
    """Backward-compatible Sony-specific representative-frame conversion."""

    return convert_log_frame_for_display(path, backend, SONY_SLOG3_SGAMUT3CINE)
