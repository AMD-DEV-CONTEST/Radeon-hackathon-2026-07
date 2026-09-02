"""
Visual diff between two screenshots.
Supports: pixel diff, region diff, text diff via OCR, layout bounding-box diff,
and thresholded similarity scoring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

try:
    import numpy as np
    from PIL import Image, ImageChops

    _FULL_AVAILABLE = True
except ImportError:
    _FULL_AVAILABLE = False
    log.warning("[visual_diff] Pillow/numpy not installed — diff will be limited")


@dataclass
class DiffRegion:
    x: int
    y: int
    w: int
    h: int
    diff_score: float  # 0.0 = identical, 1.0 = completely different

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h, "diff_score": self.diff_score}


@dataclass
class VisualDiffResult:
    pixel_diff_score: float  # 0.0–1.0 (fraction of changed pixels)
    similar: bool
    threshold: float
    diff_regions: list[DiffRegion] = field(default_factory=list)
    text_added: list[str] = field(default_factory=list)
    text_removed: list[str] = field(default_factory=list)
    layout_changed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "pixel_diff_score": self.pixel_diff_score,
            "similar": self.similar,
            "threshold": self.threshold,
            "diff_regions": [r.to_dict() for r in self.diff_regions],
            "text_added": self.text_added,
            "text_removed": self.text_removed,
            "layout_changed": self.layout_changed,
            "metadata": self.metadata,
        }


def pixel_diff(img_a: Image.Image, img_b: Image.Image) -> float:
    """Return fraction of pixels that differ between two same-size images."""
    if not _FULL_AVAILABLE:
        return 1.0
    if img_a.size != img_b.size:
        img_b = img_b.resize(img_a.size, Image.LANCZOS)  # type: ignore[attr-defined]
    diff = ImageChops.difference(img_a.convert("RGB"), img_b.convert("RGB"))
    arr = np.array(diff)
    changed = np.any(arr > 5, axis=2)  # 5/255 tolerance for JPEG artifacts
    return float(changed.mean())


def region_diff(
    img_a: Image.Image,
    img_b: Image.Image,
    block_size: int = 32,
) -> list[DiffRegion]:
    """Divide image into blocks and score each block's pixel diff."""
    if not _FULL_AVAILABLE:
        return []
    if img_a.size != img_b.size:
        img_b = img_b.resize(img_a.size, Image.LANCZOS)  # type: ignore[attr-defined]
    w, h = img_a.size
    regions = []
    for y in range(0, h, block_size):
        for x in range(0, w, block_size):
            bw = min(block_size, w - x)
            bh = min(block_size, h - y)
            crop_a = img_a.crop((x, y, x + bw, y + bh))
            crop_b = img_b.crop((x, y, x + bw, y + bh))
            score = pixel_diff(crop_a, crop_b)
            if score > 0.02:  # skip near-identical blocks
                regions.append(DiffRegion(x=x, y=y, w=bw, h=bh, diff_score=round(score, 4)))
    return regions


def text_diff(img_a: Image.Image, img_b: Image.Image) -> tuple[list[str], list[str]]:
    """Return (text_added, text_removed) between two screenshots via OCR."""
    from vision.ocr_scanner import extract_words

    words_a = set(extract_words(img_a))
    words_b = set(extract_words(img_b))
    added = sorted(words_b - words_a)
    removed = sorted(words_a - words_b)
    return added, removed


def compare(
    path_a: str,
    path_b: str,
    threshold: float = 0.05,
    include_text_diff: bool = True,
    include_region_diff: bool = True,
) -> VisualDiffResult:
    """
    Full comparison pipeline between two screenshot paths.
    Returns VisualDiffResult with pixel score, regions, and text changes.
    """
    if not _FULL_AVAILABLE:
        return VisualDiffResult(pixel_diff_score=1.0, similar=False, threshold=threshold)

    img_a = Image.open(path_a).convert("RGB")
    img_b = Image.open(path_b).convert("RGB")

    score = pixel_diff(img_a, img_b)
    regions = region_diff(img_a, img_b) if include_region_diff else []
    text_added, text_removed = text_diff(img_a, img_b) if include_text_diff else ([], [])
    layout_changed = img_a.size != img_b.size

    return VisualDiffResult(
        pixel_diff_score=round(score, 6),
        similar=score <= threshold,
        threshold=threshold,
        diff_regions=regions,
        text_added=text_added,
        text_removed=text_removed,
        layout_changed=layout_changed,
    )
