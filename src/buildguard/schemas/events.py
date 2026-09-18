"""Risk event schemas."""

from pathlib import Path

from pydantic import Field

from buildguard.schemas.common import RecordSchema, Severity


class RiskEvent(RecordSchema):
    session_id: str | None = None
    event_type: str = Field(min_length=1, max_length=128)
    severity: Severity
    description: str = Field(min_length=1, max_length=4000)
    camera_id: str | None = Field(default=None, max_length=128)
    evidence_paths: list[Path] = Field(default_factory=list)
    acknowledged: bool = False
