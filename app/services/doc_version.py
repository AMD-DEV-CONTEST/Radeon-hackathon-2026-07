"""Document Version Management & Incremental Index Tracker (Stage G).

Tracks per-file version metadata:
- SHA-256 checksum (computed by manifest)
- parse_version : incremented on re-parse
- index_version : incremented on re-index
- replacement chain via `replaced_by`
- Full change log (document_change_log table)

Incremental indexing strategy:
1. Compare current SHA-256 with last known version.
2. Only re-parse and re-index files whose hash changed.
3. Track affected chunks for targeted cache invalidation.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class DocVersion(BaseModel):
    """A record of a single version of a document in a project."""
    id: int | None = None
    project_id: str = ""
    relative_path: str = ""
    sha256: str = ""
    size_bytes: int = 0
    parse_version: int = 1
    index_version: int = 1
    replaced_by: str | None = None
    replaced_reason: str = ""
    file_modified_at: str = ""
    first_seen_at: str = ""
    last_seen_at: str = ""
    is_current: bool = True


class DocChangeLog(BaseModel):
    """A record of a detected change to a document."""
    id: int | None = None
    project_id: str = ""
    relative_path: str = ""
    change_type: str = "modified"
    old_sha256: str = ""
    new_sha256: str = ""
    old_parse_version: int = 0
    new_parse_version: int = 0
    old_index_version: int = 0
    new_index_version: int = 0
    affected_chunks: str = "[]"
    changed_at: str = ""


class ChangeImpact(BaseModel):
    """An impact record linking a doc change to an affected entity."""
    id: int | None = None
    project_id: str = ""
    relative_path: str = ""
    change_log_id: int = 0
    affected_entity_type: str = "task"
    affected_entity_id: str = ""
    impact_reason: str = ""
    severity: str = "medium"
    created_at: str = ""


# ---------------------------------------------------------------------------
# File-change detection
# ---------------------------------------------------------------------------

@dataclass
class FileChangeDiff:
    """Diff between current filesystem state and last-known version.

    Returns three buckets of file paths.
    """
    new_files: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    unchanged_files: list[str] = field(default_factory=list)


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA-256 of a file; returns empty string on failure."""
    import hashlib

    try:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return ""


