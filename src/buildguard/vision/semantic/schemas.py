"""Auditable outputs from a semantic image pre-router."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from buildguard.schemas.common import StrictSchema

SemanticRoutingStatus = Literal["completed", "fallback"]


class SemanticExpertScore(StrictSchema):
    """Calibrated relevance for one existing specialist detector."""

    model_name: str = Field(min_length=1, max_length=256)
    positive_similarity: float = Field(ge=-1, le=1)
    negative_similarity: float = Field(ge=-1, le=1)
    probability: float = Field(ge=0, le=1)


class SemanticRoutingResult(StrictSchema):
    """Trace data only; these scores are never defect or risk evidence."""

    status: SemanticRoutingStatus
    model_name: str = Field(min_length=1, max_length=256)
    model_revision: str | None = None
    checkpoint_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    expert_scores: list[SemanticExpertScore] = Field(default_factory=list)
    processing_ms: float = Field(default=0, ge=0)
    cache_hit: bool = False
    error: str | None = None

    def probabilities(self) -> dict[str, float]:
        return {item.model_name: item.probability for item in self.expert_scores}
