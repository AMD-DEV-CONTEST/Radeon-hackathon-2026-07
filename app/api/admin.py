"""Stage J — Admin API: backup, restore, log rotation, stress test.

Administrative endpoints for production management tasks.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import Settings
from app.schemas.models import (
    BackupCreateRequest,
    BackupEntry,
    BackupRestoreRequest,
    LogRotationResult,
    StressTestConfigModel,
)
from app.services.backup import BackupService, get_backup
from app.services.log_rotation import LogRotationService, get_log_rotation
from app.services.stress_test import StressConfig, StressTestRunner
from app.security.permissions import require_system_admin

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_system_admin)]
)


def _get_backup(request: Request) -> BackupService:
    return get_backup(request.app.state.settings)


def _get_log_rotation(request: Request) -> LogRotationService:
    return get_log_rotation(request.app.state.settings)


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


@router.post("/backup")
async def create_backup(
    body: BackupCreateRequest,
    backup: Annotated[BackupService, Depends(_get_backup)],
) -> dict:
    """Create an on-demand full backup."""
    try:
        manifest = backup.create_backup(label=body.label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return manifest


@router.get("/backup", response_model=list[BackupEntry])
async def list_backups(
    backup: Annotated[BackupService, Depends(_get_backup)],
) -> list[BackupEntry]:
    """List all available backups."""
    listings = backup.list_backups()
    return [
        BackupEntry(
            backup_dir=b.get("backup_dir", ""),
            name=b.get("name", ""),
            timestamp=b.get("timestamp", ""),
            label=b.get("label", ""),
            total_size_bytes=b.get("total_size_bytes", 0),
            file_count=len(b.get("files", [])),
            status=b.get("status", "unknown"),
        )
        for b in listings
    ]


@router.post("/backup/restore")
async def restore_backup(
    body: BackupRestoreRequest,
    backup: Annotated[BackupService, Depends(_get_backup)],
) -> dict:
    """Restore from a backup directory."""
    try:
        result = backup.restore(body.backup_dir, dry_run=body.dry_run)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/backup/cleanup")
async def cleanup_backups(
    backup: Annotated[BackupService, Depends(_get_backup)],
) -> dict:
    """Remove backups older than the retention period."""
    removed = backup.cleanup_old_backups()
    return {"removed": removed}


# ---------------------------------------------------------------------------
# Log Rotation
# ---------------------------------------------------------------------------


@router.post("/logs/rotate", response_model=LogRotationResult)
async def rotate_logs(
    rotation: Annotated[LogRotationService, Depends(_get_log_rotation)],
    log_file: str = "app.log",
) -> LogRotationResult:
    """Rotate a log file if it exceeds the size threshold."""
    try:
        result = rotation.rotate(log_file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/logs/rotate-all")
async def rotate_all_logs(
    rotation: Annotated[LogRotationService, Depends(_get_log_rotation)],
) -> dict:
    """Rotate all log files."""
    results = rotation.rotate_all()
    rotated = sum(1 for r in results if r.get("rotated"))
    return {"total": len(results), "rotated": rotated, "details": results}


@router.post("/logs/cleanup")
async def cleanup_logs(
    rotation: Annotated[LogRotationService, Depends(_get_log_rotation)],
) -> dict:
    """Remove old rotated logs beyond retention."""
    removed = rotation.cleanup_old_logs()
    return {"removed": removed}


# ---------------------------------------------------------------------------
# Stress Test
# ---------------------------------------------------------------------------


@router.post("/stress-test")
async def run_stress_test(
    config: StressTestConfigModel,
) -> dict:
    """Run a stress test with the given configuration.

    Uses mock handlers for safety — real handlers can be injected as needed.
    """
    sc = StressConfig(
        large_file_count=config.large_file_count,
        large_file_size_mb=config.large_file_size_mb,
        batch_file_count=config.batch_file_count,
        batch_file_size_kb=config.batch_file_size_kb,
        long_context_prompt_tokens=config.long_context_prompt_tokens,
        long_context_requests=config.long_context_requests,
        multi_project_count=config.multi_project_count,
        multi_project_requests_per_project=config.multi_project_requests_per_project,
    )

    async def mock_llm(**kwargs: object) -> str:
        await asyncio.sleep(0.1)
        return "Mock response for stress test"

    async def mock_embedding(**kwargs: object) -> list[list[float]]:
        await asyncio.sleep(0.05)
        return [[0.1] * 384]

    async def mock_import(**kwargs: object) -> dict:
        await asyncio.sleep(0.2)
        return {"status": "ok"}

    runner = StressTestRunner(
        sc, llm_call=mock_llm, embedding_call=mock_embedding, file_import=mock_import
    )

    report = await runner.run_all()

    return {
        "overall_status": report.overall_status,
        "duration_seconds": report.duration_seconds,
        "total_requests": report.total_requests,
        "total_successful": report.total_successful,
        "phases": [
            {
                "phase": r.phase,
                "requests": r.total_requests,
                "successful": r.successful,
                "failed": r.failed,
                "avg_latency_ms": r.avg_latency_ms,
                "p95_latency_ms": r.p95_latency_ms,
                "throughput_req_per_sec": r.throughput_requests_per_sec,
                "errors": r.errors[:10],
            }
            for r in report.results
        ],
    }
