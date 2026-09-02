"""Report Pydantic schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.enums import Recommendation


class ReportCreate(BaseModel):
    interview_id: UUID
    overall_score: float | None = Field(default=None, ge=0, le=100)
    recommendation: Recommendation | None = None
    performance_confidence: float | None = Field(default=None, ge=0, le=100)
    summary: str | None = Field(default=None, max_length=10000)
    executive_note: str | None = Field(default=None, max_length=10000)
    competency_matrix: dict[str, Any] | list[Any] | None = None
    pulse_series: dict[str, Any] | list[Any] | None = None
    export_path: str | None = Field(default=None, max_length=1024)

    @field_validator("summary", "executive_note", "export_path")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ReportUpdate(BaseModel):
    overall_score: float | None = Field(default=None, ge=0, le=100)
    recommendation: Recommendation | None = None
    performance_confidence: float | None = Field(default=None, ge=0, le=100)
    summary: str | None = Field(default=None, max_length=10000)
    executive_note: str | None = Field(default=None, max_length=10000)
    competency_matrix: dict[str, Any] | list[Any] | None = None
    pulse_series: dict[str, Any] | list[Any] | None = None
    export_path: str | None = Field(default=None, max_length=1024)

    @field_validator("summary", "executive_note", "export_path")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    interview_id: UUID
    overall_score: float | None
    recommendation: Recommendation | None
    performance_confidence: float | None
    summary: str | None
    executive_note: str | None
    competency_matrix: dict[str, Any] | list[Any] | None
    pulse_series: dict[str, Any] | list[Any] | None
    export_path: str | None
    created_at: datetime
    updated_at: datetime
