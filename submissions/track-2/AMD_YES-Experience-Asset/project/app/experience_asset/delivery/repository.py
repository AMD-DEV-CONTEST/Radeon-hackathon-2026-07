"""Isolated E7 SQLite persistence without touching shared migration numbering."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from app.experience_asset.domain.models import ExportRecord

from .models import (
    AuditEventV1,
    DeletionItemState,
    DeletionItemV1,
    DeletionJobState,
    DeletionRequestState,
    DeletionRequestV1,
    DeliveryOperation,
    DraftState,
    ExportRequestState,
    StoredRouteDraftV1,
)


class DeliveryPersistenceError(RuntimeError):
    """SQLite could not durably complete an E7 operation."""


class DeliveryConflictError(DeliveryPersistenceError):
    """An idempotency identity or current-state precondition conflicts."""


class DeliveryNotFoundError(DeliveryPersistenceError):
    """The requested E7 record does not exist."""


@dataclass(frozen=True)
class ExportRequestSnapshot:
    request_id: UUID
    draft_id: UUID
    operation: DeliveryOperation
    state: ExportRequestState
    approval_id: UUID | None
    error_code: str | None
    records: list[ExportRecord]


@dataclass(frozen=True)
class DeletionJobSnapshot:
    job_id: UUID
    request_id: UUID
    asset_id: UUID
    state: DeletionJobState
    terminal_state: str | None
    last_error_code: str | None
    draft_count: int
    export_count: int
    items: list[DeletionItemV1]


class E7DeliveryRepository:
    """Owns E7 draft/export/deletion state in an isolated SQLite table family."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS e7_assets (
        asset_id TEXT PRIMARY KEY,
        lifecycle TEXT NOT NULL,
        current_draft_id TEXT,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS e7_route_drafts (
        draft_id TEXT PRIMARY KEY,
        create_request_id TEXT NOT NULL UNIQUE,
        asset_id TEXT NOT NULL,
        version_id TEXT NOT NULL,
        route TEXT NOT NULL,
        language TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        state TEXT NOT NULL,
        superseded_by_draft_id TEXT,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(asset_id) REFERENCES e7_assets(asset_id)
    );
    CREATE INDEX IF NOT EXISTS e7_drafts_asset_state
        ON e7_route_drafts(asset_id, state);
    CREATE TABLE IF NOT EXISTS e7_export_requests (
        request_id TEXT PRIMARY KEY,
        draft_id TEXT NOT NULL,
        operation TEXT NOT NULL,
        state TEXT NOT NULL,
        approval_id TEXT,
        error_code TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(draft_id) REFERENCES e7_route_drafts(draft_id)
    );
    CREATE TABLE IF NOT EXISTS e7_exports (
        export_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        version_id TEXT NOT NULL,
        route TEXT NOT NULL,
        route_draft_hash TEXT NOT NULL,
        format TEXT NOT NULL,
        file_hash TEXT NOT NULL,
        path TEXT NOT NULL,
        created_at TEXT NOT NULL,
        state TEXT NOT NULL,
        last_error_code TEXT,
        FOREIGN KEY(request_id) REFERENCES e7_export_requests(request_id)
    );
    CREATE INDEX IF NOT EXISTS e7_exports_asset_state ON e7_exports(asset_id, state);
    CREATE TABLE IF NOT EXISTS e7_deletion_requests (
        request_id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        confirmation_token TEXT NOT NULL,
        state TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        confirmed_at TEXT,
        completed_at TEXT,
        job_id TEXT,
        FOREIGN KEY(asset_id) REFERENCES e7_assets(asset_id)
    );
    CREATE INDEX IF NOT EXISTS e7_deletion_request_asset_state
        ON e7_deletion_requests(asset_id, state);
    CREATE TABLE IF NOT EXISTS e7_deletion_jobs (
        job_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL UNIQUE,
        asset_id TEXT NOT NULL,
        state TEXT NOT NULL,
        terminal_state TEXT,
        last_error_code TEXT,
        draft_count INTEGER NOT NULL,
        export_count INTEGER NOT NULL,
        started_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT,
        FOREIGN KEY(request_id) REFERENCES e7_deletion_requests(request_id)
    );
    CREATE TABLE IF NOT EXISTS e7_deletion_items (
        job_id TEXT NOT NULL,
        path TEXT NOT NULL,
        state TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error_code TEXT,
        PRIMARY KEY(job_id, path),
        FOREIGN KEY(job_id) REFERENCES e7_deletion_jobs(job_id)
    );
    CREATE TABLE IF NOT EXISTS e7_audit_events (
        event_id TEXT PRIMARY KEY,
        event_type TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        draft_id TEXT,
        request_id TEXT,
        state TEXT NOT NULL,
        occurred_at TEXT NOT NULL,
        details_json TEXT NOT NULL
    );
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with closing(self._connect()) as connection:
                connection.executescript(self._SCHEMA)
                connection.commit()
        except sqlite3.Error as exc:
            raise DeliveryPersistenceError("failed to initialize E7 delivery storage") from exc

    @staticmethod
    def _draft_from_row(row: sqlite3.Row) -> StoredRouteDraftV1:
        draft = StoredRouteDraftV1.model_validate_json(row["payload_json"])
        return draft.model_copy(
            update={
                "state": DraftState(row["state"]),
                "superseded_by_draft_id": (
                    UUID(row["superseded_by_draft_id"]) if row["superseded_by_draft_id"] else None
                ),
                "updated_at": datetime.fromisoformat(row["updated_at"]),
            }
        )

    def get_draft(self, draft_id: UUID) -> StoredRouteDraftV1:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT * FROM e7_route_drafts WHERE draft_id = ?", (str(draft_id),)
                ).fetchone()
        except sqlite3.Error as exc:
            raise DeliveryPersistenceError("failed to read route draft") from exc
        if row is None:
            raise DeliveryNotFoundError(f"route draft {draft_id} was not found")
        return self._draft_from_row(row)

    def get_draft_by_request(self, request_id: UUID) -> StoredRouteDraftV1 | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT * FROM e7_route_drafts WHERE create_request_id = ?",
                    (str(request_id),),
                ).fetchone()
        except sqlite3.Error as exc:
            raise DeliveryPersistenceError("failed to read draft idempotency record") from exc
        return self._draft_from_row(row) if row else None

    def save_draft(self, draft: StoredRouteDraftV1) -> StoredRouteDraftV1:
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM e7_route_drafts WHERE create_request_id = ?",
                    (str(draft.create_request_id),),
                ).fetchone()
                if existing:
                    connection.rollback()
                    return self._draft_from_row(existing)
                asset = connection.execute(
                    "SELECT lifecycle FROM e7_assets WHERE asset_id = ?",
                    (str(draft.asset_id),),
                ).fetchone()
                if asset and asset["lifecycle"] in {"DELETION_PENDING", "DELETED"}:
                    raise DeliveryConflictError("asset is locked for deletion")
                connection.execute(
                    """INSERT INTO e7_assets(asset_id, lifecycle, current_draft_id, updated_at)
                    VALUES (?, 'ACTIVE', NULL, ?)
                    ON CONFLICT(asset_id) DO UPDATE SET updated_at = excluded.updated_at""",
                    (str(draft.asset_id), draft.updated_at.isoformat()),
                )
                current_rows = connection.execute(
                    """SELECT draft_id FROM e7_route_drafts
                    WHERE asset_id = ? AND state = 'CURRENT'""",
                    (str(draft.asset_id),),
                ).fetchall()
                for current in current_rows:
                    connection.execute(
                        """UPDATE e7_route_drafts
                        SET state = 'SUPERSEDED', superseded_by_draft_id = ?, updated_at = ?
                        WHERE draft_id = ?""",
                        (
                            str(draft.draft.route_draft_id),
                            draft.updated_at.isoformat(),
                            current["draft_id"],
                        ),
                    )
                    connection.execute(
                        """UPDATE e7_exports SET state = 'SUPERSEDED'
                        WHERE request_id IN (
                            SELECT request_id FROM e7_export_requests WHERE draft_id = ?
                        ) AND state != 'DELETED'""",
                        (current["draft_id"],),
                    )
                    self._insert_audit(
                        connection,
                        event_type="ROUTE_DRAFT_SUPERSEDED",
                        asset_id=draft.asset_id,
                        draft_id=UUID(current["draft_id"]),
                        request_id=draft.create_request_id,
                        state="SUPERSEDED",
                        occurred_at=draft.updated_at,
                        details={"superseded_by": str(draft.draft.route_draft_id)},
                    )
                connection.execute(
                    """INSERT INTO e7_route_drafts(
                        draft_id, create_request_id, asset_id, version_id, route, language,
                        content_hash, state, superseded_by_draft_id, payload_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'CURRENT', NULL, ?, ?, ?)""",
                    (
                        str(draft.draft.route_draft_id),
                        str(draft.create_request_id),
                        str(draft.asset_id),
                        str(draft.draft.canonical_version_id),
                        draft.draft.route.value,
                        draft.draft.language,
                        draft.draft.content_hash,
                        draft.model_dump_json(),
                        draft.created_at.isoformat(),
                        draft.updated_at.isoformat(),
                    ),
                )
                connection.execute(
                    """UPDATE e7_assets SET current_draft_id = ?, lifecycle = 'ACTIVE',
                    updated_at = ? WHERE asset_id = ?""",
                    (
                        str(draft.draft.route_draft_id),
                        draft.updated_at.isoformat(),
                        str(draft.asset_id),
                    ),
                )
                self._insert_audit(
                    connection,
                    event_type="ROUTE_DRAFT_SAVED",
                    asset_id=draft.asset_id,
                    draft_id=draft.draft.route_draft_id,
                    request_id=draft.create_request_id,
                    state="CURRENT",
                    occurred_at=draft.created_at,
                    details={
                        "version_id": str(draft.draft.canonical_version_id),
                        "route": draft.draft.route.value,
                        "language": draft.draft.language,
                        "renderer_input_identity": draft.renderer_input_identity,
                    },
                )
                connection.commit()
        except DeliveryConflictError:
            raise
        except sqlite3.IntegrityError as exc:
            raise DeliveryConflictError("route draft identity already differs") from exc
        except sqlite3.Error as exc:
            raise DeliveryPersistenceError("failed to save route draft") from exc
        return self.get_draft(draft.draft.route_draft_id)

    @staticmethod
    def _export_from_row(row: sqlite3.Row) -> ExportRecord:
        return ExportRecord(
            export_id=UUID(row["export_id"]),
            asset_id=UUID(row["asset_id"]),
            version_id=UUID(row["version_id"]),
            route=row["route"],
            route_draft_hash=row["route_draft_hash"],
            format=row["format"],
            file_hash=row["file_hash"],
            path=row["path"],
            created_at=datetime.fromisoformat(row["created_at"]),
            state=row["state"],
        )

    def _export_snapshot(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> ExportRequestSnapshot:
        records = connection.execute(
            "SELECT * FROM e7_exports WHERE request_id = ? ORDER BY format",
            (row["request_id"],),
        ).fetchall()
        return ExportRequestSnapshot(
            request_id=UUID(row["request_id"]),
            draft_id=UUID(row["draft_id"]),
            operation=DeliveryOperation(row["operation"]),
            state=ExportRequestState(row["state"]),
            approval_id=UUID(row["approval_id"]) if row["approval_id"] else None,
            error_code=row["error_code"],
            records=[self._export_from_row(record) for record in records],
        )

    def get_export_request(self, request_id: UUID) -> ExportRequestSnapshot | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT * FROM e7_export_requests WHERE request_id = ?",
                    (str(request_id),),
                ).fetchone()
                return self._export_snapshot(connection, row) if row else None
        except sqlite3.Error as exc:
            raise DeliveryPersistenceError("failed to read export request") from exc

    def prepare_export(
        self,
        *,
        request_id: UUID,
        draft: StoredRouteDraftV1,
        operation: DeliveryOperation,
        approval_id: UUID | None,
        records: list[ExportRecord],
        now: datetime,
    ) -> ExportRequestSnapshot:
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM e7_export_requests WHERE request_id = ?",
                    (str(request_id),),
                ).fetchone()
                if existing:
                    snapshot = self._export_snapshot(connection, existing)
                    connection.rollback()
                    if (
                        snapshot.draft_id != draft.draft.route_draft_id
                        or snapshot.operation is not operation
                        or snapshot.approval_id != approval_id
                    ):
                        raise DeliveryConflictError(
                            "export request identity already has other inputs"
                        )
                    return snapshot
                current = connection.execute(
                    "SELECT state FROM e7_route_drafts WHERE draft_id = ?",
                    (str(draft.draft.route_draft_id),),
                ).fetchone()
                if current is None:
                    raise DeliveryNotFoundError("route draft was not persisted")
                if current["state"] != "CURRENT":
                    raise DeliveryConflictError("only the current route draft can be exported")
                asset = connection.execute(
                    "SELECT lifecycle FROM e7_assets WHERE asset_id = ?",
                    (str(draft.asset_id),),
                ).fetchone()
                if asset is None or asset["lifecycle"] != "ACTIVE":
                    raise DeliveryConflictError("asset is not active for export")
                connection.execute(
                    """INSERT INTO e7_export_requests(
                        request_id, draft_id, operation, state, approval_id,
                        error_code, created_at, updated_at
                    ) VALUES (?, ?, ?, 'PENDING', ?, NULL, ?, ?)""",
                    (
                        str(request_id),
                        str(draft.draft.route_draft_id),
                        operation.value,
                        str(approval_id) if approval_id else None,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
                for record in records:
                    connection.execute(
                        """INSERT INTO e7_exports(
                            export_id, request_id, asset_id, version_id, route,
                            route_draft_hash, format, file_hash, path, created_at,
                            state, last_error_code
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'FAILED', 'NOT_WRITTEN')""",
                        (
                            str(record.export_id),
                            str(request_id),
                            str(record.asset_id),
                            str(record.version_id),
                            record.route.value,
                            record.route_draft_hash,
                            record.format.value,
                            record.file_hash,
                            record.path,
                            record.created_at.isoformat(),
                        ),
                    )
                self._insert_audit(
                    connection,
                    event_type="EXPORT_REQUESTED",
                    asset_id=draft.asset_id,
                    draft_id=draft.draft.route_draft_id,
                    request_id=request_id,
                    state="PENDING",
                    occurred_at=now,
                    details={"operation": operation.value},
                )
                connection.commit()
        except (DeliveryConflictError, DeliveryNotFoundError):
            raise
        except sqlite3.Error as exc:
            raise DeliveryPersistenceError("failed to prepare export request") from exc
        snapshot = self.get_export_request(request_id)
        assert snapshot is not None
        return snapshot

    def mark_export_written(self, export_id: UUID, *, now: datetime) -> None:
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """SELECT e.request_id, r.draft_id, d.state AS draft_state
                    FROM e7_exports e
                    JOIN e7_export_requests r ON r.request_id = e.request_id
                    JOIN e7_route_drafts d ON d.draft_id = r.draft_id
                    WHERE e.export_id = ?""",
                    (str(export_id),),
                ).fetchone()
                if row is None:
                    raise DeliveryNotFoundError("export record was not prepared")
                state = "CURRENT" if row["draft_state"] == "CURRENT" else "SUPERSEDED"
                connection.execute(
                    "UPDATE e7_exports SET state = ?, last_error_code = NULL WHERE export_id = ?",
                    (state, str(export_id)),
                )
                connection.execute(
                    "UPDATE e7_export_requests SET updated_at = ? WHERE request_id = ?",
                    (now.isoformat(), row["request_id"]),
                )
                connection.commit()
        except DeliveryNotFoundError:
            raise
        except sqlite3.Error as exc:
            raise DeliveryPersistenceError("failed to mark export written") from exc

    def mark_export_failed(self, export_id: UUID, *, code: str, now: datetime) -> None:
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                updated = connection.execute(
                    """UPDATE e7_exports SET state = 'FAILED', last_error_code = ?
                    WHERE export_id = ?""",
                    (code, str(export_id)),
                )
                if updated.rowcount != 1:
                    raise DeliveryNotFoundError("export record was not prepared")
                connection.execute(
                    """UPDATE e7_export_requests SET state = 'FAILED', error_code = ?,
                    updated_at = ? WHERE request_id = (
                        SELECT request_id FROM e7_exports WHERE export_id = ?
                    )""",
                    (code, now.isoformat(), str(export_id)),
                )
                connection.commit()
        except DeliveryNotFoundError:
            raise
        except sqlite3.Error as exc:
            raise DeliveryPersistenceError("failed to mark export failure") from exc

    def finish_export_request(
        self,
        request_id: UUID,
        *,
        state: ExportRequestState,
        error_code: str | None,
        now: datetime,
    ) -> ExportRequestSnapshot:
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """SELECT r.*, d.asset_id FROM e7_export_requests r
                    JOIN e7_route_drafts d ON d.draft_id = r.draft_id
                    WHERE r.request_id = ?""",
                    (str(request_id),),
                ).fetchone()
                if row is None:
                    raise DeliveryNotFoundError("export request was not prepared")
                connection.execute(
                    """UPDATE e7_export_requests SET state = ?, error_code = ?, updated_at = ?
                    WHERE request_id = ?""",
                    (state.value, error_code, now.isoformat(), str(request_id)),
                )
                self._insert_audit(
                    connection,
                    event_type="EXPORT_COMPLETED"
                    if state is ExportRequestState.COMPLETE
                    else "EXPORT_FAILED",
                    asset_id=UUID(row["asset_id"]),
                    draft_id=UUID(row["draft_id"]),
                    request_id=request_id,
                    state=state.value,
                    occurred_at=now,
                    details={"error_code": error_code},
                )
                connection.commit()
        except (DeliveryNotFoundError, DeliveryConflictError):
            raise
        except sqlite3.Error as exc:
            raise DeliveryPersistenceError("failed to finish export request") from exc
        snapshot = self.get_export_request(request_id)
        assert snapshot is not None
        return snapshot

    def list_exports(
        self, *, asset_id: UUID | None = None, draft_id: UUID | None = None
    ) -> list[ExportRecord]:
        if (asset_id is None) == (draft_id is None):
            raise ValueError("provide exactly one of asset_id or draft_id")
        query = "SELECT * FROM e7_exports WHERE asset_id = ? ORDER BY created_at, format"
        params = (str(asset_id),)
        if draft_id:
            query = """SELECT e.* FROM e7_exports e JOIN e7_export_requests r
                ON r.request_id = e.request_id WHERE r.draft_id = ?
                ORDER BY e.created_at, e.format"""
            params = (str(draft_id),)
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(query, params).fetchall()
        except sqlite3.Error as exc:
            raise DeliveryPersistenceError("failed to list exports") from exc
        return [self._export_from_row(row) for row in rows]

    def create_deletion_request(self, request: DeletionRequestV1) -> DeletionRequestV1:
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM e7_deletion_requests WHERE request_id = ?",
                    (str(request.request_id),),
                ).fetchone()
                if existing:
                    persisted = self._deletion_request_from_row(existing)
                    if persisted.asset_id != request.asset_id:
                        raise DeliveryConflictError(
                            "deletion request identity already has another asset"
                        )
                    if (
                        persisted.state is DeletionRequestState.REQUESTED
                        and request.created_at > persisted.expires_at
                    ):
                        self._expire_deletion_request(
                            connection,
                            request_id=persisted.request_id,
                            asset_id=persisted.asset_id,
                            expires_at=persisted.expires_at,
                            now=request.created_at,
                        )
                        connection.commit()
                        return self.get_deletion_request(request.request_id)
                    connection.rollback()
                    return persisted
                asset = connection.execute(
                    "SELECT lifecycle FROM e7_assets WHERE asset_id = ?",
                    (str(request.asset_id),),
                ).fetchone()
                if asset is None:
                    raise DeliveryNotFoundError("asset has no E7-managed delivery state")
                if asset["lifecycle"] == "DELETED":
                    raise DeliveryConflictError("asset is already deleted")
                stale_requests = connection.execute(
                    """SELECT request_id, expires_at FROM e7_deletion_requests
                    WHERE asset_id = ? AND state = 'REQUESTED'""",
                    (str(request.asset_id),),
                ).fetchall()
                for stale in stale_requests:
                    expires_at = datetime.fromisoformat(stale["expires_at"])
                    if request.created_at > expires_at:
                        self._expire_deletion_request(
                            connection,
                            request_id=UUID(stale["request_id"]),
                            asset_id=request.asset_id,
                            expires_at=expires_at,
                            now=request.created_at,
                        )
                active = connection.execute(
                    """SELECT request_id FROM e7_deletion_requests
                    WHERE asset_id = ? AND state IN ('REQUESTED', 'CONFIRMED')""",
                    (str(request.asset_id),),
                ).fetchone()
                if active:
                    raise DeliveryConflictError(
                        f"asset already has deletion request {active['request_id']}"
                    )
                connection.execute(
                    """INSERT INTO e7_deletion_requests(
                        request_id, asset_id, confirmation_token, state, created_at,
                        expires_at, confirmed_at, completed_at, job_id
                    ) VALUES (?, ?, ?, 'REQUESTED', ?, ?, NULL, NULL, NULL)""",
                    (
                        str(request.request_id),
                        str(request.asset_id),
                        request.confirmation_token,
                        request.created_at.isoformat(),
                        request.expires_at.isoformat(),
                    ),
                )
                self._insert_audit(
                    connection,
                    event_type="DELETION_REQUESTED",
                    asset_id=request.asset_id,
                    draft_id=None,
                    request_id=request.request_id,
                    state="REQUESTED",
                    occurred_at=request.created_at,
                    details={"expires_at": request.expires_at.isoformat()},
                )
                connection.commit()
        except (DeliveryConflictError, DeliveryNotFoundError):
            raise
        except sqlite3.Error as exc:
            raise DeliveryPersistenceError("failed to create deletion request") from exc
        return self.get_deletion_request(request.request_id)

    @staticmethod
    def _deletion_request_from_row(row: sqlite3.Row) -> DeletionRequestV1:
        return DeletionRequestV1(
            request_id=UUID(row["request_id"]),
            asset_id=UUID(row["asset_id"]),
            state=DeletionRequestState(row["state"]),
            confirmation_token=row["confirmation_token"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            confirmed_at=(
                datetime.fromisoformat(row["confirmed_at"]) if row["confirmed_at"] else None
            ),
            completed_at=(
                datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None
            ),
            job_id=UUID(row["job_id"]) if row["job_id"] else None,
        )

    def get_deletion_request(self, request_id: UUID) -> DeletionRequestV1:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT * FROM e7_deletion_requests WHERE request_id = ?",
                    (str(request_id),),
                ).fetchone()
        except sqlite3.Error as exc:
            raise DeliveryPersistenceError("failed to read deletion request") from exc
        if row is None:
            raise DeliveryNotFoundError("deletion request was not found")
        return self._deletion_request_from_row(row)

    def begin_deletion(
        self,
        request_id: UUID,
        *,
        confirmation_token: str,
        now: datetime,
        job_id: UUID,
    ) -> DeletionJobSnapshot:
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                request = connection.execute(
                    "SELECT * FROM e7_deletion_requests WHERE request_id = ?",
                    (str(request_id),),
                ).fetchone()
                if request is None:
                    raise DeliveryNotFoundError("deletion request was not found")
                if request["confirmation_token"] != confirmation_token:
                    raise DeliveryConflictError("deletion confirmation token does not match")
                if request["state"] == "EXPIRED":
                    raise DeliveryConflictError("deletion request expired before confirmation")
                if request["state"] == "REQUESTED" and now > datetime.fromisoformat(
                    request["expires_at"]
                ):
                    self._expire_deletion_request(
                        connection,
                        request_id=request_id,
                        asset_id=UUID(request["asset_id"]),
                        expires_at=datetime.fromisoformat(request["expires_at"]),
                        now=now,
                    )
                    connection.commit()
                    raise DeliveryConflictError("deletion request expired before confirmation")
                existing = connection.execute(
                    "SELECT * FROM e7_deletion_jobs WHERE request_id = ?",
                    (str(request_id),),
                ).fetchone()
                if existing:
                    snapshot = self._job_snapshot(connection, existing)
                    connection.rollback()
                    return snapshot
                asset_id = UUID(request["asset_id"])
                paths = connection.execute(
                    """SELECT DISTINCT path FROM e7_exports
                    WHERE asset_id = ? AND state != 'DELETED'""",
                    (str(asset_id),),
                ).fetchall()
                draft_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM e7_route_drafts WHERE asset_id = ?",
                    (str(asset_id),),
                ).fetchone()["count"]
                export_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM e7_exports WHERE asset_id = ?",
                    (str(asset_id),),
                ).fetchone()["count"]
                connection.execute(
                    """INSERT INTO e7_deletion_jobs(
                        job_id, request_id, asset_id, state, terminal_state,
                        last_error_code, draft_count, export_count, started_at,
                        updated_at, completed_at
                    ) VALUES (?, ?, ?, 'FILES_PENDING', NULL, NULL, ?, ?, ?, ?, NULL)""",
                    (
                        str(job_id),
                        str(request_id),
                        str(asset_id),
                        draft_count,
                        export_count,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
                for path in paths:
                    connection.execute(
                        """INSERT INTO e7_deletion_items(
                            job_id, path, state, attempts, last_error_code
                        )
                        VALUES (?, ?, 'PENDING', 0, NULL)""",
                        (str(job_id), path["path"]),
                    )
                connection.execute(
                    """UPDATE e7_deletion_requests SET state = 'CONFIRMED', confirmed_at = ?,
                    job_id = ? WHERE request_id = ?""",
                    (now.isoformat(), str(job_id), str(request_id)),
                )
                connection.execute(
                    """UPDATE e7_assets SET lifecycle = 'DELETION_PENDING', updated_at = ?
                    WHERE asset_id = ?""",
                    (now.isoformat(), str(asset_id)),
                )
                self._insert_audit(
                    connection,
                    event_type="DELETION_CONFIRMED",
                    asset_id=asset_id,
                    draft_id=None,
                    request_id=request_id,
                    state="FILES_PENDING",
                    occurred_at=now,
                    details={"managed_file_count": len(paths)},
                )
                connection.commit()
        except (DeliveryConflictError, DeliveryNotFoundError):
            raise
        except sqlite3.Error as exc:
            raise DeliveryPersistenceError("failed to begin confirmed deletion") from exc
        return self.get_deletion_job(request_id)

    @staticmethod
    def _deletion_item_from_row(row: sqlite3.Row) -> DeletionItemV1:
        return DeletionItemV1(
            path=row["path"],
            state=DeletionItemState(row["state"]),
            attempts=row["attempts"],
            last_error_code=row["last_error_code"],
        )

    def _job_snapshot(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> DeletionJobSnapshot:
        items = connection.execute(
            "SELECT * FROM e7_deletion_items WHERE job_id = ? ORDER BY path",
            (row["job_id"],),
        ).fetchall()
        return DeletionJobSnapshot(
            job_id=UUID(row["job_id"]),
            request_id=UUID(row["request_id"]),
            asset_id=UUID(row["asset_id"]),
            state=DeletionJobState(row["state"]),
            terminal_state=row["terminal_state"],
            last_error_code=row["last_error_code"],
            draft_count=row["draft_count"],
            export_count=row["export_count"],
            items=[self._deletion_item_from_row(item) for item in items],
        )

    def get_deletion_job(self, request_id: UUID) -> DeletionJobSnapshot:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT * FROM e7_deletion_jobs WHERE request_id = ?",
                    (str(request_id),),
                ).fetchone()
                if row is None:
                    raise DeliveryNotFoundError("deletion job was not found")
                return self._job_snapshot(connection, row)
        except DeliveryNotFoundError:
            raise
        except sqlite3.Error as exc:
            raise DeliveryPersistenceError("failed to read deletion job") from exc

    def mark_deletion_item(
        self,
        job_id: UUID,
        path: str,
        *,
        state: DeletionItemState,
        error_code: str | None,
        now: datetime,
    ) -> None:
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                updated = connection.execute(
                    """UPDATE e7_deletion_items SET state = ?, attempts = attempts + 1,
                    last_error_code = ? WHERE job_id = ? AND path = ?""",
                    (state.value, error_code, str(job_id), path),
                )
                if updated.rowcount != 1:
                    raise DeliveryNotFoundError("deletion item was not found")
                connection.execute(
                    "UPDATE e7_deletion_jobs SET updated_at = ? WHERE job_id = ?",
                    (now.isoformat(), str(job_id)),
                )
                connection.commit()
        except DeliveryNotFoundError:
            raise
        except sqlite3.Error as exc:
            raise DeliveryPersistenceError("failed to persist deletion item result") from exc

    def mark_deletion_job(
        self,
        request_id: UUID,
        *,
        state: DeletionJobState,
        terminal_state: str | None,
        error_code: str | None,
        now: datetime,
    ) -> DeletionJobSnapshot:
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM e7_deletion_jobs WHERE request_id = ?",
                    (str(request_id),),
                ).fetchone()
                if row is None:
                    raise DeliveryNotFoundError("deletion job was not found")
                connection.execute(
                    """UPDATE e7_deletion_jobs SET state = ?, terminal_state = ?,
                    last_error_code = ?, updated_at = ? WHERE request_id = ?""",
                    (state.value, terminal_state, error_code, now.isoformat(), str(request_id)),
                )
                self._insert_audit(
                    connection,
                    event_type=(
                        "DELETION_PARTIAL_FAILURE"
                        if state is DeletionJobState.PARTIAL_FAILURE
                        else "DELETION_FILES_REMOVED"
                    ),
                    asset_id=UUID(row["asset_id"]),
                    draft_id=None,
                    request_id=request_id,
                    state=state.value,
                    occurred_at=now,
                    details={"error_code": error_code},
                )
                connection.commit()
        except DeliveryNotFoundError:
            raise
        except sqlite3.Error as exc:
            raise DeliveryPersistenceError("failed to update deletion job") from exc
        return self.get_deletion_job(request_id)

    def finalize_deletion(self, request_id: UUID, *, now: datetime) -> DeletionJobSnapshot:
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                job = connection.execute(
                    "SELECT * FROM e7_deletion_jobs WHERE request_id = ?",
                    (str(request_id),),
                ).fetchone()
                if job is None:
                    raise DeliveryNotFoundError("deletion job was not found")
                if job["state"] == "COMPLETED":
                    snapshot = self._job_snapshot(connection, job)
                    connection.rollback()
                    return snapshot
                remaining = connection.execute(
                    """SELECT COUNT(*) AS count FROM e7_deletion_items
                    WHERE job_id = ? AND state != 'DELETED'""",
                    (job["job_id"],),
                ).fetchone()["count"]
                if remaining:
                    raise DeliveryConflictError("managed files remain before final deletion")
                asset_id = UUID(job["asset_id"])
                connection.execute("DELETE FROM e7_exports WHERE asset_id = ?", (str(asset_id),))
                connection.execute(
                    """DELETE FROM e7_export_requests WHERE draft_id IN (
                        SELECT draft_id FROM e7_route_drafts WHERE asset_id = ?
                    )""",
                    (str(asset_id),),
                )
                connection.execute(
                    "DELETE FROM e7_route_drafts WHERE asset_id = ?", (str(asset_id),)
                )
                connection.execute(
                    """UPDATE e7_assets SET lifecycle = 'DELETED', current_draft_id = NULL,
                    updated_at = ? WHERE asset_id = ?""",
                    (now.isoformat(), str(asset_id)),
                )
                connection.execute(
                    """UPDATE e7_deletion_requests SET state = 'COMPLETED', completed_at = ?
                    WHERE request_id = ?""",
                    (now.isoformat(), str(request_id)),
                )
                connection.execute(
                    """UPDATE e7_deletion_jobs SET state = 'COMPLETED',
                    terminal_state = 'SUCCEEDED', last_error_code = NULL,
                    updated_at = ?, completed_at = ? WHERE request_id = ?""",
                    (now.isoformat(), now.isoformat(), str(request_id)),
                )
                self._insert_audit(
                    connection,
                    event_type="DELETION_COMPLETED",
                    asset_id=asset_id,
                    draft_id=None,
                    request_id=request_id,
                    state="COMPLETED",
                    occurred_at=now,
                    details={
                        "deleted_draft_count": job["draft_count"],
                        "deleted_export_count": job["export_count"],
                    },
                )
                connection.commit()
        except (DeliveryNotFoundError, DeliveryConflictError):
            raise
        except sqlite3.Error as exc:
            raise DeliveryPersistenceError("failed to finalize deletion") from exc
        return self.get_deletion_job(request_id)

    def record_failure_best_effort(
        self,
        *,
        asset_id: UUID,
        request_id: UUID,
        event_type: str,
        state: str,
        code: str,
        now: datetime,
    ) -> None:
        try:
            with closing(self._connect()) as connection:
                self._insert_audit(
                    connection,
                    event_type=event_type,
                    asset_id=asset_id,
                    draft_id=None,
                    request_id=request_id,
                    state=state,
                    occurred_at=now,
                    details={"error_code": code},
                )
                connection.commit()
        except sqlite3.Error:
            return

    def _expire_deletion_request(
        self,
        connection: sqlite3.Connection,
        *,
        request_id: UUID,
        asset_id: UUID,
        expires_at: datetime,
        now: datetime,
    ) -> None:
        connection.execute(
            """UPDATE e7_deletion_requests SET state = 'EXPIRED'
            WHERE request_id = ? AND state = 'REQUESTED'""",
            (str(request_id),),
        )
        self._insert_audit(
            connection,
            event_type="DELETION_REQUEST_EXPIRED",
            asset_id=asset_id,
            draft_id=None,
            request_id=request_id,
            state="EXPIRED",
            occurred_at=now,
            details={"expires_at": expires_at.isoformat()},
        )

    def list_audit_events(self, asset_id: UUID) -> list[AuditEventV1]:
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    """SELECT * FROM e7_audit_events WHERE asset_id = ?
                    ORDER BY occurred_at, rowid""",
                    (str(asset_id),),
                ).fetchall()
        except sqlite3.Error as exc:
            raise DeliveryPersistenceError("failed to list audit events") from exc
        return [
            AuditEventV1(
                event_id=UUID(row["event_id"]),
                event_type=row["event_type"],
                asset_id=UUID(row["asset_id"]),
                draft_id=UUID(row["draft_id"]) if row["draft_id"] else None,
                request_id=UUID(row["request_id"]) if row["request_id"] else None,
                state=row["state"],
                occurred_at=datetime.fromisoformat(row["occurred_at"]),
                details=json.loads(row["details_json"]),
            )
            for row in rows
        ]

    def content_counts(self, asset_id: UUID) -> tuple[int, int]:
        with closing(self._connect()) as connection:
            drafts = connection.execute(
                "SELECT COUNT(*) AS count FROM e7_route_drafts WHERE asset_id = ?",
                (str(asset_id),),
            ).fetchone()["count"]
            exports = connection.execute(
                "SELECT COUNT(*) AS count FROM e7_exports WHERE asset_id = ?",
                (str(asset_id),),
            ).fetchone()["count"]
        return drafts, exports

    @staticmethod
    def _insert_audit(
        connection: sqlite3.Connection,
        *,
        event_type: str,
        asset_id: UUID,
        draft_id: UUID | None,
        request_id: UUID | None,
        state: str,
        occurred_at: datetime,
        details: dict[str, str | int | bool | None],
    ) -> None:
        connection.execute(
            """INSERT INTO e7_audit_events(
                event_id, event_type, asset_id, draft_id, request_id,
                state, occurred_at, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()),
                event_type,
                str(asset_id),
                str(draft_id) if draft_id else None,
                str(request_id) if request_id else None,
                state,
                occurred_at.isoformat(),
                json.dumps(details, sort_keys=True, separators=(",", ":")),
            ),
        )
