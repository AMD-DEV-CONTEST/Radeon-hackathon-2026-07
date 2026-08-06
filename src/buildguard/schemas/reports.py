"""Report schemas."""

from pathlib import Path

from pydantic import Field

from buildguard.schemas.common import RecordSchema


class ReportRecord(RecordSchema):
    session_id: str | None = None
    title: str = Field(min_length=1, max_length=500)
    report_type: str = Field(min_length=1, max_length=128)
    output_path: Path
    summary: str = Field(min_length=1, max_length=10_000)
