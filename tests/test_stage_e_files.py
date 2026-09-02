"""Stage E — File upload hardening tests (size limits, MIME validation, virus scan)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas.models import ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES
from app.services.files import validate_file, UploadValidationError


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path / "projects",
        output_root=tmp_path / "outputs",
        vector_db_root=tmp_path / "vectors",
        sqlite_path=tmp_path / "sqlite" / "projectpack.db",
        log_root=tmp_path / "logs",
    )


def _setup_project(client: TestClient) -> None:
    assert client.post(
        "/api/projects", json={"project_id": "demo-project", "name": "Demo"}
    ).status_code == 201


# ── Extension whitelist ─────────────────────────────────────────────────────


def test_allowed_extensions_are_defined() -> None:
    """ALLOWED_EXTENSIONS covers the expected document types."""
    assert ".md" in ALLOWED_EXTENSIONS
    assert ".txt" in ALLOWED_EXTENSIONS
    assert ".pdf" in ALLOWED_EXTENSIONS
    assert ".docx" in ALLOWED_EXTENSIONS
    assert ".xlsx" in ALLOWED_EXTENSIONS
    assert ".csv" in ALLOWED_EXTENSIONS


def test_disallowed_extension_blocked_in_api(tmp_path: Path) -> None:
    """Upload with .exe extension returns 422 error."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        _setup_project(client)
        resp = client.post(
            "/api/projects/demo-project/files",
            files={"file": ("malware.exe", b"bad content", "application/octet-stream")},
        )
        assert resp.status_code == 422


# ── Size limits ─────────────────────────────────────────────────────────────


def test_file_exceeding_max_size_blocked(tmp_path: Path) -> None:
    """File larger than max_upload_size_mb returns 422."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        _setup_project(client)
        # Create content > 50MB by using a small max
        settings_small = Settings(
            project_root=tmp_path / "projects",
            output_root=tmp_path / "outputs",
            vector_db_root=tmp_path / "vectors",
            sqlite_path=tmp_path / "sqlite" / "projectpack.db",
            log_root=tmp_path / "logs",
            max_upload_size_mb=1,
        )
        app_small = create_app(settings_small)
        with TestClient(app_small) as small_client:
            small_client.post(
                "/api/projects", json={"project_id": "demo-project", "name": "Demo"}
            ).status_code == 201

            big_content = b"x" * (2 * 1024 * 1024)  # 2 MB
            resp = small_client.post(
                "/api/projects/demo-project/files",
                files={"file": ("big.md", big_content, "text/markdown")},
            )
            assert resp.status_code == 422
            detail = resp.json().get("detail", {})
            assert isinstance(detail, dict)
            assert detail.get("error_code") == "FILE_TOO_LARGE"


# ── Empty file ──────────────────────────────────────────────────────────────


def test_empty_file_blocked(tmp_path: Path) -> None:
    """Empty file upload returns 422."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        _setup_project(client)
        resp = client.post(
            "/api/projects/demo-project/files",
            files={"file": ("empty.md", b"", "text/markdown")},
        )
        assert resp.status_code == 422


# ── MIME validation ─────────────────────────────────────────────────────────


def test_validate_file_rejects_extension_content_mismatch(tmp_path: Path) -> None:
    """PDF magic bytes with .txt extension should be flagged."""
    s = _settings(tmp_path)
    pdf_content = b"%PDF-1.4\nfake pdf"
    with pytest.raises(UploadValidationError) as captured:
        validate_file("report.txt", pdf_content, s)
    assert captured.value.validation.error_code == "FILE_MIME_MISMATCH"


def test_mime_type_validates_content(tmp_path: Path) -> None:
    """A valid .md file with markdown content should pass MIME validation."""
    s = _settings(tmp_path)
    # Should not raise
    validate_file("readme.md", b"# Hello\n\nThis is a test.\n", s)


# ── Virus scan placeholder ──────────────────────────────────────────────────


def test_virus_scan_disabled_by_default(tmp_path: Path) -> None:
    """By default, virus scan is disabled so uploads pass."""
    s = _settings(tmp_path)
    assert s.virus_scan_enabled is False
    # Upload should succeed without virus scan
    validate_file("report.md", b"# Content\n", s)


def test_virus_scan_config_is_customizable() -> None:
    """Virus scan command and enabled flag are configurable."""
    s = Settings(
        project_root=Path("/tmp/projects"),
        output_root=Path("/tmp/outputs"),
        vector_db_root=Path("/tmp/vectors"),
        sqlite_path=Path("/tmp/sqlite/db"),
        log_root=Path("/tmp/logs"),
        virus_scan_enabled=True,
        virus_scan_command=["custom-scanner", "--mode", "fast"],
    )
    assert s.virus_scan_enabled is True
    assert s.virus_scan_command == ["custom-scanner", "--mode", "fast"]


# ── Filename length ─────────────────────────────────────────────────────────


def test_long_filename_blocked(tmp_path: Path) -> None:
    """Filename exceeding max_upload_filename_length returns 422."""
    s = _settings(tmp_path)
    s = s.model_copy(update={"max_upload_filename_length": 100})

    long_name = "a" * 200 + ".md"
    try:
        validate_file(long_name, b"# Content\n", s)
    except UploadValidationError as exc:
        assert exc.validation.error_code == "FILE_NAME_TOO_LONG"
    else:
        raise AssertionError("Expected UploadValidationError")


# ── UploadResult model ──────────────────────────────────────────────────────


def test_upload_result_has_required_fields(tmp_path: Path) -> None:
    """API upload response includes UploadResult fields."""
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        _setup_project(client)
        resp = client.post(
            "/api/projects/demo-project/files",
            files={"file": ("status.md", b"# Status\nDone.\n", "text/markdown")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "relative_path" in data
        assert "size_bytes" in data
        assert "mime_detected" in data
        assert "virus_scan_status" in data
        assert data["virus_scan_status"] == "skipped"
