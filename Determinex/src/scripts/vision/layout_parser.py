"""Layout parsing — extract structural regions from screenshots."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

try:
    import numpy as np
    from PIL import Image

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


@dataclass
class LayoutRegion:
    label: str  # "header", "sidebar", "content", "footer", "modal", "button", "input", "text"
    x: int
    y: int
    w: int
    h: int
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
            "confidence": self.confidence,
        }


def parse_layout(img_or_path: str | Image.Image) -> list[LayoutRegion]:  # type: ignore[name-defined]
    """
    Heuristic layout parser using brightness/edge detection.
    Returns a list of candidate layout regions.

    For production use, replace with a trained layout model (e.g. DocTR, LayoutLM).
    """
    if not _AVAILABLE:
        return []
    try:
        if isinstance(img_or_path, str):
            img = Image.open(img_or_path).convert("RGB")
        else:
            img = img_or_path.convert("RGB")
        return _heuristic_layout(img)
    except Exception as exc:
        log.error("[layout_parser] parse_layout failed: %s", exc)
        return []


def _heuristic_layout(img: Image.Image) -> list[LayoutRegion]:
    w, h = img.size
    arr = np.array(img)
    regions: list[LayoutRegion] = []

    # Rough heuristic: top 10% = header, bottom 8% = footer
    if h > 200:
        regions.append(LayoutRegion("header", 0, 0, w, int(h * 0.10), confidence=0.6))
        regions.append(LayoutRegion("footer", 0, int(h * 0.92), w, int(h * 0.08), confidence=0.6))

    # Rough heuristic: left 20% if narrow column (sidebar)
    left_strip = arr[:, : int(w * 0.20), :]
    right_strip = arr[:, int(w * 0.80) :, :]
    if _is_uniform_color(left_strip):
        regions.append(LayoutRegion("sidebar", 0, 0, int(w * 0.20), h, confidence=0.5))
    if _is_uniform_color(right_strip):
        regions.append(
            LayoutRegion("sidebar_right", int(w * 0.80), 0, int(w * 0.20), h, confidence=0.5)
        )

    # Content area = remainder
    content_x = int(w * 0.20) if any(r.label == "sidebar" for r in regions) else 0
    content_w = (
        w - content_x - (int(w * 0.20) if any(r.label == "sidebar_right" for r in regions) else 0)
    )
    content_y = int(h * 0.10) if h > 200 else 0
    content_h = h - content_y - (int(h * 0.08) if h > 200 else 0)
    regions.append(
        LayoutRegion("content", content_x, content_y, content_w, content_h, confidence=0.4)
    )

    return regions


def _is_uniform_color(arr: np.ndarray, tolerance: int = 30) -> bool:
    std = arr.std(axis=(0, 1))
    return bool((std < tolerance).all())
