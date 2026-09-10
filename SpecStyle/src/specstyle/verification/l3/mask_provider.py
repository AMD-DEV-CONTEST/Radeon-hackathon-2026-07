"""Mask provider: manual/input masks with strict validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from specstyle.domain.identifiers import ArtifactId
from specstyle.errors import DomainError


@dataclass(frozen=True, slots=True)
class Mask:
    """Binary mask as flat 0/1 rows; size matches image."""

    width: int
    height: int
    data: tuple[int, ...]  # length width*height, values 0 or 1

    def __post_init__(self) -> None:
        if type(self.width) is not int or type(self.height) is not int:
            raise DomainError("invalid mask size")
        if self.width < 1 or self.height < 1:
            raise DomainError("invalid mask size")
        if type(self.data) is not tuple or len(self.data) != self.width * self.height:
            raise DomainError("invalid mask data")
        if any(v not in (0, 1) for v in self.data):
            raise DomainError("invalid mask data")

    def foreground_count(self) -> int:
        return sum(self.data)


@runtime_checkable
class MaskProvider(Protocol):
    def get_mask(self, artifact_id: ArtifactId, /) -> Mask | None: ...


class DictMaskProvider:
    def __init__(self, masks: dict[ArtifactId, Mask]) -> None:
        if type(masks) is not dict:
            raise DomainError("invalid mask map")
        self._masks = dict(masks)

    def get_mask(self, artifact_id: ArtifactId, /) -> Mask | None:
        if type(artifact_id) is not ArtifactId:
            raise DomainError("invalid artifact id")
        return self._masks.get(artifact_id)


def validate_mask_for_image(
    mask: Mask | None, image_size: tuple[int, int], /
) -> str | None:
    """Return error reason code or None if ok."""
    if mask is None:
        return "MASK_MISSING"
    if (mask.width, mask.height) != image_size:
        return "MASK_SIZE_MISMATCH"
    if mask.foreground_count() == 0:
        return "MASK_EMPTY"
    return None
