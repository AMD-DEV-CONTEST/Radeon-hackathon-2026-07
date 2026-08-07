"""Put every frame on a common canvas by moving pixels only.

No scaling, no rotation, no interpolation — alignment shifts content by whole
pixels and nothing else, so the set of colours in a frame is identical before
and after (BACKEND_CLI_PLAN.md 8.5).

The idea is one *registration point* per frame: whatever the mode, each frame
contributes a point that must end up at the same place on the output canvas.
Everything else is bookkeeping.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal, Mapping

import numpy as np

from .errors import UsageError
from .model import Frame, FrameSet, Point, Rect, RgbaImage, Size, WorkshopWarning

AlignMode = Literal["center", "canvas_center", "feet", "anchor", "custom"]
EmptyPolicy = Literal["error", "canvas_center", "fallback"]
Overflow = Literal["error", "clip"]

ALPHA_THRESHOLD = 1


@dataclass(frozen=True, slots=True)
class AlignmentSpec:
    mode: AlignMode = "center"
    canvas: Size | None = None  # None means "smallest canvas that fits everything"
    padding: int = 0
    offsets: Mapping[str, Point] = field(default_factory=dict)
    empty: EmptyPolicy = "error"
    fallback_anchor: Point | None = None
    overflow: Overflow = "error"

    def __post_init__(self) -> None:
        if self.mode not in ("center", "canvas_center", "feet", "anchor", "custom"):
            raise UsageError("unknown alignment mode", mode=self.mode)
        if self.padding < 0:
            raise UsageError("padding must not be negative", padding=self.padding)
        if self.mode == "custom" and not self.offsets:
            raise UsageError("custom mode needs an offset per frame")
        if self.empty == "fallback" and self.fallback_anchor is None:
            raise UsageError("empty=fallback needs a fallback anchor")
        if self.overflow not in ("error", "clip"):
            raise UsageError("unknown overflow policy", overflow=self.overflow)


@dataclass(frozen=True, slots=True)
class FramePlacement:
    id: str
    offset: Point
    content: Rect

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "offset": list(self.offset.as_tuple()),
            "content": list(self.content.as_tuple()),
        }


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    frames: FrameSet
    canvas: Size
    anchor: Point
    placements: tuple[FramePlacement, ...]
    warnings: tuple[WorkshopWarning, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """The dry-run report: target canvas and every per-frame offset."""

        return {
            "canvas": list(self.canvas.as_tuple()),
            "anchor": list(self.anchor.as_tuple()),
            "frames": [p.to_dict() for p in self.placements],
            "warnings": [w.to_dict() for w in self.warnings],
            "metrics": dict(self.metrics),
        }


def opaque_bounds(image: RgbaImage) -> Rect | None:
    """Bounding box of pixels with alpha above the threshold, or None."""

    mask = image.array[:, :, 3] >= ALPHA_THRESHOLD
    if not mask.any():
        return None
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    top, bottom = int(rows[0]), int(rows[-1])
    left, right = int(cols[0]), int(cols[-1])
    return Rect(left, top, right - left + 1, bottom - top + 1)


def _registration_point(
    frame: Frame, spec: AlignmentSpec, warnings: list[WorkshopWarning]
) -> Point:
    """The point in frame-local coordinates that must line up across frames."""

    if spec.mode == "canvas_center":
        return Point(frame.image.width // 2, frame.image.height // 2)
    if spec.mode == "anchor":
        return frame.anchor

    bounds = opaque_bounds(frame.image)
    if bounds is None:
        # An empty frame has no bounding box, so there is nothing to derive a
        # registration point from.  Guessing here silently shifts a frame by an
        # arbitrary amount, so it has to be an explicit decision.
        if spec.empty == "error":
            raise UsageError(
                "frame is fully transparent and has no reference point; "
                "pass empty=canvas_center or empty=fallback",
                frame=frame.id,
                mode=spec.mode,
            )
        warnings.append(
            WorkshopWarning(
                code="align.empty_frame",
                message=f"frame {frame.id} is empty; used the {spec.empty} reference",
                details={"frame": frame.id},
            )
        )
        if spec.empty == "fallback":
            return spec.fallback_anchor  # type: ignore[return-value]
        return Point(frame.image.width // 2, frame.image.height // 2)

    if spec.mode == "center":
        return Point(bounds.x + bounds.width // 2, bounds.y + bounds.height // 2)
    if spec.mode == "feet":
        # Horizontal centre of the silhouette, vertical baseline at its lowest
        # opaque row.  Half-open, so the baseline is the row *below* the feet.
        return Point(bounds.x + bounds.width // 2, bounds.bottom)

    raise UsageError("unknown alignment mode", mode=spec.mode)


def align_frames(
    frames: FrameSet, spec: AlignmentSpec = AlignmentSpec()
) -> AlignmentResult:
    """Move every frame onto one shared canvas."""

    if len(frames) == 0:
        raise UsageError("frame set is empty", frame_set=frames.id)

    warnings: list[WorkshopWarning] = []

    if spec.mode == "custom":
        raw_offsets = []
        for frame in frames.frames:
            if frame.id not in spec.offsets:
                raise UsageError(
                    "custom mode needs an offset for every frame", frame=frame.id
                )
            raw_offsets.append(spec.offsets[frame.id])
    else:
        points = [_registration_point(frame, spec, warnings) for frame in frames.frames]
        raw_offsets = [Point(-p.x, -p.y) for p in points]

    # Shift the whole layout so nothing sits at a negative coordinate.
    min_x = min(o.x for o in raw_offsets)
    min_y = min(o.y for o in raw_offsets)
    max_x = max(o.x + f.image.width for o, f in zip(raw_offsets, frames.frames))
    max_y = max(o.y + f.image.height for o, f in zip(raw_offsets, frames.frames))

    pad = spec.padding
    auto = Size(max_x - min_x + pad * 2, max_y - min_y + pad * 2)
    shift = Point(-min_x + pad, -min_y + pad)

    canvas = spec.canvas or auto
    if spec.canvas is not None:
        # Keep relative alignment exact and centre the whole layout in the
        # requested canvas; only the common origin moves.
        shift = Point(
            shift.x + (canvas.width - auto.width) // 2,
            shift.y + (canvas.height - auto.height) // 2,
        )

    # Every registration point was mapped to the layout origin, so the shared
    # anchor is simply where that origin landed on the canvas.
    anchor = shift

    placements: list[FramePlacement] = []
    out_frames: list[Frame] = []

    for frame, raw in zip(frames.frames, raw_offsets):
        offset = Point(raw.x + shift.x, raw.y + shift.y)
        content = Rect(offset.x, offset.y, frame.image.width, frame.image.height)

        if spec.overflow == "error" and not Rect(
            0, 0, canvas.width, canvas.height
        ).contains_rect(content):
            raise UsageError(
                "frame does not fit the requested canvas; enlarge it or pass overflow=clip",
                frame=frame.id,
                content=list(content.as_tuple()),
                canvas=list(canvas.as_tuple()),
            )

        out_frames.append(
            replace(
                frame,
                image=_paste(frame.image, offset, canvas),
                source_size=canvas,
                trim_rect=_clip(content, canvas),
                trim_offset=offset,
                anchor=anchor,
            )
        )
        placements.append(FramePlacement(id=frame.id, offset=offset, content=content))

    clipped = [p.id for p in placements if _clip(p.content, canvas) != p.content]
    if clipped:
        warnings.append(
            WorkshopWarning(
                code="align.clipped",
                message=f"{len(clipped)} frame(s) were clipped by the canvas",
                details={"frames": clipped},
            )
        )

    return AlignmentResult(
        frames=FrameSet(id=frames.id, frames=tuple(out_frames), canvas_size=canvas),
        canvas=canvas,
        anchor=anchor,
        placements=tuple(placements),
        warnings=tuple(warnings),
        metrics={
            "mode": spec.mode,
            "frames": len(out_frames),
            "canvas": f"{canvas.width}x{canvas.height}",
            "auto_canvas": f"{auto.width}x{auto.height}",
        },
    )


def _paste(image: RgbaImage, offset: Point, canvas: Size) -> RgbaImage:
    out = np.zeros((canvas.height, canvas.width, 4), dtype=np.uint8)

    dst_x0 = max(offset.x, 0)
    dst_y0 = max(offset.y, 0)
    dst_x1 = min(offset.x + image.width, canvas.width)
    dst_y1 = min(offset.y + image.height, canvas.height)
    if dst_x1 <= dst_x0 or dst_y1 <= dst_y0:
        return RgbaImage(out)

    out[dst_y0:dst_y1, dst_x0:dst_x1] = image.array[
        dst_y0 - offset.y : dst_y1 - offset.y, dst_x0 - offset.x : dst_x1 - offset.x
    ]
    return RgbaImage(out)


def _clip(rect: Rect, canvas: Size) -> Rect:
    x = max(0, rect.x)
    y = max(0, rect.y)
    return Rect(
        x,
        y,
        max(0, min(rect.right, canvas.width) - x),
        max(0, min(rect.bottom, canvas.height) - y),
    )
