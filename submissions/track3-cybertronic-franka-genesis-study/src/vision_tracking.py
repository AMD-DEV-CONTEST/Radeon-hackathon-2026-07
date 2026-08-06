from dataclasses import asdict
from dataclasses import dataclass
from typing import Optional
from typing import Tuple

import numpy as np


@dataclass
class Detection:
    found: bool
    center_x: Optional[float]
    center_y: Optional[float]
    bbox: Optional[Tuple[int, int, int, int]]
    confidence: float
    area: int
    image_width: int
    image_height: int

    def to_dict(self):
        return asdict(self)


class RedObjectTracker:
    """Lightweight red-object detector for rendered Genesis camera frames."""

    def __init__(
        self,
        red_margin=35,
        min_red=80,
        max_green=150,
        max_blue=150,
        min_area=30,
    ):
        self.red_margin = red_margin
        self.min_red = min_red
        self.max_green = max_green
        self.max_blue = max_blue
        self.min_area = min_area

    def detect(self, frame):
        image = normalize_rgb_frame(frame)

        if image is None:
            return Detection(
                found=False,
                center_x=None,
                center_y=None,
                bbox=None,
                confidence=0.0,
                area=0,
                image_width=0,
                image_height=0,
            )

        height, width = image.shape[:2]
        red = image[:, :, 0].astype(np.int16)
        green = image[:, :, 1].astype(np.int16)
        blue = image[:, :, 2].astype(np.int16)

        mask = (
            (red >= self.min_red)
            & (green <= self.max_green)
            & (blue <= self.max_blue)
            & (red - green >= self.red_margin)
            & (red - blue >= self.red_margin)
        )

        ys, xs = np.nonzero(mask)
        area = int(xs.size)

        if area < self.min_area:
            return Detection(
                found=False,
                center_x=None,
                center_y=None,
                bbox=None,
                confidence=0.0,
                area=area,
                image_width=width,
                image_height=height,
            )

        x0 = int(xs.min())
        x1 = int(xs.max())
        y0 = int(ys.min())
        y1 = int(ys.max())
        center_x = float(xs.mean())
        center_y = float(ys.mean())

        bbox_area = max(1, (x1 - x0 + 1) * (y1 - y0 + 1))
        density = min(1.0, area / bbox_area)
        image_ratio = min(1.0, area / max(1, width * height) * 200.0)
        confidence = float(0.7 * density + 0.3 * image_ratio)

        return Detection(
            found=True,
            center_x=center_x,
            center_y=center_y,
            bbox=(x0, y0, x1, y1),
            confidence=confidence,
            area=area,
            image_width=width,
            image_height=height,
        )


class ExponentialSmoother:
    def __init__(self, alpha=0.35):
        self.alpha = alpha
        self.value = None

    def update(self, value):
        value = np.asarray(value, dtype=np.float32)

        if self.value is None:
            self.value = value
        else:
            self.value = (
                self.alpha * value
                + (1.0 - self.alpha) * self.value
            )

        return self.value.copy()


def normalize_rgb_frame(frame):
    """Convert common camera return types to HxWx3 uint8 RGB frames."""
    if frame is None:
        return None

    frame = _extract_rgb_candidate(frame)

    if frame is None:
        return None

    if hasattr(frame, "detach"):
        frame = frame.detach().cpu().numpy()
    elif hasattr(frame, "cpu"):
        frame = frame.cpu().numpy()
    else:
        frame = np.asarray(frame)

    if frame.ndim == 4:
        frame = frame[0]

    if frame.ndim == 3 and frame.shape[0] in (3, 4):
        frame = np.moveaxis(frame, 0, -1)

    if frame.ndim == 2:
        frame = np.repeat(frame[:, :, None], 3, axis=2)

    if frame.ndim != 3 or frame.shape[2] < 3:
        return None

    frame = frame[:, :, :3]

    if np.issubdtype(frame.dtype, np.floating):
        max_value = float(np.nanmax(frame)) if frame.size else 1.0
        if max_value <= 1.0:
            frame = frame * 255.0

    frame = np.nan_to_num(frame, nan=0.0, posinf=255.0, neginf=0.0)
    return np.clip(frame, 0, 255).astype(np.uint8)


def _extract_rgb_candidate(value):
    if isinstance(value, dict):
        for key in ("rgb", "color", "image", "frame"):
            if key in value:
                return value[key]
        return None

    if isinstance(value, (tuple, list)):
        if not value:
            return None
        for item in value:
            candidate = _extract_rgb_candidate(item)
            if candidate is not None:
                return candidate
        return None

    return value


def draw_detection_overlay(
    frame,
    detection,
    reference_center=None,
    target_center=None,
):
    image = normalize_rgb_frame(frame)

    if image is None:
        return None

    annotated = image.copy()
    height, width = annotated.shape[:2]

    if reference_center is None:
        reference_center = (width / 2.0, height / 2.0)

    _draw_cross(
        annotated,
        int(reference_center[0]),
        int(reference_center[1]),
        color=(80, 180, 255),
        size=10,
    )

    if target_center is not None:
        _draw_cross(
            annotated,
            int(target_center[0]),
            int(target_center[1]),
            color=(255, 230, 0),
            size=8,
        )

    if detection.found and detection.bbox is not None:
        x0, y0, x1, y1 = detection.bbox
        _draw_rect(
            annotated,
            x0,
            y0,
            x1,
            y1,
            color=(0, 255, 0),
            thickness=2,
        )
        _draw_cross(
            annotated,
            int(detection.center_x),
            int(detection.center_y),
            color=(0, 255, 0),
            size=8,
        )
        _draw_line(
            annotated,
            int(reference_center[0]),
            int(reference_center[1]),
            int(detection.center_x),
            int(detection.center_y),
            color=(255, 255, 255),
        )
    else:
        _draw_rect(
            annotated,
            8,
            8,
            min(width - 1, 80),
            min(height - 1, 48),
            color=(255, 0, 0),
            thickness=2,
        )

    return annotated


def _draw_rect(image, x0, y0, x1, y1, color, thickness=1):
    height, width = image.shape[:2]
    x0 = max(0, min(width - 1, int(x0)))
    x1 = max(0, min(width - 1, int(x1)))
    y0 = max(0, min(height - 1, int(y0)))
    y1 = max(0, min(height - 1, int(y1)))

    for offset in range(thickness):
        yy0 = max(0, y0 - offset)
        yy1 = min(height - 1, y1 + offset)
        xx0 = max(0, x0 - offset)
        xx1 = min(width - 1, x1 + offset)
        image[yy0, xx0 : xx1 + 1] = color
        image[yy1, xx0 : xx1 + 1] = color
        image[yy0 : yy1 + 1, xx0] = color
        image[yy0 : yy1 + 1, xx1] = color


def _draw_cross(image, x, y, color, size=6):
    height, width = image.shape[:2]
    x0 = max(0, x - size)
    x1 = min(width - 1, x + size)
    y0 = max(0, y - size)
    y1 = min(height - 1, y + size)

    if 0 <= y < height:
        image[y, x0 : x1 + 1] = color
    if 0 <= x < width:
        image[y0 : y1 + 1, x] = color


def _draw_line(image, x0, y0, x1, y1, color):
    steps = max(abs(x1 - x0), abs(y1 - y0), 1)

    for i in range(steps + 1):
        t = i / steps
        x = int(round(x0 + (x1 - x0) * t))
        y = int(round(y0 + (y1 - y0) * t))
        if 0 <= y < image.shape[0] and 0 <= x < image.shape[1]:
            image[y, x] = color
