"""Atomic local mask persistence and optional overlays."""

from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from buildguard.schemas.common import BoundingBox


def save_mask(
    mask: NDArray[np.bool_],
    output_dir: Path,
    *,
    image_checksum: str,
    prompt_box: BoundingBox,
    index: int,
) -> Path:
    root = output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    material = (
        f"{image_checksum}|{prompt_box.x1:.4f}|{prompt_box.y1:.4f}|"
        f"{prompt_box.x2:.4f}|{prompt_box.y2:.4f}|{index}"
    )
    name = f"mask-{hashlib.sha256(material.encode()).hexdigest()[:24]}.png"
    target = (root / name).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("Generated mask path escaped its configured output directory") from exc
    encoded_mask = np.asarray(mask, dtype=np.uint8) * 255
    ok, encoded = cv2.imencode(".png", encoded_mask)
    if not ok:
        raise ValueError("Could not encode segmentation mask")
    temporary = target.with_suffix(".tmp.png")
    temporary.write_bytes(encoded.tobytes())
    temporary.replace(target)
    return target


def overlay_mask(
    image: NDArray[np.uint8],
    mask: NDArray[np.bool_],
    *,
    color: tuple[int, int, int] = (0, 180, 255),
    alpha: float = 0.4,
) -> NDArray[np.uint8]:
    if image.shape[:2] != mask.shape:
        raise ValueError("Overlay mask shape must match the image")
    if alpha < 0 or alpha > 1:
        raise ValueError("Overlay alpha must be within 0..1")
    canvas = image.copy()
    tint = np.empty_like(canvas)
    tint[:] = color
    blended = cv2.addWeighted(canvas, 1 - alpha, tint, alpha, 0)
    canvas[mask] = blended[mask]
    return canvas
