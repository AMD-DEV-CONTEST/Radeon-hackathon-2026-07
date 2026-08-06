"""Deterministic image and temporal feature extraction for one RoI."""

from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray

from buildguard.schemas.common import BoundingBox
from buildguard.vision.routing.schemas import RoiContext, RoiFeatures


def _validate_image(image: NDArray[np.uint8]) -> None:
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("routing image must be a non-empty HxWx3 uint8 BGR array")
    if image.size == 0:
        raise ValueError("routing image must not be empty")


class RoiFeatureExtractor:
    """Extract bounded normalized features without model inference."""

    def extract(
        self,
        image: NDArray[np.uint8],
        bounding_box: BoundingBox,
        context: RoiContext,
        *,
        previous_image: NDArray[np.uint8] | None = None,
    ) -> RoiFeatures:
        _validate_image(image)
        height, width = image.shape[:2]
        box = bounding_box.clip(float(width), float(height))
        x1, y1 = int(box.x1), int(box.y1)
        x2, y2 = max(x1 + 1, int(np.ceil(box.x2))), max(y1 + 1, int(np.ceil(box.y2)))
        roi = image[y1:y2, x1:x2]
        if roi.size == 0:
            raise ValueError("ROI has no pixels after clipping")
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        brightness = float(np.mean(gray) / 255.0)
        standard_deviation = np.asarray(gray, dtype=np.float64).std().item()
        contrast = min(1.0, float(standard_deviation) / 127.5)
        laplacian_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        sharpness = laplacian_variance / (laplacian_variance + 100.0)
        blur = 1.0 - sharpness
        edges = cv2.Canny(gray, 80, 160)
        edge_density = float(np.count_nonzero(edges) / edges.size)
        texture_score = min(1.0, (contrast + edge_density + sharpness) / 3.0)
        motion_score = 0.0
        if previous_image is not None:
            _validate_image(previous_image)
            previous_roi = previous_image[y1:y2, x1:x2]
            if previous_roi.shape == roi.shape:
                previous_gray = cv2.cvtColor(previous_roi, cv2.COLOR_BGR2GRAY)
                motion_score = float(
                    np.mean(cv2.absdiff(gray, previous_gray)) / 255.0
                )
        return RoiFeatures(
            roi_label=context.roi_label,
            roi_confidence=context.roi_confidence,
            area_ratio=box.area / float(width * height),
            aspect_ratio=box.width / box.height,
            center=(
                ((box.x1 + box.x2) / 2.0) / width,
                ((box.y1 + box.y2) / 2.0) / height,
            ),
            brightness=brightness,
            contrast=contrast,
            blur=blur,
            edge_density=edge_density,
            texture_score=texture_score,
            motion_score=motion_score,
            track_age=context.track_age,
            previous_probability=context.previous_probability,
            previous_detection_confidence=context.previous_detection_confidence,
            device_load=context.device_load,
            high_risk=context.high_risk,
        )
