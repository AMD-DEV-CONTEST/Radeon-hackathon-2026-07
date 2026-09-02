"""Resume Pydantic schemas."""

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.constants import ALLOWED_RESUME_EXTENSIONS, UPLOAD_MAX_SIZE_MB
from models.enums import ResumeStatus


class ResumeCreate(BaseModel):
    candidate_id: UUID
    file_name: str = Field(min_length=1, max_length=255)
    file_path: str = Field(min_length=1, max_length=1024)
    file_type: str | None = Field(default=None, max_length=100)
    file_size: int | None = Field(default=None, ge=1)
    raw_text: str | None = None
    parsed_data: dict[str, Any] | None = None
    status: ResumeStatus = ResumeStatus.UPLOADED

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("file_name cannot be empty")
        extension = Path(cleaned).suffix.lower()
        if extension not in ALLOWED_RESUME_EXTENSIONS:
            allowed = ", ".join(ALLOWED_RESUME_EXTENSIONS)
            raise ValueError(f"Unsupported file type. Allowed: {allowed}")
        return cleaned

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("file_path cannot be empty")
        return cleaned

    @field_validator("file_size")
    @classmethod
    def validate_file_size(cls, value: int | None) -> int | None:
        if value is None:
            return None
        max_bytes = UPLOAD_MAX_SIZE_MB * 1024 * 1024
        if value > max_bytes:
            raise ValueError(f"file_size exceeds {UPLOAD_MAX_SIZE_MB}MB limit")
        return value


class ResumeUpdate(BaseModel):
    file_name: str | None = Field(default=None, min_length=1, max_length=255)
    file_path: str | None = Field(default=None, min_length=1, max_length=1024)
    file_type: str | None = Field(default=None, max_length=100)
    file_size: int | None = Field(default=None, ge=1)
    status: ResumeStatus | None = None
    raw_text: str | None = None
    parsed_data: dict[str, Any] | None = None

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("file_name cannot be empty")
        extension = Path(cleaned).suffix.lower()
        if extension not in ALLOWED_RESUME_EXTENSIONS:
            allowed = ", ".join(ALLOWED_RESUME_EXTENSIONS)
            raise ValueError(f"Unsupported file type. Allowed: {allowed}")
        return cleaned

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("file_path cannot be empty")
        return cleaned

    @field_validator("file_size")
    @classmethod
    def validate_file_size(cls, value: int | None) -> int | None:
        if value is None:
            return None
        max_bytes = UPLOAD_MAX_SIZE_MB * 1024 * 1024
        if value > max_bytes:
            raise ValueError(f"file_size exceeds {UPLOAD_MAX_SIZE_MB}MB limit")
        return value


class ResumeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    candidate_id: UUID
    file_name: str
    file_path: str
    file_type: str | None
    file_size: int | None
    status: ResumeStatus
    raw_text: str | None
    parsed_data: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
