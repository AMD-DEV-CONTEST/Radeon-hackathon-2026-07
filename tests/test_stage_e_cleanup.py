"""Stage E — Cleanup job tests."""

from pathlib import Path
import time

from app.config import Settings
from app.services.cleanup import (
    CleanupReport,
    run_cleanup,
    _age_days,
    _cleanup_expired_projects,
    _cleanup_temp_uploads,
    _cleanup_old_indexes,
)


def _settings(tmp_path: Path, *, smoke_days: int = 1, temp_days: int = 7, index_days: int = 30) -> Settings:
    return Settings(
        project_root=tmp_path / "projects",
        output_root=tmp_path / "outputs",
        vector_db_root=tmp_path / "vectors",
        sqlite_path=tmp_path / "sqlite" / "projectpack.db",
        log_root=tmp_path / "logs",
        cleanup_smoke_project_days=smoke_days,
        cleanup_temp_upload_days=temp_days,
        cleanup_old_index_days=index_days,
        cleanup_enabled=True,
    )


# ── CleanupReport ──────────────────────────────────────────────────────────


def test_cleanup_report_defaults() -> None:
    """CleanupReport starts with zero counters."""
    report = CleanupReport()
    assert report.projects_removed == 0
    assert report.temp_files_removed == 0
    assert report.indexes_removed == 0
    assert report.total == 0
    assert report.success is True


def test_cleanup_report_with_errors() -> None:
    """CleanupReport.success is False when errors exist."""
    report = CleanupReport()
    report.errors.append("Something went wrong")
    assert report.success is False


# ── Smoke project cleanup ───────────────────────────────────────────────────


def test_cleanup_removes_expired_smoke_projects(tmp_path: Path) -> None:
    """Smoke project older than retention gets removed."""
    settings = _settings(tmp_path, smoke_days=0)  # any age qualifies

    proj_dir = settings.project_root / "smoke-test-001"
    proj_dir.mkdir(parents=True)
    (proj_dir / "source").mkdir()

    out_dir = settings.output_root / "smoke-test-001"
    out_dir.mkdir(parents=True)

    time.sleep(0.01)

    # Call the inner function directly
    report = CleanupReport()
    _cleanup_expired_projects(settings, report)
    assert report.projects_removed == 1, f"projects_removed={report.projects_removed}, errors={report.errors}"
    assert not proj_dir.exists()
    assert not out_dir.exists()


def test_cleanup_respects_retention_period(tmp_path: Path) -> None:
    """Project within retention period is NOT removed."""
    settings = _settings(tmp_path, smoke_days=365)
    proj_dir = settings.project_root / "smoke-test-002"
    proj_dir.mkdir(parents=True)
    (proj_dir / "source").mkdir()

    time.sleep(0.01)

    report = run_cleanup(settings)
    assert report.projects_removed == 0
    assert proj_dir.exists()


def test_cleanup_only_targets_smoke_prefix(tmp_path: Path) -> None:
    """Non-smoke projects are not removed even when expired."""
    settings = _settings(tmp_path, smoke_days=0)
    normal_proj = settings.project_root / "normal-project"
    normal_proj.mkdir(parents=True)
    (normal_proj / "source").mkdir()

    report = run_cleanup(settings)
    assert report.projects_removed == 0
    assert normal_proj.exists()


# ── Temp file cleanup ───────────────────────────────────────────────────────


def test_cleanup_removes_old_tmp_files(tmp_path: Path) -> None:
    """.tmp files older than retention are removed."""
    settings = _settings(tmp_path, temp_days=0)
    tmp_dir = settings.project_root / "some-project" / "source"
    tmp_dir.mkdir(parents=True)
    tmp_file = tmp_dir / "old.tmp"
    tmp_file.write_text("stale data")
    time.sleep(0.01)

    report = CleanupReport()
    _cleanup_temp_uploads(settings, report)
    assert report.temp_files_removed >= 1
    assert not tmp_file.exists()


def test_cleanup_keeps_recent_tmp_files(tmp_path: Path) -> None:
    """Recently created .tmp files are kept."""
    settings = _settings(tmp_path, temp_days=365)
    tmp_dir = settings.project_root / "some-project" / "source"
    tmp_dir.mkdir(parents=True)
    tmp_file = tmp_dir / "recent.tmp"
    tmp_file.write_text("fresh data")
    time.sleep(0.01)

    report = run_cleanup(settings)
    assert report.temp_files_removed == 0
    assert tmp_file.exists()


# ── Vector index cleanup ────────────────────────────────────────────────────


def test_cleanup_removes_old_vector_indexes(tmp_path: Path) -> None:
    """Old vector indexes are removed on cleanup."""
    settings = _settings(tmp_path, index_days=0)
    index_dir = settings.vector_db_root / "old-index"
    index_dir.mkdir(parents=True)
    (index_dir / "data.faiss").write_text("dummy")
    time.sleep(0.01)

    report = CleanupReport()
    _cleanup_old_indexes(settings, report)
    assert report.indexes_removed == 1
    assert not index_dir.exists()


def test_cleanup_keeps_recent_indexes(tmp_path: Path) -> None:
    """Recent vector indexes survive cleanup."""
    settings = _settings(tmp_path, index_days=365)
    index_dir = settings.vector_db_root / "recent-index"
    index_dir.mkdir(parents=True)
    (index_dir / "data.faiss").write_text("fresh")
    time.sleep(0.01)

    report = run_cleanup(settings)
    assert report.indexes_removed == 0
    assert index_dir.exists()


# ── Disabled cleanup ────────────────────────────────────────────────────────


def test_disabled_cleanup_does_nothing(tmp_path: Path) -> None:
    """When cleanup_enabled=False, nothing is removed."""
    settings = _settings(tmp_path, smoke_days=0)
    settings = settings.model_copy(update={"cleanup_enabled": False})

    proj_dir = settings.project_root / "smoke-disable-test"
    proj_dir.mkdir(parents=True)

    report = run_cleanup(settings)
    assert report.projects_removed == 0


# ── Age helper ──────────────────────────────────────────────────────────────


def test_age_days(tmp_path: Path) -> None:
    """_age_days returns an approximate number of days since mtime."""
    f = tmp_path / "test.file"
    f.write_text("content")
    age = _age_days(f)
    assert age >= 0
    assert age < 1.0
