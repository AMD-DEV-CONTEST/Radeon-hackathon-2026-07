"""Stable segmentation boundary used by the deterministic pose-card renderer."""

from src.tools.person_segmenter import (
    PersonSegmenter,
    get_shared_person_segmenter,
)

__all__ = ["PersonSegmenter", "get_shared_person_segmenter"]
