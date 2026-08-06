from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid
from typing import Any


_SAFE_PART = re.compile(r"^[A-Za-z0-9_.-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MEDIA_SUFFIXES = {
    "audio/wav": "wav",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/x-nv12": "nv12",
    "video/mp4": "mp4",
}
_TIME_ANOMALY_THRESHOLD_MS = 2_000
_GAP_CONFIRM_AFTER_MS = 2 * 60 * 1000
_GAP_CONFIRM_LATER_COUNT = 20
_MAX_TRACKED_GAPS_PER_STREAM = 10_000


class MediaUploadValidationError(ValueError):
    pass


class SequenceConflictError(ValueError):
    pass


@dataclass(frozen=True)
class MediaUploadMetadata:
    device_id: str
    boot_id: str
    stream_id: str
    sequence: int
    captured_at_device_ms: int | None
    monotonic_ms: int
    clock_synced: bool
    filename: str
    media_type: str
    content_length: int
    sha256: str
    duration_ms: int = 0


@dataclass(frozen=True)
class MediaGapMetadata:
    device_id: str
    boot_id: str
    sequence: int
    start_monotonic_ms: int
    end_monotonic_ms: int
    reason: str


@dataclass(frozen=True)
class MediaAcceptResult:
    status: str
    record: dict[str, Any]

    @property
    def duplicate(self) -> bool:
        return self.status == "already_accepted"


