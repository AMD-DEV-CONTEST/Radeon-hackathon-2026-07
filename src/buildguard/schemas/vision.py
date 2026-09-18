"""Vision inspection schemas."""

from pathlib import Path

from pydantic import Field

from buildguard.schemas.common import BoundingBox, RecordSchema, Severity, StrictSchema


class Detection(StrictSchema):
    label: str = Field(min_length=1, max_length=128)
    confidence: float = Field(ge=0, le=1)
    bounding_box: BoundingBox
    source_model: str = Field(default="unknown", min_length=1, max_length=256)
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)


class RiskAssessment(StrictSchema):
    severity: Severity
    score: float = Field(ge=0, le=1)
    summary: str = Field(min_length=1, max_length=2000)
    recommended_actions: list[str] = Field(default_factory=list, max_length=50)


class InspectionResult(RecordSchema):
    source_path: Path
    detections: list[Detection] = Field(default_factory=list)
    risks: list[RiskAssessment] = Field(default_factory=list)
    model_name: str = Field(min_length=1)
    processing_ms: float = Field(ge=0)
    success: bool = True
    error: str | None = Field(default=None, max_length=2000)
