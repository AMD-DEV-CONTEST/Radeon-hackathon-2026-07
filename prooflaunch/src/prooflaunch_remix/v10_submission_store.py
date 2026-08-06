from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Mapping


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RUN_STATUSES = frozenset(
    {
        "queued",
        "running",
        "auditing",
        "repairing",
        "awaiting_release",
        "bundle_ready",
        "blocked",
        "failed",
        "rejected",
        "cancelled",
    }
)
_GENESIS_HASH = "0" * 64
_READ_CHUNK_SIZE = 1024 * 1024


class SubmissionStoreError(RuntimeError):
    """Base class for durable submission-store failures."""


class UnsafePathError(SubmissionStoreError):
    """Raised when an untrusted or escaped filesystem path is observed."""


class IntegrityError(SubmissionStoreError):
    """Raised when persisted bytes or metadata fail an integrity check."""


class ConflictError(SubmissionStoreError):
    """Raised when an immutable identity is reused with different content."""


class LeaseError(SubmissionStoreError):
    """Raised when a worker does not own the live lease it is mutating."""


class IdempotencyConflict(ConflictError):
    """Raised when an idempotency key is reused with a different request body."""


@dataclass(frozen=True)
class ArtifactRecord:
    sha256: str
    byte_length: int
    media_type: str
    relative_path: str
    created_at: str


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    request_sha256: str
    request: Mapping[str, Any]
    status: str
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class EventRecord:
    event_id: int
    run_id: str
    sequence: int
    event_type: str
    payload: Mapping[str, Any]
    occurred_at: str
    previous_hash: str
    event_hash: str


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    run_id: str
    preview_sha256: str
    decision: str
    approver: str
    reason: str
    decided_at: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class MultimodalDeliverableRecord:
    registration_id: str
    run_id: str
    capability_id: str
    artifact_sha256: str
    execution_receipt_sha256: str
    media_type: str
    campaign_id: str
    model_id: str
    model_revision: str
    accelerator: str
    rights_basis: str
    rights_locator: str
    registered_by: str
    registered_at: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class MultimodalDeliverableReviewRecord:
    review_id: str
    registration_id: str
    run_id: str
    decision: str
    reviewer: str
    reason: str
    reviewed_at: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class CapabilityDeliverableRecord:
    registration_id: str
    run_id: str
    capability_id: str
    artifact_role: str
    artifact_sha256: str
    execution_receipt_sha256: str
    media_type: str
    campaign_id: str
    model_id: str
    model_revision: str
    accelerator: str
    rights_basis: str
    rights_locator: str
    registered_by: str
    registered_at: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class CapabilityDeliverableReviewRecord:
    review_id: str
    registration_id: str
    run_id: str
    decision: str
    reviewer: str
    reason: str
    reviewed_at: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    run_id: str
    kind: str
    payload: Mapping[str, Any]
    status: str
    attempts: int
    lease_owner: str | None
    lease_token: str | None
    lease_expires_at: str | None
    result: Mapping[str, Any] | None
    error: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class LearningMemoryRecord:
    memory_id: str
    org_id: str
    project_id: str
    source_run_id: str
    observation_id: str
    memory_sha256: str
    approved_by: str
    reason: str
    approved_at: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class StrategyMemoryResolutionRecord:
    resolution_id: str
    org_id: str
    project_id: str
    source_run_id: str
    base_decision_sha256: str
    channel: str
    winner_memory_id: str
    resolution_sha256: str
    resolved_by: str
    reason: str
    resolved_at: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class MemoryCapsuleImportRecord:
    capsule_id: str
    org_id: str
    project_id: str
    context_sha256: str
    capsule_sha256: str
    status: str
    imported_at: str
    reviewed_by: str | None
    review_reason: str | None
    reviewed_at: str | None
    capsule: Mapping[str, Any]


@dataclass(frozen=True)
class IdempotencyResult:
    disposition: str
    request_sha256: str
    response_code: int | None = None
    response_body: bytes | None = None

    @property
    def is_replay(self) -> bool:
        return self.disposition == "replay"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    current = value or _utc_now()
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return (
        current.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("value must be finite JSON data") from error


def _json_mapping(value: Mapping[str, Any], field_name: str) -> str:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return _canonical_json(dict(value))


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_sha256(value: str, field_name: str = "sha256") -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field_name} contains unsafe characters")
    return value


