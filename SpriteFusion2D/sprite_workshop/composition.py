"""Stack several frame sets into one: body + clothes + weapon + effects.

Layers register on their anchors and composite with straight-alpha source-over.
No Photoshop blend modes in this version — if a real asset needs one, it gets
added with a golden fixture rather than guessed at (BACKEND_CLI_PLAN.md 8.6).

Input frame sets are never modified; every output frame records which source
frame each layer contributed, so a wrong match is visible instead of mysterious.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence

import numpy as np

from .errors import UsageError
from .model import Frame, FrameSet, Point, Rect, RgbaImage, Size, WorkshopWarning

MatchMode = Literal["by_index", "by_id", "by_tag", "broadcast"]
MissingPolicy = Literal["error", "skip_layer", "hold_last"]
CanvasRule = Literal["union", "fixed", "from_layer"]
Overflow = Literal["error", "clip"]


@dataclass(frozen=True, slots=True)
class LayerInput:
    name: str
    frames: FrameSet

    def __post_init__(self) -> None:
        if len(self.frames) == 0:
            raise UsageError("layer has no frames", layer=self.name)


@dataclass(frozen=True, slots=True)
class CompositionSpec:
    match: MatchMode = "by_index"
    match_keys: tuple[str, ...] = ()
    # A one-frame layer is almost always a static weapon or prop meant to ride
    # along the whole animation, so it broadcasts even under by_index/by_id.
    # It is a flag rather than a hidden rule because it does override the
    # requested match mode, and that should be visible.
    broadcast_single: bool = True
    missing: MissingPolicy = "error"
    canvas: CanvasRule = "union"
    canvas_size: Size | None = None
    canvas_layer: str | None = None
    overflow: Overflow = "error"
    padding: int = 0

    def __post_init__(self) -> None:
        if self.match not in ("by_index", "by_id", "by_tag", "broadcast"):
            raise UsageError("unknown match mode", match=self.match)
        if self.missing not in ("error", "skip_layer", "hold_last"):
            raise UsageError("unknown missing policy", missing=self.missing)
        if self.canvas == "fixed" and self.canvas_size is None:
            raise UsageError("canvas=fixed needs canvas_size")
        if self.canvas == "from_layer" and not self.canvas_layer:
            raise UsageError("canvas=from_layer needs canvas_layer")
        if self.padding < 0:
            raise UsageError("padding must not be negative", padding=self.padding)


@dataclass(frozen=True, slots=True)
class LayerMatch:
    layer: str
    frame_id: str | None
    held: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"layer": self.layer, "frame": self.frame_id, "held": self.held}


@dataclass(frozen=True, slots=True)
class CompositionResult:
    frames: FrameSet
    canvas: Size
    anchor: Point
    matches: tuple[tuple[LayerMatch, ...], ...]
    warnings: tuple[WorkshopWarning, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "canvas": list(self.canvas.as_tuple()),
            "anchor": list(self.anchor.as_tuple()),
            "frames": [
                {
                    "id": frame.id,
                    "layers": [m.to_dict() for m in matches],
                }
                for frame, matches in zip(self.frames.frames, self.matches)
            ],
            "warnings": [w.to_dict() for w in self.warnings],
            "metrics": dict(self.metrics),
        }


# ------------------------------------------------------------------- matching


def _match_for(
    base: Frame,
    index: int,
    layer: LayerInput,
    spec: CompositionSpec,
) -> Frame | None:
    if spec.match == "broadcast" or (spec.broadcast_single and len(layer.frames) == 1):
        return layer.frames.frames[0]

    if spec.match == "by_index":
        if index < len(layer.frames):
            return layer.frames.frames[index]
        return None

    if spec.match == "by_id":
        for frame in layer.frames.frames:
            if frame.id == base.id:
                return frame
        return None

    keys = spec.match_keys or tuple(sorted(base.tags))
    if not keys:
        raise UsageError(
            "by_tag needs tags on the base frames or an explicit key list",
            frame=base.id,
        )

    wanted = {key: base.tags.get(key) for key in keys}
    candidates = [
        frame
        for frame in layer.frames.frames
        if all(frame.tags.get(key) == value for key, value in wanted.items())
    ]
    if len(candidates) > 1:
        raise UsageError(
            "tag match is ambiguous; narrow it with explicit match keys",
            frame=base.id,
            layer=layer.name,
            matches=[c.id for c in candidates],
            keys=list(keys),
        )
    return candidates[0] if candidates else None


# ------------------------------------------------------------------ compositing


def composite_over(base: np.ndarray, top: np.ndarray) -> np.ndarray:
    """Straight-alpha source-over.

    Straight, not premultiplied: the whole pipeline stores straight RGBA, and
    converting back and forth would round twice.
    """

    src_a = top[:, :, 3].astype(np.float64) / 255.0
    dst_a = base[:, :, 3].astype(np.float64) / 255.0
    out_a = src_a + dst_a * (1.0 - src_a)

    src_rgb = top[:, :, :3].astype(np.float64)
    dst_rgb = base[:, :, :3].astype(np.float64)

    weighted = src_rgb * src_a[..., None] + dst_rgb * (dst_a * (1.0 - src_a))[..., None]
    with np.errstate(invalid="ignore", divide="ignore"):
        out_rgb = np.where(
            out_a[..., None] > 0, weighted / np.maximum(out_a[..., None], 1e-12), 0.0
        )

    out = np.empty_like(base)
    out[:, :, :3] = np.clip(np.rint(out_rgb), 0, 255).astype(np.uint8)
    out[:, :, 3] = np.clip(np.rint(out_a * 255.0), 0, 255).astype(np.uint8)
    # Keep the 5.1 persistence rule: no hidden colour under full transparency.
    out[out[:, :, 3] == 0] = 0
    return out


# ---------------------------------------------------------------- public API


def compose_layers(
    layers: Sequence[LayerInput],
    spec: CompositionSpec = CompositionSpec(),
    *,
    set_id: str = "composed",
) -> CompositionResult:
    """Composite layers in the given order; the first layer is the base."""

    if not layers:
        raise UsageError("composition needs at least one layer")

    names = [layer.name for layer in layers]
    if len(set(names)) != len(names):
        raise UsageError("layer names must be unique", layers=names)

    base_layer = layers[0]
    warnings: list[WorkshopWarning] = []

    # Resolve which source frame each layer contributes to each output frame.
    resolved: list[list[Frame | None]] = []
    matches: list[list[LayerMatch]] = []
    last_seen: dict[str, Frame] = {}

    for index, base in enumerate(base_layer.frames.frames):
        row: list[Frame | None] = []
        row_matches: list[LayerMatch] = []
        for layer in layers:
            frame = (
                base if layer is base_layer else _match_for(base, index, layer, spec)
            )
            held = False

            if frame is None:
                if spec.missing == "error":
                    raise UsageError(
                        "layer has no frame for this position; "
                        "choose missing=skip_layer or missing=hold_last",
                        layer=layer.name,
                        base_frame=base.id,
                        index=index,
                    )
                if spec.missing == "hold_last" and layer.name in last_seen:
                    frame = last_seen[layer.name]
                    held = True
                else:
                    warnings.append(
                        WorkshopWarning(
                            code="compose.layer_skipped",
                            message=f"layer {layer.name} contributed nothing to {base.id}",
                            details={"layer": layer.name, "frame": base.id},
                        )
                    )
            if frame is not None and not held:
                last_seen[layer.name] = frame

            row.append(frame)
            row_matches.append(
                LayerMatch(
                    layer=layer.name, frame_id=frame.id if frame else None, held=held
                )
            )
        resolved.append(row)
        matches.append(row_matches)

    canvas, anchor = _resolve_canvas(layers, resolved, spec)

    out_frames: list[Frame] = []
    for base, row in zip(base_layer.frames.frames, resolved):
        buffer = np.zeros((canvas.height, canvas.width, 4), dtype=np.uint8)
        for frame in row:
            if frame is None:
                continue
            placed = _place(frame, anchor, canvas, spec, base.id)
            buffer = composite_over(buffer, placed)

        image = RgbaImage(buffer)
        out_frames.append(
            Frame(
                id=base.id,
                image=image,
                source_size=canvas,
                trim_rect=Rect(0, 0, canvas.width, canvas.height),
                trim_offset=Point(0, 0),
                anchor=anchor,
                label=base.label,
                tags=dict(base.tags),
            )
        )

    return CompositionResult(
        frames=FrameSet(id=set_id, frames=tuple(out_frames), canvas_size=canvas),
        canvas=canvas,
        anchor=anchor,
        matches=tuple(tuple(row) for row in matches),
        warnings=tuple(warnings),
        metrics={
            "layers": len(layers),
            "frames": len(out_frames),
            "match": spec.match,
            "canvas": f"{canvas.width}x{canvas.height}",
        },
    )


def _resolve_canvas(
    layers: Sequence[LayerInput],
    resolved: Sequence[Sequence[Frame | None]],
    spec: CompositionSpec,
) -> tuple[Size, Point]:
    """Decide the output canvas and where the shared anchor sits on it.

    Without a fixed rule here, the same body with different clothes produces
    different canvas sizes and every downstream atlas goes wrong
    (BACKEND_CLI_PLAN.md 8.6).
    """

    if spec.canvas == "from_layer":
        layer = next(
            (layer for layer in layers if layer.name == spec.canvas_layer), None
        )
        if layer is None:
            raise UsageError(
                "canvas_layer is not one of the layers", layer=spec.canvas_layer
            )
        reference = layer.frames.frames[0]
        return reference.image.size, reference.anchor

    # Anchor-relative extents across every frame of every layer that is used.
    min_x = min_y = 0
    max_x = max_y = 0
    seen = False
    for row in resolved:
        for frame in row:
            if frame is None:
                continue
            seen = True
            min_x = min(min_x, -frame.anchor.x)
            min_y = min(min_y, -frame.anchor.y)
            max_x = max(max_x, frame.image.width - frame.anchor.x)
            max_y = max(max_y, frame.image.height - frame.anchor.y)

    if not seen:
        raise UsageError("no layer contributed any frame")

    pad = spec.padding
    union = Size(max_x - min_x + pad * 2, max_y - min_y + pad * 2)
    anchor = Point(-min_x + pad, -min_y + pad)

    if spec.canvas == "fixed":
        fixed = spec.canvas_size
        assert fixed is not None
        anchor = Point(
            anchor.x + (fixed.width - union.width) // 2,
            anchor.y + (fixed.height - union.height) // 2,
        )
        return fixed, anchor

    return union, anchor


def _place(
    frame: Frame, anchor: Point, canvas: Size, spec: CompositionSpec, base_id: str
) -> np.ndarray:
    """Drop a layer frame onto the canvas so its anchor lands on ``anchor``."""

    offset = Point(anchor.x - frame.anchor.x, anchor.y - frame.anchor.y)
    content = Rect(offset.x, offset.y, frame.image.width, frame.image.height)

    if spec.overflow == "error" and not Rect(
        0, 0, canvas.width, canvas.height
    ).contains_rect(content):
        raise UsageError(
            "layer frame does not fit the canvas; enlarge it or pass overflow=clip",
            frame=frame.id,
            base_frame=base_id,
            content=list(content.as_tuple()),
            canvas=list(canvas.as_tuple()),
        )

    out = np.zeros((canvas.height, canvas.width, 4), dtype=np.uint8)
    dst_x0 = max(offset.x, 0)
    dst_y0 = max(offset.y, 0)
    dst_x1 = min(offset.x + frame.image.width, canvas.width)
    dst_y1 = min(offset.y + frame.image.height, canvas.height)
    if dst_x1 <= dst_x0 or dst_y1 <= dst_y0:
        return out

    out[dst_y0:dst_y1, dst_x0:dst_x1] = frame.image.array[
        dst_y0 - offset.y : dst_y1 - offset.y, dst_x0 - offset.x : dst_x1 - offset.x
    ]
    return out
