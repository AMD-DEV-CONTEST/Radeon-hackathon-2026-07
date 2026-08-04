from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from policyseal.domain.enums import ContentCategory, FileKind


class AgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewIntent(StrEnum):
    EXPLAIN = "explain"
    SIMULATE = "simulate"
    DRAFT_EXCEPTION = "draft_exception"


class SemanticRegionInput(AgentModel):
    region_id: str = Field(min_length=1, max_length=200)
    file_kind: FileKind
    location: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=4_000)


class ModelClassification(AgentModel):
    region_id: str = Field(min_length=1, max_length=200)
    category: ContentCategory
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=3)


class ClassificationBatch(AgentModel):
    classifications: tuple[ModelClassification, ...]


class ClassificationOutcome(AgentModel):
    region_id: str
    category: ContentCategory | None
    confidence: float
    evidence_ids: tuple[str, ...]
    requires_human_review: bool
    reason_code: str
    model_assisted: bool


@dataclass(frozen=True, slots=True)
class LocalCompletion:
    content: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True, slots=True)
class CompletionAttempt:
    batch_index: int
    pass_index: int
    region_ids: tuple[str, ...]
    completion: LocalCompletion


@dataclass(frozen=True, slots=True)
class ClassificationRun:
    outcomes: tuple[ClassificationOutcome, ...]
    latency_ms: float = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
