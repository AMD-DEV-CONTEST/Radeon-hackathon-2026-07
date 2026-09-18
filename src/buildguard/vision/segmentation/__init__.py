"""Optional local fine-segmentation adapters."""

from buildguard.vision.segmentation.base import (
    FineSegmentationAdapter,
    PointPrompt,
    SegmentationMask,
)
from buildguard.vision.segmentation.sam2_adapter import Sam2LocalAdapter

__all__ = [
    "FineSegmentationAdapter",
    "PointPrompt",
    "Sam2LocalAdapter",
    "SegmentationMask",
]
