"""Deterministic binary-mask geometry metrics."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from buildguard.schemas.common import BoundingBox


def normalize_mask(
    mask: NDArray[np.bool_] | NDArray[np.integer[Any]],
    image_shape: tuple[int, int],
) -> NDArray[np.bool_]:
    normalized = np.asarray(mask, dtype=np.bool_)
    if normalized.ndim != 2 or normalized.shape != image_shape:
        raise ValueError(
            f"Mask shape {normalized.shape} does not match image shape {image_shape}"
        )
    return normalized


def mask_area(mask: NDArray[np.bool_]) -> int:
    return int(np.count_nonzero(mask))


def mask_area_ratio(mask: NDArray[np.bool_]) -> float:
    if mask.size == 0:
        raise ValueError("Mask must not be empty")
    return mask_area(mask) / float(mask.size)


def mask_bounding_box(mask: NDArray[np.bool_]) -> BoundingBox:
    rows, columns = np.nonzero(mask)
    if rows.size == 0:
        raise ValueError("Cannot measure an empty segmentation mask")
    return BoundingBox(
        x1=float(columns.min()),
        y1=float(rows.min()),
        x2=float(columns.max() + 1),
        y2=float(rows.max() + 1),
    )


def mask_perimeter(mask: NDArray[np.bool_]) -> float:
    encoded = np.asarray(mask, dtype=np.uint8) * 255
    contours, _ = cv2.findContours(
        encoded,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_NONE,
    )
    perimeter = sum(float(cv2.arcLength(contour, True)) for contour in contours)
    if perimeter <= 0:
        raise ValueError("Cannot measure the perimeter of an empty mask")
    return perimeter

