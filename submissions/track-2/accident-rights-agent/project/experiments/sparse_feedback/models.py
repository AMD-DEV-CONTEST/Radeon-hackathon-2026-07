"""Strict sparse preference record; intentionally contains no training fields."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Preference(str, Enum):
    A = "A"
    B = "B"
    TIE = "tie"
    ABSTAIN = "abstain"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SparseFeedbackRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    question_id: str = Field(min_length=1)
    answer_A: str
    answer_B: str
    preferred: Preference
    reason: str = Field(min_length=1)
    missing_evidence: list[str] = Field(default_factory=list)
    unsupported_claim: list[str] = Field(default_factory=list)
    risk_level: RiskLevel
