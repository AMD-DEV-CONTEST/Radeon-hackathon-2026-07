"""Fine-segmentation contracts and validated mask results."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, field_validator

from buildguard.schemas.common import BoundingBox, StrictSchema
from buildguard.vision.preprocessing import DecodedImage


class PointPrompt(StrictSchema):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    label: int = Field(ge=0, le=1)


class RawMaskPrediction(BaseModel):
    """Output contract expected from an explicitly supplied SAM 2 output adapter."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    mask: NDArray[np.bool_]
    confidence: float = Field(ge=0, le=1)
    stability: float = Field(ge=0, le=1)

    @field_validator("mask")
    @classmethod
    def valid_mask(cls, value: NDArray[np.bool_]) -> NDArray[np.bool_]:
        mask = np.asarray(value, dtype=np.bool_)
        if mask.ndim != 2 or mask.size == 0:
            raise ValueError("segmentation mask must be a non-empty 2D array")
        return mask


class SegmentationMask(BaseModel):
    """One measured mask in original-image coordinates."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    mask: NDArray[np.bool_]
    area: int = Field(gt=0)
    area_ratio: float = Field(gt=0, le=1)
    perimeter: float = Field(gt=0)
    bounding_box: BoundingBox
    confidence: float = Field(ge=0, le=1)
    stability: float = Field(ge=0, le=1)
    source_model: str = Field(min_length=1, max_length=256)
    mask_path: Path

    @field_validator("mask")
    @classmethod
    def valid_mask(cls, value: NDArray[np.bool_]) -> NDArray[np.bool_]:
        mask = np.asarray(value, dtype=np.bool_)
        if mask.ndim != 2 or mask.size == 0:
            raise ValueError("segmentation mask must be a non-empty 2D array")
        return mask


class FineSegmentationAdapter(ABC):
    """Segment one decoded image from box prompts."""

    @abstractmethod
    def segment(
        self,
        image: DecodedImage,
        bbox_prompts: list[BoundingBox],
        point_prompts: list[PointPrompt] | None = None,
    ) -> list[SegmentationMask]:
        """Return masks and deterministic geometry measurements."""

    @abstractmethod
    def unload(self) -> None:
        """Release loaded local model resources when supported."""
