"""One-grid-pixel sprite outlines with deterministic colour selection."""

from __future__ import annotations

import colorsys
import time
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

import numpy as np

from .errors import UsageError
from .model import FrameSet, RgbaImage, WorkshopWarning


@dataclass(frozen=True, slots=True)
class OutlineSpec:
    position: str = "outer"
    thickness: int = 1
    connectivity: int = 8
    skip_diagonal: bool = True
    color_mode: str = "fixed"
    color: tuple[int, int, int] = (0, 0, 0)
    darken: int = 40
    hue_shift: int = -12
    inner_shadow: bool = False

    def __post_init__(self) -> None:
        if self.position not in {"outer", "inner", "center"}:
            raise UsageError("invalid outline position", position=self.position)
        if not 1 <= self.thickness <= 4:
            raise UsageError("outline thickness must be 1..4", thickness=self.thickness)
        if self.connectivity not in {4, 8}:
            raise UsageError("outline connectivity must be 4 or 8")
        if self.color_mode not in {"fixed", "darken-neighbor", "hue-shift"}:
            raise UsageError("invalid outline color mode", color_mode=self.color_mode)


@dataclass(frozen=True, slots=True)
class OutlineResult:
    frames: FrameSet
    warnings: tuple[WorkshopWarning, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)


def _shift(mask: np.ndarray, dy: int, dx: int) -> np.ndarray:
    out = np.zeros_like(mask)
    ys = slice(max(0, dy), min(mask.shape[0], mask.shape[0] + dy))
    xs = slice(max(0, dx), min(mask.shape[1], mask.shape[1] + dx))
    src_y = slice(max(0, -dy), min(mask.shape[0], mask.shape[0] - dy))
    src_x = slice(max(0, -dx), min(mask.shape[1], mask.shape[1] - dx))
    out[ys, xs] = mask[src_y, src_x]
    return out


def _neighbors(connectivity: int, skip_diagonal: bool) -> tuple[tuple[int, int], ...]:
    cardinal = ((-1, 0), (1, 0), (0, -1), (0, 1))
    if connectivity == 4 or skip_diagonal:
        return cardinal
    return cardinal + ((-1, -1), (-1, 1), (1, -1), (1, 1))


def _dilate(
    mask: np.ndarray, radius: int, offsets: tuple[tuple[int, int], ...]
) -> np.ndarray:
    result = mask.copy()
    for _ in range(radius):
        result = np.logical_or.reduce(
            (result, *(_shift(result, dy, dx) for dy, dx in offsets))
        )
    return result


def _erode(
    mask: np.ndarray, radius: int, offsets: tuple[tuple[int, int], ...]
) -> np.ndarray:
    result = mask.copy()
    for _ in range(radius):
        result = np.logical_and.reduce(
            (result, *(_shift(result, dy, dx) for dy, dx in offsets))
        )
    return result


def _neighbor_rgb(
    rgba: np.ndarray, target: np.ndarray, opaque: np.ndarray
) -> np.ndarray:
    rgb_sum = np.zeros((*opaque.shape, 3), dtype=np.float32)
    count = np.zeros(opaque.shape, dtype=np.float32)
    for dy, dx in _neighbors(8, False):
        source_mask = _shift(opaque, dy, dx)
        shifted_rgb = np.stack(
            [_shift(rgba[:, :, channel], dy, dx) for channel in range(3)], axis=2
        )
        rgb_sum += shifted_rgb * source_mask[:, :, None]
        count += source_mask
    count = np.maximum(count, 1.0)
    out = rgb_sum / count[:, :, None]
    out[~target] = 0
    return out


def _colorize(
    rgba: np.ndarray, mask: np.ndarray, opaque: np.ndarray, spec: OutlineSpec
) -> np.ndarray:
    if spec.color_mode == "fixed":
        return np.broadcast_to(
            np.asarray(spec.color, dtype=np.uint8), (*mask.shape, 3)
        ).copy()
    base = _neighbor_rgb(rgba, mask, opaque)
    if spec.color_mode == "darken-neighbor":
        return np.clip(base * (1.0 - spec.darken / 100.0), 0, 255).astype(np.uint8)
    output = np.zeros_like(base, dtype=np.uint8)
    for y, x in zip(*np.nonzero(mask)):
        r, g, b = base[y, x] / 255.0
        h, s, v = colorsys.rgb_to_hsv(float(r), float(g), float(b))
        output[y, x] = (
            np.asarray(
                colorsys.hsv_to_rgb((h + spec.hue_shift / 360.0) % 1.0, s, v * 0.65)
            )
            * 255
        )
    return output


def apply_outline(frames: FrameSet, spec: OutlineSpec = OutlineSpec()) -> OutlineResult:
    started = time.perf_counter()
    offsets = _neighbors(spec.connectivity, spec.skip_diagonal)
    output_frames = []
    warnings: list[WorkshopWarning] = []
    total_outline = 0
    total_pixels = 0

    if spec.thickness > 2:
        warnings.append(
            WorkshopWarning("outline.thick", "描边超过 2 格，可能淹没小尺寸细节")
        )

    for frame in frames.frames:
        rgba = frame.image.copy_writable()
        opaque = rgba[:, :, 3] > 0
        outer_radius = (
            spec.thickness
            if spec.position == "outer"
            else (spec.thickness + 1) // 2
            if spec.position == "center"
            else 0
        )
        inner_radius = (
            spec.thickness
            if spec.position == "inner"
            else spec.thickness // 2
            if spec.position == "center"
            else 0
        )
        outer = (
            _dilate(opaque, outer_radius, offsets) & ~opaque
            if outer_radius
            else np.zeros_like(opaque)
        )
        inner = (
            opaque & ~_erode(opaque, inner_radius, offsets)
            if inner_radius
            else np.zeros_like(opaque)
        )
        mask = outer | inner
        colors = _colorize(rgba, mask, opaque, spec)
        rgba[mask, :3] = colors[mask]
        rgba[outer, 3] = 255
        if spec.inner_shadow:
            shadow = opaque & ~_erode(opaque, 1, offsets)
            rgba[shadow, :3] = np.clip(
                rgba[shadow, :3].astype(np.float32) * 0.6, 0, 255
            ).astype(np.uint8)
            mask |= shadow
        if outer_radius and (
            opaque[0].any()
            or opaque[-1].any()
            or opaque[:, 0].any()
            or opaque[:, -1].any()
        ):
            warnings.append(
                WorkshopWarning(
                    "outline.clipped", "画布边缘的外描边被裁切", {"frame": frame.id}
                )
            )
        total_outline += int(mask.sum())
        total_pixels += int(mask.size)
        output_frames.append(replace(frame, image=RgbaImage(rgba)))

    elapsed = (time.perf_counter() - started) * 1000.0
    return OutlineResult(
        replace(frames, frames=tuple(output_frames)),
        tuple(warnings),
        {
            "outline_pixels": total_outline,
            "total_pixels": total_pixels,
            "elapsed_ms": elapsed,
        },
    )
