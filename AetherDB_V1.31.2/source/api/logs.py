"""Read-only diagnostic log API."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.dependencies.auth import require_admin
from services.logger import get_log_stats, read_logs, redact_sensitive_text


router = APIRouter(
    prefix="/api/logs",
    tags=["logs"],
    dependencies=[Depends(require_admin)],
)


LogType = Literal["app", "error", "access"]


@router.get("")
def get_logs(
    log_type: Annotated[LogType, Query()] = "app",
    lines: Annotated[int, Query(ge=1, le=2000)] = 200,
    level: Annotated[str | None, Query(max_length=16)] = None,
    keyword: Annotated[str | None, Query(max_length=120)] = None,
):
    """Return bounded, redacted log lines for local troubleshooting."""
    safe_lines = [
        redact_sensitive_text(line.rstrip("\n\r"))
        for line in read_logs(
            log_type=log_type,
            lines=lines,
            level=level,
            keyword=keyword,
        )
    ]
    return {
        "log_type": log_type,
        "lines": safe_lines,
        "line_count": len(safe_lines),
        "max_lines": lines,
    }


@router.get("/stats")
def get_logs_stats():
    """Return non-sensitive log file metadata."""
    return {"items": get_log_stats()}
