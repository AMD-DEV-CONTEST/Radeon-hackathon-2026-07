"""Cut one sheet into frames: fixed grid, connected components, or manual rects.

Every mode goes through the same naming and tagging contract, so a frame set
never comes out of here without usable ids and tags (BACKEND_CLI_PLAN.md 5.3,
8.4).

On provenance: ``Frame.source_size`` / ``trim_rect`` / ``trim_offset`` describe
the frame's *own* canvas, because that is what packing and export mean by those
fields.  Where the frame sat in the sheet is separate provenance and rides on
``SliceResult.source_rects`` — overloading the trim fields with two different
meanings is how sprites start jumping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence

import numpy as np

from ._labeling import label_mask
from .errors import UsageError
from .ids import DEFAULT_NAME_TEMPLATE, normalize_tags, render_names
from .model import Frame, FrameSet, Point, Rect, RgbaImage, Size, WorkshopWarning

SliceMode = Literal["grid", "components", "manual"]
ReadingOrder = Literal["row", "column"]
TailPolicy = Literal["error", "crop", "pad"]

ALPHA_THRESHOLD = 1


@dataclass(frozen=True, slots=True)
class GridSpec:
    """Either cell size or cell count, never both (BACKEND_CLI_PLAN.md 8.4)."""

    columns: int | None = None
    rows: int | None = None
    cell_width: int | None = None
    cell_height: int | None = None
    margin: tuple[int, int, int, int] = (0, 0, 0, 0)  # left, top, right, bottom
    gap: tuple[int, int] = (0, 0)  # x, y
    order: ReadingOrder = "row"
    keep_empty: bool = False
    tail: TailPolicy = "error"

    def __post_init__(self) -> None:
        by_count = self.columns is not None or self.rows is not None
        by_size = self.cell_width is not None or self.cell_height is not None
        if by_count and by_size:
            raise UsageError(
                "give either rows/columns or cell size, not both",
                columns=self.columns,
                rows=self.rows,
                cell_width=self.cell_width,
                cell_height=self.cell_height,
            )
        if not by_count and not by_size:
            raise UsageError("grid mode needs rows/columns or a cell size")
        for name, value in (
            ("columns", self.columns),
            ("rows", self.rows),
            ("cell_width", self.cell_width),
            ("cell_height", self.cell_height),
        ):
            if value is not None and value < 1:
                raise UsageError(f"{name} must be positive", **{name: value})
        if any(v < 0 for v in self.margin) or any(v < 0 for v in self.gap):
            raise UsageError("margin and gap must not be negative")
        if self.tail not in ("error", "crop", "pad"):
            raise UsageError("unknown tail policy", tail=self.tail)


@dataclass(frozen=True, slots=True)
class ComponentsSpec:
    min_area: int = 1
    merge_gap: int = 0
    padding: int = 0
    connectivity: int = 8
    order: ReadingOrder = "row"

    def __post_init__(self) -> None:
        if self.connectivity not in (4, 8):
            raise UsageError(
                "connectivity must be 4 or 8", connectivity=self.connectivity
            )
        for name, value in (
            ("min_area", self.min_area),
            ("merge_gap", self.merge_gap),
            ("padding", self.padding),
        ):
            if value < 0:
                raise UsageError(f"{name} must not be negative", **{name: value})


@dataclass(frozen=True, slots=True)
class NamedRect:
    name: str
    rect: Rect


@dataclass(frozen=True, slots=True)
class ManualSpec:
    rects: tuple[NamedRect, ...] = ()

    def __post_init__(self) -> None:
        if not self.rects:
            raise UsageError("manual mode needs at least one rectangle")


@dataclass(frozen=True, slots=True)
class SliceSpec:
    mode: SliceMode = "grid"
    grid: GridSpec | None = None
    components: ComponentsSpec | None = None
    manual: ManualSpec | None = None
    name_template: str = DEFAULT_NAME_TEMPLATE
    tag_rows: Mapping[int, Mapping[str, str]] = field(default_factory=dict)
    tag_cols: Mapping[int, Mapping[str, str]] = field(default_factory=dict)
    tags: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in ("grid", "components", "manual"):
            raise UsageError("unknown slice mode", mode=self.mode)
        if self.mode == "grid" and self.grid is None:
            raise UsageError("grid mode needs a GridSpec")
        if self.mode == "components" and self.components is None:
            raise UsageError("components mode needs a ComponentsSpec")
        if self.mode == "manual" and self.manual is None:
            raise UsageError("manual mode needs a ManualSpec")
        normalize_tags(self.tags)


@dataclass(frozen=True, slots=True)
class SliceResult:
    frames: FrameSet
    source_rects: tuple[Rect, ...]
    warnings: tuple[WorkshopWarning, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """The dry-run report: candidate boxes, order, ids and tags."""

        return {
            "frames": [
                {
                    "id": frame.id,
                    "index": index,
                    "rect": list(rect.as_tuple()),
                    "size": list(frame.size.as_tuple()),
                    "tags": dict(frame.tags),
                }
                for index, (frame, rect) in enumerate(
                    zip(self.frames.frames, self.source_rects)
                )
            ],
            "count": len(self.frames),
            "warnings": [w.to_dict() for w in self.warnings],
            "metrics": dict(self.metrics),
        }


# ------------------------------------------------------------------ grid mode


def _grid_rects(
    image: RgbaImage, spec: GridSpec, warnings: list[WorkshopWarning]
) -> tuple[list[Rect], list[tuple[int, int]]]:
    left, top, right, bottom = spec.margin
    gap_x, gap_y = spec.gap

    content_w = image.width - left - right
    content_h = image.height - top - bottom
    if content_w <= 0 or content_h <= 0:
        raise UsageError(
            "margins leave no content",
            width=image.width,
            height=image.height,
            margin=spec.margin,
        )

    if spec.columns is not None or spec.rows is not None:
        columns = spec.columns or 1
        rows = spec.rows or 1
        cell_w = _cell_from_count(content_w, columns, gap_x, spec, "width", warnings)
        cell_h = _cell_from_count(content_h, rows, gap_y, spec, "height", warnings)
    else:
        cell_w = spec.cell_width or content_w
        cell_h = spec.cell_height or content_h
        columns = (content_w + gap_x) // (cell_w + gap_x)
        rows = (content_h + gap_y) // (cell_h + gap_y)
        if columns < 1 or rows < 1:
            raise UsageError(
                "cell size is larger than the content area",
                cell=(cell_w, cell_h),
                content=(content_w, content_h),
            )
        used_w = columns * cell_w + (columns - 1) * gap_x
        used_h = rows * cell_h + (rows - 1) * gap_y
        _report_tail(content_w - used_w, content_h - used_h, spec, warnings)

    rects: list[Rect] = []
    coords: list[tuple[int, int]] = []
    for row in range(rows):
        for col in range(columns):
            rects.append(
                Rect(
                    left + col * (cell_w + gap_x),
                    top + row * (cell_h + gap_y),
                    cell_w,
                    cell_h,
                )
            )
            coords.append((row, col))

    if spec.order == "column":
        order = sorted(range(len(rects)), key=lambda i: (coords[i][1], coords[i][0]))
        rects = [rects[i] for i in order]
        coords = [coords[i] for i in order]

    return rects, coords


def _cell_from_count(
    content: int,
    count: int,
    gap: int,
    spec: GridSpec,
    axis: str,
    warnings: list[WorkshopWarning],
) -> int:
    """Resolve cell size from a cell count, applying the tail policy."""

    usable = content - (count - 1) * gap
    if usable < count:
        raise UsageError(
            f"not enough {axis} for {count} cells", content=content, gap=gap, axis=axis
        )

    cell = usable // count
    remainder = usable - cell * count
    if remainder == 0:
        return cell

    if spec.tail == "error":
        raise UsageError(
            f"sheet {axis} does not divide evenly; use --tail crop or --tail pad",
            content=content,
            cells=count,
            remainder=remainder,
        )
    if spec.tail == "crop":
        warnings.append(
            WorkshopWarning(
                code="slice.tail_cropped",
                message=f"dropped {remainder}px of {axis} that did not fit the grid",
                details={"axis": axis, "remainder": remainder},
            )
        )
        return cell

    # pad: grow every cell by one and let the last one run past the edge, which
    # the extractor fills with transparency.
    warnings.append(
        WorkshopWarning(
            code="slice.tail_padded",
            message=f"padded cells to cover {remainder}px of leftover {axis}",
            details={"axis": axis, "remainder": remainder},
        )
    )
    return cell + 1


def _report_tail(
    remainder_w: int, remainder_h: int, spec: GridSpec, warnings: list[WorkshopWarning]
) -> None:
    if remainder_w == 0 and remainder_h == 0:
        return
    if spec.tail == "error":
        raise UsageError(
            "sheet does not divide evenly into cells; use --tail crop or --tail pad",
            remainder=(remainder_w, remainder_h),
        )
    warnings.append(
        WorkshopWarning(
            code="slice.tail_cropped",
            message=f"ignored {remainder_w}x{remainder_h}px outside the grid",
            details={"remainder": [remainder_w, remainder_h]},
        )
    )


# ------------------------------------------------------------ components mode


def _component_rects(
    image: RgbaImage, spec: ComponentsSpec, warnings: list[WorkshopWarning]
) -> list[Rect]:
    mask = image.array[:, :, 3] >= ALPHA_THRESHOLD
    if not mask.any():
        return []

    labelled = label_mask(mask, connectivity=spec.connectivity)
    boxes = [c.bounds for c in labelled.components if c.area >= spec.min_area]
    dropped = labelled.count - len(boxes)
    if dropped:
        warnings.append(
            WorkshopWarning(
                code="slice.specks_dropped",
                message=f"dropped {dropped} component(s) under min_area",
                details={"min_area": spec.min_area},
            )
        )

    if spec.merge_gap > 0:
        boxes = _merge_close(boxes, spec.merge_gap)

    if spec.padding:
        boxes = [
            _clip(
                Rect(
                    b.x - spec.padding,
                    b.y - spec.padding,
                    b.width + spec.padding * 2,
                    b.height + spec.padding * 2,
                ),
                image.width,
                image.height,
            )
            for b in boxes
        ]

    return _reading_order(boxes, spec.order)


def _merge_close(boxes: Sequence[Rect], gap: int) -> list[Rect]:
    """Union boxes whose expanded bounds touch, until nothing changes.

    Discrete effects and detached weapon parts get split into pieces by plain
    connectivity; this is the knob that puts them back together
    (BACKEND_CLI_PLAN.md 8.4).
    """

    current = list(boxes)
    changed = True
    while changed:
        changed = False
        merged: list[Rect] = []
        for box in current:
            for index, other in enumerate(merged):
                if _within(box, other, gap):
                    merged[index] = _union(box, other)
                    changed = True
                    break
            else:
                merged.append(box)
        current = merged
    return current


def _within(a: Rect, b: Rect, gap: int) -> bool:
    """True when the two boxes are within ``gap`` pixels of each other.

    Used for merging, where touching counts as close.  Do not reuse this for
    overlap: with ``gap=0`` two merely adjacent boxes still come back True.
    """

    return not (
        a.x - gap > b.right
        or b.x - gap > a.right
        or a.y - gap > b.bottom
        or b.y - gap > a.bottom
    )


def _overlaps(a: Rect, b: Rect) -> bool:
    """True only when the boxes share at least one pixel.

    Half-open on all sides, so edge-to-edge neighbours do not overlap in either
    direction.
    """

    return not (a.right <= b.x or b.right <= a.x or a.bottom <= b.y or b.bottom <= a.y)


def _union(a: Rect, b: Rect) -> Rect:
    x = min(a.x, b.x)
    y = min(a.y, b.y)
    return Rect(x, y, max(a.right, b.right) - x, max(a.bottom, b.bottom) - y)


def _clip(rect: Rect, width: int, height: int) -> Rect:
    x = max(0, rect.x)
    y = max(0, rect.y)
    return Rect(x, y, min(rect.right, width) - x, min(rect.bottom, height) - y)


def _reading_order(boxes: Sequence[Rect], order: ReadingOrder) -> list[Rect]:
    """Group into bands first, then read across — plain top-left sorting
    interleaves frames whose tops differ by a pixel."""

    if not boxes:
        return []

    if order == "column":
        bands = _bands(boxes, key=lambda r: (r.x, r.right))
        return [b for band in bands for b in sorted(band, key=lambda r: (r.y, r.x))]

    bands = _bands(boxes, key=lambda r: (r.y, r.bottom))
    return [b for band in bands for b in sorted(band, key=lambda r: (r.x, r.y))]


def _bands(boxes: Sequence[Rect], key) -> list[list[Rect]]:
    ordered = sorted(boxes, key=key)
    bands: list[list[Rect]] = []
    limit = None
    for box in ordered:
        start, end = key(box)
        if limit is None or start >= limit:
            bands.append([box])
            limit = end
        else:
            bands[-1].append(box)
            limit = max(limit, end)
    return bands


# ---------------------------------------------------------------- manual mode


def _manual_rects(
    image: RgbaImage, spec: ManualSpec, warnings: list[WorkshopWarning]
) -> tuple[list[Rect], list[str]]:
    bounds = Rect(0, 0, image.width, image.height)
    rects: list[Rect] = []
    names: list[str] = []

    for entry in spec.rects:
        if not bounds.contains_rect(entry.rect):
            raise UsageError(
                "rectangle is outside the image",
                name=entry.name,
                rect=list(entry.rect.as_tuple()),
                image=[image.width, image.height],
            )
        rects.append(entry.rect)
        names.append(entry.name)

    for i, a in enumerate(rects):
        for b in rects[i + 1 :]:
            if _overlaps(a, b):
                warnings.append(
                    WorkshopWarning(
                        code="slice.overlap",
                        message="manual rectangles overlap",
                        details={"a": list(a.as_tuple()), "b": list(b.as_tuple())},
                    )
                )
                break

    return rects, names


# ---------------------------------------------------------------- public API


def slice_frames(
    image: RgbaImage, spec: SliceSpec, *, set_id: str = "frames"
) -> SliceResult:
    """Cut a sheet into a frame set."""

    warnings: list[WorkshopWarning] = []
    coords: list[tuple[int, int]] = []
    names: list[str] | None = None

    if spec.mode == "grid":
        rects, coords = _grid_rects(image, spec.grid, warnings)
    elif spec.mode == "components":
        rects = _component_rects(image, spec.components, warnings)
    else:
        rects, names = _manual_rects(image, spec.manual, warnings)

    if not rects:
        raise UsageError("slicing produced no frames", mode=spec.mode)

    keep: list[int] = []
    for index, rect in enumerate(rects):
        crop = _extract(image, rect)
        empty = not bool((crop[:, :, 3] >= ALPHA_THRESHOLD).any())
        if spec.mode == "grid" and empty and not spec.grid.keep_empty:
            continue
        keep.append(index)

    if not keep:
        raise UsageError("every candidate frame was empty", mode=spec.mode)

    skipped = len(rects) - len(keep)
    if skipped:
        warnings.append(
            WorkshopWarning(
                code="slice.empty_skipped",
                message=f"skipped {skipped} fully transparent cell(s)",
                details={"skipped": skipped},
            )
        )

    tag_list = [_tags_for(index, coords, spec) for index in keep]
    ids, id_warnings = render_names(
        spec.name_template,
        frame_set=set_id,
        count=len(keep),
        rows=[coords[i][0] for i in keep] if coords else None,
        cols=[coords[i][1] for i in keep] if coords else None,
        names=[names[i] for i in keep] if names else None,
        tags=tag_list,
    )
    for message in id_warnings:
        warnings.append(WorkshopWarning(code="slice.id_collision", message=message))

    frames: list[Frame] = []
    source_rects: list[Rect] = []
    for position, index in enumerate(keep):
        rect = rects[index]
        crop = _extract(image, rect)
        frame_image = RgbaImage(crop).normalized()
        frames.append(
            Frame(
                id=ids[position],
                image=frame_image,
                source_size=frame_image.size,
                trim_rect=Rect(0, 0, frame_image.width, frame_image.height),
                trim_offset=Point(0, 0),
                anchor=Point(frame_image.width // 2, frame_image.height),
                tags=tag_list[position],
            )
        )
        source_rects.append(rect)

    return SliceResult(
        frames=FrameSet(id=set_id, frames=tuple(frames)),
        source_rects=tuple(source_rects),
        warnings=tuple(warnings),
        metrics={
            "mode": spec.mode,
            "candidates": len(rects),
            "frames": len(frames),
            "sheet": f"{image.width}x{image.height}",
        },
    )


def _tags_for(
    index: int, coords: Sequence[tuple[int, int]], spec: SliceSpec
) -> dict[str, str]:
    tags = dict(spec.tags)
    if coords:
        row, col = coords[index]
        tags.update(spec.tag_rows.get(row, {}))
        tags.update(spec.tag_cols.get(col, {}))
    return normalize_tags(tags)


def _extract(image: RgbaImage, rect: Rect) -> np.ndarray:
    """Crop, padding with transparency where the rect runs past the edge."""

    out = np.zeros((rect.height, rect.width, 4), dtype=np.uint8)
    src_x0 = max(rect.x, 0)
    src_y0 = max(rect.y, 0)
    src_x1 = min(rect.right, image.width)
    src_y1 = min(rect.bottom, image.height)
    if src_x1 <= src_x0 or src_y1 <= src_y0:
        return out

    out[src_y0 - rect.y : src_y1 - rect.y, src_x0 - rect.x : src_x1 - rect.x] = (
        image.array[src_y0:src_y1, src_x0:src_x1]
    )
    return out


def reassemble(result: SliceResult, canvas: Size) -> RgbaImage:
    """Put sliced frames back where they came from.

    Only used by tests and by anyone verifying a slice, but it is the property
    that proves the provenance metadata is right (BACKEND_CLI_PLAN.md 11.4).
    """

    out = np.zeros((canvas.height, canvas.width, 4), dtype=np.uint8)
    for frame, rect in zip(result.frames.frames, result.source_rects):
        x1 = min(rect.right, canvas.width)
        y1 = min(rect.bottom, canvas.height)
        out[rect.y : y1, rect.x : x1] = frame.image.array[: y1 - rect.y, : x1 - rect.x]
    return RgbaImage(out)