def _require_nonempty(value: str, field_name: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be a non-empty bounded string")
    if "\x00" in value:
        raise ValueError(f"{field_name} contains a NUL byte")
    return value


def _secure_directory(path: Path) -> Path:
    if not path.is_absolute():
        raise UnsafePathError("store root must be an absolute server-owned path")
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise UnsafePathError("store root must be a real directory, not a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise UnsafePathError("store root changed during initialization")
    path.chmod(0o700)
    return path.resolve(strict=True)


def _safe_relative_path(root: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str) or "\\" in relative_path or "\x00" in relative_path:
        raise UnsafePathError("artifact path is not a safe POSIX relative path")
    parsed = PurePosixPath(relative_path)
    if parsed.is_absolute() or not parsed.parts or any(part in {"", ".", ".."} for part in parsed.parts):
        raise UnsafePathError("artifact path must remain relative to the CAS root")
    candidate = root.joinpath(*parsed.parts)
    current = root
    for part in parsed.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise UnsafePathError("artifact path traverses a symlink")
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError as error:
        raise UnsafePathError("artifact path escaped the CAS root") from error
    return candidate


def _row_to_artifact(row: sqlite3.Row) -> ArtifactRecord:
    return ArtifactRecord(
        sha256=row["sha256"],
        byte_length=row["byte_length"],
        media_type=row["media_type"],
        relative_path=row["relative_path"],
        created_at=row["created_at"],
    )


class ArtifactStore:
    """Server-owned, content-addressed artifact storage.

    PUT accepts a readable byte stream, never a client-supplied filesystem path.
    HEAD returns verified metadata without exposing an absolute server path.
    """

    def __init__(self, owner: "SubmissionStore") -> None:
        self._owner = owner
        self.root = owner.root / "cas"
        self.root.mkdir(mode=0o700, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise UnsafePathError("CAS root must be a real directory")
        self.root.chmod(0o700)

    @staticmethod
    def relative_path_for(sha256: str) -> str:
        digest = _require_sha256(sha256)
        return f"cas/{digest[:2]}/{digest}"

    def _cas_relative_path(self, sha256: str) -> str:
        return self.relative_path_for(sha256).removeprefix("cas/")

    def _path_for(self, relative_path: str) -> Path:
        if not relative_path.startswith("cas/"):
            raise UnsafePathError("artifact metadata does not name the CAS namespace")
        return _safe_relative_path(self.root, relative_path.removeprefix("cas/"))

    @staticmethod
    def _hash_file(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        length = 0
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(_READ_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
                length += len(chunk)
        return digest.hexdigest(), length

    def put(
        self,
        source: BinaryIO,
        *,
        expected_sha256: str,
        media_type: str = "application/octet-stream",
    ) -> ArtifactRecord:
        digest_expected = _require_sha256(expected_sha256, "expected_sha256")
        _require_nonempty(media_type, "media_type", maximum=255)
        if isinstance(source, (str, bytes, bytearray, os.PathLike, Path)) or not callable(
            getattr(source, "read", None)
        ):
            raise TypeError("source must be a readable byte stream, never a client path")

        cas_relative = self._cas_relative_path(digest_expected)
        final_path = _safe_relative_path(self.root, cas_relative)
        final_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if final_path.parent.is_symlink():
            raise UnsafePathError("CAS shard directory cannot be a symlink")
        final_path.parent.chmod(0o700)

        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".put-", suffix=".tmp", dir=final_path.parent
            )
            temporary_path = Path(temporary_name)
            os.fchmod(descriptor, 0o600)
            digest = hashlib.sha256()
            length = 0
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                while True:
                    chunk = source.read(_READ_CHUNK_SIZE)
                    if not chunk:
                        break
                    if not isinstance(chunk, bytes):
                        raise TypeError("artifact streams must yield bytes")
                    handle.write(chunk)
                    digest.update(chunk)
                    length += len(chunk)
                handle.flush()
                os.fsync(handle.fileno())

            observed = digest.hexdigest()
            if observed != digest_expected:
                raise IntegrityError(
                    f"artifact digest mismatch: expected {digest_expected}, observed {observed}"
                )

            try:
                os.link(temporary_path, final_path)
                final_path.chmod(0o600)
            except FileExistsError:
                if final_path.is_symlink() or not final_path.is_file():
                    raise UnsafePathError("existing CAS target is not a regular file")
                existing_hash, existing_length = self._hash_file(final_path)
                if existing_hash != digest_expected or existing_length != length:
                    raise IntegrityError("existing CAS object failed integrity verification")

            relative_path = self.relative_path_for(digest_expected)
            created_at = _iso()
            with self._owner._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM artifacts WHERE sha256 = ?", (digest_expected,)
                ).fetchone()
                if existing is None:
                    connection.execute(
                        """
                        INSERT INTO artifacts(
                            sha256, byte_length, media_type, relative_path, created_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (digest_expected, length, media_type, relative_path, created_at),
                    )
                elif (
                    existing["byte_length"] != length
                    or existing["media_type"] != media_type
                    or existing["relative_path"] != relative_path
                ):
                    raise ConflictError("artifact identity was reused with different metadata")
                connection.commit()
            return self.head(digest_expected)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def head(self, sha256: str) -> ArtifactRecord:
        digest = _require_sha256(sha256)
        with self._owner._connect() as connection:
            row = connection.execute(
                "SELECT * FROM artifacts WHERE sha256 = ?", (digest,)
            ).fetchone()
        if row is None:
            raise KeyError("unknown artifact")
        record = _row_to_artifact(row)
        path = self._path_for(record.relative_path)
        if path.is_symlink() or not path.is_file():
            raise IntegrityError("artifact content is missing or not a regular file")
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode != 0o600:
            raise IntegrityError("artifact content permissions are not 0600")
        observed_hash, observed_length = self._hash_file(path)
        if observed_hash != record.sha256 or observed_length != record.byte_length:
            raise IntegrityError("artifact content no longer matches its HEAD metadata")
        return record

    def resolve_server_path(self, sha256: str) -> Path:
        """Return a verified absolute path for trusted in-process workers only.

        The caller supplies a digest, never a path. ``head`` revalidates the DB
        record, containment, file type, mode, byte length and content hash on
        every resolution before this method exposes the server-owned path.
        """

        record = self.head(sha256)
        path = self._path_for(record.relative_path)
        try:
            path.resolve(strict=True).relative_to(self.root)
        except (FileNotFoundError, ValueError) as error:
            raise UnsafePathError("resolved artifact escaped or disappeared") from error
        if path.is_symlink() or not path.is_file():
            raise UnsafePathError("resolved artifact is not a regular CAS file")
        return path


class SubmissionStore:
    """SQLite/WAL persistence for the Day-1 Agent control plane.

    This module persists state, leases and evidence only. It deliberately does
    not expose HTTP handlers and does not execute Supervisor work.
    """

    def __init__(self, root: Path) -> None:
        if isinstance(root, str):
            root = Path(root)
        if not isinstance(root, Path):
            raise TypeError("root must be a server-owned pathlib.Path")
        self.root = _secure_directory(root)
        self.database_path = self.root / "submission.sqlite3"
        if self.database_path.is_symlink() or (
            self.database_path.exists() and not self.database_path.is_file()
        ):
            raise UnsafePathError("SQLite target must be a regular server-owned file")
        self._initialize_database()
        if self.database_path.is_symlink() or not self.database_path.is_file():
            raise UnsafePathError("SQLite target changed during initialization")
        self.artifacts = ArtifactStore(self)

    def _connect(self) -> sqlite3.Connection:
        if self.database_path.is_symlink() or (
            self.database_path.exists() and not self.database_path.is_file()
        ):
            raise UnsafePathError("SQLite target is no longer a regular file")
        connection = sqlite3.connect(
            self.database_path,
            timeout=5.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    request_sha256 TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    sha256 TEXT PRIMARY KEY,
                    byte_length INTEGER NOT NULL CHECK(byte_length >= 0),
                    media_type TEXT NOT NULL,
                    relative_path TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS artifact_tenants (
                    tenant_id TEXT NOT NULL,
                    artifact_sha256 TEXT NOT NULL REFERENCES artifacts(sha256) ON DELETE RESTRICT,
                    granted_at TEXT NOT NULL,
                    PRIMARY KEY(tenant_id, artifact_sha256)
                );
                CREATE INDEX IF NOT EXISTS artifact_tenants_by_artifact
                    ON artifact_tenants(artifact_sha256, tenant_id);

                CREATE TABLE IF NOT EXISTS run_artifacts (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
                    artifact_sha256 TEXT NOT NULL REFERENCES artifacts(sha256) ON DELETE RESTRICT,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, role)
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
                    preview_sha256 TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('approve', 'reject')),
                    approver TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS approvals_one_per_run
                    ON approvals(run_id);

                CREATE TABLE IF NOT EXISTS multimodal_deliverables (
                    registration_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
                    capability_id TEXT NOT NULL CHECK(capability_id IN ('video_generation','audio_generation')),
                    artifact_sha256 TEXT NOT NULL REFERENCES artifacts(sha256) ON DELETE RESTRICT,
                    execution_receipt_sha256 TEXT NOT NULL REFERENCES artifacts(sha256) ON DELETE RESTRICT,
                    media_type TEXT NOT NULL,
                    campaign_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    model_revision TEXT NOT NULL,
                    accelerator TEXT NOT NULL,
                    rights_basis TEXT NOT NULL,
                    rights_locator TEXT NOT NULL,
                    registered_by TEXT NOT NULL,
                    registered_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(run_id, capability_id)
                );
                CREATE INDEX IF NOT EXISTS multimodal_deliverables_run
                    ON multimodal_deliverables(run_id, capability_id);

                CREATE TABLE IF NOT EXISTS multimodal_deliverable_reviews (
                    review_id TEXT PRIMARY KEY,
                    registration_id TEXT NOT NULL REFERENCES multimodal_deliverables(registration_id) ON DELETE RESTRICT,
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
                    decision TEXT NOT NULL CHECK(decision IN ('pass','reject')),
                    reviewer TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(registration_id)
                );
                CREATE INDEX IF NOT EXISTS multimodal_deliverable_reviews_run
                    ON multimodal_deliverable_reviews(run_id, registration_id);

                CREATE TABLE IF NOT EXISTS capability_deliverables (
                    registration_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
                    capability_id TEXT NOT NULL CHECK(capability_id IN (
                        'data_strategy','content_scheduling','text_generation',
                        'data_analysis','geo_visibility','seo_operations',
                        'employee_agent','advertising'
                    )),
                    artifact_role TEXT NOT NULL,
                    artifact_sha256 TEXT NOT NULL REFERENCES artifacts(sha256) ON DELETE RESTRICT,
                    execution_receipt_sha256 TEXT NOT NULL REFERENCES artifacts(sha256) ON DELETE RESTRICT,
                    media_type TEXT NOT NULL,
                    campaign_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    model_revision TEXT NOT NULL,
                    accelerator TEXT NOT NULL,
                    rights_basis TEXT NOT NULL,
                    rights_locator TEXT NOT NULL,
                    registered_by TEXT NOT NULL,
                    registered_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(run_id, capability_id)
                );
                CREATE INDEX IF NOT EXISTS capability_deliverables_run
                    ON capability_deliverables(run_id, capability_id);

                CREATE TABLE IF NOT EXISTS capability_deliverable_reviews (
                    review_id TEXT PRIMARY KEY,
                    registration_id TEXT NOT NULL REFERENCES capability_deliverables(registration_id) ON DELETE RESTRICT,
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
                    decision TEXT NOT NULL CHECK(decision IN ('pass','reject')),
                    reviewer TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(registration_id)
                );
                CREATE INDEX IF NOT EXISTS capability_deliverable_reviews_run
                    ON capability_deliverable_reviews(run_id, registration_id);

                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('queued','leased','succeeded','failed','cancelled')),
                    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                    lease_owner TEXT,
                    lease_token TEXT,
                    lease_expires_at TEXT,
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_claimable
                    ON jobs(status, lease_expires_at, created_at, job_id);

                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
                    sequence INTEGER NOT NULL CHECK(sequence >= 1),
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    UNIQUE(run_id, sequence),
                    UNIQUE(run_id, event_hash)
                );
                CREATE INDEX IF NOT EXISTS events_after_id ON events(run_id, event_id);

                CREATE TABLE IF NOT EXISTS idempotency_commands (
                    namespace TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending', 'completed')),
                    response_code INTEGER,
                    response_body BLOB,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(namespace, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS learning_memories (
                    memory_id TEXT PRIMARY KEY,
                    org_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    source_run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
                    observation_id TEXT NOT NULL,
                    memory_sha256 TEXT NOT NULL UNIQUE,
                    approved_by TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    approved_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(source_run_id, observation_id)
                );
                CREATE INDEX IF NOT EXISTS learning_memories_scope
                    ON learning_memories(org_id, project_id, approved_at, memory_id);

                CREATE TABLE IF NOT EXISTS strategy_memory_resolutions (
                    resolution_id TEXT PRIMARY KEY,
                    org_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    source_run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE RESTRICT,
                    base_decision_sha256 TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    winner_memory_id TEXT NOT NULL,
                    resolution_sha256 TEXT NOT NULL UNIQUE,
                    resolved_by TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    resolved_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(org_id, project_id, base_decision_sha256, channel)
                );
                CREATE INDEX IF NOT EXISTS strategy_memory_resolutions_scope
                    ON strategy_memory_resolutions(
                        org_id, project_id, resolved_at, resolution_id
                    );

                CREATE TABLE IF NOT EXISTS memory_capsule_imports (
                    capsule_id TEXT PRIMARY KEY,
                    org_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    context_sha256 TEXT NOT NULL,
                    capsule_sha256 TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ('pending_review','approved','rejected')),
                    imported_at TEXT NOT NULL,
                    reviewed_by TEXT,
                    review_reason TEXT,
                    reviewed_at TEXT,
                    capsule_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS memory_capsule_imports_scope
                    ON memory_capsule_imports(org_id, project_id, status, imported_at, capsule_id);
                """
            )
        self.database_path.chmod(0o600)

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            run_id=row["run_id"],
            request_sha256=row["request_sha256"],
            request=json.loads(row["request_json"]),
            status=row["status"],
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> EventRecord:
        return EventRecord(
            event_id=row["event_id"],
            run_id=row["run_id"],
            sequence=row["sequence"],
            event_type=row["event_type"],
            payload=json.loads(row["payload_json"]),
            occurred_at=row["occurred_at"],
            previous_hash=row["previous_hash"],
            event_hash=row["event_hash"],
        )

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            job_id=row["job_id"],
            run_id=row["run_id"],
            kind=row["kind"],
            payload=json.loads(row["payload_json"]),
            status=row["status"],
            attempts=row["attempts"],
            lease_owner=row["lease_owner"],
            lease_token=row["lease_token"],
            lease_expires_at=row["lease_expires_at"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _append_event_tx(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        occurred_at: str | None = None,
    ) -> EventRecord:
        _require_identifier(run_id, "run_id")
        _require_identifier(event_type, "event_type")
        scoped_payload = dict(payload)
        run_row = connection.execute(
            "SELECT request_json FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if run_row is None:
            raise KeyError("unknown run")
        request = json.loads(run_row["request_json"])
        tenant_id = request.get("org_id") if isinstance(request, Mapping) else None
        if tenant_id is not None:
            _require_identifier(tenant_id, "run tenant_id")
            supplied_tenant = scoped_payload.get("tenant_id")
            if supplied_tenant is not None and supplied_tenant != tenant_id:
                raise ConflictError("event tenant_id disagrees with the run tenant")
            scoped_payload["tenant_id"] = tenant_id
        payload_json = _json_mapping(scoped_payload, "event payload")
        previous = connection.execute(
            """
            SELECT sequence, event_hash FROM events
            WHERE run_id = ? ORDER BY sequence DESC LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        sequence = 1 if previous is None else previous["sequence"] + 1
        previous_hash = _GENESIS_HASH if previous is None else previous["event_hash"]
        timestamp = occurred_at or _iso()
        core = {
            "run_id": run_id,
            "sequence": sequence,
            "event_type": event_type,
            "payload": json.loads(payload_json),
            "occurred_at": timestamp,
            "previous_hash": previous_hash,
        }
        event_hash = _digest_bytes(_canonical_json(core).encode("utf-8"))
        cursor = connection.execute(
            """
            INSERT INTO events(
                run_id, sequence, event_type, payload_json, occurred_at,
                previous_hash, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                sequence,
                event_type,
                payload_json,
                timestamp,
                previous_hash,
                event_hash,
            ),
        )
        return EventRecord(
            event_id=int(cursor.lastrowid),
            event_hash=event_hash,
            **core,
        )

    def create_run(
        self,
        run_id: str,
        request: Mapping[str, Any],
        *,
        status: str = "queued",
    ) -> RunRecord:
        _require_identifier(run_id, "run_id")
        if status not in _RUN_STATUSES:
            raise ValueError("unknown run status")
        request_json = _json_mapping(request, "request")
        request_sha256 = _digest_bytes(request_json.encode("utf-8"))
        timestamp = _iso()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if existing is not None:
                if existing["request_sha256"] != request_sha256:
                    raise ConflictError("run ID was reused with a different request")
                connection.commit()
                return self._row_to_run(existing)
            connection.execute(
                """
                INSERT INTO runs(
                    run_id, request_sha256, request_json, status, version,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (run_id, request_sha256, request_json, status, timestamp, timestamp),
            )
            self._append_event_tx(
                connection,
                run_id,
                "run_created",
                {"request_sha256": request_sha256, "status": status},
                occurred_at=timestamp,
            )
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            connection.commit()
        assert row is not None
        return self._row_to_run(row)

    def get_run(self, run_id: str) -> RunRecord:
        _require_identifier(run_id, "run_id")
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError("unknown run")
        return self._row_to_run(row)

    def require_run_tenant(self, run_id: str, tenant_id: str) -> RunRecord:
        """Return a run only when its immutable request belongs to the tenant."""

        _require_identifier(tenant_id, "tenant_id")
        run = self.get_run(run_id)
        observed = run.request.get("org_id")
        if observed != tenant_id:
            raise KeyError("unknown run")
        return run

    def grant_artifact_to_tenant(self, tenant_id: str, sha256: str) -> ArtifactRecord:
        """Bind an uploaded CAS object to a tenant without duplicating its bytes."""

        _require_identifier(tenant_id, "tenant_id")
        digest = _require_sha256(sha256)
        record = self.artifacts.head(digest)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO artifact_tenants(
                    tenant_id, artifact_sha256, granted_at
                ) VALUES (?, ?, ?)
                """,
                (tenant_id, digest, _iso()),
            )
        return record

    def require_tenant_artifact(self, tenant_id: str, sha256: str) -> ArtifactRecord:
        """Return CAS metadata only when the tenant has proved possession by upload."""

        _require_identifier(tenant_id, "tenant_id")
        digest = _require_sha256(sha256)
        with self._connect() as connection:
            allowed = connection.execute(
                """
                SELECT 1 FROM artifact_tenants
                WHERE tenant_id = ? AND artifact_sha256 = ?
                """,
                (tenant_id, digest),
            ).fetchone()
        if allowed is None:
            raise KeyError("unknown artifact")
        return self.artifacts.head(digest)

    def transition_run(
        self,
        run_id: str,
        *,
        expected_status: str,
        new_status: str,
        details: Mapping[str, Any] | None = None,
    ) -> RunRecord:
        _require_identifier(run_id, "run_id")
        if expected_status not in _RUN_STATUSES or new_status not in _RUN_STATUSES:
            raise ValueError("unknown run status")
        details_json = _json_mapping(details or {}, "transition details")
        timestamp = _iso()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE runs SET status = ?, version = version + 1, updated_at = ?
                WHERE run_id = ? AND status = ?
                """,
                (new_status, timestamp, run_id, expected_status),
            )
            if cursor.rowcount != 1:
                exists = connection.execute(
                    "SELECT 1 FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                if exists is None:
                    raise KeyError("unknown run")
                raise ConflictError("run status changed before this transition")
            self._append_event_tx(
                connection,
                run_id,
                "run_status_changed",
                {
                    "from": expected_status,
                    "to": new_status,
                    "details": json.loads(details_json),
                },
                occurred_at=timestamp,
            )
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            connection.commit()
        assert row is not None
        return self._row_to_run(row)

    def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> EventRecord:
        """Append one transactionally sequenced, hash-chained run event."""

        _require_identifier(run_id, "run_id")
        _require_identifier(event_type, "event_type")
        _json_mapping(payload, "event payload")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone() is None:
                raise KeyError("unknown run")
            event = self._append_event_tx(connection, run_id, event_type, payload)
            connection.commit()
        return event

    def link_artifact(self, run_id: str, sha256: str, *, role: str) -> ArtifactRecord:
        _require_identifier(run_id, "run_id")
        digest = _require_sha256(sha256)
        _require_identifier(role, "artifact role")
        record = self.artifacts.head(digest)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT artifact_sha256 FROM run_artifacts WHERE run_id = ? AND role = ?",
                (run_id, role),
            ).fetchone()
            if existing is not None and existing["artifact_sha256"] != digest:
                raise ConflictError("artifact role is already bound to different content")
            connection.execute(
                """
                INSERT OR IGNORE INTO run_artifacts(run_id, artifact_sha256, role, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, digest, role, _iso()),
            )
            if existing is None:
                self._append_event_tx(
                    connection,
                    run_id,
                    "artifact_linked",
                    {"role": role, "sha256": digest},
                )
            connection.commit()
        return record

    def linked_artifact(self, run_id: str, role: str) -> ArtifactRecord:
        """Return verified HEAD metadata for one server-defined run role."""

        _require_identifier(run_id, "run_id")
        _require_identifier(role, "artifact role")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT artifact_sha256 FROM run_artifacts
                WHERE run_id = ? AND role = ?
                """,
                (run_id, role),
            ).fetchone()
        if row is None:
            raise KeyError("run has no artifact for this role")
        return self.artifacts.head(row["artifact_sha256"])

    def record_approval(
        self,
        run_id: str,
        *,
        approval_id: str,
        preview_sha256: str,
        decision: str,
        approver: str,
        reason: str,
        decided_at: datetime,
        payload: Mapping[str, Any] | None = None,
    ) -> ApprovalRecord:
        _require_identifier(run_id, "run_id")
        _require_identifier(approval_id, "approval_id")
        digest = _require_sha256(preview_sha256, "preview_sha256")
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        _require_nonempty(approver, "approver")
        _require_nonempty(reason, "reason", maximum=4096)
        timestamp = _iso(decided_at)
        payload_json = _json_mapping(payload or {}, "approval payload")
        values = (
            approval_id,
            run_id,
            digest,
            decision,
            approver,
            reason,
            timestamp,
            payload_json,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
            existing_for_run = connection.execute(
                "SELECT * FROM approvals WHERE run_id = ?", (run_id,)
            ).fetchone()
            if existing_for_run is not None and existing_for_run["approval_id"] != approval_id:
                raise ConflictError("run already has an immutable release decision")
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO approvals(
                        approval_id, run_id, preview_sha256, decision, approver,
                        reason, decided_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                self._append_event_tx(
                    connection,
                    run_id,
                    "release_decision_recorded",
                    {
                        "approval_id": approval_id,
                        "preview_sha256": digest,
                        "decision": decision,
                        "approver": approver,
                    },
                    occurred_at=timestamp,
                )
            else:
                observed = tuple(existing[name] for name in (
                    "approval_id", "run_id", "preview_sha256", "decision",
                    "approver", "reason", "decided_at", "payload_json"
                ))
                if observed != values:
                    raise ConflictError("approval ID was reused with different content")
            connection.commit()
        return ApprovalRecord(
            approval_id=approval_id,
            run_id=run_id,
            preview_sha256=digest,
            decision=decision,
            approver=approver,
            reason=reason,
            decided_at=timestamp,
            payload=json.loads(payload_json),
        )

    def get_approval(self, run_id: str) -> ApprovalRecord | None:
        _require_identifier(run_id, "run_id")
        self.get_run(run_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return ApprovalRecord(
            approval_id=row["approval_id"],
            run_id=row["run_id"],
            preview_sha256=row["preview_sha256"],
            decision=row["decision"],
            approver=row["approver"],
            reason=row["reason"],
            decided_at=row["decided_at"],
            payload=json.loads(row["payload_json"]),
        )

    @staticmethod
    def _row_to_multimodal_deliverable(
        row: sqlite3.Row,
    ) -> MultimodalDeliverableRecord:
        return MultimodalDeliverableRecord(
            registration_id=row["registration_id"],
            run_id=row["run_id"],
            capability_id=row["capability_id"],
            artifact_sha256=row["artifact_sha256"],
            execution_receipt_sha256=row["execution_receipt_sha256"],
            media_type=row["media_type"],
            campaign_id=row["campaign_id"],
            model_id=row["model_id"],
            model_revision=row["model_revision"],
            accelerator=row["accelerator"],
            rights_basis=row["rights_basis"],
            rights_locator=row["rights_locator"],
            registered_by=row["registered_by"],
            registered_at=row["registered_at"],
            payload=json.loads(row["payload_json"]),
        )

    @staticmethod
    def _row_to_multimodal_review(
        row: sqlite3.Row,
    ) -> MultimodalDeliverableReviewRecord:
        return MultimodalDeliverableReviewRecord(
            review_id=row["review_id"],
            registration_id=row["registration_id"],
            run_id=row["run_id"],
            decision=row["decision"],
            reviewer=row["reviewer"],
            reason=row["reason"],
            reviewed_at=row["reviewed_at"],
            payload=json.loads(row["payload_json"]),
        )

    def record_multimodal_deliverable(
        self,
        *,
        registration_id: str,
        run_id: str,
        capability_id: str,
        artifact_sha256: str,
        execution_receipt_sha256: str,
        media_type: str,
        campaign_id: str,
        model_id: str,
        model_revision: str,
        accelerator: str,
        rights_basis: str,
        rights_locator: str,
        registered_by: str,
        payload: Mapping[str, Any],
        registered_at: datetime | None = None,
    ) -> MultimodalDeliverableRecord:
        _require_identifier(registration_id, "registration_id")
        _require_identifier(run_id, "run_id")
        if capability_id not in {"video_generation", "audio_generation"}:
            raise ValueError("capability_id must be video_generation or audio_generation")
        artifact_digest = _require_sha256(artifact_sha256, "artifact_sha256")
        receipt_digest = _require_sha256(
            execution_receipt_sha256, "execution_receipt_sha256"
        )
        for value, name in (
            (media_type, "media_type"),
            (campaign_id, "campaign_id"),
            (model_id, "model_id"),
            (model_revision, "model_revision"),
            (accelerator, "accelerator"),
            (rights_basis, "rights_basis"),
            (rights_locator, "rights_locator"),
            (registered_by, "registered_by"),
        ):
            _require_nonempty(value, name)
        payload_json = _json_mapping(payload, "multimodal deliverable payload")
        timestamp = _iso(registered_at)
        values = (
            registration_id,
            run_id,
            capability_id,
            artifact_digest,
            receipt_digest,
            media_type,
            campaign_id,
            model_id,
            model_revision,
            accelerator,
            rights_basis,
            rights_locator,
            registered_by,
            timestamp,
            payload_json,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT request_json FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None:
                raise KeyError("unknown run")
            request = json.loads(run["request_json"])
            if request.get("campaign_id") != campaign_id:
                raise ConflictError("deliverable campaign_id disagrees with its run")
            for digest in (artifact_digest, receipt_digest):
                if connection.execute(
                    "SELECT 1 FROM artifacts WHERE sha256 = ?", (digest,)
                ).fetchone() is None:
                    raise KeyError("unknown artifact")
            existing = connection.execute(
                "SELECT * FROM multimodal_deliverables WHERE registration_id = ? OR "
                "(run_id = ? AND capability_id = ?)",
                (registration_id, run_id, capability_id),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO multimodal_deliverables(
                        registration_id, run_id, capability_id, artifact_sha256,
                        execution_receipt_sha256, media_type, campaign_id, model_id,
                        model_revision, accelerator, rights_basis, rights_locator,
                        registered_by, registered_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                role = f"generated_{capability_id.removesuffix('_generation')}_master"
                connection.execute(
                    """
                    INSERT INTO run_artifacts(run_id, artifact_sha256, role, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (run_id, artifact_digest, role, timestamp),
                )
                self._append_event_tx(
                    connection,
                    run_id,
                    "multimodal_deliverable_registered",
                    {
                        "registration_id": registration_id,
                        "capability_id": capability_id,
                        "artifact_sha256": artifact_digest,
                        "execution_receipt_sha256": receipt_digest,
                        "media_type": media_type,
                        "campaign_id": campaign_id,
                        "model_id": model_id,
                        "model_revision": model_revision,
                        "accelerator": accelerator,
                        "rights_basis": rights_basis,
                        "rights_locator": rights_locator,
                        "registered_by": registered_by,
                    },
                    occurred_at=timestamp,
                )
                existing = connection.execute(
                    "SELECT * FROM multimodal_deliverables WHERE registration_id = ?",
                    (registration_id,),
                ).fetchone()
            else:
                observed = tuple(existing[name] for name in (
                    "registration_id", "run_id", "capability_id", "artifact_sha256",
                    "execution_receipt_sha256", "media_type", "campaign_id", "model_id",
                    "model_revision", "accelerator", "rights_basis", "rights_locator",
                    "registered_by", "registered_at", "payload_json"
                ))
                if observed != values:
                    raise ConflictError(
                        "multimodal deliverable identity is already bound to different content"
                    )
            connection.commit()
        assert existing is not None
        return self._row_to_multimodal_deliverable(existing)

    def list_multimodal_deliverables(
        self, run_id: str
    ) -> tuple[MultimodalDeliverableRecord, ...]:
        _require_identifier(run_id, "run_id")
        self.get_run(run_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM multimodal_deliverables WHERE run_id = ? "
                "ORDER BY capability_id, registration_id",
                (run_id,),
            ).fetchall()
        return tuple(self._row_to_multimodal_deliverable(row) for row in rows)

    def record_multimodal_deliverable_review(
        self,
        *,
        review_id: str,
        registration_id: str,
        run_id: str,
        decision: str,
        reviewer: str,
        reason: str,
        payload: Mapping[str, Any],
        reviewed_at: datetime | None = None,
    ) -> MultimodalDeliverableReviewRecord:
        _require_identifier(review_id, "review_id")
        _require_identifier(registration_id, "registration_id")
        _require_identifier(run_id, "run_id")
        if decision not in {"pass", "reject"}:
            raise ValueError("decision must be pass or reject")
        _require_nonempty(reviewer, "reviewer")
        _require_nonempty(reason, "reason", maximum=4096)
        payload_json = _json_mapping(payload, "multimodal review payload")
        timestamp = _iso(reviewed_at)
        values = (
            review_id,
            registration_id,
            run_id,
            decision,
            reviewer,
            reason,
            timestamp,
            payload_json,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            registration = connection.execute(
                "SELECT run_id FROM multimodal_deliverables WHERE registration_id = ?",
                (registration_id,),
            ).fetchone()
            if registration is None:
                raise KeyError("unknown multimodal deliverable")
            if registration["run_id"] != run_id:
                raise ConflictError("multimodal review run disagrees with registration")
            existing = connection.execute(
                "SELECT * FROM multimodal_deliverable_reviews WHERE review_id = ? OR registration_id = ?",
                (review_id, registration_id),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO multimodal_deliverable_reviews(
                        review_id, registration_id, run_id, decision, reviewer,
                        reason, reviewed_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                self._append_event_tx(
                    connection,
                    run_id,
                    "multimodal_deliverable_reviewed",
                    {
                        "review_id": review_id,
                        "registration_id": registration_id,
                        "decision": decision,
                        "reviewer": reviewer,
                    },
                    occurred_at=timestamp,
                )
                existing = connection.execute(
                    "SELECT * FROM multimodal_deliverable_reviews WHERE review_id = ?",
                    (review_id,),
                ).fetchone()
            else:
                observed = tuple(existing[name] for name in (
                    "review_id", "registration_id", "run_id", "decision",
                    "reviewer", "reason", "reviewed_at", "payload_json"
                ))
                if observed != values:
                    raise ConflictError(
                        "multimodal review identity is already bound to different content"
                    )
            connection.commit()
        assert existing is not None
        return self._row_to_multimodal_review(existing)

    def list_multimodal_deliverable_reviews(
        self, run_id: str
    ) -> tuple[MultimodalDeliverableReviewRecord, ...]:
        _require_identifier(run_id, "run_id")
        self.get_run(run_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM multimodal_deliverable_reviews WHERE run_id = ? "
                "ORDER BY reviewed_at, review_id",
                (run_id,),
            ).fetchall()
        return tuple(self._row_to_multimodal_review(row) for row in rows)

    @staticmethod
    def _row_to_capability_deliverable(
        row: sqlite3.Row,
    ) -> CapabilityDeliverableRecord:
        return CapabilityDeliverableRecord(
            registration_id=row["registration_id"],
            run_id=row["run_id"],
            capability_id=row["capability_id"],
            artifact_role=row["artifact_role"],
            artifact_sha256=row["artifact_sha256"],
            execution_receipt_sha256=row["execution_receipt_sha256"],
            media_type=row["media_type"],
            campaign_id=row["campaign_id"],
            model_id=row["model_id"],
            model_revision=row["model_revision"],
            accelerator=row["accelerator"],
            rights_basis=row["rights_basis"],
            rights_locator=row["rights_locator"],
            registered_by=row["registered_by"],
            registered_at=row["registered_at"],
            payload=json.loads(row["payload_json"]),
        )

    @staticmethod
    def _row_to_capability_review(
        row: sqlite3.Row,
    ) -> CapabilityDeliverableReviewRecord:
        return CapabilityDeliverableReviewRecord(
            review_id=row["review_id"],
            registration_id=row["registration_id"],
            run_id=row["run_id"],
            decision=row["decision"],
            reviewer=row["reviewer"],
            reason=row["reason"],
            reviewed_at=row["reviewed_at"],
            payload=json.loads(row["payload_json"]),
        )

    def record_capability_deliverable(
        self,
        *,
        registration_id: str,
        run_id: str,
        capability_id: str,
        artifact_role: str,
        artifact_sha256: str,
        execution_receipt_sha256: str,
        media_type: str,
        campaign_id: str,
        model_id: str,
        model_revision: str,
        accelerator: str,
        rights_basis: str,
        rights_locator: str,
        registered_by: str,
        payload: Mapping[str, Any],
        registered_at: datetime | None = None,
    ) -> CapabilityDeliverableRecord:
        allowed = {
            "data_strategy", "content_scheduling", "text_generation",
            "data_analysis", "geo_visibility", "seo_operations",
            "employee_agent", "advertising",
        }
        _require_identifier(registration_id, "registration_id")
        _require_identifier(run_id, "run_id")
        if capability_id not in allowed:
            raise ValueError("unsupported capability deliverable")
        _require_identifier(artifact_role, "artifact_role")
        artifact_digest = _require_sha256(artifact_sha256, "artifact_sha256")
        receipt_digest = _require_sha256(
            execution_receipt_sha256, "execution_receipt_sha256"
        )
        for value, name in (
            (media_type, "media_type"), (campaign_id, "campaign_id"),
            (model_id, "model_id"), (model_revision, "model_revision"),
            (accelerator, "accelerator"), (rights_basis, "rights_basis"),
            (rights_locator, "rights_locator"), (registered_by, "registered_by"),
        ):
            _require_nonempty(value, name)
        payload_json = _json_mapping(payload, "capability deliverable payload")
        timestamp = _iso(registered_at)
        values = (
            registration_id, run_id, capability_id, artifact_role,
            artifact_digest, receipt_digest, media_type, campaign_id, model_id,
            model_revision, accelerator, rights_basis, rights_locator,
            registered_by, timestamp, payload_json,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT request_json FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None:
                raise KeyError("unknown run")
            if json.loads(run["request_json"]).get("campaign_id") != campaign_id:
                raise ConflictError("deliverable campaign_id disagrees with its run")
            for digest in (artifact_digest, receipt_digest):
                if connection.execute(
                    "SELECT 1 FROM artifacts WHERE sha256 = ?", (digest,)
                ).fetchone() is None:
                    raise KeyError("unknown artifact")
            existing = connection.execute(
                "SELECT * FROM capability_deliverables WHERE registration_id = ? OR "
                "(run_id = ? AND capability_id = ?)",
                (registration_id, run_id, capability_id),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO capability_deliverables(
                        registration_id, run_id, capability_id, artifact_role,
                        artifact_sha256, execution_receipt_sha256, media_type,
                        campaign_id, model_id, model_revision, accelerator,
                        rights_basis, rights_locator, registered_by, registered_at,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                connection.execute(
                    """
                    INSERT INTO run_artifacts(run_id, artifact_sha256, role, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (run_id, artifact_digest, f"generated_{capability_id}_deliverable", timestamp),
                )
                self._append_event_tx(
                    connection,
                    run_id,
                    "capability_deliverable_registered",
                    {
                        "registration_id": registration_id,
                        "capability_id": capability_id,
                        "artifact_role": artifact_role,
                        "artifact_sha256": artifact_digest,
                        "execution_receipt_sha256": receipt_digest,
                        "campaign_id": campaign_id,
                        "model_id": model_id,
                        "model_revision": model_revision,
                        "accelerator": accelerator,
                        "rights_basis": rights_basis,
                        "rights_locator": rights_locator,
                        "registered_by": registered_by,
                    },
                    occurred_at=timestamp,
                )
                existing = connection.execute(
                    "SELECT * FROM capability_deliverables WHERE registration_id = ?",
                    (registration_id,),
                ).fetchone()
            else:
                observed = tuple(existing[name] for name in (
                    "registration_id", "run_id", "capability_id", "artifact_role",
                    "artifact_sha256", "execution_receipt_sha256", "media_type",
                    "campaign_id", "model_id", "model_revision", "accelerator",
                    "rights_basis", "rights_locator", "registered_by", "registered_at",
                    "payload_json",
                ))
                if observed != values:
                    raise ConflictError(
                        "capability deliverable identity is already bound to different content"
                    )
            connection.commit()
        assert existing is not None
        return self._row_to_capability_deliverable(existing)

    def list_capability_deliverables(
        self, run_id: str
    ) -> tuple[CapabilityDeliverableRecord, ...]:
        _require_identifier(run_id, "run_id")
        self.get_run(run_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM capability_deliverables WHERE run_id = ? "
                "ORDER BY capability_id, registration_id",
                (run_id,),
            ).fetchall()
        return tuple(self._row_to_capability_deliverable(row) for row in rows)

    def record_capability_deliverable_review(
        self,
        *,
        review_id: str,
        registration_id: str,
        run_id: str,
        decision: str,
        reviewer: str,
        reason: str,
        payload: Mapping[str, Any],
        reviewed_at: datetime | None = None,
    ) -> CapabilityDeliverableReviewRecord:
        _require_identifier(review_id, "review_id")
        _require_identifier(registration_id, "registration_id")
        _require_identifier(run_id, "run_id")
        if decision not in {"pass", "reject"}:
            raise ValueError("decision must be pass or reject")
        _require_nonempty(reviewer, "reviewer")
        _require_nonempty(reason, "reason", maximum=4096)
        payload_json = _json_mapping(payload, "capability review payload")
        timestamp = _iso(reviewed_at)
        values = (
            review_id, registration_id, run_id, decision, reviewer, reason,
            timestamp, payload_json,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            registration = connection.execute(
                "SELECT run_id FROM capability_deliverables WHERE registration_id = ?",
                (registration_id,),
            ).fetchone()
            if registration is None:
                raise KeyError("unknown capability deliverable")
            if registration["run_id"] != run_id:
                raise ConflictError("capability review run disagrees with registration")
            existing = connection.execute(
                "SELECT * FROM capability_deliverable_reviews WHERE review_id = ? OR "
                "registration_id = ?",
                (review_id, registration_id),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO capability_deliverable_reviews(
                        review_id, registration_id, run_id, decision, reviewer,
                        reason, reviewed_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                self._append_event_tx(
                    connection,
                    run_id,
                    "capability_deliverable_reviewed",
                    {
                        "review_id": review_id,
                        "registration_id": registration_id,
                        "decision": decision,
                        "reviewer": reviewer,
                    },
                    occurred_at=timestamp,
                )
                existing = connection.execute(
                    "SELECT * FROM capability_deliverable_reviews WHERE review_id = ?",
                    (review_id,),
                ).fetchone()
            else:
                observed = tuple(existing[name] for name in (
                    "review_id", "registration_id", "run_id", "decision",
                    "reviewer", "reason", "reviewed_at", "payload_json",
                ))
                if observed != values:
                    raise ConflictError(
                        "capability review identity is already bound to different content"
                    )
            connection.commit()
        assert existing is not None
        return self._row_to_capability_review(existing)

    def list_capability_deliverable_reviews(
        self, run_id: str
    ) -> tuple[CapabilityDeliverableReviewRecord, ...]:
        _require_identifier(run_id, "run_id")
        self.get_run(run_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM capability_deliverable_reviews WHERE run_id = ? "
                "ORDER BY reviewed_at, review_id",
                (run_id,),
            ).fetchall()
        return tuple(self._row_to_capability_review(row) for row in rows)

    @staticmethod
    def _row_to_learning_memory(row: sqlite3.Row) -> LearningMemoryRecord:
        return LearningMemoryRecord(
            memory_id=row["memory_id"],
            org_id=row["org_id"],
            project_id=row["project_id"],
            source_run_id=row["source_run_id"],
            observation_id=row["observation_id"],
            memory_sha256=row["memory_sha256"],
            approved_by=row["approved_by"],
            reason=row["reason"],
            approved_at=row["approved_at"],
            payload=json.loads(row["payload_json"]),
        )

    def record_learning_memory(
        self,
        *,
        memory_id: str,
        org_id: str,
        project_id: str,
        source_run_id: str,
        observation_id: str,
        approved_by: str,
        reason: str,
        payload: Mapping[str, Any],
        approved_at: datetime | None = None,
    ) -> LearningMemoryRecord:
        _require_identifier(memory_id, "memory_id")
        _require_identifier(org_id, "org_id")
        _require_identifier(project_id, "project_id")
        _require_identifier(source_run_id, "source_run_id")
        _require_identifier(observation_id, "observation_id")
        _require_nonempty(approved_by, "approved_by")
        _require_nonempty(reason, "reason", maximum=4096)
        payload_json = _json_mapping(payload, "learning memory payload")
        timestamp = _iso(approved_at)
        core = {
            "memory_id": memory_id,
            "org_id": org_id,
            "project_id": project_id,
            "source_run_id": source_run_id,
            "observation_id": observation_id,
            "approved_by": approved_by,
            "reason": reason,
            "approved_at": timestamp,
            "payload": json.loads(payload_json),
        }
        memory_sha256 = _digest_bytes(_canonical_json(core).encode("utf-8"))
        values = (
            memory_id,
            org_id,
            project_id,
            source_run_id,
            observation_id,
            memory_sha256,
            approved_by,
            reason,
            timestamp,
            payload_json,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source = connection.execute(
                "SELECT request_json FROM runs WHERE run_id = ?", (source_run_id,)
            ).fetchone()
            if source is None:
                raise KeyError("unknown source run")
            source_request = json.loads(source["request_json"])
            if (
                source_request.get("org_id") != org_id
                or source_request.get("project_id") != project_id
            ):
                raise ConflictError(
                    "learning memory scope disagrees with its source run"
                )
            existing = connection.execute(
                "SELECT * FROM learning_memories WHERE memory_id = ? OR "
                "(source_run_id = ? AND observation_id = ?)",
                (memory_id, source_run_id, observation_id),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO learning_memories(
                        memory_id, org_id, project_id, source_run_id,
                        observation_id, memory_sha256, approved_by, reason,
                        approved_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                self._append_event_tx(
                    connection,
                    source_run_id,
                    "learning_memory_promoted",
                    {
                        "memory_id": memory_id,
                        "observation_id": observation_id,
                        "memory_sha256": memory_sha256,
                        "org_id": org_id,
                        "project_id": project_id,
                    },
                    occurred_at=timestamp,
                )
            else:
                observed = tuple(
                    existing[name]
                    for name in (
                        "memory_id",
                        "org_id",
                        "project_id",
                        "source_run_id",
                        "observation_id",
                        "memory_sha256",
                        "approved_by",
                        "reason",
                        "approved_at",
                        "payload_json",
                    )
                )
                if observed != values:
                    raise ConflictError(
                        "learning memory identity was reused with different content"
                    )
            row = connection.execute(
                "SELECT * FROM learning_memories WHERE memory_id = ?", (memory_id,)
            ).fetchone()
            connection.commit()
        assert row is not None
        return self._row_to_learning_memory(row)

    def list_learning_memories(
        self,
        org_id: str,
        project_id: str,
    ) -> list[LearningMemoryRecord]:
        _require_identifier(org_id, "org_id")
        _require_identifier(project_id, "project_id")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM learning_memories
                WHERE org_id = ? AND project_id = ?
                ORDER BY approved_at, memory_id
                """,
                (org_id, project_id),
            ).fetchall()
        return [self._row_to_learning_memory(row) for row in rows]

    @staticmethod
    def _row_to_strategy_memory_resolution(
        row: sqlite3.Row,
    ) -> StrategyMemoryResolutionRecord:
        return StrategyMemoryResolutionRecord(
            resolution_id=row["resolution_id"],
            org_id=row["org_id"],
            project_id=row["project_id"],
            source_run_id=row["source_run_id"],
            base_decision_sha256=row["base_decision_sha256"],
            channel=row["channel"],
            winner_memory_id=row["winner_memory_id"],
            resolution_sha256=row["resolution_sha256"],
            resolved_by=row["resolved_by"],
            reason=row["reason"],
            resolved_at=row["resolved_at"],
            payload=json.loads(row["payload_json"]),
        )

    def record_strategy_memory_resolution(
        self,
        *,
        resolution_id: str,
        org_id: str,
        project_id: str,
        source_run_id: str,
        base_decision_sha256: str,
        channel: str,
        winner_memory_id: str,
        resolved_by: str,
        reason: str,
        payload: Mapping[str, Any],
        resolved_at: datetime | None = None,
    ) -> StrategyMemoryResolutionRecord:
        _require_identifier(resolution_id, "resolution_id")
        _require_identifier(org_id, "org_id")
        _require_identifier(project_id, "project_id")
        _require_identifier(source_run_id, "source_run_id")
        _require_sha256(base_decision_sha256, "base_decision_sha256")
        _require_nonempty(channel, "channel", maximum=200)
        _require_identifier(winner_memory_id, "winner_memory_id")
        _require_nonempty(resolved_by, "resolved_by")
        _require_nonempty(reason, "reason", maximum=4096)
        payload_json = _json_mapping(payload, "strategy memory resolution payload")
        parsed_payload = json.loads(payload_json)
        resolution_sha256 = _require_sha256(
            str(parsed_payload.get("resolution_sha256", "")),
            "resolution_sha256",
        )
        timestamp = _iso(resolved_at)
        payload_bindings = {
            "source_run_id": source_run_id,
            "base_decision_sha256": base_decision_sha256,
            "channel": channel,
            "winner_memory_id": winner_memory_id,
            "resolved_by": resolved_by,
            "reason": reason,
            "resolved_at": timestamp,
        }
        if any(parsed_payload.get(key) != value for key, value in payload_bindings.items()):
            raise ConflictError("strategy memory resolution fields disagree with payload")
        values = (
            resolution_id,
            org_id,
            project_id,
            source_run_id,
            base_decision_sha256,
            channel,
            winner_memory_id,
            resolution_sha256,
            resolved_by,
            reason,
            timestamp,
            payload_json,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source = connection.execute(
                "SELECT request_json FROM runs WHERE run_id = ?", (source_run_id,)
            ).fetchone()
            if source is None:
                raise KeyError("unknown source run")
            source_request = json.loads(source["request_json"])
            if (
                source_request.get("org_id") != org_id
                or source_request.get("project_id") != project_id
            ):
                raise ConflictError(
                    "strategy memory resolution scope disagrees with its source run"
                )
            existing = connection.execute(
                """
                SELECT * FROM strategy_memory_resolutions
                WHERE resolution_id = ? OR resolution_sha256 = ? OR
                    (org_id = ? AND project_id = ? AND
                     base_decision_sha256 = ? AND channel = ?)
                """,
                (
                    resolution_id,
                    resolution_sha256,
                    org_id,
                    project_id,
                    base_decision_sha256,
                    channel,
                ),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO strategy_memory_resolutions(
                        resolution_id, org_id, project_id, source_run_id,
                        base_decision_sha256, channel, winner_memory_id,
                        resolution_sha256, resolved_by, reason, resolved_at,
                        payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                self._append_event_tx(
                    connection,
                    source_run_id,
                    "strategy_memory_conflict_resolved_for_future_runs",
                    {
                        "resolution_id": resolution_id,
                        "base_decision_sha256": base_decision_sha256,
                        "channel": channel,
                        "winner_memory_id": winner_memory_id,
                        "resolution_sha256": resolution_sha256,
                        "source_run_mutated": False,
                    },
                    occurred_at=timestamp,
                )
            else:
                observed = tuple(
                    existing[name]
                    for name in (
                        "resolution_id",
                        "org_id",
                        "project_id",
                        "source_run_id",
                        "base_decision_sha256",
                        "channel",
                        "winner_memory_id",
                        "resolution_sha256",
                        "resolved_by",
                        "reason",
                        "resolved_at",
                        "payload_json",
                    )
                )
                if observed != values:
                    raise ConflictError(
                        "a frozen strategy memory conflict already has another resolution"
                    )
            row = connection.execute(
                "SELECT * FROM strategy_memory_resolutions WHERE resolution_id = ?",
                (resolution_id,),
            ).fetchone()
            connection.commit()
        assert row is not None
        return self._row_to_strategy_memory_resolution(row)

    def list_strategy_memory_resolutions(
        self,
        org_id: str,
        project_id: str,
    ) -> list[StrategyMemoryResolutionRecord]:
        _require_identifier(org_id, "org_id")
        _require_identifier(project_id, "project_id")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM strategy_memory_resolutions
                WHERE org_id = ? AND project_id = ?
                ORDER BY resolved_at, resolution_id
                """,
                (org_id, project_id),
            ).fetchall()
        return [self._row_to_strategy_memory_resolution(row) for row in rows]

    @staticmethod
    def _row_to_memory_capsule_import(
        row: sqlite3.Row,
    ) -> MemoryCapsuleImportRecord:
        return MemoryCapsuleImportRecord(
            capsule_id=row["capsule_id"],
            org_id=row["org_id"],
            project_id=row["project_id"],
            context_sha256=row["context_sha256"],
            capsule_sha256=row["capsule_sha256"],
            status=row["status"],
            imported_at=row["imported_at"],
            reviewed_by=row["reviewed_by"],
            review_reason=row["review_reason"],
            reviewed_at=row["reviewed_at"],
            capsule=json.loads(row["capsule_json"]),
        )

    def stage_memory_capsule_import(
        self,
        capsule: Mapping[str, Any],
        *,
        org_id: str,
        project_id: str,
        imported_at: datetime | None = None,
    ) -> MemoryCapsuleImportRecord:
        _require_identifier(org_id, "org_id")
        _require_identifier(project_id, "project_id")
        capsule_id = _require_identifier(capsule.get("capsule_id"), "capsule_id")
        context_sha256 = str(capsule.get("context_sha256", ""))
        capsule_sha256 = str(capsule.get("capsule_sha256", ""))
        if not _SHA256.fullmatch(context_sha256) or not _SHA256.fullmatch(capsule_sha256):
            raise IntegrityError("memory capsule digests are invalid")
        if capsule.get("tenant_id") != org_id or capsule.get("project_id") != project_id:
            raise ConflictError("memory capsule scope disagrees with import scope")
        capsule_json = _json_mapping(capsule, "memory capsule")
        timestamp = _iso(imported_at)
        values = (
            capsule_id,
            org_id,
            project_id,
            context_sha256,
            capsule_sha256,
            "pending_review",
            timestamp,
            capsule_json,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM memory_capsule_imports WHERE capsule_id = ? OR capsule_sha256 = ?",
                (capsule_id, capsule_sha256),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO memory_capsule_imports(
                        capsule_id, org_id, project_id, context_sha256,
                        capsule_sha256, status, imported_at, capsule_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            else:
                observed = tuple(
                    existing[name]
                    for name in (
                        "capsule_id", "org_id", "project_id", "context_sha256",
                        "capsule_sha256", "status", "imported_at", "capsule_json",
                    )
                )
                if observed != values:
                    if (
                        existing["capsule_id"] == capsule_id
                        and existing["org_id"] == org_id
                        and existing["project_id"] == project_id
                        and existing["context_sha256"] == context_sha256
                        and existing["capsule_sha256"] == capsule_sha256
                        and existing["capsule_json"] == capsule_json
                    ):
                        connection.commit()
                        return self._row_to_memory_capsule_import(existing)
                    raise ConflictError("memory capsule identity was reused with different content")
            row = connection.execute(
                "SELECT * FROM memory_capsule_imports WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()
            connection.commit()
        assert row is not None
        return self._row_to_memory_capsule_import(row)

    def review_memory_capsule_import(
        self,
        capsule_id: str,
        *,
        org_id: str,
        decision: str,
        reviewed_by: str,
        reason: str,
        reviewed_at: datetime | None = None,
    ) -> MemoryCapsuleImportRecord:
        _require_identifier(capsule_id, "capsule_id")
        _require_identifier(org_id, "org_id")
        if decision not in {"approve", "reject"}:
            raise ValueError("memory capsule decision must be approve or reject")
        reviewer = _require_nonempty(reviewed_by, "reviewed_by")
        normalized_reason = _require_nonempty(reason, "reason", maximum=4096)
        status = "approved" if decision == "approve" else "rejected"
        timestamp = _iso(reviewed_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM memory_capsule_imports WHERE capsule_id = ? AND org_id = ?",
                (capsule_id, org_id),
            ).fetchone()
            if row is None:
                raise KeyError("unknown memory capsule import")
            if row["status"] == "pending_review":
                connection.execute(
                    """
                    UPDATE memory_capsule_imports
                    SET status = ?, reviewed_by = ?, review_reason = ?, reviewed_at = ?
                    WHERE capsule_id = ? AND org_id = ?
                    """,
                    (status, reviewer, normalized_reason, timestamp, capsule_id, org_id),
                )
            elif (
                row["status"] != status
                or row["reviewed_by"] != reviewer
                or row["review_reason"] != normalized_reason
            ):
                raise ConflictError("a different immutable memory capsule review exists")
            result = connection.execute(
                "SELECT * FROM memory_capsule_imports WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()
            connection.commit()
        assert result is not None
        return self._row_to_memory_capsule_import(result)

    def list_memory_capsule_imports(
        self,
        org_id: str,
        project_id: str,
        *,
        status: str | None = None,
    ) -> list[MemoryCapsuleImportRecord]:
        _require_identifier(org_id, "org_id")
        _require_identifier(project_id, "project_id")
        parameters: tuple[Any, ...] = (org_id, project_id)
        clause = ""
        if status is not None:
            if status not in {"pending_review", "approved", "rejected"}:
                raise ValueError("memory capsule status is invalid")
            clause = " AND status = ?"
            parameters = (*parameters, status)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM memory_capsule_imports
                WHERE org_id = ? AND project_id = ?
                """ + clause + " ORDER BY imported_at, capsule_id",
                parameters,
            ).fetchall()
        return [self._row_to_memory_capsule_import(row) for row in rows]

    def enqueue_job(
        self,
        job_id: str,
        run_id: str,
        *,
        kind: str,
        payload: Mapping[str, Any],
    ) -> JobRecord:
        _require_identifier(job_id, "job_id")
        _require_identifier(run_id, "run_id")
        _require_identifier(kind, "job kind")
        run = self.get_run(run_id)
        scoped_payload = dict(payload)
        tenant_id = run.request.get("org_id")
        if tenant_id is not None:
            _require_identifier(tenant_id, "run tenant_id")
            supplied_tenant = scoped_payload.get("tenant_id")
            if supplied_tenant is not None and supplied_tenant != tenant_id:
                raise ConflictError("job tenant_id disagrees with the run tenant")
            scoped_payload["tenant_id"] = tenant_id
        payload_json = _json_mapping(scoped_payload, "job payload")
        timestamp = _iso()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if existing is not None:
                if (
                    existing["run_id"] != run_id
                    or existing["kind"] != kind
                    or existing["payload_json"] != payload_json
                ):
                    raise ConflictError("job ID was reused with different content")
                connection.commit()
                return self._row_to_job(existing)
            connection.execute(
                """
                INSERT INTO jobs(
                    job_id, run_id, kind, payload_json, status, attempts,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'queued', 0, ?, ?)
                """,
                (job_id, run_id, kind, payload_json, timestamp, timestamp),
            )
            self._append_event_tx(
                connection,
                run_id,
                "job_enqueued",
                {"job_id": job_id, "kind": kind},
                occurred_at=timestamp,
            )
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            connection.commit()
        assert row is not None
        return self._row_to_job(row)

    def claim_next_job(
        self,
        worker_id: str,
        *,
        lease_seconds: int = 60,
        now: datetime | None = None,
    ) -> JobRecord | None:
        _require_identifier(worker_id, "worker_id")
        if not isinstance(lease_seconds, int) or lease_seconds < 1 or lease_seconds > 3600:
            raise ValueError("lease_seconds must be an integer in [1, 3600]")
        current = now or _utc_now()
        current_iso = _iso(current)
        expires_iso = _iso(current + timedelta(seconds=lease_seconds))
        lease_token = secrets.token_hex(32)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            candidate = connection.execute(
                """
                SELECT * FROM jobs
                WHERE status = 'queued'
                   OR (status = 'leased' AND lease_expires_at <= ?)
                ORDER BY created_at, job_id
                LIMIT 1
                """,
                (current_iso,),
            ).fetchone()
            if candidate is None:
                connection.commit()
                return None
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'leased', attempts = attempts + 1,
                    lease_owner = ?, lease_token = ?, lease_expires_at = ?,
                    updated_at = ?, result_json = NULL, error = NULL
                WHERE job_id = ? AND (
                    status = 'queued'
                    OR (status = 'leased' AND lease_expires_at <= ?)
                )
                """,
                (
                    worker_id,
                    lease_token,
                    expires_iso,
                    current_iso,
                    candidate["job_id"],
                    current_iso,
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return None
            self._append_event_tx(
                connection,
                candidate["run_id"],
                "job_leased",
                {
                    "job_id": candidate["job_id"],
                    "worker_id": worker_id,
                    "attempt": candidate["attempts"] + 1,
                    "lease_expires_at": expires_iso,
                },
                occurred_at=current_iso,
            )
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (candidate["job_id"],)
            ).fetchone()
            connection.commit()
        assert row is not None
        return self._row_to_job(row)

    def finish_job(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_token: str,
        succeeded: bool,
        result: Mapping[str, Any] | None = None,
        error: str | None = None,
        now: datetime | None = None,
    ) -> JobRecord:
        _require_identifier(job_id, "job_id")
        _require_identifier(worker_id, "worker_id")
        if not isinstance(lease_token, str) or not re.fullmatch(r"[0-9a-f]{64}", lease_token):
            raise LeaseError("lease token is malformed")
        if succeeded and error is not None:
            raise ValueError("successful jobs cannot carry an error")
        if not succeeded:
            _require_nonempty(error or "", "job error", maximum=4096)
        result_json = _json_mapping(result or {}, "job result") if succeeded else None
        current_iso = _iso(now or _utc_now())
        final_status = "succeeded" if succeeded else "failed"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError("unknown job")
            if (
                row["status"] != "leased"
                or row["lease_owner"] != worker_id
                or not secrets.compare_digest(row["lease_token"] or "", lease_token)
                or row["lease_expires_at"] <= current_iso
            ):
                raise LeaseError("worker does not own a live lease for this job")
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, result_json = ?, error = ?, lease_owner = NULL,
                    lease_token = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE job_id = ?
                """,
                (final_status, result_json, error, current_iso, job_id),
            )
            self._append_event_tx(
                connection,
                row["run_id"],
                "job_finished",
                {"job_id": job_id, "status": final_status},
                occurred_at=current_iso,
            )
            final = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            connection.commit()
        assert final is not None
        return self._row_to_job(final)

    def get_job(self, job_id: str) -> JobRecord:
        _require_identifier(job_id, "job_id")
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError("unknown job")
        return self._row_to_job(row)

    def events_after(
        self,
        run_id: str,
        last_event_id: int = 0,
        *,
        limit: int = 1000,
    ) -> tuple[EventRecord, ...]:
        _require_identifier(run_id, "run_id")
        if isinstance(last_event_id, bool) or not isinstance(last_event_id, int) or last_event_id < 0:
            raise ValueError("Last-Event-ID must be a non-negative integer")
        if not isinstance(limit, int) or limit < 1 or limit > 5000:
            raise ValueError("event limit must be in [1, 5000]")
        self.get_run(run_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM events
                WHERE run_id = ? AND event_id > ?
                ORDER BY event_id LIMIT ?
                """,
                (run_id, last_event_id, limit),
            ).fetchall()
        return tuple(self._row_to_event(row) for row in rows)

    def verify_event_chain(self, run_id: str) -> bool:
        try:
            _require_identifier(run_id, "run_id")
            self.get_run(run_id)
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM events WHERE run_id = ? ORDER BY sequence",
                    (run_id,),
                ).fetchall()
            events = tuple(self._row_to_event(row) for row in rows)
        except (KeyError, ValueError, json.JSONDecodeError):
            return False
        if not events:
            return False
        previous_hash = _GENESIS_HASH
        expected_sequence = 1
        for event in events:
            if event.sequence != expected_sequence or event.previous_hash != previous_hash:
                return False
            core = {
                "run_id": event.run_id,
                "sequence": event.sequence,
                "event_type": event.event_type,
                "payload": dict(event.payload),
                "occurred_at": event.occurred_at,
                "previous_hash": event.previous_hash,
            }
            if _digest_bytes(_canonical_json(core).encode("utf-8")) != event.event_hash:
                return False
            previous_hash = event.event_hash
            expected_sequence += 1
        return True

    def begin_idempotent_command(
        self,
        namespace: str,
        idempotency_key: str,
        request_body: bytes,
    ) -> IdempotencyResult:
        _require_identifier(namespace, "idempotency namespace")
        _require_identifier(idempotency_key, "idempotency key")
        if not isinstance(request_body, bytes):
            raise TypeError("idempotent request body must be exact bytes")
        request_sha256 = _digest_bytes(request_body)
        timestamp = _iso()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM idempotency_commands
                WHERE namespace = ? AND idempotency_key = ?
                """,
                (namespace, idempotency_key),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO idempotency_commands(
                        namespace, idempotency_key, request_sha256, state,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, 'pending', ?, ?)
                    """,
                    (namespace, idempotency_key, request_sha256, timestamp, timestamp),
                )
                connection.commit()
                return IdempotencyResult("new", request_sha256)
            if not secrets.compare_digest(row["request_sha256"], request_sha256):
                raise IdempotencyConflict(
                    "idempotency key was reused with a different request body"
                )
            if row["state"] == "completed":
                connection.commit()
                return IdempotencyResult(
                    "replay",
                    request_sha256,
                    response_code=row["response_code"],
                    response_body=bytes(row["response_body"]),
                )
            connection.commit()
            return IdempotencyResult("pending", request_sha256)

    def complete_idempotent_command(
        self,
        namespace: str,
        idempotency_key: str,
        request_body: bytes,
        *,
        response_code: int,
        response_body: bytes,
    ) -> IdempotencyResult:
        _require_identifier(namespace, "idempotency namespace")
        _require_identifier(idempotency_key, "idempotency key")
        if not isinstance(request_body, bytes) or not isinstance(response_body, bytes):
            raise TypeError("idempotent request and response bodies must be exact bytes")
        if not isinstance(response_code, int) or response_code < 100 or response_code > 599:
            raise ValueError("response_code must be a valid HTTP-style status")
        request_sha256 = _digest_bytes(request_body)
        timestamp = _iso()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM idempotency_commands
                WHERE namespace = ? AND idempotency_key = ?
                """,
                (namespace, idempotency_key),
            ).fetchone()
            if row is None:
                raise KeyError("idempotency command was not begun")
            if not secrets.compare_digest(row["request_sha256"], request_sha256):
                raise IdempotencyConflict(
                    "idempotency key was reused with a different request body"
                )
            if row["state"] == "completed":
                if row["response_code"] != response_code or bytes(row["response_body"]) != response_body:
                    raise ConflictError("completed idempotency response is immutable")
            else:
                connection.execute(
                    """
                    UPDATE idempotency_commands
                    SET state = 'completed', response_code = ?, response_body = ?, updated_at = ?
                    WHERE namespace = ? AND idempotency_key = ? AND state = 'pending'
                    """,
                    (response_code, response_body, timestamp, namespace, idempotency_key),
                )
            connection.commit()
        return IdempotencyResult(
            "replay",
            request_sha256,
            response_code=response_code,
            response_body=response_body,
        )


PersistentRunStore = SubmissionStore


__all__ = [
    "ApprovalRecord",
    "ArtifactRecord",
    "ArtifactStore",
    "ConflictError",
    "EventRecord",
    "IdempotencyConflict",
    "IdempotencyResult",
    "IntegrityError",
    "JobRecord",
    "LearningMemoryRecord",
    "LeaseError",
    "PersistentRunStore",
    "RunRecord",
    "StrategyMemoryResolutionRecord",
    "SubmissionStore",
    "SubmissionStoreError",
    "UnsafePathError",
]
