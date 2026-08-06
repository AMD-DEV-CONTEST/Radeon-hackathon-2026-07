"""Deterministic background removal and mask editing.

No model, no network.  The default path is colour distance plus border
connectivity, which is what keeps a character's interior from being punched out
when it happens to share the background colour (BACKEND_CLI_PLAN.md 8.2).

Masks are ordinary RGBA frame sets, not a special type, so every edit, export
and undo already works on them.  Convention: **mask alpha is the shape you
keep** — 255 where the pixel survives, 0 where it is erased.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Mapping, Sequence

import numpy as np

from ._labeling import border_connected, label_mask
from .errors import BackendUnavailableError, UsageError
from .model import Frame, FrameSet, RgbaImage, WorkshopWarning

BackgroundMode = Literal["exact", "rgb", "lab", "rembg"]
SampleSource = Literal["corners", "border", "colors"]
AlphaMode = Literal["hard", "soft"]
DespillMode = Literal["none", "nearest"]

MODES: tuple[BackgroundMode, ...] = ("exact", "rgb", "lab", "rembg")

# Classic low-cost weighting for sRGB distance: green dominates perceived
# difference, blue matters least.  Cheap and good enough for flat backgrounds.
_RGB_WEIGHTS = np.array([2.0, 4.0, 3.0], dtype=np.float64) / 9.0


@dataclass(frozen=True, slots=True)
class BackgroundSpec:
    mode: BackgroundMode = "lab"
    samples: SampleSource = "corners"
    colors: tuple[tuple[int, int, int], ...] = ()
    points: tuple[tuple[int, int], ...] = ()
    tolerance: float = 10.0
    connectivity: int = 8
    border_only: bool = True
    min_island_area: int = 0
    max_hole_area: int = 0
    alpha: AlphaMode = "hard"
    soft_range: float = 4.0
    despill: DespillMode = "none"
    shared_background: bool = True
    mask_only: bool = False

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise UsageError("mode must be one of " + ", ".join(MODES), mode=self.mode)
        if self.samples not in ("corners", "border", "colors"):
            raise UsageError("unknown sample source", samples=self.samples)
        if self.samples == "colors" and not self.colors and not self.points:
            raise UsageError("samples=colors needs --color or --at")
        if self.tolerance < 0:
            raise UsageError("tolerance must not be negative", tolerance=self.tolerance)
        if self.connectivity not in (4, 8):
            raise UsageError(
                "connectivity must be 4 or 8", connectivity=self.connectivity
            )
        if self.alpha not in ("hard", "soft"):
            raise UsageError("alpha must be hard or soft", alpha=self.alpha)
        if self.despill == "palette":  # type: ignore[comparison-overlap]
            # Named in the plan but the palette module is later work; refuse
            # rather than ship an option that silently does nothing.
            raise UsageError(
                "despill=palette needs the palette module (BACKEND_CLI_PLAN.md 8.4c)",
                available=["none", "nearest"],
            )
        if self.despill not in ("none", "nearest"):
            raise UsageError("unknown despill mode", despill=self.despill)
        if self.despill != "none" and self.alpha == "hard":
            # Despill only has partially transparent pixels to work on.  With
            # hard alpha there are none, so accepting the flag would mean
            # silently doing nothing.
            raise UsageError(
                "despill needs soft alpha; there are no partial pixels to fix under hard alpha",
                despill=self.despill,
                alpha=self.alpha,
            )
        if self.min_island_area < 0 or self.max_hole_area < 0:
            raise UsageError("areas must not be negative")


@dataclass(frozen=True, slots=True)
class ColorCandidate:
    color: tuple[int, int, int]
    border_coverage: float
    pixels: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "color": "#%02X%02X%02X" % self.color,
            "rgb": list(self.color),
            "border_coverage": round(self.border_coverage, 4),
            "pixels": self.pixels,
        }


@dataclass(frozen=True, slots=True)
class BackgroundAnalysis:
    candidates: tuple[ColorCandidate, ...]
    chosen: ColorCandidate | None
    corner_colors: tuple[tuple[int, int, int], ...]
    erased_pixels: int
    total_pixels: int
    elapsed_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "chosen": self.chosen.to_dict() if self.chosen else None,
            "corner_colors": ["#%02X%02X%02X" % c for c in self.corner_colors],
            "erased_pixels": self.erased_pixels,
            "total_pixels": self.total_pixels,
            "erased_ratio": round(self.erased_pixels / max(self.total_pixels, 1), 4),
            "elapsed_ms": round(self.elapsed_ms, 2),
        }


@dataclass(frozen=True, slots=True)
class BackgroundResult:
    frames: FrameSet
    masks: FrameSet
    analysis: BackgroundAnalysis
    warnings: tuple[WorkshopWarning, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------- colour maths


def _to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB uint8 -> CIE Lab (D65).  Done inline to avoid a scikit-image dep."""

    srgb = rgb.astype(np.float64) / 255.0
    linear = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)

    matrix = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ]
    )
    xyz = linear @ matrix.T
    white = np.array([0.95047, 1.0, 1.08883])
    scaled = xyz / white

    epsilon = 216.0 / 24389.0
    kappa = 24389.0 / 27.0
    f = np.where(scaled > epsilon, np.cbrt(scaled), (kappa * scaled + 16.0) / 116.0)

    lab = np.empty_like(f)
    lab[..., 0] = 116.0 * f[..., 1] - 16.0
    lab[..., 1] = 500.0 * (f[..., 0] - f[..., 1])
    lab[..., 2] = 200.0 * (f[..., 1] - f[..., 2])
    return lab


