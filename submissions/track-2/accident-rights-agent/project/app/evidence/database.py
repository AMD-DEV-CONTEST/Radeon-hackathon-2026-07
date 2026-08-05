"""SQLite persistence for the accident evidence graph."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from app.schemas.evidence import (
    EvidenceConflict,
    EvidenceNode,
    Fact,
    ProcessingStatus,
    SourceFile,
    TimelineEvent,
    utc_now,
)

SCHEMA_VERSION = 1


class EvidenceStore:
    """A per-case SQLite store with foreign keys and WAL durability."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self, case_id: str) -> None:
        with self.transaction() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_files (
                    source_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL REFERENCES cases(case_id),
                    original_name TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    role TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    failure_reason TEXT NOT NULL DEFAULT '',
                    UNIQUE(case_id, sha256)
                );
                CREATE TABLE IF NOT EXISTS evidence_nodes (
                    node_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL REFERENCES cases(case_id),
                    source_id TEXT NOT NULL REFERENCES source_files(source_id),
                    node_type TEXT NOT NULL,
                    locator_json TEXT NOT NULL,
                    content TEXT,
                    content_sha256 TEXT,
                    confidence REAL NOT NULL,
                    extraction_method TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS facts (
                    fact_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL REFERENCES cases(case_id),
                    statement TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    extraction_method TEXT NOT NULL,
                    model TEXT,
                    uncertainty TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fact_sources (
                    fact_id TEXT NOT NULL REFERENCES facts(fact_id) ON DELETE CASCADE,
                    node_id TEXT NOT NULL REFERENCES evidence_nodes(node_id),
                    PRIMARY KEY(fact_id, node_id)
                );
                CREATE TABLE IF NOT EXISTS timeline_events (
                    event_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL REFERENCES cases(case_id),
                    label TEXT NOT NULL,
                    relative_order INTEGER NOT NULL,
                    timestamp_seconds REAL,
                    confidence REAL NOT NULL,
                    source_node_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conflicts (
                    conflict_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL REFERENCES cases(case_id),
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    fact_ids_json TEXT NOT NULL,
                    description TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS processing_runs (
                    run_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL REFERENCES cases(case_id),
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    failure_reason TEXT NOT NULL DEFAULT '',
                    next_step TEXT NOT NULL DEFAULT '',
                    details_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL REFERENCES cases(case_id),
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_nodes_source
                    ON evidence_nodes(source_id);
                CREATE INDEX IF NOT EXISTS idx_facts_case
                    ON facts(case_id);
                """
            )
            now = utc_now()
            db.execute(
                "INSERT OR IGNORE INTO schema_meta(key, value) VALUES('version', ?)",
                (str(SCHEMA_VERSION),),
            )
            db.execute(
                """
                INSERT OR IGNORE INTO cases(case_id, created_at, updated_at, status)
                VALUES(?, ?, ?, 'open')
                """,
                (case_id, now, now),
            )

    def add_source(self, source: SourceFile) -> SourceFile:
        with self.transaction() as db:
            existing = db.execute(
                "SELECT * FROM source_files WHERE case_id = ? AND sha256 = ?",
                (source.case_id, source.sha256),
            ).fetchone()
            if existing:
                return self._source_from_row(existing)
            db.execute(
                """
                INSERT INTO source_files(
                    source_id, case_id, original_name, stored_path, media_type,
                    kind, role, sha256, size_bytes, created_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source.source_id,
                    source.case_id,
                    source.original_name,
                    source.stored_path,
                    source.media_type,
                    source.kind.value,
                    source.role.value,
                    source.sha256,
                    source.size_bytes,
                    source.created_at,
                    source.status.value,
                ),
            )
            self._audit_in_transaction(
                db, source.case_id, "source_registered", source.to_dict()
            )
        return source

    def list_sources(self, case_id: str) -> list[SourceFile]:
        with self.transaction() as db:
            rows = db.execute(
                "SELECT * FROM source_files WHERE case_id = ? ORDER BY created_at, source_id",
                (case_id,),
            ).fetchall()
        return [self._source_from_row(row) for row in rows]

    def get_source(self, source_id: str) -> SourceFile:
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM source_files WHERE source_id = ?", (source_id,)
            ).fetchone()
        if row is None:
            raise KeyError(source_id)
        return self._source_from_row(row)

    def update_source_status(
        self,
        source_id: str,
        status: ProcessingStatus,
        failure_reason: str = "",
    ) -> None:
        with self.transaction() as db:
            db.execute(
                """
                UPDATE source_files SET status = ?, failure_reason = ?
                WHERE source_id = ?
                """,
                (status.value, failure_reason, source_id),
            )

    def update_source_role(self, source_id: str, role: Any) -> SourceFile:
        with self.transaction() as db:
            row = db.execute(
                "SELECT case_id FROM source_files WHERE source_id = ?", (source_id,)
            ).fetchone()
            if row is None:
                raise KeyError(source_id)
            db.execute(
                "UPDATE source_files SET role = ? WHERE source_id = ?",
                (role.value, source_id),
            )
            self._audit_in_transaction(
                db,
                row["case_id"],
                "source_role_updated",
                {"source_id": source_id, "role": role.value},
                "case_intake",
            )
        return self.get_source(source_id)

    def repair_synthetic_source_integrity(
        self,
        source_id: str,
        *,
        sha256: str,
        size_bytes: int,
        old_sha256: str,
        old_size_bytes: int,
    ) -> SourceFile:
        """Update integrity metadata only for an explicitly synthetic fixture.

        Real evidence is immutable. This narrow repair path exists solely to
        migrate early demo PDFs that contained a signature but no valid PDF
        object/xref structure.
        """

        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM source_files WHERE source_id = ?", (source_id,)
            ).fetchone()
            if row is None:
                raise KeyError(source_id)
            if not str(row["original_name"]).endswith("-synthetic.pdf"):
                raise PermissionError(
                    "Only declared synthetic PDF fixtures may be repaired."
                )
            db.execute(
                """
                UPDATE source_files SET sha256 = ?, size_bytes = ?
                WHERE source_id = ?
                """,
                (sha256, size_bytes, source_id),
            )
            self._audit_in_transaction(
                db,
                str(row["case_id"]),
                "synthetic_pdf_repaired",
                {
                    "source_id": source_id,
                    "original_name": row["original_name"],
                    "old_sha256": old_sha256,
                    "new_sha256": sha256,
                    "old_size_bytes": old_size_bytes,
                    "new_size_bytes": size_bytes,
                    "synthetic": True,
                },
                "experience_fixture_repair",
            )
        return self.get_source(source_id)

    def migrate_synthetic_source_media(
        self,
        source_id: str,
        *,
        original_name: str,
        stored_path: str,
        media_type: str,
        kind: str,
        sha256: str,
        size_bytes: int,
    ) -> SourceFile:
        """Replace only a declared legacy demo media source."""

        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM source_files WHERE source_id = ?", (source_id,)
            ).fetchone()
            if row is None:
                raise KeyError(source_id)
            old_name = str(row["original_name"])
            legacy_pdf = old_name.endswith("-synthetic.pdf")
            legacy_avi = str(row["role"]) == "dashcam_video" and old_name.endswith(
                "-synthetic.avi"
            )
            if not (legacy_pdf or legacy_avi):
                raise PermissionError(
                    "Only declared legacy synthetic media may be replaced."
                )
            if str(row["role"]) not in {
                "scene_photo",
                "dashcam_video",
                "road_signal_evidence",
            }:
                raise PermissionError(
                    "Only synthetic photo/video role fixtures may change media type."
                )
            db.execute(
                """
                UPDATE source_files
                SET original_name = ?, stored_path = ?, media_type = ?, kind = ?,
                    sha256 = ?, size_bytes = ?
                WHERE source_id = ?
                """,
                (
                    original_name,
                    stored_path,
                    media_type,
                    kind,
                    sha256,
                    size_bytes,
                    source_id,
                ),
            )
            self._audit_in_transaction(
                db,
                str(row["case_id"]),
                "synthetic_media_upgraded",
                {
                    "source_id": source_id,
                    "role": row["role"],
                    "old_original_name": row["original_name"],
                    "new_original_name": original_name,
                    "old_kind": row["kind"],
                    "new_kind": kind,
                    "old_sha256": row["sha256"],
                    "new_sha256": sha256,
                    "synthetic": True,
                },
                "experience_fixture_upgrade",
            )
        return self.get_source(source_id)

    def add_node(self, node: EvidenceNode) -> None:
        with self.transaction() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO evidence_nodes(
                    node_id, case_id, source_id, node_type, locator_json, content,
                    content_sha256, confidence, extraction_method, metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.node_id,
                    node.case_id,
                    node.source_id,
                    node.node_type,
                    _json(node.locator),
                    node.content,
                    node.content_sha256,
                    node.confidence,
                    node.extraction_method,
                    _json(node.metadata),
                    node.created_at,
                ),
            )

    def clear_source_derivatives(self, source_id: str) -> None:
        """Remove regenerable nodes/facts before a deterministic re-run."""

        with self.transaction() as db:
            fact_rows = db.execute(
                """
                SELECT DISTINCT fs.fact_id
                FROM fact_sources fs
                JOIN evidence_nodes en ON en.node_id = fs.node_id
                WHERE en.source_id = ?
                """,
                (source_id,),
            ).fetchall()
            if fact_rows:
                db.executemany(
                    "DELETE FROM facts WHERE fact_id = ?",
                    [(row["fact_id"],) for row in fact_rows],
                )
            db.execute("DELETE FROM evidence_nodes WHERE source_id = ?", (source_id,))

    def list_nodes(
        self, case_id: str, source_id: str | None = None
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM evidence_nodes WHERE case_id = ?"
        parameters: list[Any] = [case_id]
        if source_id:
            query += " AND source_id = ?"
            parameters.append(source_id)
        query += " ORDER BY source_id, node_id"
        with self.transaction() as db:
            rows = db.execute(query, parameters).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            locator = json.loads(item.pop("locator_json"))
            metadata = json.loads(item.pop("metadata_json"))
            result.append({**item, "locator": locator, "metadata": metadata})
        return result

    def add_fact(self, fact: Fact) -> None:
        with self.transaction() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO facts(
                    fact_id, case_id, statement, subject, predicate, value,
                    confidence, status, extraction_method, model, uncertainty,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact.fact_id,
                    fact.case_id,
                    fact.statement,
                    fact.subject,
                    fact.predicate,
                    fact.value,
                    fact.confidence,
                    fact.status.value,
                    fact.extraction_method,
                    fact.model,
                    fact.uncertainty,
                    fact.created_at,
                ),
            )
            db.execute("DELETE FROM fact_sources WHERE fact_id = ?", (fact.fact_id,))
            db.executemany(
                "INSERT INTO fact_sources(fact_id, node_id) VALUES(?, ?)",
                [(fact.fact_id, node_id) for node_id in fact.source_node_ids],
            )

    def list_facts(self, case_id: str) -> list[dict[str, Any]]:
        with self.transaction() as db:
            rows = db.execute(
                "SELECT * FROM facts WHERE case_id = ? ORDER BY created_at, fact_id",
                (case_id,),
            ).fetchall()
            result = []
            for row in rows:
                source_rows = db.execute(
                    "SELECT node_id FROM fact_sources WHERE fact_id = ? ORDER BY node_id",
                    (row["fact_id"],),
                ).fetchall()
                result.append(
                    {
                        **dict(row),
                        "source_node_ids": [item["node_id"] for item in source_rows],
                    }
                )
        return result

    def replace_timeline(self, case_id: str, events: list[TimelineEvent]) -> None:
        with self.transaction() as db:
            db.execute("DELETE FROM timeline_events WHERE case_id = ?", (case_id,))
            db.executemany(
                """
                INSERT INTO timeline_events(
                    event_id, case_id, label, relative_order, timestamp_seconds,
                    confidence, source_node_ids_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        event.event_id,
                        event.case_id,
                        event.label,
                        event.relative_order,
                        event.timestamp_seconds,
                        event.confidence,
                        _json(list(event.source_node_ids)),
                        event.created_at,
                    )
                    for event in events
                ],
            )

    def replace_conflicts(
        self, case_id: str, conflicts: list[EvidenceConflict]
    ) -> None:
        with self.transaction() as db:
            db.execute("DELETE FROM conflicts WHERE case_id = ?", (case_id,))
            db.executemany(
                """
                INSERT INTO conflicts(
                    conflict_id, case_id, subject, predicate, fact_ids_json,
                    description, severity, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        conflict.conflict_id,
                        conflict.case_id,
                        conflict.subject,
                        conflict.predicate,
                        _json(list(conflict.fact_ids)),
                        conflict.description,
                        conflict.severity,
                        conflict.created_at,
                    )
                    for conflict in conflicts
                ],
            )

    def start_run(self, run_id: str, case_id: str, stage: str) -> None:
        with self.transaction() as db:
            db.execute(
                """
                INSERT INTO processing_runs(
                    run_id, case_id, stage, status, started_at
                ) VALUES (?, ?, ?, 'running', ?)
                """,
                (run_id, case_id, stage, utc_now()),
            )

    def finish_run(
        self,
        run_id: str,
        status: str,
        *,
        failure_reason: str = "",
        next_step: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        with self.transaction() as db:
            db.execute(
                """
                UPDATE processing_runs
                SET status = ?, finished_at = ?, failure_reason = ?,
                    next_step = ?, details_json = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    utc_now(),
                    failure_reason,
                    next_step,
                    _json(details or {}),
                    run_id,
                ),
            )

    def audit(
        self, case_id: str, event_type: str, payload: dict[str, Any], actor: str
    ) -> str:
        with self.transaction() as db:
            return self._audit_in_transaction(db, case_id, event_type, payload, actor)

    def list_audit_events(self, case_id: str) -> list[dict[str, Any]]:
        with self.transaction() as db:
            rows = db.execute(
                """
                SELECT id, case_id, event_type, actor, payload_json, created_at
                FROM audit_events WHERE case_id = ? ORDER BY id
                """,
                (case_id,),
            ).fetchall()
        return [
            {
                **{
                    key: value
                    for key, value in dict(row).items()
                    if key != "payload_json"
                },
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def export_case(self, case_id: str) -> dict[str, Any]:
        with self.transaction() as db:
            case = db.execute(
                "SELECT * FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone()
            timeline = db.execute(
                "SELECT * FROM timeline_events WHERE case_id = ? ORDER BY relative_order",
                (case_id,),
            ).fetchall()
            conflicts = db.execute(
                "SELECT * FROM conflicts WHERE case_id = ? ORDER BY conflict_id",
                (case_id,),
            ).fetchall()
            runs = db.execute(
                "SELECT * FROM processing_runs WHERE case_id = ? ORDER BY started_at",
                (case_id,),
            ).fetchall()
        if case is None:
            raise KeyError(case_id)
        return {
            "case": dict(case),
            "sources": [item.to_dict() for item in self.list_sources(case_id)],
            "evidence_nodes": self.list_nodes(case_id),
            "facts": self.list_facts(case_id),
            "timeline": [_timeline_row(row) for row in timeline],
            "conflicts": [_conflict_row(row) for row in conflicts],
            "processing_runs": [_run_row(row) for row in runs],
            "audit_events": self.list_audit_events(case_id),
        }

    @staticmethod
    def _source_from_row(row: sqlite3.Row) -> SourceFile:
        from app.schemas.evidence import SourceKind, SourceRole

        return SourceFile(
            source_id=row["source_id"],
            case_id=row["case_id"],
            original_name=row["original_name"],
            stored_path=row["stored_path"],
            media_type=row["media_type"],
            kind=SourceKind(row["kind"]),
            role=SourceRole(row["role"]),
            sha256=row["sha256"],
            size_bytes=row["size_bytes"],
            created_at=row["created_at"],
            status=ProcessingStatus(row["status"]),
        )

    @staticmethod
    def _audit_in_transaction(
        db: sqlite3.Connection,
        case_id: str,
        event_type: str,
        payload: dict[str, Any],
        actor: str = "system",
    ) -> str:
        cursor = db.execute(
            """
            INSERT INTO audit_events(case_id, event_type, actor, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (case_id, event_type, actor, _json(payload), utc_now()),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("Audit insert did not return a row ID.")
        return f"AUDIT-{cursor.lastrowid}"


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: item.value if isinstance(item, Enum) else str(item),
    )


def _timeline_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    source_node_ids = json.loads(item.pop("source_node_ids_json"))
    return {**item, "source_node_ids": source_node_ids}


def _conflict_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    fact_ids = json.loads(item.pop("fact_ids_json"))
    return {**item, "fact_ids": fact_ids}


def _run_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    details = json.loads(item.pop("details_json"))
    return {**item, "details": details}
