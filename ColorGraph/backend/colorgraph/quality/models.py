from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from colorgraph.quality.temporal_motion import TemporalQualityEvidence


class CheckStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class QualityCategory(StrEnum):
    HARD_TECHNICAL = "hard_technical"
    PERCEPTUAL_RISK = "perceptual_risk"
    AESTHETIC_PREFERENCE = "aesthetic_preference"


class AuxiliaryScoreKind(StrEnum):
    PERCEPTUAL_RISK = "perceptual_risk"
    AESTHETIC_PREFERENCE = "aesthetic_preference"


class QualityCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    status: CheckStatus
    value: float
    threshold: float
    unit: str
    detail: str
    category: QualityCategory = QualityCategory.HARD_TECHNICAL
    metric_version: str = "legacy"


class AuxiliaryQualityScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: AuxiliaryScoreKind
    value: float = Field(ge=0, le=1)
    provider: str
    model_id: str
    model_revision: str
    calibration_id: str
    calibration_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    domain_calibrated: bool
    detail: str


class QualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "colorgraph.quality-report/v2"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_path: str
    output_path: str
    sampled_frames: int
    score: int = Field(ge=0, le=100)
    hard_checks_passed: bool
    checks: list[QualityCheck]
    summary: str
    metrics: dict[str, float] = Field(default_factory=dict)
    technical_score: int = Field(default=100, ge=0, le=100)
    perceptual_risk_score: int = Field(default=100, ge=0, le=100)
    technical_hard_failures: list[str] = Field(default_factory=list)
    perceptual_risks: list[str] = Field(default_factory=list)
    auxiliary_scores: list[AuxiliaryQualityScore] = Field(default_factory=list)
    aesthetic_preferences: list[AuxiliaryQualityScore] = Field(default_factory=list)
    temporal_evidence: TemporalQualityEvidence | None = None