def color_distance(
    pixels: np.ndarray, reference: np.ndarray, mode: BackgroundMode
) -> np.ndarray:
    """Distance from every pixel to one reference colour, in the mode's units.

    ``exact`` returns 0 or a large number, ``rgb`` returns weighted sRGB units,
    ``lab`` returns CIE76 delta-E.  Tolerance is always read in these units, so
    a slider in the UI means something concrete.
    """

    if mode == "exact":
        return np.where((pixels == reference).all(axis=-1), 0.0, 1e9)

    if mode == "rgb":
        delta = pixels.astype(np.float64) - reference.astype(np.float64)
        return np.sqrt((delta**2 * _RGB_WEIGHTS).sum(axis=-1))

    if mode == "lab":
        lab_pixels = _to_lab(pixels)
        lab_reference = _to_lab(reference.reshape(1, 3)).reshape(3)
        return np.sqrt(((lab_pixels - lab_reference) ** 2).sum(axis=-1))

    raise BackendUnavailableError(
        "the rembg backend is not installed",
        hint="pip install rembg onnxruntime",
        mode=mode,
    )


# ------------------------------------------------------------------- sampling


def _border_pixels(rgb: np.ndarray) -> np.ndarray:
    return np.concatenate([rgb[0, :], rgb[-1, :], rgb[:, 0], rgb[:, -1]], axis=0)


def _corner_colors(rgb: np.ndarray) -> tuple[tuple[int, int, int], ...]:
    height, width = rgb.shape[:2]
    corners = [
        rgb[0, 0],
        rgb[0, width - 1],
        rgb[height - 1, 0],
        rgb[height - 1, width - 1],
    ]
    return tuple(tuple(int(v) for v in c) for c in corners)


def _cluster_candidates(
    samples: np.ndarray, spec: BackgroundSpec
) -> list[ColorCandidate]:
    """Group sampled colours and rank them by how much border they cover.

    Ties resolve by packed RGB so the choice never depends on dict ordering
    (BACKEND_CLI_PLAN.md 5.2).
    """

    unique, counts = np.unique(samples.reshape(-1, 3), axis=0, return_counts=True)
    order = np.lexsort((unique[:, 2], unique[:, 1], unique[:, 0], -counts))
    unique, counts = unique[order], counts[order]

    total = int(counts.sum())
    clusters: list[tuple[np.ndarray, int]] = []
    for color, count in zip(unique, counts.tolist()):
        for index, (centre, weight) in enumerate(clusters):
            if (
                color_distance(color.reshape(1, 3), centre, spec.mode)[0]
                <= spec.tolerance
            ):
                clusters[index] = (centre, weight + count)
                break
        else:
            clusters.append((color, count))

    candidates = [
        ColorCandidate(
            color=tuple(int(v) for v in centre),
            border_coverage=weight / max(total, 1),
            pixels=int(weight),
        )
        for centre, weight in clusters
    ]
    candidates.sort(key=lambda c: (-c.pixels, c.color))
    return candidates


def _reference_colors(
    images: Sequence[RgbaImage], spec: BackgroundSpec
) -> tuple[list[ColorCandidate], np.ndarray]:
    if spec.samples == "colors":
        explicit: list[tuple[int, int, int]] = list(spec.colors)
        for x, y in spec.points:
            image = images[0].array
            if not (0 <= x < image.shape[1] and 0 <= y < image.shape[0]):
                raise UsageError("sample point is outside the image", x=x, y=y)
            explicit.append(tuple(int(v) for v in image[y, x, :3]))
        candidates = [
            ColorCandidate(color=color, border_coverage=1.0, pixels=0)
            for color in explicit
        ]
        return candidates, np.array(explicit, dtype=np.uint8)

    collected = [
        np.array(_corner_colors(img.array[:, :, :3]), dtype=np.uint8)
        if spec.samples == "corners"
        else _border_pixels(img.array[:, :, :3])
        for img in images
    ]
    samples = np.concatenate(collected, axis=0)
    candidates = _cluster_candidates(samples, spec)
    chosen = (
        np.array([candidates[0].color], dtype=np.uint8)
        if candidates
        else np.zeros((0, 3), np.uint8)
    )
    return candidates, chosen


