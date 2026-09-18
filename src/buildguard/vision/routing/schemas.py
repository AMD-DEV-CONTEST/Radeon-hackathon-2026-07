"""Validated data structures for visual routing."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from buildguard.config import VisionModelConfig
from buildguard.schemas.common import BoundingBox, StrictSchema
from buildguard.vision.semantic.schemas import SemanticRoutingResult

RoutingStrategy = Literal["full-all", "rule", "cost-aware", "cost-aware-guard"]


class RoiContext(StrictSchema):
    """Metadata that cannot be derived from a single image crop."""

    roi_label: str = Field(min_length=1, max_length=128)
    roi_confidence: float = Field(ge=0, le=1)
    track_age: int = Field(default=0, ge=0)
    previous_probability: float = Field(default=0, ge=0, le=1)
    previous_detection_confidence: float = Field(default=0, ge=0, le=1)
    device_load: float = Field(default=0, ge=0, le=1)
    high_risk: bool = False


class RoiFeatures(StrictSchema):
    roi_label: str = Field(min_length=1, max_length=128)
    roi_confidence: float = Field(ge=0, le=1)
    area_ratio: float = Field(gt=0, le=1)
    aspect_ratio: float = Field(gt=0)
    center: tuple[float, float]
    brightness: float = Field(ge=0, le=1)
    contrast: float = Field(ge=0, le=1)
    blur: float = Field(ge=0, le=1)
    edge_density: float = Field(ge=0, le=1)
    texture_score: float = Field(ge=0, le=1)
    motion_score: float = Field(ge=0, le=1)
    track_age: int = Field(ge=0)
    previous_probability: float = Field(ge=0, le=1)
    previous_detection_confidence: float = Field(ge=0, le=1)
    device_load: float = Field(ge=0, le=1)
    high_risk: bool = False

    @field_validator("center")
    @classmethod
    def validate_center(cls, value: tuple[float, float]) -> tuple[float, float]:
        if any(coordinate < 0 or coordinate > 1 for coordinate in value):
            raise ValueError("ROI center coordinates must be normalized to 0..1")
        return value

    @property
    def quality_score(self) -> float:
        brightness_quality = 1.0 - abs(self.brightness - 0.5) * 2.0
        sharpness = 1.0 - self.blur
        return max(
            0.0,
            min(
                1.0,
                (
                    brightness_quality
                    + self.contrast
                    + sharpness
                    + self.edge_density
                )
                / 4.0,
            ),
        )


class RoutingModel(StrictSchema):
    model_name: str = Field(min_length=1, max_length=256)
    applicable_roi_types: list[str] = Field(min_length=1)
    defect_classes: list[str] = Field(min_length=1)
    reliability: float = Field(ge=0, le=1)
    estimated_latency_ms: float = Field(ge=0)
    estimated_memory_mb: float = Field(ge=0)
    fixed_call_cost: float = Field(ge=0)
    high_risk_relevance: float = Field(ge=0, le=1)
    enabled: bool

    @classmethod
    def from_config(cls, config: VisionModelConfig) -> RoutingModel:
        return cls(
            model_name=config.model_name,
            applicable_roi_types=config.applicable_roi_types,
            defect_classes=config.defect_classes,
            reliability=config.reliability,
            estimated_latency_ms=config.estimated_latency_ms,
            estimated_memory_mb=config.estimated_memory_mb,
            fixed_call_cost=config.fixed_call_cost,
            high_risk_relevance=config.high_risk_relevance,
            enabled=config.enabled,
        )

    def applies_to(self, roi_type: str) -> bool:
        return (
            roi_type == "*"
            or "*" in self.applicable_roi_types
            or roi_type in self.applicable_roi_types
        )


class ScoredRoutingModel(StrictSchema):
    model: RoutingModel
    probability: float = Field(ge=0, le=1)
    cost: float = Field(ge=0)


class SubsetScore(StrictSchema):
    selected_model_names: list[str]
    benefit: float = Field(ge=0, le=1)
    coverage: float = Field(ge=0, le=1)
    total_cost: float = Field(ge=0)
    utility: float


class GuardResult(StrictSchema):
    selected_model_names: list[str]
    triggered: bool
    reasons: list[str] = Field(default_factory=list)
    budget_overrun: float = Field(default=0, ge=0)


class RoutingDecision(StrictSchema):
    strategy: RoutingStrategy
    roi_label: str
    candidate_model_names: list[str]
    selected_model_names: list[str]
    model_scores: list[ScoredRoutingModel]
    benefit: float = Field(ge=0, le=1)
    coverage: float = Field(ge=0, le=1)
    total_cost: float = Field(ge=0)
    utility: float
    guard_triggered: bool = False
    guard_reasons: list[str] = Field(default_factory=list)
    used_greedy_optimizer: bool = False
    probability_source: Literal["heuristic", "mobileclip2_blend"] = "heuristic"
    semantic_routing: SemanticRoutingResult | None = None

    @model_validator(mode="after")
    def selected_must_be_candidates(self) -> RoutingDecision:
        if not set(self.selected_model_names).issubset(self.candidate_model_names):
            raise ValueError("selected models must be drawn only from candidates")
        return self


class FeatureExtractionRequest(StrictSchema):
    bounding_box: BoundingBox
    context: RoiContext
