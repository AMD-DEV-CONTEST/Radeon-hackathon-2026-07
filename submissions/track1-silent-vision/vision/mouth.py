from dataclasses import dataclass

import numpy as np
from PIL import Image

from backend.schemas import MouthBox


@dataclass(frozen=True)
class MouthCropResult:
    image: np.ndarray
    box: MouthBox


def crop_mouth(image_rgb: np.ndarray, landmarks: list[tuple[float, float]], mouth_size: int) -> MouthCropResult:
    if not landmarks:
        raise ValueError("mouth landmarks are required")
    height, width = image_rgb.shape[:2]
    xs = [x for x, _ in landmarks]
    ys = [y for _, y in landmarks]
    min_x = max(0.0, min(xs))
    max_x = min(1.0, max(xs))
    min_y = max(0.0, min(ys))
    max_y = min(1.0, max(ys))
    box_width = max_x - min_x
    box_height = max_y - min_y
    if box_width <= 0 or box_height <= 0:
        raise ValueError("invalid mouth box")

    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2 + box_height * 0.12
    crop_width = box_width * 2.05
    crop_height = max(box_height * 2.25, crop_width * 0.72)
    min_x = max(0.0, center_x - crop_width / 2)
    max_x = min(1.0, center_x + crop_width / 2)
    min_y = max(0.0, center_y - crop_height / 2)
    max_y = min(1.0, center_y + crop_height / 2)
    if max_x <= min_x or max_y <= min_y:
        raise ValueError("invalid mouth box")
    left = round(min_x * width)
    right = round(max_x * width)
    top = round(min_y * height)
    bottom = round(max_y * height)
    crop = image_rgb[top:bottom, left:right]
    if crop.size == 0:
        raise ValueError("empty mouth crop")
    resized = Image.fromarray(crop).convert("L").resize((mouth_size, mouth_size), Image.Resampling.BOX)
    return MouthCropResult(
        image=np.asarray(resized, dtype=np.uint8),
        box=MouthBox(x=min_x, y=min_y, width=max_x - min_x, height=max_y - min_y),
    )
