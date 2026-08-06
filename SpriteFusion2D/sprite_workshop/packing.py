"""Arrange frames into atlas pages.

Four layouts: three fixed ones that are pure arithmetic, and ``compact`` which
is a skyline bottom-left packer.

Deviation from BACKEND_CLI_PLAN.md 8.7, flagged deliberately: the plan called
for the optional ``rectpack`` dependency behind a ``CompactPacker`` wrapper.
A skyline packer is about eighty lines, so taking the dependency would mean
shipping the most common engine-atlas case as *optional* and leaving users with
a backend-unavailable error by default.  The wrapper boundary the plan wanted is
still here: ``pack_frames`` is the only public entry point, and the layout
functions behind it can be swapped without touching callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping, Sequence

import numpy as np

from .alignment import opaque_bounds
from .errors import UsageError
from .model import FrameSet, Point, Rect, RgbaImage, Size, WorkshopWarning

Layout = Literal["horizontal", "vertical", "grid", "compact"]

MAX_PAGE_EDGE = 8192


@dataclass(frozen=True, slots=True)
class PackSpec:
    layout: Layout = "compact"
    columns: int | None = None
    rows: int | None = None
    padding: int = 0
    margin: int = 0
    extrude: int = 0
    trim: bool = False
    max_size: Size = Size(2048, 2048)
    multi_page: bool = False
    dedupe: bool = False

    def __post_init__(self) -> None:
        if self.layout not in ("horizontal", "vertical", "grid", "compact"):
            raise UsageError("unknown layout", layout=self.layout)
        if self.layout == "grid" and self.columns is None and self.rows is None:
            raise UsageError("grid layout needs columns or rows")
        if self.columns is not None and self.rows is not None:
            raise UsageError("give columns or rows for a grid, not both")
        for name, value in (
            ("padding", self.padding),
            ("margin", self.margin),
            ("extrude", self.extrude),
        ):
            if value < 0:
                raise UsageError(f"{name} must not be negative", **{name: value})
        if self.max_size.width > MAX_PAGE_EDGE or self.max_size.height > MAX_PAGE_EDGE:
            raise UsageError("page size exceeds the safety limit", limit=MAX_PAGE_EDGE)


@dataclass(frozen=True, slots=True)
class PackedFrame:
    id: str
    page: int
    rect: Rect
    source_size: Size
    trim_offset: Point
    anchor: Point
    tags: Mapping[str, str] = field(default_factory=dict)
    rotated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "page": self.page,
            "rect": list(self.rect.as_tuple()),
            "rotated": self.rotated,
            "source_size": list(self.source_size.as_tuple()),
            "trim_offset": list(self.trim_offset.as_tuple()),
            "anchor": list(self.anchor.as_tuple()),
            "tags": dict(self.tags),
        }


@dataclass(frozen=True, slots=True)
class AtlasPage:
    index: int
    image: RgbaImage

    @property
    def size(self) -> Size:
        return self.image.size


@dataclass(frozen=True, slots=True)
class AtlasBundle:
    pages: tuple[AtlasPage, ...]
    frames: tuple[PackedFrame, ...]
    warnings: tuple[WorkshopWarning, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "pages": [
                {
                    "file": f"page_{p.index}.png",
                    "width": p.size.width,
                    "height": p.size.height,
                }
                for p in self.pages
            ],
            "frames": [f.to_dict() for f in self.frames],
        }


# ------------------------------------------------------------------ preparation


@dataclass(frozen=True, slots=True)
class _Piece:
    """One frame reduced to what packing cares about."""

    id: str
    pixels: np.ndarray  # the region actually written to the atlas
    source_size: Size
    trim_offset: Point

    @property
    def width(self) -> int:
        return int(self.pixels.shape[1])

    @property
    def height(self) -> int:
        return int(self.pixels.shape[0])


def _prepare(frames: FrameSet, spec: PackSpec) -> list[_Piece]:
    pieces: list[_Piece] = []
    for frame in frames.frames:
        box = Rect(0, 0, frame.image.width, frame.image.height)
        if spec.trim:
            trimmed = opaque_bounds(frame.image)
            # A fully transparent frame has no bounding box; keep one pixel so
            # the frame still exists in the atlas rather than vanishing.
            box = trimmed or Rect(0, 0, 1, 1)

        pixels = frame.image.array[box.y : box.bottom, box.x : box.right]
        pieces.append(
            _Piece(
                id=frame.id,
                pixels=pixels,
                source_size=frame.image.size,
                trim_offset=Point(box.x, box.y),
            )
        )
    return pieces


def _dedupe(pieces: Sequence[_Piece]) -> tuple[list[_Piece], dict[str, str]]:
    """Map frames with byte-identical pixels onto one shared piece.

    Comparison is exact and in-memory only; nothing is persisted, per the
    no-stored-hashes rule (BACKEND_CLI_PLAN.md 5.2).
    """

    unique: list[_Piece] = []
    alias: dict[str, str] = {}
    for piece in pieces:
        for kept in unique:
            if kept.pixels.shape == piece.pixels.shape and np.array_equal(
                kept.pixels, piece.pixels
            ):
                alias[piece.id] = kept.id
                break
        else:
            unique.append(piece)
    return unique, alias


# --------------------------------------------------------------------- layouts


def _fixed_positions(
    pieces: Sequence[_Piece], spec: PackSpec
) -> list[tuple[int, int, int]]:
    """Return ``(page, x, y)`` for the three arithmetic layouts."""

    step = spec.padding + spec.extrude * 2
    if spec.layout == "horizontal":
        columns = len(pieces)
    elif spec.layout == "vertical":
        columns = 1
    elif spec.columns is not None:
        columns = spec.columns
    else:
        columns = max(1, -(-len(pieces) // (spec.rows or 1)))

    cell_w = max(p.width for p in pieces)
    cell_h = max(p.height for p in pieces)

    out: list[tuple[int, int, int]] = []
    for index in range(len(pieces)):
        row, col = divmod(index, columns)
        out.append(
            (
                0,
                spec.margin + col * (cell_w + step) + spec.extrude,
                spec.margin + row * (cell_h + step) + spec.extrude,
            )
        )
    return out


def _skyline_positions(
    pieces: Sequence[_Piece], spec: PackSpec
) -> tuple[list[tuple[int, int, int]], list[Size]]:
    """Bottom-left skyline packing, one page at a time.

    Pieces arrive pre-sorted by area then id, so the result is deterministic
    (BACKEND_CLI_PLAN.md 5.2).
    """

    step = spec.padding + spec.extrude * 2
    limit_w = spec.max_size.width
    limit_h = spec.max_size.height

    positions: list[tuple[int, int, int]] = [(-1, -1, -1)] * len(pieces)
    page_sizes: list[Size] = []
    remaining = list(range(len(pieces)))
    page = 0

    while remaining:
        # Skyline as a list of (x, width, height) segments across the page.
        skyline: list[list[int]] = [
            [spec.margin, limit_w - spec.margin * 2, spec.margin]
        ]
        placed_now: list[int] = []
        used_w = used_h = 0

        for index in remaining:
            piece = pieces[index]
            need_w = piece.width + spec.extrude * 2
            need_h = piece.height + spec.extrude * 2
            spot = _skyline_find(skyline, need_w + step, need_h, limit_w, limit_h, spec)
            if spot is None:
                continue

            x, y = spot
            _skyline_add(skyline, x, need_w + step, y + need_h + step)
            positions[index] = (page, x + spec.extrude, y + spec.extrude)
            placed_now.append(index)
            used_w = max(used_w, x + need_w)
            used_h = max(used_h, y + need_h)

        if not placed_now:
            biggest = max(remaining, key=lambda i: pieces[i].width * pieces[i].height)
            raise UsageError(
                "a frame does not fit the page size",
                frame=pieces[biggest].id,
                frame_size=[pieces[biggest].width, pieces[biggest].height],
                max_size=list(spec.max_size.as_tuple()),
            )

        page_sizes.append(Size(used_w + spec.margin, used_h + spec.margin))
        done = set(placed_now)
        remaining = [i for i in remaining if i not in done]
        page += 1

        if remaining and not spec.multi_page:
            raise UsageError(
                "frames do not fit one page; pass multi_page or a larger max_size",
                remaining=len(remaining),
                max_size=list(spec.max_size.as_tuple()),
            )

    return positions, page_sizes


def _skyline_find(
    skyline: Sequence[Sequence[int]],
    need_w: int,
    need_h: int,
    limit_w: int,
    limit_h: int,
    spec: PackSpec,
) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    for start in range(len(skyline)):
        x = skyline[start][0]
        if x + need_w > limit_w - spec.margin:
            break

        width_left = need_w
        y = 0
        for segment in skyline[start:]:
            y = max(y, segment[2])
            width_left -= segment[1]
            if width_left <= 0:
                break
        if width_left > 0:
            continue
        if y + need_h > limit_h - spec.margin:
            continue

        # Bottom-left: lowest y wins, then leftmost x.
        if best is None or (y, x) < (best[1], best[0]):
            best = (x, y)
    return best


def _skyline_add(skyline: list[list[int]], x: int, width: int, top: int) -> None:
    new: list[list[int]] = []
    for seg_x, seg_w, seg_top in skyline:
        seg_end = seg_x + seg_w
        if seg_end <= x or seg_x >= x + width:
            new.append([seg_x, seg_w, seg_top])
            continue
        if seg_x < x:
            new.append([seg_x, x - seg_x, seg_top])
        if seg_end > x + width:
            new.append([x + width, seg_end - (x + width), seg_top])
    new.append([x, width, top])
    new.sort(key=lambda s: s[0])

    merged: list[list[int]] = []
    for segment in new:
        if (
            merged
            and merged[-1][2] == segment[2]
            and merged[-1][0] + merged[-1][1] == segment[0]
        ):
            merged[-1][1] += segment[1]
        else:
            merged.append(segment)
    skyline[:] = merged


# ---------------------------------------------------------------- public API


def pack_frames(frames: FrameSet, spec: PackSpec = PackSpec()) -> AtlasBundle:
    """Lay frames out into one or more atlas pages."""

    if len(frames) == 0:
        raise UsageError("frame set is empty", frame_set=frames.id)

    warnings: list[WorkshopWarning] = []
    pieces = _prepare(frames, spec)

    alias: dict[str, str] = {}
    if spec.dedupe:
        pieces, alias = _dedupe(pieces)
        if alias:
            warnings.append(
                WorkshopWarning(
                    code="pack.deduped",
                    message=f"{len(alias)} frame(s) share pixels with another frame",
                    details={"aliases": alias},
                )
            )

    if spec.layout == "compact":
        # Area-descending then id keeps packing stable across runs.
        order = sorted(
            range(len(pieces)),
            key=lambda i: (-(pieces[i].width * pieces[i].height), pieces[i].id),
        )
        ordered = [pieces[i] for i in order]
        positions, page_sizes = _skyline_positions(ordered, spec)
        placement = dict(zip((p.id for p in ordered), positions))
    else:
        positions = _fixed_positions(pieces, spec)
        placement = dict(zip((p.id for p in pieces), positions))
        width = max(
            x + p.width + spec.extrude for (_, x, _), p in zip(positions, pieces)
        )
        height = max(
            y + p.height + spec.extrude for (_, _, y), p in zip(positions, pieces)
        )
        page_sizes = [Size(width + spec.margin, height + spec.margin)]
        if width > spec.max_size.width or height > spec.max_size.height:
            raise UsageError(
                "fixed layout exceeds the page size",
                size=[width, height],
                max_size=list(spec.max_size.as_tuple()),
            )

    buffers = [np.zeros((s.height, s.width, 4), np.uint8) for s in page_sizes]
    for piece in pieces:
        page, x, y = placement[piece.id]
        _blit(buffers[page], piece.pixels, x, y, spec.extrude)

    by_id = {p.id: p for p in pieces}
    packed: list[PackedFrame] = []
    for frame in frames.frames:
        source_id = alias.get(frame.id, frame.id)
        piece = by_id[source_id]
        page, x, y = placement[source_id]
        packed.append(
            PackedFrame(
                id=frame.id,
                page=page,
                rect=Rect(x, y, piece.width, piece.height),
                source_size=piece.source_size,
                trim_offset=piece.trim_offset,
                anchor=frame.anchor,
                tags=dict(frame.tags),
            )
        )

    return AtlasBundle(
        pages=tuple(
            AtlasPage(index=i, image=RgbaImage(buffer))
            for i, buffer in enumerate(buffers)
        ),
        frames=tuple(packed),
        warnings=tuple(warnings),
        metrics={
            "layout": spec.layout,
            "frames": len(packed),
            "pages": len(buffers),
            "page_sizes": [f"{s.width}x{s.height}" for s in page_sizes],
            "coverage": round(_coverage(pieces, page_sizes), 4),
        },
    )


def _blit(page: np.ndarray, pixels: np.ndarray, x: int, y: int, extrude: int) -> None:
    height, width = pixels.shape[:2]
    page[y : y + height, x : x + width] = pixels
    if extrude <= 0:
        return

    # Repeat the edge rows/columns outwards so engine bilinear sampling cannot
    # pull in a neighbouring frame's colour.
    for i in range(1, extrude + 1):
        page[y - i, x : x + width] = pixels[0]
        page[y + height + i - 1, x : x + width] = pixels[-1]
    top, bottom = y - extrude, y + height + extrude
    for i in range(1, extrude + 1):
        page[top:bottom, x - i] = page[top:bottom, x]
        page[top:bottom, x + width + i - 1] = page[top:bottom, x + width - 1]


def _coverage(pieces: Iterable[_Piece], page_sizes: Sequence[Size]) -> float:
    used = sum(p.width * p.height for p in pieces)
    total = sum(s.width * s.height for s in page_sizes)
    return used / total if total else 0.0
