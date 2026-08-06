"""contracts.py — typed Pydantic response models for the Learning Companion API.

These models are the single source of truth for the OpenAPI schema (exported by
scripts/audit_contracts.sh) and are synchronized with web/src/lib/api.ts via the
checked-in OpenAPI snapshot + regenerated TypeScript types.

Covers: skills, cards, review sessions, extraction results, stats, and errors.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SkillOut(BaseModel):
    id: int
    name: str
    description: str = ""
    growth_value: float
    decay_rate: float
    status: str
    last_reviewed_at: Optional[str] = None
    last_decay_at: Optional[str] = None
    created_at: str
    updated_at: str
    card_count: Optional[int] = None


class SkillCreateOut(SkillOut):
    pass


class CardOut(BaseModel):
    id: int
    skill_id: int
    content: str
    source_material: str = ""
    mastery_level: int = 0
    last_reviewed_at: Optional[str] = None
    created_at: str
    updated_at: str


class SessionOut(BaseModel):
    id: int
    skill_id: int
    status: str
    card_index: int = 0
    total_cards: int = 0
    phase: str = "learn"
    retries: int = 0
    judged: dict[str, object] = Field(default_factory=dict)
    user_override: bool = False
    transcript: list[dict[str, object]] = Field(default_factory=list)
    created_at: str
    completed_at: Optional[str] = None


class SkillDetailOut(BaseModel):
    id: int
    name: str
    description: str = ""
    growth_value: float
    decay_rate: float
    status: str
    last_reviewed_at: Optional[str] = None
    last_decay_at: Optional[str] = None
    created_at: str
    updated_at: str
    cards: list[CardOut] = Field(default_factory=list)
    sessions: list[SessionOut] = Field(default_factory=list)


class SkillListOut(BaseModel):
    skills: list[SkillOut]


class CardItem(BaseModel):
    id: int
    content: str
    source: str = ""


class ExtractOut(BaseModel):
    ok: bool
    mode: Optional[str] = None
    cards: list[CardItem] = Field(default_factory=list)
    error: Optional[str] = None
    latency_s: Optional[float] = None
    raw: Optional[str] = None
    skill_id: Optional[int] = None
    quick: Optional[dict[str, object]] = None
    full: Optional[dict[str, object]] = None


class ReviewStartOut(BaseModel):
    ok: bool
    resumed: bool = False
    session: Optional[SessionOut] = None
    error: Optional[str] = None


class ReviewMessageOut(BaseModel):
    ok: bool
    content: str = ""
    judgment: Optional[dict[str, object]] = None
    done: bool = False
    error: Optional[str] = None


class ReviewCompleteOut(BaseModel):
    ok: bool
    skill_id: Optional[int] = None
    growth_value: Optional[float] = None
    error: Optional[str] = None


class StatsOut(BaseModel):
    skills: int
    cards: int
    sessions: int
    active_sessions: int
    total_growth: float
    avg_growth: float
    # Todo 8: distinguish target-schema states
    preview_units: int = 0
    verified_units: int = 0
    pending_extractions: int = 0
    failed_extractions: int = 0
    assessment_due: int = 0
    review_due: int = 0


class DecayOut(BaseModel):
    applied: list[dict[str, object]] = Field(default_factory=list)
    today: str


class ErrorOut(BaseModel):
    detail: str


# ---- evaluation report schema (machine-consumed by run_eval.py + validators) ----
class ReportMetrics(BaseModel):
    source_support: float
    unsupported_claim: float
    key_point_coverage: float
    grading_agreement: float
    duplicate: float
    schema_validity: float


class EvalReport(BaseModel):
    report_schema_version: int = 1
    model: str
    metrics: ReportMetrics
    fatal_failures: list[dict[str, object]] = Field(default_factory=list)
    inputs: dict[str, object] = Field(default_factory=dict)
    environment: dict[str, object] = Field(default_factory=dict)
    created_at: str
