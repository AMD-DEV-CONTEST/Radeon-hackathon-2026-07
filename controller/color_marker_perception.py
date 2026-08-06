"""Color-marker perception and planar camera calibration for visual servoing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class MarkerCalibration:
    """Independent pixel-to-table homographies for the object and target markers."""

    object_homography: np.ndarray
    target_homography: np.ndarray

    @classmethod
    def load(cls, path: str | Path) -> "MarkerCalibration":
        payload = json.loads(Path(path).read_text())
        return cls(
            object_homography=np.asarray(payload["object_homography"], dtype=np.float32),
            target_homography=np.asarray(payload["target_homography"], dtype=np.float32),
        )

    def save(self, path: str | Path, *, metadata: dict[str, object]) -> None:
        Path(path).write_text(json.dumps({
            "object_homography": self.object_homography.tolist(),
            "target_homography": self.target_homography.tolist(),
            **metadata,
        }, indent=2) + "\n")


class ColorMarkerPerception:
    """Detect the red object and green target tile in an RGB Genesis frame."""

    def __init__(self, calibration: MarkerCalibration, *, min_area_px: float = 12.0) -> None:
        self.calibration = calibration
        self.min_area_px = float(min_area_px)

    @staticmethod
    def _centroid(mask: np.ndarray, min_area_px: float) -> np.ndarray | None:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        contour = max(contours, key=cv2.contourArea)
        moments = cv2.moments(contour)
        if cv2.contourArea(contour) < min_area_px or moments["m00"] == 0.0:
            return None
        return np.asarray([moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]], dtype=np.float32)

    @classmethod
    def red_centroid(cls, rgb: np.ndarray, *, min_area_px: float = 12.0) -> np.ndarray | None:
        hsv = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2HSV)
        lower = cv2.inRange(hsv, np.array([0, 90, 50]), np.array([12, 255, 255]))
        upper = cv2.inRange(hsv, np.array([168, 90, 50]), np.array([180, 255, 255]))
        return cls._centroid(cv2.bitwise_or(lower, upper), min_area_px)

    @classmethod
    def green_centroid(cls, rgb: np.ndarray, *, min_area_px: float = 12.0) -> np.ndarray | None:
        hsv = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv, np.array([35, 70, 45]), np.array([95, 255, 255]))
        return cls._centroid(mask, min_area_px)

    @staticmethod
    def _project(pixel: np.ndarray, homography: np.ndarray) -> np.ndarray:
        point = cv2.perspectiveTransform(pixel.reshape(1, 1, 2), homography).reshape(2)
        return point.astype(np.float32)

    def estimate(self, rgb: np.ndarray) -> tuple[np.ndarray | None, np.ndarray | None]:
        object_pixel = self.red_centroid(rgb, min_area_px=self.min_area_px)
        target_pixel = self.green_centroid(rgb, min_area_px=self.min_area_px)
        object_xy = None if object_pixel is None else self._project(object_pixel, self.calibration.object_homography)
        target_xy = None if target_pixel is None else self._project(target_pixel, self.calibration.target_homography)
        return object_xy, target_xy
