"""Safe image decoding and geometric preprocessing."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import cv2
import numpy as np
from numpy.typing import NDArray

from buildguard.vision.schemas import LetterboxTransform


@dataclass(frozen=True)
class DecodedImage:
    path: Path
    checksum: str
    bgr: NDArray[np.uint8]

    @property
    def width(self) -> int:
        return int(self.bgr.shape[1])

    @property
    def height(self) -> int:
        return int(self.bgr.shape[0])


def decode_image(path: Path) -> DecodedImage:
    source = path.resolve()
    try:
        content = source.read_bytes()
    except OSError as exc:
        raise ValueError(f"Cannot read image {source}: {exc}") from exc
    checksum = hashlib.sha256(content).hexdigest()
    encoded = np.frombuffer(content, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError(f"Image is damaged or unsupported: {source}")
    return DecodedImage(
        path=source,
        checksum=checksum,
        bgr=cast("NDArray[np.uint8]", image),
    )


def bgr_to_rgb(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    return cast("NDArray[np.uint8]", cv2.cvtColor(image, cv2.COLOR_BGR2RGB))


def rgb_to_bgr(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    return cast("NDArray[np.uint8]", cv2.cvtColor(image, cv2.COLOR_RGB2BGR))


def letterbox(
    image: NDArray[np.uint8],
    target_size: tuple[int, int],
    color: tuple[int, int, int] = (114, 114, 114),
) -> tuple[NDArray[np.uint8], LetterboxTransform]:
    target_width, target_height = target_size
    if target_width <= 0 or target_height <= 0:
        raise ValueError("Letterbox target dimensions must be positive")
    height, width = image.shape[:2]
    scale = min(target_width / width, target_height / height)
    resized_width = max(1, round(width * scale))
    resized_height = max(1, round(height * scale))
    resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
    pad_width = target_width - resized_width
    pad_height = target_height - resized_height
    left = pad_width // 2
    right = pad_width - left
    top = pad_height // 2
    bottom = pad_height - top
    output = cv2.copyMakeBorder(
        resized,
        top,
        bottom,
        left,
        right,
        cv2.BORDER_CONSTANT,
        value=color,
    )
    return cast("NDArray[np.uint8]", output), LetterboxTransform(
        original_width=width,
        original_height=height,
        target_width=target_width,
        target_height=target_height,
        scale=scale,
        pad_x=float(left),
        pad_y=float(top),
    )
