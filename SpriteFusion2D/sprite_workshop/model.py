"""Immutable value objects shared by every workshop module.

The image and coordinate contract lives here (BACKEND_CLI_PLAN.md 5).  Working
images are always ``[H, W, 4]`` uint8 RGBA, the origin is top-left, and every
rectangle is half-open.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterator, Mapping

import numpy as np

from .errors import UsageError

RGBA_CHANNELS = 4


@dataclass(frozen=True, slots=True)
class Size:
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width < 0 or self.height < 0:
            raise UsageError(
                "size must not be negative", width=self.width, height=self.height
            )

    def as_tuple(self) -> tuple[int, int]:
        return self.width, self.height


@dataclass(frozen=True, slots=True)
class Point:
    x: int
    y: int

    def __post_init__(self) -> None:
        if not isinstance(self.x, int) or not isinstance(self.y, int):
            raise UsageError("point coordinates must be integers", x=self.x, y=self.y)

    def as_tuple(self) -> tuple[int, int]:
        return self.x, self.y


@dataclass(frozen=True, slots=True)
class Rect:
    """Half-open rectangle: right and bottom edges are excluded."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width < 0 or self.height < 0:
            raise UsageError(
                "rect size must not be negative", width=self.width, height=self.height
            )

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def contains_rect(self, other: "Rect") -> bool:
        return (
            other.x >= self.x
            and other.y >= self.y
            and other.right <= self.right
            and other.bottom <= self.bottom
        )

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.width, self.height


class RgbaImage:
    """A read-only ``[H, W, 4]`` uint8 RGBA buffer.

    ``frozen=True`` on a dataclass would only freeze the reference, so the
    array is explicitly marked non-writeable: immutability is enforced at
    runtime rather than by convention (BACKEND_CLI_PLAN.md 6.1).
    """

    __slots__ = ("_array",)

    def __init__(self, array: np.ndarray) -> None:
        if array.ndim != 3 or array.shape[2] != RGBA_CHANNELS:
            raise UsageError(
                "image must have shape [H, W, 4]", shape=tuple(array.shape)
            )
        if array.dtype != np.uint8:
            raise UsageError("image dtype must be uint8", dtype=str(array.dtype))
        buffer = np.ascontiguousarray(array)
        if buffer is array:
            buffer = array.copy()
        buffer.flags.writeable = False
        self._array = buffer

    @property
    def array(self) -> np.ndarray:
        return self._array

    @property
    def width(self) -> int:
        return int(self._array.shape[1])

    @property
    def height(self) -> int:
        return int(self._array.shape[0])

    @property
    def size(self) -> Size:
        return Size(self.width, self.height)

    def copy_writable(self) -> np.ndarray:
        """Return a mutable copy for a transform to work on."""

        out = self._array.copy()
        out.flags.writeable = True
        return out

    def normalized(self) -> "RgbaImage":
        """Zero the RGB of fully transparent pixels (BACKEND_CLI_PLAN.md 5.1)."""

        buffer = self.copy_writable()
        buffer[buffer[:, :, 3] == 0] = 0
        return RgbaImage(buffer)

    def has_hidden_color(self) -> bool:
        transparent = self._array[:, :, 3] == 0
        if not transparent.any():
            return False
        return bool(self._array[transparent][:, :3].any())

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RgbaImage):
            return NotImplemented
        return np.array_equal(self._array, other._array)

    def __repr__(self) -> str:
        return f"RgbaImage({self.width}x{self.height})"


@dataclass(frozen=True, slots=True)
class Frame:
    """One frame plus the metadata needed to put it back where it came from.

    ``duration_ms`` deliberately does not live here: a frame can appear in
    several clips with different timing, so duration belongs to Clip only
    (BACKEND_CLI_PLAN.md 6.1, 8.8).
    """

    id: str
    image: RgbaImage
    source_size: Size
    trim_rect: Rect
    trim_offset: Point
    anchor: Point
    label: str = ""
    tags: Mapping[str, str] = field(default_factory=dict)

    @property
    def size(self) -> Size:
        return self.image.size

    def with_tags(self, tags: Mapping[str, str]) -> "Frame":
        return replace(self, tags=dict(tags))


@dataclass(frozen=True, slots=True)
class FrameSet:
    id: str
    frames: tuple[Frame, ...]
    canvas_size: Size | None = None

    def __iter__(self) -> Iterator[Frame]:
        return iter(self.frames)

    def __len__(self) -> int:
        return len(self.frames)

    def index_of(self, frame_id: str) -> int:
        for index, frame in enumerate(self.frames):
            if frame.id == frame_id:
                return index
        raise UsageError(f"frame not found: {frame_id}", frame_set=self.id)


@dataclass(frozen=True, slots=True)
class AssetRef:
    name: str
    version: int


@dataclass(frozen=True, slots=True)
class WorkshopWarning:
    code: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class OperationReport:
    operation: str
    changed: bool
    revision: int | None = None
    outputs: tuple[str, ...] = ()
    warnings: tuple[WorkshopWarning, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)
