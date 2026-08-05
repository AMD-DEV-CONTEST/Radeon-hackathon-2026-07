"""Append-only case memory stored beside the existing Evidence Graph."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.schemas.memory import (
    CaseCapsule,
    FactTransitionEvent,
    MemoryEvent,
    MemoryFactStatus,
    utc_now,
)


class CaseMemoryStore:
    def __init__(self, path: Path | str, case_id: str):
        self.path = Path(path)
        self.case_id = case_id

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        db = self.connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self) -> None:
        with self.transaction() as db:
            case = db.execute(
                "SELECT 1 FROM cases WHERE case_id = ?", (self.case_id,)
            ).fetchone()
            if case is None:
                raise KeyError(f"Unknown case: {self.case_id}")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_events (
                    event_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL REFERENCES cases(case_id),
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(case_id, version)
                );
                CREATE TABLE IF NOT EXISTS memory_fact_state (
                    case_id TEXT NOT NULL REFERENCES cases(case_id),
                    fact_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    PRIMARY KEY(case_id, fact_id)
                );
                CREATE TABLE IF NOT EXISTS case_capsules (
                    case_id TEXT NOT NULL REFERENCES cases(case_id),
                    version INTEGER NOT NULL,
                    capsule_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(case_id, version)
                );
                CREATE TABLE IF NOT EXISTS working_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL REFERENCES cases(case_id),
                    node_name TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    before_tokens INTEGER NOT NULL,
                    after_tokens INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def next_version(self, db: sqlite3.Connection | None = None) -> int:
        if db is not None:
            row = db.execute(
                "SELECT COALESCE(MAX(version), 0) AS version "
                "FROM memory_events WHERE case_id = ?",
                (self.case_id,),
            ).fetchone()
            return int(row["version"]) + 1
        with self.transaction() as connection:
            return self.next_version(connection)

    def append_event(
        self, event_type: str, actor: str, payload: dict[str, Any]
    ) -> MemoryEvent:
        self.initialize()
        with self.transaction() as db:
            event = MemoryEvent(
                event_id=f"MEM-{uuid.uuid4().hex[:20].upper()}",
                case_id=self.case_id,
                event_type=event_type,
                actor=actor,
                version=self.next_version(db),
                payload=payload,
            )
            self._insert_event(db, event)
        return event

    def register_fact(
        self,
        fact_id: str,
        *,
        status: MemoryFactStatus = MemoryFactStatus.UNVERIFIED,
        actor: str = "memory_bootstrap",
    ) -> None:
        self.initialize()
        with self.transaction() as db:
            existing = db.execute(
                "SELECT 1 FROM memory_fact_state WHERE case_id = ? AND fact_id = ?",
                (self.case_id, fact_id),
            ).fetchone()
            if existing:
                return
            version = self.next_version(db)
            db.execute(
                """
                INSERT INTO memory_fact_state(case_id, fact_id, status, version)
                VALUES (?, ?, ?, ?)
                """,
                (self.case_id, fact_id, status.value, version),
            )
            self._insert_event(
                db,
                MemoryEvent(
                    event_id=f"MEM-{uuid.uuid4().hex[:20].upper()}",
                    case_id=self.case_id,
                    event_type="fact_registered",
                    actor=actor,
                    version=version,
                    payload={"fact_id": fact_id, "status": status.value},
                ),
            )

    def transition_fact(
        self,
        fact_id: str,
        to_status: MemoryFactStatus,
        *,
        actor: str,
        reason: str,
    ) -> FactTransitionEvent:
        self.initialize()
        with self.transaction() as db:
            row = db.execute(
                "SELECT status FROM memory_fact_state "
                "WHERE case_id = ? AND fact_id = ?",
                (self.case_id, fact_id),
            ).fetchone()
            if row is None:
                raise KeyError(fact_id)
            version = self.next_version(db)
            transition = FactTransitionEvent(
                event_id=f"MEM-{uuid.uuid4().hex[:20].upper()}",
                case_id=self.case_id,
                fact_id=fact_id,
                from_status=MemoryFactStatus(row["status"]),
                to_status=to_status,
                actor=actor,
                reason=reason,
                version=version,
            )
            db.execute(
                """
                UPDATE memory_fact_state SET status = ?, version = ?
                WHERE case_id = ? AND fact_id = ?
                """,
                (to_status.value, version, self.case_id, fact_id),
            )
            self._insert_event(
                db,
                MemoryEvent(
                    event_id=transition.event_id,
                    case_id=self.case_id,
                    event_type="fact_transition",
                    actor=actor,
                    timestamp=transition.timestamp,
                    version=version,
                    payload=transition.model_dump(mode="json"),
                ),
            )
        return transition

    def save_capsule(self, capsule: CaseCapsule) -> CaseCapsule:
        self.initialize()
        with self.transaction() as db:
            previous = db.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM case_capsules "
                "WHERE case_id = ?",
                (self.case_id,),
            ).fetchone()
            expected = int(previous["version"]) + 1
            if capsule.version != expected:
                raise ValueError(
                    f"Capsule version must be {expected}, got {capsule.version}."
                )
            db.execute(
                """
                INSERT INTO case_capsules(case_id, version, capsule_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    self.case_id,
                    capsule.version,
                    capsule.model_dump_json(),
                    utc_now(),
                ),
            )
            event = MemoryEvent(
                event_id=f"MEM-{uuid.uuid4().hex[:20].upper()}",
                case_id=self.case_id,
                event_type="capsule_saved",
                actor=capsule.last_updated_by,
                version=self.next_version(db),
                payload={"capsule_version": capsule.version},
            )
            self._insert_event(db, event)
        return capsule

    def latest_capsule(self) -> CaseCapsule | None:
        self.initialize()
        with self.transaction() as db:
            row = db.execute(
                """
                SELECT capsule_json FROM case_capsules
                WHERE case_id = ? ORDER BY version DESC LIMIT 1
                """,
                (self.case_id,),
            ).fetchone()
        return None if row is None else CaseCapsule.model_validate_json(
            row["capsule_json"]
        )

    def record_working_context(
        self,
        node_name: str,
        context: dict[str, Any],
        *,
        before_tokens: int,
        after_tokens: int,
    ) -> None:
        self.initialize()
        with self.transaction() as db:
            db.execute(
                """
                INSERT INTO working_memory(
                    case_id, node_name, context_json, before_tokens,
                    after_tokens, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    self.case_id,
                    node_name,
                    json.dumps(context, ensure_ascii=False, sort_keys=True),
                    before_tokens,
                    after_tokens,
                    utc_now(),
                ),
            )

    def list_events(self) -> list[MemoryEvent]:
        self.initialize()
        with self.transaction() as db:
            rows = db.execute(
                "SELECT * FROM memory_events WHERE case_id = ? ORDER BY version",
                (self.case_id,),
            ).fetchall()
        return [
            MemoryEvent(
                event_id=row["event_id"],
                case_id=row["case_id"],
                event_type=row["event_type"],
                actor=row["actor"],
                timestamp=row["timestamp"],
                version=row["version"],
                payload=json.loads(row["payload_json"]),
            )
            for row in rows
        ]

    def fact_status(self, fact_id: str) -> MemoryFactStatus:
        self.initialize()
        with self.transaction() as db:
            row = db.execute(
                "SELECT status FROM memory_fact_state "
                "WHERE case_id = ? AND fact_id = ?",
                (self.case_id, fact_id),
            ).fetchone()
        if row is None:
            raise KeyError(fact_id)
        return MemoryFactStatus(row["status"])

    @staticmethod
    def _insert_event(db: sqlite3.Connection, event: MemoryEvent) -> None:
        db.execute(
            """
            INSERT INTO memory_events(
                event_id, case_id, event_type, actor, timestamp, version,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.case_id,
                event.event_type,
                event.actor,
                event.timestamp,
                event.version,
                json.dumps(event.payload, ensure_ascii=False, sort_keys=True),
            ),
        )
