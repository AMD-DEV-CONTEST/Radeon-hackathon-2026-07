from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.files import router as files_router
from app.api.projects import router as projects_router
from app.api.runs import router as runs_router
from app.api.global_runs import router as global_runs_router
from app.api.tasks import router as tasks_router

# Phase H routers
from app.api.auth import router as auth_router, setup_auth
from app.api.members import router as members_router
from app.api.overview import router as overview_router
from app.api.task_board import router as task_board_router
from app.api.risks import router as risks_router
from app.api.reports import router as reports_router
from app.api.comments import router as comments_router
from app.api.notifications import router as notifications_router

# Stage I routers
from app.api.integrations import router as integrations_router
from app.api.automation_tasks import router as automation_tasks_router

# Stage J routers
from app.api.monitor import router as monitor_router
from app.api.admin import router as admin_router

from app.config import Settings
from app.services.cleanup import run_cleanup
from app.services.membership import MembershipService
from app.services.comments import CommentService
from app.services.notifications import NotificationService
from app.services.report_center import ReportCenterService
from app.services.backup import BackupService
from app.services.log_rotation import LogRotationService


async def _cleanup_loop(settings: Settings) -> None:
    """Background task that runs cleanup on a configurable interval (Stage E)."""
    while settings.cleanup_enabled:
        await asyncio.sleep(settings.cleanup_cron_interval_minutes * 60)
        try:
            run_cleanup(settings)
        except Exception:
            pass  # cleanup must never crash the app


async def _auto_backup_loop(settings: Settings) -> None:
    """Background task that creates automatic backups (Stage J)."""
    if not settings.backup_auto_enabled:
        return
    backup_svc = BackupService(settings)
    while True:
        await asyncio.sleep(settings.backup_cron_interval_minutes * 60)
        try:
            backup_svc.create_backup(label="auto")
            backup_svc.cleanup_old_backups()
        except Exception:
            pass


async def _log_rotation_loop(settings: Settings) -> None:
    """Background task that rotates logs periodically (Stage J)."""
    if not settings.log_rotation_enabled:
        return
    rotation_svc = LogRotationService(settings)
    while True:
        await asyncio.sleep(3600)  # check every hour
        try:
            rotation_svc.rotate_all()
            rotation_svc.cleanup_old_logs()
        except Exception:
            pass


def create_app(
    settings: Settings | None = None,
    *,
    model_health_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    runtime_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        for directory in runtime_settings.required_directories():
            directory.mkdir(parents=True, exist_ok=True)
        cleanup_task = asyncio.create_task(_cleanup_loop(runtime_settings))
        backup_task = asyncio.create_task(_auto_backup_loop(runtime_settings))
        rotation_task = asyncio.create_task(_log_rotation_loop(runtime_settings))
        yield
        for t in (cleanup_task, backup_task, rotation_task):
            t.cancel()
        try:
            await asyncio.gather(cleanup_task, backup_task, rotation_task)
        except asyncio.CancelledError:
            pass

    app = FastAPI(title="ProjectPack Office Agent", version="0.1.0", lifespan=lifespan)
    app.state.settings = runtime_settings
    app.state.model_health_transport = model_health_transport
    # If sqlite_path is a directory, append the db filename; otherwise use as-is
    sqlite_path = runtime_settings.sqlite_path
    if sqlite_path.is_dir():
        db_path = str(sqlite_path / "projectpack.db")
    else:
        db_path = str(sqlite_path)
    app.state.db_path = db_path

    # Phase H service initialization
    app.state.auth_service = setup_auth(app.state.db_path)
    app.state.membership_service = MembershipService(app.state.db_path)
    app.state.comment_service = CommentService(app.state.db_path)
    app.state.notification_service = NotificationService(app.state.db_path)
    app.state.report_center_service = ReportCenterService(app.state.db_path)

    # Core routers
    app.include_router(health_router)
    app.include_router(projects_router)
    app.include_router(files_router)
    app.include_router(runs_router)
    app.include_router(global_runs_router)
    app.include_router(tasks_router)

    # Phase H routers
    app.include_router(auth_router)
    app.include_router(members_router)
    app.include_router(overview_router)
    app.include_router(task_board_router)
    app.include_router(risks_router)
    app.include_router(reports_router)
    app.include_router(comments_router)
    app.include_router(notifications_router)

    # Stage I routers
    app.include_router(integrations_router)
    app.include_router(automation_tasks_router)

    # Stage J routers
    app.include_router(monitor_router)
    app.include_router(admin_router)

    return app


app = create_app()