def detect_file_changes(
    project_root: Path,
    file_paths: list[str],
    conn_or_versions: sqlite3.Connection | dict[str, DocVersion],
    *,
    project_id: str | None = None,
) -> FileChangeDiff:
    """Compare current SHA-256 values against stored versions.

    Returns a :class:`FileChangeDiff` categorising files as
    new / modified / deleted / unchanged.
    """
    # Resolve stored state
    if isinstance(conn_or_versions, sqlite3.Connection):
        stored: dict[str, DocVersion] = _load_current_versions(conn_or_versions, project_id)
    else:
        stored = conn_or_versions  # dict[str, DocVersion]

    diff = FileChangeDiff()
    root = project_root.resolve()
    for rel_path in file_paths:
        candidate = (root / rel_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ValueError("file path escapes project root") from error
        abs_path = candidate
        exists = abs_path.exists()
        current_hash = compute_file_sha256(abs_path) if exists else ""
        stored_entry = stored.get(rel_path)

        if not exists and stored_entry:
            diff.deleted_files.append(rel_path)
        elif exists and stored_entry is None:
            diff.new_files.append(rel_path)
        elif exists and stored_entry and current_hash != stored_entry.sha256:
            diff.modified_files.append(rel_path)
        elif exists and stored_entry:
            diff.unchanged_files.append(rel_path)
        elif exists and stored_entry is None:
            diff.new_files.append(rel_path)

    return diff


def _load_current_versions(
    conn: sqlite3.Connection, project_id: str | None = None
) -> dict[str, DocVersion]:
    """Load current document versions from db into a dict keyed by relative_path."""
    if project_id is None:
        cursor = conn.execute("SELECT * FROM document_version WHERE is_current = 1")
    else:
        cursor = conn.execute(
            "SELECT * FROM document_version WHERE is_current = 1 AND project_id = ?",
            (project_id,),
        )
    rows = cursor.fetchall()
    result: dict[str, DocVersion] = {}
    for row in rows:
        dv = _row_to_doc_version(row)
        result[dv.relative_path] = dv
    return result


# ---------------------------------------------------------------------------
# Version management
# ---------------------------------------------------------------------------

def record_file_version(
    conn: sqlite3.Connection,
    project_id: str,
    relative_path: str,
    sha256: str,
    size_bytes: int = 0,
    file_modified_at: str = "",
) -> DocVersion:
    """Insert or bump the version of a file.

    If an existing record matches the same SHA-256, return it unchanged.
    Otherwise, insert a new version and mark the old one replaced.
    """
    now = datetime.now().isoformat(timespec="seconds")

    cursor = conn.execute(
        "SELECT * FROM document_version WHERE project_id = ? AND relative_path = ? AND is_current = 1",
        (project_id, relative_path),
    )
    row = cursor.fetchone()

    if row is None:
        # New file
        dv = DocVersion(
            project_id=project_id,
            relative_path=relative_path,
            sha256=sha256,
            size_bytes=size_bytes,
            parse_version=1,
            index_version=1,
            file_modified_at=file_modified_at,
            first_seen_at=now,
            last_seen_at=now,
            is_current=True,
        )
        _insert_version(conn, dv)
        return dv

    existing = _row_to_doc_version(row)
    if existing.sha256 == sha256:
        # Same content – update last_seen
        conn.execute(
            "UPDATE document_version SET last_seen_at = ?, size_bytes = COALESCE(NULLIF(?,''), '0') WHERE id = ?",
            (now, str(size_bytes) if size_bytes else "0", existing.id),
        )
        conn.commit()
        existing.last_seen_at = now
        return existing

    # Content changed – create replacement record
    new_version_id = str(uuid.uuid4().hex[:12])
    new_pv = existing.parse_version + 1
    new_iv = existing.index_version + 1

    # Mark old as replaced
    conn.execute(
        "UPDATE document_version SET is_current = 0, replaced_by = ? WHERE id = ?",
        (new_version_id, existing.id),
    )

    dv = DocVersion(
        project_id=project_id,
        relative_path=relative_path,
        sha256=sha256,
        size_bytes=size_bytes,
        parse_version=new_pv,
        index_version=new_iv,
        file_modified_at=file_modified_at,
        first_seen_at=existing.first_seen_at,
        last_seen_at=now,
        is_current=True,
    )
    _insert_version(conn, dv)

    # Log change
    change_log = DocChangeLog(
        project_id=project_id,
        relative_path=relative_path,
        change_type="modified",
        old_sha256=existing.sha256,
        new_sha256=sha256,
        old_parse_version=existing.parse_version,
        new_parse_version=new_pv,
        old_index_version=existing.index_version,
        new_index_version=new_iv,
        affected_chunks="[]",
        changed_at=now,
    )
    _insert_change_log(conn, change_log)

    return dv


def mark_file_deleted(conn: sqlite3.Connection, project_id: str, relative_path: str) -> None:
    """Mark a file as deleted (version still retained for audit)."""
    conn.execute(
        "UPDATE document_version SET is_current = 0 WHERE project_id = ? AND relative_path = ? AND is_current = 1",
        (project_id, relative_path),
    )
    now = datetime.now().isoformat(timespec="seconds")
    change_log = DocChangeLog(
        project_id=project_id,
        relative_path=relative_path,
        change_type="deleted",
        changed_at=now,
    )
    _insert_change_log(conn, change_log)
    conn.commit()


# ---------------------------------------------------------------------------
# Change log & impact
# ---------------------------------------------------------------------------

def record_change_impact(
    conn: sqlite3.Connection,
    project_id: str,
    relative_path: str,
    change_log_id: int,
    affected_entity_type: str,
    affected_entity_id: str,
    impact_reason: str,
    severity: str = "medium",
) -> ChangeImpact:
    """Record a change impact relationship."""
    impact = ChangeImpact(
        project_id=project_id,
        relative_path=relative_path,
        change_log_id=change_log_id,
        affected_entity_type=affected_entity_type,
        affected_entity_id=affected_entity_id,
        impact_reason=impact_reason,
        severity=severity,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    conn.execute(
        """INSERT INTO change_impact
           (project_id, relative_path, change_log_id, affected_entity_type,
            affected_entity_id, impact_reason, severity, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            impact.project_id, impact.relative_path, impact.change_log_id,
            impact.affected_entity_type, impact.affected_entity_id,
            impact.impact_reason, impact.severity, impact.created_at,
        ),
    )
    conn.commit()
    return impact


def get_affected_entities(
    conn: sqlite3.Connection,
    project_id: str,
    relative_paths: list[str],
) -> list[ChangeImpact]:
    """Return all impact records for specified doc paths in a project."""
    placeholders = ",".join("?" * len(relative_paths))
    cursor = conn.execute(
        f"SELECT * FROM change_impact WHERE project_id = ? AND relative_path IN ({placeholders})",
        (project_id, *relative_paths),
    )
    rows = cursor.fetchall()
    impacts: list[ChangeImpact] = []
    for row in rows:
        impacts.append(_row_to_change_impact(row))
    return impacts


def get_change_logs(
    conn: sqlite3.Connection,
    project_id: str,
    limit: int = 50,
) -> list[DocChangeLog]:
    """Return recent change logs for a project."""
    cursor = conn.execute(
        "SELECT * FROM document_change_log WHERE project_id = ? ORDER BY changed_at DESC LIMIT ?",
        (project_id, limit),
    )
    logs: list[DocChangeLog] = []
    for row in cursor.fetchall():
        logs.append(_row_to_change_log(row))
    return logs


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _insert_version(conn: sqlite3.Connection, dv: DocVersion) -> None:
    cursor = conn.execute(
        "INSERT INTO document_version"
        " (project_id, relative_path, sha256, size_bytes,"
        " parse_version, index_version, replaced_by, replaced_reason,"
        " file_modified_at, first_seen_at, last_seen_at, is_current)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            dv.project_id, dv.relative_path, dv.sha256, dv.size_bytes,
            dv.parse_version, dv.index_version, dv.replaced_by or "", dv.replaced_reason,
            dv.file_modified_at, dv.first_seen_at, dv.last_seen_at, int(dv.is_current),
        ),
    )
    dv.id = cursor.lastrowid
    conn.commit()


def _insert_change_log(conn: sqlite3.Connection, cl: DocChangeLog) -> None:
    conn.execute(
        """INSERT INTO document_change_log
           (project_id, relative_path, change_type, old_sha256, new_sha256,
            old_parse_version, new_parse_version, old_index_version, new_index_version,
            affected_chunks, changed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            cl.project_id, cl.relative_path, cl.change_type,
            cl.old_sha256, cl.new_sha256,
            cl.old_parse_version, cl.new_parse_version,
            cl.old_index_version, cl.new_index_version,
            cl.affected_chunks, cl.changed_at,
        ),
    )
    conn.commit()


def _row_to_doc_version(row: tuple) -> DocVersion:
    cols = [
        "id", "project_id", "relative_path", "sha256", "size_bytes",
        "parse_version", "index_version", "replaced_by", "replaced_reason",
        "file_modified_at", "first_seen_at", "last_seen_at", "is_current",
    ]
    d = dict(zip(cols, row))
    d["is_current"] = bool(d.get("is_current", 0))
    return DocVersion(**d)


def _row_to_change_log(row: tuple) -> DocChangeLog:
    cols = [
        "id", "project_id", "relative_path", "change_type",
        "old_sha256", "new_sha256", "old_parse_version", "new_parse_version",
        "old_index_version", "new_index_version", "affected_chunks", "changed_at",
    ]
    d = dict(zip(cols, row))
    return DocChangeLog(**d)


def _row_to_change_impact(row: tuple) -> ChangeImpact:
    cols = [
        "id", "project_id", "relative_path", "change_log_id",
        "affected_entity_type", "affected_entity_id",
        "impact_reason", "severity", "created_at",
    ]
    d = dict(zip(cols, row))
    return ChangeImpact(**d)


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Ensure all Stage G DDL is applied."""
    from app.schemas.doc_version_sql import DOC_VERSION_DDL

    conn.executescript(DOC_VERSION_DDL)
    conn.commit()


def initialise_project_versions(
    conn: sqlite3.Connection,
    project_id: str,
    root: Path,
    file_paths: list[str],
) -> dict[str, DocVersion]:
    """First-run initialisation: record versions for all known files.

    Returns a dict of relative_path -> DocVersion.
    """
    result: dict[str, DocVersion] = {}
    for rp in file_paths:
        fp = root / rp
        if not fp.exists():
            continue
        sha = compute_file_sha256(fp)
        mtime = datetime.fromtimestamp(fp.stat().st_mtime).isoformat(timespec="seconds")
        dv = record_file_version(
            conn, project_id, rp, sha,
            size_bytes=fp.stat().st_size,
            file_modified_at=mtime,
        )
        result[rp] = dv
    return result
