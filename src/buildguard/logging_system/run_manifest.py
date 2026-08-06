"""Run provenance manifest."""

from datetime import datetime
from pathlib import Path

from pydantic import Field

from buildguard.schemas.common import StrictSchema
from buildguard.utils.time import utc_now


class RunManifest(StrictSchema):
    run_id: str = Field(min_length=1, max_length=128)
    started_at: datetime = Field(default_factory=utc_now)
    project_name: str = Field(min_length=1, max_length=256)
    environment: str = Field(min_length=1, max_length=128)
    workspace_path: Path
    config_snapshot_path: Path
    status: str = "running"

