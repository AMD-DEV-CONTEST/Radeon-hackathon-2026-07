"""Data models for file manifest and parsed documents (Phase A)."""

import hashlib
from pathlib import Path
from pydantic import BaseModel, Field


class SourceFile(BaseModel):
    """Metadata record for a single source file."""

    relative_path: str
    format: str = Field(description="md|txt|pdf|docx|xlsx|unsupported")
    sha256: str | None = Field(default=None, description="Hex-encoded SHA-256 digest when safe to read")
    size_bytes: int | None = Field(default=None, ge=0, description="File size in bytes when available")
    modified_time: float | None = Field(default=None, description="POSIX timestamp when available")
    parse_status: str = Field(default="pending", description="pending|success|failed|unsupported")
    error_message: str | None = Field(default=None, description="Error detail when failed")


class ContentChunk(BaseModel):
    """A parsed content segment with citation-level location metadata."""

    content: str
    relative_path: str
    chunk_index: int = Field(ge=0)

    # Common line tracking
    line_start: int | None = None
    line_end: int | None = None

    # PDF specific
    page_number: int | None = None

    # DOCX specific
    heading_path: str | None = None
    paragraph_index: int | None = None

    # XLSX specific
    sheet_name: str | None = None
    header_columns: list[str] | None = None
    cell_range: str | None = None

    # Markdown specific
    section_title: str | None = None
    heading_level: int | None = None


class ParsedDocument(BaseModel):
    """Fully parsed document with structured chunks."""

    relative_path: str
    format: str
    chunks: list[ContentChunk]


class ImportResult(BaseModel):
    """Aggregated result of importing a project's source files."""

    project_id: str
    total_files: int = Field(ge=0)
    success_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    files: list[SourceFile] = Field(default_factory=list)
    parsed: list[ParsedDocument] = Field(default_factory=list)


def compute_sha256(file_path: Path) -> str:
    """Compute the SHA-256 hex digest of a file.

    Args:
        file_path: Absolute or relative path to the file.

    Returns:
        Lowercase hex-encoded SHA-256 digest.

    Raises:
        FileNotFoundError: If `file_path` does not exist.
    """
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def build_source_file(
    full_path: Path,
    relative_path: str,
    fmt: str,
    *,
    sha256: str | None = None,
) -> SourceFile:
    """Build a SourceFile record from a filesystem path.

    Args:
        full_path: Absolute path to the file on disk.
        relative_path: Path relative to project root.
        fmt: Detected format string.
        sha256: Pre-computed digest; computed automatically if None.

    Returns:
        A populated SourceFile instance.
    """
    stat = full_path.stat()
    return SourceFile(
        relative_path=relative_path,
        format=fmt,
        sha256=sha256 if sha256 else compute_sha256(full_path),
        size_bytes=stat.st_size,
        modified_time=stat.st_mtime,
        parse_status="pending" if fmt != "unsupported" else "unsupported",
    )


def build_rejected_source_file(
    full_path: Path,
    relative_path: str,
    fmt: str,
    error_message: str,
) -> SourceFile:
    """Record an unsafe path without opening or hashing its target."""
    try:
        stat = full_path.lstat()
        size_bytes: int | None = stat.st_size
        modified_time: float | None = stat.st_mtime
    except OSError:
        size_bytes = None
        modified_time = None
    return SourceFile(
        relative_path=relative_path,
        format=fmt,
        sha256=None,
        size_bytes=size_bytes,
        modified_time=modified_time,
        parse_status="failed",
        error_message=error_message,
    )
