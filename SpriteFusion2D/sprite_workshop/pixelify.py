"""Deterministic illustration-to-pixel-art conversion."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

import numpy as np

from .errors import UsageError
from .model import FrameSet, Point, Rect, RgbaImage, Size, WorkshopWarning
from .palettes import PALETTES, get_palette


@dataclass(frozen=True, slots=True)
class PixelifySpec:
    target_width: int = 64
    palette: str = "auto"
    colors: int = 16
    dither: str = "none"
    sharpen: int = 0
    seed: int = 42

    def __post_init__(self) -> None:
        if not 8 <= self.target_width <= 512:
            raise UsageError(
                "target width must be 8..512", target_width=self.target_width
            )
        if self.palette != "auto" and self.palette not in PALETTES:
            raise UsageError("unknown palette", palette=self.palette)
        if not 2 <= self.colors <= 256:
            raise UsageError("colors must be 2..256", colors=self.colors)
        if self.dither not in {"none", "bayer4", "floyd-steinberg"}:
            raise UsageError("unknown dither mode", dither=self.dither)
        if not 0 <= self.sharpen <= 100:
            raise UsageError("sharpen must be 0..100")


@dataclass(frozen=True, slots=True)
class PixelifyResult:
    frames: FrameSet
    warnings: tuple[WorkshopWarning, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)


def _area_weights(source: int, target: int) -> np.ndarray:
    scale = source / target
    weights = np.zeros((target, source), dtype=np.float32)
    for out in range(target):
        left, right = out * scale, (out + 1) * scale
        first, last = int(np.floor(left)), int(np.ceil(right))
        for src in range(first, min(last, source)):
            weights[out, src] = max(0.0, min(right, src + 1) - max(left, src)) / scale
    return weights


def _resize_area_linear(rgba: np.ndarray, width: int, height: int) -> np.ndarray:
    wy = _area_weights(rgba.shape[0], height)
    wx = _area_weights(rgba.shape[1], width)
    rgb = rgba[:, :, :3].astype(np.float32) / 255.0
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    alpha = rgba[:, :, 3].astype(np.float32) / 255.0
    premul = linear * alpha[:, :, None]
    out_a = np.einsum("yh,hw,xw->yx", wy, alpha, wx, optimize=True)
    out_p = np.einsum("yh,hwc,xw->yxc", wy, premul, wx, optimize=True)
    safe = np.maximum(out_a[:, :, None], 1e-6)
    out_l = out_p / safe
    srgb = np.where(
        out_l <= 0.0031308,
        out_l * 12.92,
        1.055 * np.maximum(out_l, 0) ** (1 / 2.4) - 0.055,
    )
    result = np.zeros((height, width, 4), dtype=np.uint8)
    result[:, :, :3] = np.clip(np.rint(srgb * 255), 0, 255).astype(np.uint8)
    result[:, :, 3] = np.where(out_a >= 0.5, 255, 0).astype(np.uint8)
    result[result[:, :, 3] == 0, :3] = 0
    return result


def _learn_palette(rgb: np.ndarray, count: int, seed: int) -> np.ndarray:
    pixels, weights = np.unique(rgb.reshape(-1, 3), axis=0, return_counts=True)
    if len(pixels) <= count:
        return pixels.astype(np.uint8)
    rng = np.random.default_rng(seed)
    centers = [pixels[int(np.argmax(weights))].astype(np.float32)]
    for _ in range(1, count):
        dist = np.min(
            ((pixels[:, None].astype(np.float32) - np.asarray(centers)[None]) ** 2).sum(
                axis=2
            ),
            axis=1,
        )
        probability = dist * weights
        if probability.sum() == 0:
            break
        centers.append(
            pixels[rng.choice(len(pixels), p=probability / probability.sum())].astype(
                np.float32
            )
        )
    centers_a = np.asarray(centers)
    for _ in range(16):
        labels = np.argmin(
            ((pixels[:, None].astype(np.float32) - centers_a[None]) ** 2).sum(axis=2),
            axis=1,
        )
        updated = centers_a.copy()
        for index in range(len(centers_a)):
            chosen = labels == index
            if chosen.any():
                updated[index] = np.average(
                    pixels[chosen], axis=0, weights=weights[chosen]
                )
        if np.allclose(updated, centers_a):
            break
        centers_a = updated
    return np.clip(np.rint(centers_a), 0, 255).astype(np.uint8)


def _nearest(rgb: np.ndarray, palette: np.ndarray) -> np.ndarray:
    flat = rgb.reshape(-1, 3).astype(np.float32)
    labels = np.argmin(
        ((flat[:, None] - palette[None].astype(np.float32)) ** 2).sum(axis=2), axis=1
    )
    return palette[labels].reshape(rgb.shape)


def _quantize(rgb: np.ndarray, palette: np.ndarray, mode: str) -> np.ndarray:
    if mode == "none":
        return _nearest(rgb, palette)
    work = rgb.astype(np.float32).copy()
    if mode == "bayer4":
        matrix = np.asarray(
            ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5)),
            dtype=np.float32,
        )
        threshold = (
            np.tile(
                matrix, (int(np.ceil(rgb.shape[0] / 4)), int(np.ceil(rgb.shape[1] / 4)))
            )[: rgb.shape[0], : rgb.shape[1]]
            - 7.5
        ) / 16.0
        work += threshold[:, :, None] * 24.0
        return _nearest(np.clip(work, 0, 255).astype(np.uint8), palette)
    output = np.zeros_like(rgb)
    for y in range(rgb.shape[0]):
        for x in range(rgb.shape[1]):
            old = np.clip(work[y, x], 0, 255)
            new = _nearest(old.reshape(1, 1, 3).astype(np.uint8), palette)[0, 0]
            output[y, x] = new
            error = old - new
            for dy, dx, weight in (
                (0, 1, 7 / 16),
                (1, -1, 3 / 16),
                (1, 0, 5 / 16),
                (1, 1, 1 / 16),
            ):
                yy, xx = y + dy, x + dx
                if yy < rgb.shape[0] and 0 <= xx < rgb.shape[1]:
                    work[yy, xx] += error * weight
    return output


def _unsharp(rgb: np.ndarray, amount: int) -> np.ndarray:
    if amount <= 0:
        return rgb
    work = rgb.astype(np.float32)
    padded = np.pad(work, ((1, 1), (1, 1), (0, 0)), mode="edge")
    blur = (
        padded[1:-1, 1:-1] * 4
        + padded[:-2, 1:-1]
        + padded[2:, 1:-1]
        + padded[1:-1, :-2]
        + padded[1:-1, 2:]
    ) / 8.0
    return np.clip(np.rint(work + (amount / 100.0) * (work - blur)), 0, 255).astype(
        np.uint8
    )


def pixelify_frames(
    frames: FrameSet, spec: PixelifySpec = PixelifySpec()
) -> PixelifyResult:
    started = time.perf_counter()
    outputs = []
    warnings: list[WorkshopWarning] = []
    colors_used: set[tuple[int, int, int]] = set()
    if spec.dither == "floyd-steinberg":
        warnings.append(
            WorkshopWarning(
                "pixelify.diffusion", "误差扩散会打散色块，可能影响后续描边"
            )
        )
    for frame in frames.frames:
        height = max(
            1, round(frame.image.height * spec.target_width / frame.image.width)
        )
        rgba = _resize_area_linear(frame.image.array, spec.target_width, height)
        rgba[:, :, :3] = _unsharp(rgba[:, :, :3], spec.sharpen)
        visible = rgba[:, :, 3] > 0
        palette = (
            get_palette(spec.palette)
            if spec.palette != "auto"
            else _learn_palette(
                rgba[visible, :3] if visible.any() else np.zeros((1, 3), np.uint8),
                spec.colors,
                spec.seed,
            )
        )
        rgba[:, :, :3] = _quantize(rgba[:, :, :3], palette, spec.dither)
        rgba[~visible, :3] = 0
        colors_used.update(
            map(tuple, np.unique(rgba[visible, :3], axis=0))
        ) if visible.any() else None
        size = Size(spec.target_width, height)
        outputs.append(
            replace(
                frame,
                image=RgbaImage(rgba),
                source_size=size,
                trim_rect=Rect(0, 0, size.width, size.height),
                trim_offset=Point(0, 0),
                anchor=Point(size.width // 2, size.height - 1),
            )
        )
    result_set = replace(
        frames,
        frames=tuple(outputs),
        canvas_size=outputs[0].image.size if outputs else None,
    )
    first = frames.frames[0]
    out_first = outputs[0]
    return PixelifyResult(
        result_set,
        tuple(warnings),
        {
            "source_width": first.image.width,
            "source_height": first.image.height,
            "out_width": out_first.image.width,
            "out_height": out_first.image.height,
            "colors_used": len(colors_used),
            "elapsed_ms": (time.perf_counter() - started) * 1000.0,
        },
    )