# ------------------------------------------------------------------ mask work


def _candidate_mask(
    rgb: np.ndarray, references: np.ndarray, spec: BackgroundSpec
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(is_background, nearest_distance)``."""

    if references.size == 0:
        return np.zeros(rgb.shape[:2], dtype=bool), np.full(rgb.shape[:2], 1e9)

    distances = np.stack(
        [color_distance(rgb, reference, spec.mode) for reference in references], axis=0
    )
    nearest = distances.min(axis=0)
    return nearest <= spec.tolerance, nearest


def _clean_mask(background: np.ndarray, spec: BackgroundSpec) -> np.ndarray:
    """Border connectivity, island removal, hole filling — in that order."""

    if spec.border_only:
        background = border_connected(background, connectivity=spec.connectivity)

    if spec.min_island_area > 0 and background.any():
        # Small background specks are more likely noise than real background.
        labelled = label_mask(background, connectivity=spec.connectivity)
        drop = [c.label for c in labelled.components if c.area < spec.min_island_area]
        if drop:
            background = background & ~np.isin(labelled.labels, drop)

    if spec.max_hole_area > 0:
        foreground = ~background
        labelled = label_mask(foreground, connectivity=spec.connectivity)
        height, width = background.shape
        for component in labelled.components:
            if component.area > spec.max_hole_area:
                continue
            bounds = component.bounds
            touches_border = (
                bounds.x == 0
                or bounds.y == 0
                or bounds.right >= width
                or bounds.bottom >= height
            )
            # Only fill genuinely enclosed holes; a speck on the edge is not one.
            if not touches_border:
                background = background | (labelled.labels == component.label)

    return background


def _alpha_from_mask(
    background: np.ndarray, distances: np.ndarray, spec: BackgroundSpec
) -> np.ndarray:
    if spec.alpha == "hard":
        return np.where(background, 0, 255).astype(np.uint8)

    # Soft alpha lives in a band *outside* the hard threshold: at or under the
    # tolerance the pixel is fully erased, and it fades back to opaque over the
    # next ``soft_range`` distance units.  The band is border-filtered the same
    # way the hard mask is, so a soft edge cannot leak into the character.
    # Opt-in only; hard alpha stays the default for pixel art (plan 14.1).
    span = max(spec.soft_range, 1e-6)
    widened = distances <= spec.tolerance + span
    if spec.border_only:
        widened = border_connected(widened, connectivity=spec.connectivity)
    widened = widened | background

    ramp = np.clip((distances - spec.tolerance) / span, 0.0, 1.0) * 255.0
    alpha = np.where(background, 0.0, np.where(widened, ramp, 255.0))
    return np.clip(alpha, 0, 255).astype(np.uint8)


def _despill_nearest(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Push partially transparent pixels toward their nearest opaque neighbour."""

    opaque = alpha == 255
    partial = (alpha > 0) & ~opaque
    if not partial.any() or not opaque.any():
        return rgb

    out = rgb.copy()
    height, width = alpha.shape
    ys, xs = np.nonzero(partial)
    for y, x in zip(ys.tolist(), xs.tolist()):
        y0, y1 = max(y - 1, 0), min(y + 2, height)
        x0, x1 = max(x - 1, 0), min(x + 2, width)
        window = opaque[y0:y1, x0:x1]
        if not window.any():
            continue
        neighbours = rgb[y0:y1, x0:x1][window]
        out[y, x] = neighbours.mean(axis=0).round().astype(np.uint8)
    return out


# ---------------------------------------------------------------- public API


def analyze_background(
    frames: FrameSet, spec: BackgroundSpec = BackgroundSpec()
) -> BackgroundAnalysis:
    """Report what removal *would* do, without touching the project."""

    started = time.perf_counter()
    images = [frame.image for frame in frames.frames]
    if not images:
        raise UsageError("frame set is empty", frame_set=frames.id)

    candidates, references = _reference_colors(images, spec)

    erased = 0
    total = 0
    for image in images:
        rgb = image.array[:, :, :3]
        background, _distances = _candidate_mask(rgb, references, spec)
        background = _clean_mask(background, spec)
        erased += int(background.sum())
        total += rgb.shape[0] * rgb.shape[1]

    return BackgroundAnalysis(
        candidates=tuple(candidates[:8]),
        chosen=candidates[0] if candidates else None,
        corner_colors=_corner_colors(images[0].array[:, :, :3]),
        erased_pixels=erased,
        total_pixels=total,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
    )


def remove_background(
    frames: FrameSet, spec: BackgroundSpec = BackgroundSpec()
) -> BackgroundResult:
    """Make the background transparent and return both frames and masks."""

    started = time.perf_counter()
    images = [frame.image for frame in frames.frames]
    if not images:
        raise UsageError("frame set is empty", frame_set=frames.id)

    warnings: list[WorkshopWarning] = []

    if spec.shared_background or spec.samples == "colors":
        candidates, references = _reference_colors(images, spec)
        per_frame_refs = [references] * len(images)
    else:
        # Sampling each frame independently is what makes an animation flicker,
        # so it is opt-out rather than the default.
        candidates = []
        per_frame_refs = []
        for image in images:
            frame_candidates, reference = _reference_colors([image], spec)
            candidates = candidates or frame_candidates
            per_frame_refs.append(reference)
        warnings.append(
            WorkshopWarning(
                code="background.per_frame_samples",
                message="sampling per frame can drift across an animation; "
                "use shared_background unless the frames really differ",
            )
        )

    new_frames: list[Frame] = []
    mask_frames: list[Frame] = []
    erased = 0
    total = 0

    for frame, references in zip(frames.frames, per_frame_refs):
        rgba = frame.image.array
        rgb = rgba[:, :, :3]

        background, distances = _candidate_mask(rgb, references, spec)
        background = _clean_mask(background, spec)

        alpha = _alpha_from_mask(background, distances, spec)
        # Respect alpha the source already had; removal only ever adds transparency.
        alpha = np.minimum(alpha, rgba[:, :, 3])

        out_rgb = _despill_nearest(rgb, alpha) if spec.despill == "nearest" else rgb

        composed = np.dstack([out_rgb, alpha])
        cleaned = RgbaImage(composed).normalized()

        mask_rgba = np.empty_like(composed)
        mask_rgba[:, :, :3] = 255
        mask_rgba[:, :, 3] = alpha
        mask_image = RgbaImage(mask_rgba).normalized()

        new_frames.append(replace(frame, image=cleaned))
        mask_frames.append(replace(frame, id=f"{frame.id}_mask", image=mask_image))

        erased += int((alpha == 0).sum())
        total += alpha.size

    analysis = BackgroundAnalysis(
        candidates=tuple(candidates[:8]),
        chosen=candidates[0] if candidates else None,
        corner_colors=_corner_colors(images[0].array[:, :, :3]),
        erased_pixels=erased,
        total_pixels=total,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
    )

    return BackgroundResult(
        frames=FrameSet(
            id=frames.id, frames=tuple(new_frames), canvas_size=frames.canvas_size
        ),
        masks=FrameSet(id=f"{frames.id}_mask", frames=tuple(mask_frames)),
        analysis=analysis,
        warnings=tuple(warnings),
        metrics={
            "frames": len(new_frames),
            "transparent_pixels": erased,
            "mode": spec.mode,
            "tolerance": spec.tolerance,
            "elapsed_ms": round(analysis.elapsed_ms, 2),
        },
    )


def apply_mask(frames: FrameSet, masks: FrameSet, *, invert: bool = False) -> FrameSet:
    """Apply a mask frame set to a frame set, pairing frames by position.

    The mask is an ordinary frame set, so a user can export it, fix it in any
    editor, import it back, and apply it here (BACKEND_CLI_PLAN.md 8.2).
    """

    if len(masks) not in (1, len(frames)):
        raise UsageError(
            "mask must have one frame or the same count as the target",
            frames=len(frames),
            masks=len(masks),
        )

    out: list[Frame] = []
    for index, frame in enumerate(frames.frames):
        mask_frame = masks.frames[0] if len(masks) == 1 else masks.frames[index]
        if mask_frame.image.size != frame.image.size:
            raise UsageError(
                "mask size does not match the frame",
                frame=frame.id,
                frame_size=frame.image.size.as_tuple(),
                mask_size=mask_frame.image.size.as_tuple(),
            )

        mask_alpha = mask_frame.image.array[:, :, 3]
        if invert:
            mask_alpha = 255 - mask_alpha

        rgba = frame.image.array.copy()
        rgba[:, :, 3] = np.minimum(rgba[:, :, 3], mask_alpha)
        out.append(replace(frame, image=RgbaImage(rgba).normalized()))

    return FrameSet(id=frames.id, frames=tuple(out), canvas_size=frames.canvas_size)
