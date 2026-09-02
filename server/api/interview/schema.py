"""Interview Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models.enums import InterviewStatus


class InterviewCreate(BaseModel):
    candidate_id: UUID
    resume_id: UUID | None = None
    role: str = Field(min_length=1, max_length=255)
    status: InterviewStatus = InterviewStatus.SCHEDULED
    complexity: str | None = Field(default=None, max_length=100)
    duration_seconds: int | None = Field(default=None, ge=1, le=24 * 60 * 60)
    started_at: datetime | None = None
    ended_at: datetime | None = None

    @field_validator("role")
    @classmethod
    def strip_role(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("role cannot be empty")
        return cleaned

    @field_validator("complexity")
    @classmethod
    def strip_complexity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def validate_time_range(self) -> InterviewCreate:
        if self.started_at and self.ended_at and self.ended_at < self.started_at:
            raise ValueError("ended_at must be greater than or equal to started_at")
        return self


class InterviewUpdate(BaseModel):
    resume_id: UUID | None = None
    role: str | None = Field(default=None, min_length=1, max_length=255)
    status: InterviewStatus | None = None
    score: float | None = Field(default=None, ge=0, le=100)
    progress: float | None = Field(default=None, ge=0, le=100)
    complexity: str | None = Field(default=None, max_length=100)
    duration_seconds: int | None = Field(default=None, ge=1, le=24 * 60 * 60)
    started_at: datetime | None = None
    ended_at: datetime | None = None

    @field_validator("role", "complexity")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def validate_time_range(self) -> InterviewUpdate:
        if self.started_at and self.ended_at and self.ended_at < self.started_at:
            raise ValueError("ended_at must be greater than or equal to started_at")
        return self


class InterviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    candidate_id: UUID
    user_id: UUID
    resume_id: UUID | None
    role: str
    status: InterviewStatus
    score: float | None
    progress: float | None
    complexity: str | None
    duration_seconds: int | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime
    updated_at: datetime
