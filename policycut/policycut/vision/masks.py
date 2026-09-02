"""Mask post-processing and npz persistence.

Pure numpy + OpenCV, no torch. cv2 itself is optional: if it is missing,
numpy-only fallbacks keep dilation/feathering functional (hole filling and
small-component removal are then skipped).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np

try:  # cv2 is a light dependency but stay import-safe everywhere
    import cv2
except Exception:  # pragma: no cover - exercised on machines without OpenCV
    cv2 = None  # type: ignore

logger = logging.getLogger(__name__)

MIN_COMPONENT_FRACTION = 0.0005  # of frame area
MIN_COMPONENT_PX = 16


def _to_binary(mask: np.ndarray) -> np.ndarray:
    """Any mask (bool / uint8 alpha / float) -> uint8 {0, 1} 2-D array."""
    arr = np.asarray(mask)
    while arr.ndim > 2:
        arr = arr.squeeze(0) if arr.shape[0] == 1 else arr[..., 0]
    if arr.dtype == np.bool_:
        return arr.astype(np.uint8)
    if np.issubdtype(arr.dtype, np.floating):
        return (arr > 0.5).astype(np.uint8)
    return (arr > 127).astype(np.uint8) if arr.max(initial=0) > 1 else (arr > 0).astype(np.uint8)


def _fill_holes(binary: np.ndarray) -> np.ndarray:
    """Fill fully enclosed holes via flood fill from a padded border."""
    if cv2 is None:
        return binary
    h, w = binary.shape
    padded = np.zeros((h + 2, w + 2), np.uint8)
    padded[1:-1, 1:-1] = binary
    flood_mask = np.zeros((h + 4, w + 4), np.uint8)
    cv2.floodFill(padded, flood_mask, (0, 0), 1)
    holes = (padded[1:-1, 1:-1] == 0) & (binary == 0)
    out = binary.copy()
    out[holes] = 1
    return out


def _remove_small_components(binary: np.ndarray) -> np.ndarray:
    """Drop connected components smaller than a minimum area.

    If every component is tiny, the largest one is kept: for redaction it is
    safer to blur a speck than to silently drop the only region we have.
    """
    if cv2 is None or not binary.any():
        return binary
    h, w = binary.shape
    min_area = max(MIN_COMPONENT_PX, int(MIN_COMPONENT_FRACTION * h * w))
    num, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if num <= 1:
        return binary
    areas = stats[1:, cv2.CC_STAT_AREA]
    keep = [i + 1 for i, area in enumerate(areas) if area >= min_area]
    if not keep:
        keep = [1 + int(np.argmax(areas))]
    out = np.isin(labels, keep).astype(np.uint8)
    return out


def _dilate(binary: np.ndarray, dilate_px: int) -> np.ndarray:
    if dilate_px <= 0:
        return binary
    if cv2 is not None:
        size = 2 * dilate_px + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        return cv2.dilate(binary, kernel, iterations=1)
    # numpy fallback: iterative 3x3 max (approximates a square dilation)
    out = binary.astype(bool)
    for _ in range(dilate_px):
        shifted = out.copy()
        shifted[1:, :] |= out[:-1, :]
        shifted[:-1, :] |= out[1:, :]
        shifted[:, 1:] |= out[:, :-1]
        shifted[:, :-1] |= out[:, 1:]
        out = shifted
    return out.astype(np.uint8)


def _feather(alpha: np.ndarray, feather_px: int) -> np.ndarray:
    if feather_px <= 0:
        return alpha
    if cv2 is not None:
        ksize = 2 * feather_px + 1
        return cv2.GaussianBlur(alpha, (ksize, ksize), sigmaX=float(feather_px))
    # numpy fallback: three passes of box blur approximate a gaussian
    out = alpha.astype(np.float32)
    radius = max(1, feather_px)
    for _ in range(3):
        out = _box_blur(out, radius)
    return np.clip(out, 0, 255).astype(np.uint8)


def _box_blur(img: np.ndarray, radius: int) -> np.ndarray:
    """Separable box blur via cumulative sums (numpy only)."""
    size = 2 * radius + 1

    def blur_axis(a: np.ndarray, axis: int) -> np.ndarray:
        pad = [(0, 0), (0, 0)]
        pad[axis] = (radius, radius)
        padded = np.pad(a, pad, mode="edge")
        csum = np.cumsum(padded, axis=axis, dtype=np.float64)
        zeros_shape = list(csum.shape)
        zeros_shape[axis] = 1
        csum = np.concatenate([np.zeros(zeros_shape), csum], axis=axis)
        hi = np.take(csum, range(size, csum.shape[axis]), axis=axis)
        lo = np.take(csum, range(0, csum.shape[axis] - size), axis=axis)
        return ((hi - lo) / size).astype(np.float32)

    return blur_axis(blur_axis(img, 0), 1)


def postprocess_mask(mask: np.ndarray, dilate_px: int = 8, feather_px: int = 3) -> np.ndarray:
    """Turn a raw (bool/float/uint8) segmentation mask into a uint8 alpha.

    Steps: binarize -> morphological close + fill holes -> remove small
    components -> dilate by dilate_px -> gaussian feather by feather_px.
    Returns a uint8 array in 0..255 with the same H, W as the input.
    """
    binary = _to_binary(mask)
    if binary.size == 0 or not binary.any():
        return np.zeros(binary.shape, dtype=np.uint8)

    if cv2 is not None:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    binary = _fill_holes(binary)
    binary = _remove_small_components(binary)
    binary = _dilate(binary, int(dilate_px))
    alpha = (binary.astype(np.uint8)) * 255
    alpha = _feather(alpha, int(feather_px))
    return alpha.astype(np.uint8)


def union_with_box(alpha: np.ndarray, box_px: tuple, pad_px: int = 0) -> np.ndarray:
    """Union a uint8 alpha mask with a solid (padded) pixel-space box.

    box_px is (x, y, w, h) in pixels of the alpha's resolution. The padded
    box region is set fully opaque (255); everything else is unchanged.
    """
    out = np.asarray(alpha, dtype=np.uint8).copy()
    if out.ndim != 2:
        out = _to_binary(out) * 255
    h, w = out.shape
    x, y, bw, bh = box_px
    x0 = max(0, int(np.floor(float(x) - pad_px)))
    y0 = max(0, int(np.floor(float(y) - pad_px)))
    x1 = min(w, int(np.ceil(float(x) + float(bw) + pad_px)))
    y1 = min(h, int(np.ceil(float(y) + float(bh) + pad_px)))
    if x1 > x0 and y1 > y0:
        out[y0:y1, x0:x1] = 255
    return out


def _downsample_2x(alpha: np.ndarray) -> np.ndarray:
    h, w = alpha.shape[:2]
    if h <= 1 or w <= 1:
        return alpha.astype(np.uint8)
    new_size = (max(1, (w + 1) // 2), max(1, (h + 1) // 2))
    if cv2 is not None:
        return cv2.resize(alpha, new_size, interpolation=cv2.INTER_AREA).astype(np.uint8)
    return np.ascontiguousarray(alpha[::2, ::2]).astype(np.uint8)


def save_masks_npz(path, masks: dict) -> None:
    """Save {t_or_frame_idx: mask} as compressed npz, downsampled 2x.

    Per CONTRACTS.md §12, masks are stored `{t: mask}` at the input (proxy)
    resolution downsampled 2x. Keys are "f<key>" where <key> preserves the
    numeric value ("f123" for ints, "f0.5" for float timestamps). Masks may
    be bool or uint8 alpha; they are stored as uint8. The write is atomic
    (tmp file + os.replace).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, np.ndarray] = {}
    for frame_key, mask in masks.items():
        arr = np.asarray(mask)
        while arr.ndim > 2:
            arr = arr.squeeze(0) if arr.shape[0] == 1 else arr[..., 0]
        if arr.dtype == np.bool_:
            arr = arr.astype(np.uint8) * 255
        elif arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        key = float(frame_key)
        name = f"f{int(key)}" if key.is_integer() else f"f{key!r}"
        arrays[name] = _downsample_2x(arr)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "wb") as fh:
            np.savez_compressed(fh, **arrays)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    logger.debug("Saved %d masks to %s", len(arrays), path)


def load_masks_npz(path) -> dict:
    """Load masks saved by save_masks_npz -> {t_or_frame_idx: uint8 alpha}.

    Keys are ints when integral ("f123" -> 123) and floats otherwise
    ("f0.5" -> 0.5). Arrays are returned at the STORED resolution, i.e.
    downsampled 2x from what was passed to save_masks_npz — callers upscale
    to the target frame size when applying (see media/render.py).
    Missing or unreadable files return {} (tolerant reads per contract).
    """
    path = Path(path)
    if not path.is_file():
        return {}
    out: dict = {}
    try:
        with np.load(path) as data:
            for key in data.files:
                if not key.startswith("f"):
                    continue
                raw = key[1:]
                try:
                    frame_key = int(raw)
                except ValueError:
                    try:
                        frame_key = float(raw)
                    except ValueError:
                        continue
                out[frame_key] = np.asarray(data[key], dtype=np.uint8)
    except Exception as exc:
        logger.warning("Failed to load masks npz %s: %s", path, exc)
        return {}
    return out
