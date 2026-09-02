"""Screenshot loading and normalization for all visual agent environments."""

from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

try:
    from PIL import Image

    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False
    log.warning("[vision] Pillow not installed — screenshot operations will be limited")


def load_screenshot(path: str | Path) -> Image.Image | None:
    """Load a screenshot from disk. Returns PIL Image or None if unavailable."""
    if not _PIL_AVAILABLE:
        log.error("[vision] Pillow required for load_screenshot")
        return None
    try:
        return Image.open(path).convert("RGB")
    except Exception as exc:
        log.error("[vision] Failed to load screenshot %s: %s", path, exc)
        return None


def screenshot_to_bytes(img: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def screenshot_hash(path: str | Path) -> str:
    """SHA-256 of raw file bytes — stable across runs, format-preserving."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception as exc:
        log.error("[vision] screenshot_hash failed for %s: %s", path, exc)
        return ""


def resize_for_model(
    img: Image.Image,
    max_width: int = 1280,
    max_height: int = 960,
) -> Image.Image:
    """Downscale large screenshots before sending to vision models."""
    if not _PIL_AVAILABLE:
        return img
    w, h = img.size
    if w <= max_width and h <= max_height:
        return img
    ratio = min(max_width / w, max_height / h)
    new_size = (int(w * ratio), int(h * ratio))
    return img.resize(new_size, Image.LANCZOS)  # type: ignore[attr-defined]


def crop_region(img: Image.Image, x: int, y: int, w: int, h: int) -> Image.Image:
    return img.crop((x, y, x + w, y + h))


def metadata_from_file(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    stat = p.stat() if p.exists() else None
    return {
        "path": str(p),
        "exists": p.exists(),
        "size_bytes": stat.st_size if stat else 0,
        "hash": screenshot_hash(p) if p.exists() else "",
    }
