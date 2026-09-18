"""Visual inspection and evidence schemas."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, model_validator

from buildguard.schemas.common import BoundingBox, StrictSchema
from buildguard.schemas.rag import RetrievedEvidence
from buildguard.schemas.vision import Detection, InspectionResult, RiskAssessment
from buildguard.vision.routing.schemas import RoutingDecision


class LetterboxTransform(StrictSchema):
    original_width: int = Field(gt=0)
    original_height: int = Field(gt=0)
    target_width: int = Field(gt=0)
    target_height: int = Field(gt=0)
    scale: float = Field(gt=0)
    pad_x: float = Field(ge=0)
    pad_y: float = Field(ge=0)


class EvidenceRecord(StrictSchema):
    evidence_id: str = Field(min_length=64, max_length=64)
    image_path: Path
    bbox: BoundingBox
    confidence: float = Field(ge=0, le=1)
    source_model: str
    visualization_path: Path
    requires_review: bool
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class InspectionSummary(StrictSchema):
    image_path: Path
    success: bool
    detection_count: int = Field(ge=0)
    category_counts: dict[str, int] = Field(default_factory=dict)
    max_confidence: float = Field(default=0, ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    risk_candidates: list[str] = Field(default_factory=list)
    routing_decisions: list[RoutingDecision] = Field(default_factory=list)
    error: str | None = None


class SingleImageInspectionInput(StrictSchema):
    image_path: Path
    requested_classes: list[str] | None = None
    model_names: list[str] | None = None


class SingleImageInspectionOutput(StrictSchema):
    inspection: InspectionResult
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    summary: InspectionSummary


class BatchImageInspectionInput(StrictSchema):
    directory: Path | None = None
    image_paths: list[Path] = Field(default_factory=list)
    recursive: bool = False
    max_items: int | None = Field(default=None, ge=1, le=10_000)
    requested_classes: list[str] | None = None
    model_names: list[str] | None = None

    @model_validator(mode="after")
    def require_source(self) -> BatchImageInspectionInput:
        if self.directory is None and not self.image_paths:
            raise ValueError("directory or image_paths is required")
        return self


class ImageFailure(StrictSchema):
    image_path: Path
    error: str


class BatchInspectionResult(StrictSchema):
    results: list[SingleImageInspectionOutput] = Field(default_factory=list)
    failures: list[ImageFailure] = Field(default_factory=list)
    category_counts: dict[str, int] = Field(default_factory=dict)
    risk_candidates: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class BatchInspectionToolOutput(StrictSchema):
    """LLM-safe aggregate without raw bounding boxes."""

    summaries: list[InspectionSummary] = Field(default_factory=list)
    failed_images: list[ImageFailure] = Field(default_factory=list)
    category_counts: dict[str, int] = Field(default_factory=dict)
    risk_candidates: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class RiskAssessmentInput(StrictSchema):
    inspection_result: InspectionResult | None = None
    inspection_results: list[InspectionResult] = Field(default_factory=list, max_length=1000)
    retrieved_evidence: list[RetrievedEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_inspection_source(self) -> RiskAssessmentInput:
        if self.inspection_result is None and not self.inspection_results:
            raise ValueError("inspection_result or inspection_results is required")
        if self.inspection_result is not None and self.inspection_results:
            raise ValueError("provide either inspection_result or inspection_results, not both")
        return self


class RiskAssessmentOutput(StrictSchema):
    assessment: RiskAssessment
    assessments: list[RiskAssessment] = Field(default_factory=list)
    component_scores: dict[str, float] = Field(default_factory=dict)
    component_scores_batch: list[dict[str, float]] = Field(default_factory=list)
    governing_detection: Detection | None = None
    governing_detections: list[Detection | None] = Field(default_factory=list)
