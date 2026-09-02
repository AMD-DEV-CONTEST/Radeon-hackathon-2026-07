"""Cleanup jobs for Stage E — purge expired resources on a schedule.

Covers:
- Expired smoke‑test projects
- Stale temporary uploads
- Old vector indexes
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from app.config import Settings


class CleanupReport:
    """Summary of a single cleanup pass."""

    __slots__ = ("projects_removed", "temp_files_removed", "indexes_removed", "errors")

    def __init__(self) -> None:
        self.projects_removed = 0
        self.temp_files_removed = 0
        self.indexes_removed = 0
        self.errors: list[str] = []

    @property
    def total(self) -> int:
        return self.projects_removed + self.temp_files_removed + self.indexes_removed

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


def _age_days(path: Path) -> float:
    """Return file/dir age in days (mtime based)."""
    try:
        stat = path.stat()
        return (time.time() - stat.st_mtime) / 86400.0
    except OSError:
        return 0.0


def _remove_tree_safe(path: Path, report: CleanupReport, label: str) -> None:
    """Remove a directory tree, recording any errors."""
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
    except Exception as exc:
        report.errors.append(f"{label} {path}: {exc}")


def run_cleanup(settings: Settings) -> CleanupReport:
    """Execute one synchronous cleanup pass."""
    report = CleanupReport()

    # 1. Expired smoke‑test projects
    if settings.cleanup_smoke_project_days > 0:
        _cleanup_expired_projects(settings, report)

    # 2. Stale temporary uploads
    if settings.cleanup_temp_upload_days > 0:
        _cleanup_temp_uploads(settings, report)

    # 3. Old vector indexes
    if settings.cleanup_old_index_days > 0:
        _cleanup_old_indexes(settings, report)

    return report


# ---------------------------------------------------------------------------
# Internal cleanup routines
# ---------------------------------------------------------------------------


def _cleanup_expired_projects(settings: Settings, report: CleanupReport) -> None:
    """Remove smoke‑test projects older than retention period."""
    retention = float(settings.cleanup_smoke_project_days)
    project_root = settings.project_root
    if not project_root.is_dir():
        return

    for project_dir in sorted(project_root.iterdir()):
        if not project_dir.is_dir():
            continue
        if not project_dir.name.startswith("smoke-"):
            continue
        if _age_days(project_dir) < retention:
            continue

        # Also remove corresponding output directory
        output_dir = settings.output_root / project_dir.name
        if output_dir.exists():
            _remove_tree_safe(output_dir, report, f"output/{project_dir.name}")

        _remove_tree_safe(project_dir, report, f"project/{project_dir.name}")
        report.projects_removed += 1


def _cleanup_temp_uploads(settings: Settings, report: CleanupReport) -> None:
    """Remove ``.tmp`` and ``.upload`` files older than retention."""
    retention = float(settings.cleanup_temp_upload_days)

    for root_dir in (settings.project_root, settings.output_root):
        if not root_dir.is_dir():
            continue
        for tmp in root_dir.rglob("*.tmp"):
            if _age_days(tmp) >= retention:
                tmp.unlink(missing_ok=True)
                report.temp_files_removed += 1


def _cleanup_old_indexes(settings: Settings, report: CleanupReport) -> None:
    """Remove vector‑index directories older than retention."""
    retention = float(settings.cleanup_old_index_days)

    vector_root = settings.vector_db_root
    if not vector_root.is_dir():
        return

    for index_dir in sorted(vector_root.iterdir()):
        if not index_dir.is_dir():
            continue
        if _age_days(index_dir) >= retention:
            _remove_tree_safe(index_dir, report, f"index/{index_dir.name}")
            report.indexes_removed += 1