class ReliableMediaStore:
    """Durable, idempotent ingress ledger for device media uploads."""

    def __init__(self, root: str | Path, *, now_ms=None) -> None:
        self.root = Path(root).expanduser().resolve()
        self.media_root = self.root / "media"
        self.db_path = self.root / "media-upload.sqlite3"
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def accept(
        self,
        metadata: MediaUploadMetadata,
        body: bytes,
        *,
        server_received_at_ms: int | None = None,
    ) -> MediaAcceptResult:
        metadata = self._validate(metadata, body)
        received_at_ms = (
            int(server_received_at_ms)
            if server_received_at_ms is not None
            else int(self.now_ms())
        )
        key = (
            metadata.device_id,
            metadata.boot_id,
            metadata.stream_id,
            metadata.sequence,
        )
        with self._lock, self._connect() as db:
            existing = self._record_for_key(db, key)
            if existing is not None:
                if existing["sha256"] != metadata.sha256:
                    raise SequenceConflictError(
                        "same device_id/boot_id/stream_id/sequence has different content"
                    )
                self._ensure_existing_file(existing, body)
                return MediaAcceptResult("already_accepted", existing)

            db.execute("BEGIN IMMEDIATE")
            corrected_at_ms = self._corrected_time(db, metadata, received_at_ms)
            storage_path = self._storage_path(metadata)
            self._write_atomic(storage_path, body)
            record_id = str(uuid.uuid4())
            try:
                db.execute(
                    """
                    INSERT INTO media_files (
                        id, device_id, boot_id, stream_id, sequence,
                        filename, media_type, storage_path,
                        captured_at_device_ms, captured_at_corrected_ms,
                        monotonic_ms, clock_synced, duration_ms,
                        content_length, sha256, server_received_at_ms,
                        status, clock_anomaly, clock_deviation_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              'stored', 0, NULL)
                    """,
                    (
                        record_id,
                        metadata.device_id,
                        metadata.boot_id,
                        metadata.stream_id,
                        metadata.sequence,
                        metadata.filename,
                        metadata.media_type,
                        str(storage_path),
                        metadata.captured_at_device_ms,
                        corrected_at_ms,
                        metadata.monotonic_ms,
                        int(metadata.clock_synced),
                        metadata.duration_ms,
                        metadata.content_length,
                        metadata.sha256,
                        received_at_ms,
                    ),
                )
                self._recompute_clock_anomalies(db, metadata)
                self._recompute_gaps(db, metadata, received_at_ms)
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                existing = self._record_for_key(db, key)
                if existing is None or existing["sha256"] != metadata.sha256:
                    raise SequenceConflictError(
                        "same device_id/boot_id/stream_id/sequence has different content"
                    )
                return MediaAcceptResult("already_accepted", existing)
            record = self._record_for_key(db, key)
            if record is None:
                raise RuntimeError("stored media record disappeared")
            return MediaAcceptResult("accepted", record)

    def accept_gap(
        self,
        metadata: MediaGapMetadata,
        *,
        server_received_at_ms: int | None = None,
    ) -> MediaAcceptResult:
        """Durably record an intentional interval with no Memory media.

        Gaps have their own sequence domain so they cannot disturb the audio
        and camera stream ledgers. Repeating the same key and payload is an
        idempotent success; changing the interval or reason is a conflict.
        """
        self._validate_part(metadata.device_id, "device_id")
        self._validate_part(metadata.boot_id, "boot_id")
        if metadata.sequence < 0:
            raise MediaUploadValidationError("gap sequence must be non-negative")
        if metadata.start_monotonic_ms < 0:
            raise MediaUploadValidationError("gap start_monotonic_ms must be non-negative")
        if metadata.end_monotonic_ms <= metadata.start_monotonic_ms:
            raise MediaUploadValidationError(
                "gap end_monotonic_ms must be greater than start_monotonic_ms"
            )
        reason = metadata.reason.strip()
        if not reason or len(reason) > 64 or not _SAFE_PART.fullmatch(reason):
            raise MediaUploadValidationError("invalid gap reason")
        received_at_ms = int(
            self.now_ms() if server_received_at_ms is None else server_received_at_ms
        )
        key = (metadata.device_id, metadata.boot_id, metadata.sequence)
        with self._lock, self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM media_gaps
                WHERE device_id = ? AND boot_id = ? AND sequence = ?
                """,
                key,
            ).fetchone()
            if row is not None:
                existing = self._row(row)
                if (
                    int(existing["start_monotonic_ms"]) != metadata.start_monotonic_ms
                    or int(existing["end_monotonic_ms"]) != metadata.end_monotonic_ms
                    or str(existing["reason"]) != reason
                ):
                    raise SequenceConflictError(
                        "same device_id/boot_id/gap sequence has different metadata"
                    )
                return MediaAcceptResult("already_accepted", existing)
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    """
                    INSERT INTO media_gaps (
                        id, device_id, boot_id, sequence,
                        start_monotonic_ms, end_monotonic_ms, reason,
                        server_received_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        metadata.device_id,
                        metadata.boot_id,
                        metadata.sequence,
                        metadata.start_monotonic_ms,
                        metadata.end_monotonic_ms,
                        reason,
                        received_at_ms,
                    ),
                )
                db.commit()
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise SequenceConflictError("gap sequence conflict") from exc
            row = db.execute(
                """
                SELECT * FROM media_gaps
                WHERE device_id = ? AND boot_id = ? AND sequence = ?
                """,
                key,
            ).fetchone()
            if row is None:
                raise RuntimeError("stored media gap disappeared")
            return MediaAcceptResult("accepted", self._row(row))

    def declared_gaps(self, *, device_id: str, boot_id: str) -> list[dict[str, Any]]:
        self._validate_part(device_id, "device_id")
        self._validate_part(boot_id, "boot_id")
        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM media_gaps
                WHERE device_id = ? AND boot_id = ?
                ORDER BY sequence ASC
                """,
                (device_id, boot_id),
            ).fetchall()
            return [self._row(row) for row in rows]

    def records(
        self,
        *,
        device_id: str,
        boot_id: str,
        stream_id: str,
    ) -> list[dict[str, Any]]:
        self._validate_part(device_id, "device_id")
        self._validate_part(boot_id, "boot_id")
        self._validate_part(stream_id, "stream_id")
        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM media_files
                WHERE device_id = ? AND boot_id = ? AND stream_id = ?
                ORDER BY sequence ASC
                """,
                (device_id, boot_id, stream_id),
            ).fetchall()
            return [self._row(row) for row in rows]

    def pending_projection_records(
        self,
        *,
        device_id: str,
        boot_id: str,
        stream_id: str,
    ) -> list[dict[str, Any]]:
        self._validate_part(device_id, "device_id")
        self._validate_part(boot_id, "boot_id")
        self._validate_part(stream_id, "stream_id")
        with self._lock, self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM media_files
                WHERE device_id = ? AND boot_id = ? AND stream_id = ?
                  AND projection_status != 'projected'
                ORDER BY sequence ASC
                """,
                (device_id, boot_id, stream_id),
            ).fetchall()
            return [self._row(row) for row in rows]

    def max_projected_sequence(
        self,
        *,
        device_id: str,
        boot_id: str,
        stream_id: str,
    ) -> int | None:
        with self._lock, self._connect() as db:
            row = db.execute(
                """
                SELECT MAX(sequence) AS value FROM media_files
                WHERE device_id = ? AND boot_id = ? AND stream_id = ?
                  AND projection_status = 'projected'
                """,
                (device_id, boot_id, stream_id),
            ).fetchone()
            return int(row["value"]) if row and row["value"] is not None else None

    def mark_projected_through(
        self,
        *,
        device_id: str,
        boot_id: str,
        stream_id: str,
        sequence: int,
        projected_at_ms: int | None = None,
    ) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                UPDATE media_files
                SET projection_status = 'projected', projected_at_ms = ?,
                    projection_error = NULL
                WHERE device_id = ? AND boot_id = ? AND stream_id = ?
                  AND sequence <= ?
                """,
                (
                    int(projected_at_ms or self.now_ms()),
                    device_id,
                    boot_id,
                    stream_id,
                    sequence,
                ),
            )
            db.commit()

    def mark_projected(
        self,
        *,
        device_id: str,
        boot_id: str,
        stream_id: str,
        sequence: int,
        projected_at_ms: int | None = None,
    ) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                UPDATE media_files
                SET projection_status = 'projected', projected_at_ms = ?,
                    projection_error = NULL
                WHERE device_id = ? AND boot_id = ? AND stream_id = ?
                  AND sequence = ?
                """,
                (
                    int(projected_at_ms or self.now_ms()),
                    device_id,
                    boot_id,
                    stream_id,
                    sequence,
                ),
            )
            db.commit()

    def gaps(
        self,
        *,
        device_id: str,
        boot_id: str,
        stream_id: str,
        now_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        self._validate_part(device_id, "device_id")
        self._validate_part(boot_id, "boot_id")
        self._validate_part(stream_id, "stream_id")
        metadata = MediaUploadMetadata(
            device_id=device_id,
            boot_id=boot_id,
            stream_id=stream_id,
            sequence=0,
            captured_at_device_ms=None,
            monotonic_ms=0,
            clock_synced=False,
            filename="status.bin",
            media_type="image/jpeg",
            content_length=0,
            sha256="0" * 64,
        )
        with self._lock, self._connect() as db:
            self._recompute_gaps(
                db,
                metadata,
                int(self.now_ms() if now_ms is None else now_ms),
            )
            db.commit()
            rows = db.execute(
                """
                SELECT * FROM sequence_gaps
                WHERE device_id = ? AND boot_id = ? AND stream_id = ?
                ORDER BY missing_sequence ASC
                """,
                (device_id, boot_id, stream_id),
            ).fetchall()
            return [self._row(row) for row in rows]

    def _validate(
        self,
        metadata: MediaUploadMetadata,
        body: bytes,
    ) -> MediaUploadMetadata:
        for field in ("device_id", "boot_id", "stream_id"):
            self._validate_part(str(getattr(metadata, field)), field)
        if metadata.sequence < 0:
            raise MediaUploadValidationError("sequence must be non-negative")
        if metadata.monotonic_ms < 0:
            raise MediaUploadValidationError("monotonic_ms must be non-negative")
        if metadata.duration_ms < 0:
            raise MediaUploadValidationError("duration_ms must be non-negative")
        if metadata.clock_synced and metadata.captured_at_device_ms is None:
            raise MediaUploadValidationError(
                "captured_at_ms is required when clock_synced is true"
            )
        if not metadata.clock_synced and metadata.captured_at_device_ms is not None:
            raise MediaUploadValidationError(
                "captured_at_ms must be omitted when clock_synced is false"
            )
        if metadata.media_type not in _MEDIA_SUFFIXES:
            raise MediaUploadValidationError(
                f"unsupported media_type: {metadata.media_type}"
            )
        filename = metadata.filename.strip()
        if not filename or len(filename) > 255 or Path(filename).name != filename:
            raise MediaUploadValidationError("filename must be a plain file name")
        if metadata.content_length != len(body):
            raise MediaUploadValidationError(
                f"content_length mismatch: expected {metadata.content_length}, got {len(body)}"
            )
        digest = hashlib.sha256(body).hexdigest()
        normalized_sha = metadata.sha256.strip().lower()
        if not _SHA256.fullmatch(normalized_sha):
            raise MediaUploadValidationError("sha256 must be 64 lowercase hex characters")
        if normalized_sha != digest:
            raise MediaUploadValidationError("sha256 mismatch")
        return MediaUploadMetadata(
            **{**asdict(metadata), "filename": filename, "sha256": normalized_sha}
        )

    def _corrected_time(
        self,
        db: sqlite3.Connection,
        metadata: MediaUploadMetadata,
        received_at_ms: int,
    ) -> int:
        anchor = db.execute(
            "SELECT * FROM clock_anchors WHERE device_id = ? AND boot_id = ?",
            (metadata.device_id, metadata.boot_id),
        ).fetchone()
        source = "device_synced" if metadata.clock_synced else "server_received"
        base_epoch_ms = (
            int(metadata.captured_at_device_ms) - metadata.monotonic_ms
            if metadata.clock_synced
            else received_at_ms - metadata.monotonic_ms
        )
        if anchor is None:
            db.execute(
                """
                INSERT INTO clock_anchors (
                    device_id, boot_id, base_epoch_ms, source,
                    anchor_monotonic_ms, anchor_wall_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    metadata.device_id,
                    metadata.boot_id,
                    base_epoch_ms,
                    source,
                    metadata.monotonic_ms,
                    metadata.captured_at_device_ms
                    if metadata.clock_synced
                    else received_at_ms,
                    received_at_ms,
                ),
            )
        elif anchor["source"] != "device_synced" and metadata.clock_synced:
            db.execute(
                """
                UPDATE clock_anchors
                SET base_epoch_ms = ?, source = 'device_synced',
                    anchor_monotonic_ms = ?, anchor_wall_ms = ?, updated_at_ms = ?
                WHERE device_id = ? AND boot_id = ?
                """,
                (
                    base_epoch_ms,
                    metadata.monotonic_ms,
                    metadata.captured_at_device_ms,
                    received_at_ms,
                    metadata.device_id,
                    metadata.boot_id,
                ),
            )
            db.execute(
                """
                UPDATE media_files
                SET captured_at_corrected_ms = ? + monotonic_ms
                WHERE device_id = ? AND boot_id = ?
                """,
                (base_epoch_ms, metadata.device_id, metadata.boot_id),
            )
        else:
            base_epoch_ms = int(anchor["base_epoch_ms"])
        return base_epoch_ms + metadata.monotonic_ms

    def _recompute_clock_anomalies(
        self,
        db: sqlite3.Connection,
        metadata: MediaUploadMetadata,
    ) -> None:
        rows = db.execute(
            """
            SELECT id, captured_at_device_ms, monotonic_ms
            FROM media_files
            WHERE device_id = ? AND boot_id = ? AND stream_id = ?
            ORDER BY sequence ASC
            """,
            (metadata.device_id, metadata.boot_id, metadata.stream_id),
        ).fetchall()
        previous = None
        for row in rows:
            anomaly = 0
            deviation = None
            if previous is not None:
                mono_delta = int(row["monotonic_ms"]) - int(previous["monotonic_ms"])
                if mono_delta <= 0:
                    anomaly = 1
                    deviation = mono_delta
                elif (
                    row["captured_at_device_ms"] is not None
                    and previous["captured_at_device_ms"] is not None
                ):
                    wall_delta = int(row["captured_at_device_ms"]) - int(
                        previous["captured_at_device_ms"]
                    )
                    deviation = wall_delta - mono_delta
                    anomaly = int(abs(deviation) > _TIME_ANOMALY_THRESHOLD_MS)
            db.execute(
                "UPDATE media_files SET clock_anomaly = ?, clock_deviation_ms = ? WHERE id = ?",
                (anomaly, deviation, row["id"]),
            )
            previous = row

    def _recompute_gaps(
        self,
        db: sqlite3.Connection,
        metadata: MediaUploadMetadata,
        now_ms: int,
    ) -> None:
        key = (metadata.device_id, metadata.boot_id, metadata.stream_id)
        rows = db.execute(
            """
            SELECT sequence FROM media_files
            WHERE device_id = ? AND boot_id = ? AND stream_id = ?
            ORDER BY sequence ASC
            """,
            key,
        ).fetchall()
        sequences = [int(row["sequence"]) for row in rows]
        present = set(sequences)
        existing_rows = db.execute(
            """
            SELECT * FROM sequence_gaps
            WHERE device_id = ? AND boot_id = ? AND stream_id = ?
            """,
            key,
        ).fetchall()
        existing = {int(row["missing_sequence"]): row for row in existing_rows}
        if sequences:
            start = sequences[0]
            stop = min(sequences[-1], start + _MAX_TRACKED_GAPS_PER_STREAM)
            missing = {value for value in range(start, stop + 1) if value not in present}
        else:
            missing = set()
        for sequence, row in existing.items():
            if sequence not in missing and row["status"] != "resolved":
                db.execute(
                    """
                    UPDATE sequence_gaps
                    SET status = 'resolved', resolved_at_ms = ?
                    WHERE device_id = ? AND boot_id = ? AND stream_id = ?
                      AND missing_sequence = ?
                    """,
                    (now_ms, *key, sequence),
                )
        for sequence in sorted(missing):
            row = existing.get(sequence)
            detected_at_ms = int(row["detected_at_ms"]) if row else now_ms
            later_count = sum(value > sequence for value in sequences)
            status = (
                "missing"
                if now_ms - detected_at_ms >= _GAP_CONFIRM_AFTER_MS
                and later_count >= _GAP_CONFIRM_LATER_COUNT
                else "detected"
            )
            db.execute(
                """
                INSERT INTO sequence_gaps (
                    device_id, boot_id, stream_id, missing_sequence,
                    status, detected_at_ms, resolved_at_ms, later_count
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(device_id, boot_id, stream_id, missing_sequence)
                DO UPDATE SET status = excluded.status,
                              resolved_at_ms = NULL,
                              later_count = excluded.later_count
                """,
                (*key, sequence, status, detected_at_ms, later_count),
            )

    def _storage_path(self, metadata: MediaUploadMetadata) -> Path:
        captured = (
            str(metadata.captured_at_device_ms)
            if metadata.captured_at_device_ms is not None
            else "unsynced"
        )
        suffix = _MEDIA_SUFFIXES[metadata.media_type]
        return (
            self.media_root
            / metadata.device_id
            / f"boot-{metadata.boot_id}"
            / metadata.stream_id
            / f"{metadata.sequence:012d}-{captured}-{metadata.sha256[:12]}.{suffix}"
        )

    @staticmethod
    def _write_atomic(path: Path, body: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != hashlib.sha256(body).hexdigest():
                raise SequenceConflictError(f"stored file content mismatch: {path.name}")
            return
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
        try:
            with temporary.open("xb") as output:
                output.write(body)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            try:
                directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            except (AttributeError, OSError):
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _ensure_existing_file(self, record: dict[str, Any], body: bytes) -> None:
        path = Path(str(record["storage_path"]))
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]:
            return
        self._write_atomic(path, body)

    @staticmethod
    def _validate_part(value: str, field: str) -> None:
        if not value or len(value) > 160 or not _SAFE_PART.fullmatch(value):
            raise MediaUploadValidationError(f"invalid {field}")

    @staticmethod
    def _record_for_key(
        db: sqlite3.Connection,
        key: tuple[str, str, str, int],
    ) -> dict[str, Any] | None:
        row = db.execute(
            """
            SELECT * FROM media_files
            WHERE device_id = ? AND boot_id = ? AND stream_id = ? AND sequence = ?
            """,
            key,
        ).fetchone()
        return ReliableMediaStore._row(row) if row is not None else None

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        for key in ("clock_synced", "clock_anomaly"):
            if key in value:
                value[key] = bool(value[key])
        return value

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        return db

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS media_files (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    boot_id TEXT NOT NULL,
                    stream_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    storage_path TEXT NOT NULL,
                    captured_at_device_ms INTEGER,
                    captured_at_corrected_ms INTEGER NOT NULL,
                    monotonic_ms INTEGER NOT NULL,
                    clock_synced INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    content_length INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    server_received_at_ms INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    clock_anomaly INTEGER NOT NULL DEFAULT 0,
                    clock_deviation_ms INTEGER,
                    projection_status TEXT NOT NULL DEFAULT 'pending',
                    projected_at_ms INTEGER,
                    projection_error TEXT,
                    UNIQUE(device_id, boot_id, stream_id, sequence)
                );

                CREATE INDEX IF NOT EXISTS idx_media_stream_sequence
                ON media_files(device_id, boot_id, stream_id, sequence);

                CREATE TABLE IF NOT EXISTS sequence_gaps (
                    device_id TEXT NOT NULL,
                    boot_id TEXT NOT NULL,
                    stream_id TEXT NOT NULL,
                    missing_sequence INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    detected_at_ms INTEGER NOT NULL,
                    resolved_at_ms INTEGER,
                    later_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(device_id, boot_id, stream_id, missing_sequence)
                );

                CREATE TABLE IF NOT EXISTS media_gaps (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    boot_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    start_monotonic_ms INTEGER NOT NULL,
                    end_monotonic_ms INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    server_received_at_ms INTEGER NOT NULL,
                    UNIQUE(device_id, boot_id, sequence)
                );

                CREATE INDEX IF NOT EXISTS idx_media_gap_sequence
                ON media_gaps(device_id, boot_id, sequence);

                CREATE TABLE IF NOT EXISTS clock_anchors (
                    device_id TEXT NOT NULL,
                    boot_id TEXT NOT NULL,
                    base_epoch_ms INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    anchor_monotonic_ms INTEGER NOT NULL,
                    anchor_wall_ms INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL,
                    UNIQUE(device_id, boot_id)
                );
                """
            )
            columns = {
                str(row["name"])
                for row in db.execute("PRAGMA table_info(media_files)").fetchall()
            }
            if "projection_status" not in columns:
                db.execute(
                    "ALTER TABLE media_files ADD COLUMN projection_status TEXT NOT NULL DEFAULT 'pending'"
                )
            if "projected_at_ms" not in columns:
                db.execute(
                    "ALTER TABLE media_files ADD COLUMN projected_at_ms INTEGER"
                )
            if "projection_error" not in columns:
                db.execute(
                    "ALTER TABLE media_files ADD COLUMN projection_error TEXT"
                )
