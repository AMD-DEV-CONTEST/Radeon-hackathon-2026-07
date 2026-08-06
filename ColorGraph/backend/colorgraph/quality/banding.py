from __future__ import annotations

import cv2
import numpy as np

BANDING_METRIC_VERSION = "colorgraph.cambi-equivalent/v1"


def _scale_banding_risk(luma: np.ndarray) -> float:
    height, width = luma.shape
    if height < 8 or width < 8:
        return 0.0
    blurred = cv2.GaussianBlur(luma, (0, 0), sigmaX=0.8)
    residual = np.abs(luma - blurred)
    flatness = float(np.clip(1.0 - np.percentile(residual, 90) / 0.025, 0, 1))
    if flatness <= 0:
        return 0.0

    low = float(np.percentile(blurred, 2))
    high = float(np.percentile(blurred, 98))
    if high - low < 0.03:
        return 0.0
    quantized = np.clip(np.round(blurred * 255), 0, 255).astype(np.uint8)
    in_range = quantized[
        (blurred >= low)
        & (blurred <= high)
    ]
    if in_range.size < 128:
        return 0.0
    occupied = int(np.unique(in_range).size)
    tonal_bins = max(1, round((high - low) * 255) + 1)
    occupancy_deficit = float(
        np.clip(1.0 - occupied / min(tonal_bins, 96), 0, 1)
    )

    horizontal = np.abs(np.diff(blurred, axis=1))
    vertical = np.abs(np.diff(blurred, axis=0))
    visible_horizontal = (horizontal >= 1.5 / 255) & (horizontal <= 0.12)
    visible_vertical = (vertical >= 1.5 / 255) & (vertical <= 0.12)
    contour_density = float(
        (visible_horizontal.mean() + visible_vertical.mean()) / 2
    )
    contour_visibility = float(np.clip(contour_density / 0.05, 0, 1))
    return occupancy_deficit * flatness * (0.65 + 0.35 * contour_visibility)


def cambi_equivalent_score(luma: np.ndarray) -> float:
    """Return a deterministic 0..1 CAMBI-inspired banding risk.

    This is an in-tree equivalent metric, not Netflix CAMBI. It combines
    multi-scale tonal-level sparsity, local flatness, and persistent
    low-contrast contours so that texture/noise does not masquerade as banding.
    """

    values = np.asarray(luma, dtype=np.float32)
    if values.ndim != 2:
        raise ValueError("banding metric expects a two-dimensional luma image")
    if not np.isfinite(values).all():
        return 1.0
    values = np.clip(values, 0, 1)
    scores: list[float] = []
    current = values
    for _ in range(3):
        scores.append(_scale_banding_risk(current))
        if min(current.shape) < 32:
            break
        current = cv2.pyrDown(current)
    weights = np.asarray([1.0, 0.75, 0.5][: len(scores)], dtype=np.float64)
    return float(np.clip(np.dot(scores, weights) / weights.sum(), 0, 1))
