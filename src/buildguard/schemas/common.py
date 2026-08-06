"""Common schema primitives."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from buildguard.utils.time import utc_now


class StrictSchema(BaseModel):
    """Base domain schema with safe defaults."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Status(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    NORMAL = "normal"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class BoundingBox(StrictSchema):
    """Pixel-space axis-aligned rectangle."""

    x1: float = Field(ge=0)
    y1: float = Field(ge=0)
    x2: float = Field(gt=0)
    y2: float = Field(gt=0)

    @field_validator("x2")
    @classmethod
    def x2_after_x1(cls, value: float, info: Any) -> float:
        if "x1" in info.data and value <= info.data["x1"]:
            raise ValueError("x2 must be greater than x1")
        return value

    @field_validator("y2")
    @classmethod
    def y2_after_y1(cls, value: float, info: Any) -> float:
        if "y1" in info.data and value <= info.data["y1"]:
            raise ValueError("y2 must be greater than y1")
        return value

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return self.width * self.height

    def iou(self, other: BoundingBox) -> float:
        intersection_width = max(0.0, min(self.x2, other.x2) - max(self.x1, other.x1))
        intersection_height = max(0.0, min(self.y2, other.y2) - max(self.y1, other.y1))
        intersection = intersection_width * intersection_height
        union = self.area + other.area - intersection
        return intersection / union if union else 0.0

    def clip(self, image_width: float, image_height: float) -> BoundingBox:
        if image_width <= 0 or image_height <= 0:
            raise ValueError("image dimensions must be positive")
        x1 = min(self.x1, image_width)
        y1 = min(self.y1, image_height)
        x2 = min(self.x2, image_width)
        y2 = min(self.y2, image_height)
        if x2 <= x1 or y2 <= y1:
            raise ValueError("bounding box does not overlap the image")
        return BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2)


def new_id() -> str:
    return str(uuid4())


def validate_uuid(value: str) -> str:
    UUID(value)
    return value


class RecordSchema(StrictSchema):
    id: str = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=utc_now)

    _valid_id = field_validator("id")(validate_uuid)
