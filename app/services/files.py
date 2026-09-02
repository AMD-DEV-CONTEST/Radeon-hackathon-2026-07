from __future__ import annotations

import hashlib
import mimetypes
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from app.config import Settings
from app.schemas.models import (
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    EXTENSION_TO_MIME,
    FileValidationError,
    UploadResult,
    ProjectFileEntry,
)
from app.security.paths import ensure_project_path
from app.services.projects import ProjectNotFoundError, project_paths


class UploadValidationError(ValueError):
    def __init__(self, validation: FileValidationError) -> None:
        super().__init__(validation.message)
        self.validation = validation


class UploadConflictError(RuntimeError):
    pass


_DOCUMENT_SUFFIXES = {".md", ".txt", ".pdf", ".docx", ".xlsx"}
_TASK_SUFFIXES = {".csv", ".xlsx"}


# ---------------------------------------------------------------------------
# Stage E — MIME + extension double validation
# ---------------------------------------------------------------------------


def _detect_mime(content: bytes, filename: str) -> str:
    """Detect MIME type from content bytes and filename.

    Uses ``mimetypes`` first, then falls back to magic‑byte inspection.
    Returns a lowercase MIME type string.
    """
    suffix = Path(filename).suffix.lower()
    # Content signatures must win over the filename.  Otherwise a PDF renamed
    # to ``.txt`` would be accepted as text/plain.
    if content.startswith(b"\x25\x50\x44\x46"):
        return "application/pdf"
    if content.startswith(b"PK\x03\x04"):
        # Could be DOCX or XLSX — use extension
        if suffix == ".xlsx":
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if suffix == ".docx":
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return "application/zip"
    try:
        content.decode("utf-8")
        return "text/plain"
    except UnicodeDecodeError:
        pass

    mtype, _ = mimetypes.guess_type(filename)
    if mtype:
        return mtype.lower()

    return "application/octet-stream"


def validate_file(filename: str, content: bytes, settings: Settings) -> None:
    """Stage E upload hardening: size, extension, MIME, and virus scan.

    Raises ``UploadValidationError`` wrapping a ``FileValidationError`` on
    any validation failure.
    """
    name = Path(filename).name
    if not name or name != filename or name in {".", ".."}:
        raise UploadValidationError(
            FileValidationError(
                filename=filename,
                error_code="FILE_EMPTY",
                message="filename must not contain a path",
                user_message="文件名不能包含路径。",
            )
        )

    # 1. Filename length
    if len(name) > settings.max_upload_filename_length:
        raise UploadValidationError(
            FileValidationError(
                filename=name,
                error_code="FILE_NAME_TOO_LONG",
                message=f"Filename exceeds {settings.max_upload_filename_length} characters",
                user_message=f"文件名不能超过 {settings.max_upload_filename_length} 个字符。",
            )
        )

    # 2. Empty file
    if not content:
        raise UploadValidationError(
            FileValidationError(
                filename=name,
                error_code="FILE_EMPTY",
                message="uploaded file is empty",
                user_message="上传文件为空。",
            )
        )

    # 3. Size limit
    max_bytes = settings.max_upload_size_bytes
    if len(content) > max_bytes:
        raise UploadValidationError(
            FileValidationError(
                filename=name,
                error_code="FILE_TOO_LARGE",
                message=f"File size {len(content)} exceeds limit {max_bytes}",
                user_message=f"文件大小超过 {settings.max_upload_size_mb} MB 限制。",
            )
        )

    # 4. Extension validation
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise UploadValidationError(
            FileValidationError(
                filename=name,
                error_code="FILE_EXTENSION_NOT_ALLOWED",
                message=f"Extension '{suffix}' is not allowed",
                user_message=f"不支持的文件类型：{suffix}。",
            )
        )

    # 5. MIME + extension double validation
    detected_mime = _detect_mime(content, name)
    if detected_mime not in ALLOWED_MIME_TYPES:
        raise UploadValidationError(
            FileValidationError(
                filename=name,
                error_code="FILE_MIME_MISMATCH",
                message=f"MIME type '{detected_mime}' is not allowed",
                user_message=f"文件类型 '{detected_mime}' 不在允许列表中。",
            )
        )

    expected_mimes = EXTENSION_TO_MIME.get(suffix, [])
    if expected_mimes and detected_mime not in expected_mimes:
        raise UploadValidationError(
            FileValidationError(
                filename=name,
                error_code="FILE_MIME_MISMATCH",
                message=f"MIME type '{detected_mime}' does not match extension '{suffix}'",
                user_message="文件内容与扩展名不匹配。",
            )
        )

    # 6. Virus scan interface placeholder
    if settings.virus_scan_enabled:
        _run_virus_scan(name, content, settings)


