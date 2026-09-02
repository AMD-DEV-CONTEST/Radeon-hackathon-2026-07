"""Candidate Pydantic schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from models.enums import Recommendation


class CandidateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    title: str | None = Field(default=None, max_length=255)
    level: str | None = Field(default=None, max_length=100)
    avatar_url: str | None = Field(default=None, max_length=512)
    target_role: str | None = Field(default=None, max_length=255)
    years_of_experience: int | None = Field(default=None, ge=0, le=80)
    skills: list[str] | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name cannot be empty")
        return cleaned

    @field_validator("title", "level", "target_role")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        skills = [skill.strip() for skill in value if skill and skill.strip()]
        return skills or None


class CandidateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    title: str | None = Field(default=None, max_length=255)
    level: str | None = Field(default=None, max_length=100)
    avatar_url: str | None = Field(default=None, max_length=512)
    target_role: str | None = Field(default=None, max_length=255)
    years_of_experience: int | None = Field(default=None, ge=0, le=80)
    skills: list[str] | None = None
    score: float | None = Field(default=None, ge=0, le=100)
    recommendation: Recommendation | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr | None) -> str | None:
        if value is None:
            return None
        return str(value).strip().lower()

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name cannot be empty")
        return cleaned

    @field_validator("title", "level", "target_role")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        skills = [skill.strip() for skill in value if skill and skill.strip()]
        return skills or None


class CandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    name: str
    email: EmailStr
    title: str | None
    level: str | None
    avatar_url: str | None
    target_role: str | None
    years_of_experience: int | None
    skills: list[Any] | None
    score: float | None
    recommendation: Recommendation | None
    created_at: datetime
    updated_at: datetime
