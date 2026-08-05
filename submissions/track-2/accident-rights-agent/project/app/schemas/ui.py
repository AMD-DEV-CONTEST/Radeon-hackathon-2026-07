"""Strict UI/service contracts without duplicating business-agent schemas."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictUIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PartyRole(str, Enum):
    INSURED_DRIVER = "insured_driver"
    VEHICLE_OWNER = "vehicle_owner"
    CLAIMS_HANDLER = "claims_handler"
    LEGAL_REVIEWER = "legal_reviewer"
    OTHER = "other"


class CaseMetadata(StrictUIModel):
    case_id: str
    accident_time: datetime | None = None
    location: str = ""
    jurisdiction: str = "CN"
    party_role: PartyRole = PartyRole.INSURED_DRIVER
    manual_delivery_date: date | None = None
    created_at: datetime
    updated_at: datetime


class UploadedSource(StrictUIModel):
    source_id: str
    original_name: str
    kind: str
    role: str
    media_type: str
    size_bytes: int = Field(ge=0)
    sha256: str
    processing_status: str
    quality_issues: list[str] = Field(default_factory=list)


class CaseSummary(StrictUIModel):
    metadata: CaseMetadata
    source_count: int = Field(ge=0)
    fact_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    latest_thread_id: str | None = None
    latest_workflow_status: str | None = None


class WorkflowMode(str, Enum):
    MOCK = "mock"
    LOCAL_VLLM = "local_vllm"


class WorkflowControl(StrictUIModel):
    case_id: str
    thread_id: str
    mode: WorkflowMode
    stop_requested: bool = False
    recoverable: bool = False
    current_node: str = "pending"
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    started_at: datetime
    updated_at: datetime


class ReportArtifact(StrictUIModel):
    case_id: str
    version: int = Field(ge=1)
    generated_at: datetime
    markdown_path: Path
    html_path: Path
    audit_event_id: str

    @field_validator("markdown_path", "html_path")
    @classmethod
    def path_must_be_absolute(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("Report artifact paths must be absolute.")
        return value


class DoctorCheck(StrictUIModel):
    name: str
    status: str
    detail: str
    blocking: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