def _run_virus_scan(filename: str, content: bytes, settings: Settings) -> None:
    """Virus scan placeholder — invokes the configured command.

    Currently a no‑op when ``virus_scan_enabled=False`` (the default).
    """
    try:
        result = subprocess.run(
            [*settings.virus_scan_command, filename],
            input=content,
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise UploadValidationError(
                FileValidationError(
                    filename=filename,
                    error_code="FILE_VIRUS_DETECTED",
                    message=f"Virus scan returned {result.returncode}",
                    user_message="文件病毒扫描未通过。",
                )
            )
    except subprocess.TimeoutExpired:
        raise UploadValidationError(
            FileValidationError(
                filename=filename,
                error_code="FILE_VIRUS_DETECTED",
                message="Virus scan timed out",
                user_message="文件病毒扫描超时。",
            )
        )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def save_project_upload(
    settings: Settings, project_id: str, filename: str, content: bytes, *, task_file: bool
) -> tuple[str, UploadResult]:
    """Stage E save with full validation. Returns (relative_path, UploadResult)."""
    name = Path(filename).name
    if not name or name != filename or name in {".", ".."}:
        raise UploadValidationError(
            FileValidationError(
                filename=filename,
                error_code="FILE_EMPTY",
                message="filename must not contain a path",
                user_message="文件名不能包含路径。",
            )
        )
    suffix = Path(name).suffix.lower()
    allowed = _TASK_SUFFIXES if task_file else _DOCUMENT_SUFFIXES
    if suffix not in allowed:
        raise UploadValidationError(
            FileValidationError(
                filename=name,
                error_code="FILE_EXTENSION_NOT_ALLOWED",
                message="unsupported file type",
                user_message="不支持的文件类型。",
            )
        )

    # Full validation
    validate_file(filename, content, settings)

    paths = project_paths(settings.project_root, settings.output_root, project_id)
    if not paths["project"].is_dir():
        raise ProjectNotFoundError(project_id)
    target_name = f"tasks{suffix}" if task_file else name
    target = ensure_project_path(settings.project_root, project_id, "source", target_name)
    if target.exists():
        raise UploadConflictError(f"file already exists: {target_name}")
    target.write_bytes(content)

    sha256 = hashlib.sha256(content).hexdigest()
    detected_mime = _detect_mime(content, name)

    upload_result = UploadResult(
        relative_path=f"source/{target_name}",
        size_bytes=len(content),
        sha256=sha256,
        mime_detected=detected_mime,
        extension_matched=True,
        virus_scan_status="passed" if settings.virus_scan_enabled else "skipped",
    )
    return f"source/{target_name}", upload_result


def list_project_files(settings: Settings, project_id: str) -> list[ProjectFileEntry]:
    """Return source-file metadata through the controlled backend boundary.

    The browser never scans the project directory.  Index state is reported
    only when Stage G has persisted a current document-version record.
    """
    paths = project_paths(settings.project_root, settings.output_root, project_id)
    if not paths["project"].is_dir():
        raise ProjectNotFoundError(project_id)

    versions = _current_document_versions(settings, project_id)
    records: list[ProjectFileEntry] = []
    source_root = paths["source"]
    if not source_root.is_dir():
        return records
    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        relative_to_source = path.relative_to(source_root).as_posix()
        relative_path = f"source/{relative_to_source}"
        version = versions.get(relative_path)
        stat = path.stat()
        records.append(
            ProjectFileEntry(
                relative_path=relative_path,
                filename=path.name,
                size_bytes=stat.st_size,
                updated_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                sha256=version.get("sha256") if version else None,
                parse_version=version.get("parse_version") if version else None,
                index_version=version.get("index_version") if version else None,
                processing_status="indexed" if version and version["index_version"] > 0 else "uploaded",
                is_task_file=relative_to_source in {"tasks.csv", "tasks.xlsx"},
            )
        )
    return records


def _current_document_versions(settings: Settings, project_id: str) -> dict[str, dict[str, object]]:
    """Read persisted version records when the optional project DB exists."""
    sqlite_root = settings.sqlite_path if settings.sqlite_path.is_dir() else settings.sqlite_path.parent
    database = sqlite_root / "projects" / project_id / "tasks.db"
    if not database.is_file():
        return {}
    try:
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                "SELECT relative_path, sha256, parse_version, index_version "
                "FROM document_version WHERE project_id = ? AND is_current = 1",
                (project_id,),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.OperationalError:
        return {}
    return {row["relative_path"]: dict(row) for row in rows}
