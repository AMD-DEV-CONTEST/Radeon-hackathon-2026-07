"""SQLite persistence for the AlphaNoah P0 workflow."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, TypeVar

from ..exceptions import ConcurrentUpdateError, ObjectNotFoundError
from ..models import (
    AuditRecord,
    Decision,
    Evidence,
    Event,
    EventStatus,
    HumanReview,
    Review,
    Task,
    utc_now,
)
from ..notifications import Notification

DomainObject = TypeVar(
    "DomainObject",
    Event,
    Decision,
    HumanReview,
    Task,
    Evidence,
    Review,
    Notification,
)


class SQLiteStore:
    """Small, restart-safe store with transactional event transitions."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            trace_id TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_trace_id ON events(trace_id);

        CREATE TABLE IF NOT EXISTS decisions (
            decision_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(event_id) REFERENCES events(event_id)
        );
        CREATE INDEX IF NOT EXISTS idx_decisions_event_id ON decisions(event_id);

        CREATE TABLE IF NOT EXISTS human_reviews (
            human_review_id TEXT PRIMARY KEY,
            decision_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(decision_id) REFERENCES decisions(decision_id)
        );

        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            source_decision_id TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(source_decision_id) REFERENCES decisions(decision_id)
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_decision_id
            ON tasks(source_decision_id);

        CREATE TABLE IF NOT EXISTS evidence (
            evidence_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            validation_status TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES tasks(task_id)
        );
        CREATE INDEX IF NOT EXISTS idx_evidence_task_id ON evidence(task_id);

        CREATE TABLE IF NOT EXISTS notifications (
            notification_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            decision_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(event_id) REFERENCES events(event_id),
            FOREIGN KEY(decision_id) REFERENCES decisions(decision_id)
        );
        CREATE INDEX IF NOT EXISTS idx_notifications_event_id
            ON notifications(event_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_notifications_trace_id
            ON notifications(trace_id, created_at);

        CREATE TABLE IF NOT EXISTS post_reviews (
            review_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES tasks(task_id),
            FOREIGN KEY(event_id) REFERENCES events(event_id)
        );

        CREATE TABLE IF NOT EXISTS audit_records (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_id TEXT NOT NULL UNIQUE,
            trace_id TEXT NOT NULL,
            object_type TEXT NOT NULL,
            object_id TEXT NOT NULL,
            action TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_trace_id
            ON audit_records(trace_id, sequence);

        CREATE TABLE IF NOT EXISTS idempotency_keys (
            operation TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            object_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(operation, idempotency_key)
        );
        """
        with self._connect() as connection:
            connection.executescript(schema)

    @staticmethod
    def _json(payload: dict[str, Any]) -> str:
        return json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )

    def save_event(self, event: Event) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO events(event_id, trace_id, status, payload, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.trace_id,
                    event.status.value,
                    self._json(event.to_dict()),
                    utc_now(),
                ),
            )

    def get_event(self, event_id: str) -> Event:
        row = self._one("events", "event_id", event_id)
        return Event.from_dict(json.loads(row["payload"]))

    def list_events(self) -> list[Event]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM events ORDER BY updated_at, event_id"
            ).fetchall()
        return [Event.from_dict(json.loads(row["payload"])) for row in rows]

    def update_event(self, event: Event) -> None:
        self._update_status_object(
            "events",
            "event_id",
            event.event_id,
            event.status.value,
            event.to_dict(),
        )

    def transition_event(
        self,
        event_id: str,
        expected_status: EventStatus,
        target_status: EventStatus,
        audit: AuditRecord,
    ) -> Event:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, payload FROM events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                raise ObjectNotFoundError(f"Event not found: {event_id}")
            if row["status"] != expected_status.value:
                raise ConcurrentUpdateError(
                    f"Expected {expected_status.value}, found {row['status']}"
                )
            event = Event.from_dict(json.loads(row["payload"]))
            event.status = target_status
            connection.execute(
                """
                UPDATE events
                SET status = ?, payload = ?, updated_at = ?
                WHERE event_id = ?
                """,
                (
                    target_status.value,
                    self._json(event.to_dict()),
                    utc_now(),
                    event_id,
                ),
            )
            self._insert_audit(connection, audit)
            return event

    def save_decision(self, decision: Decision) -> None:
        self._insert_status_object(
            table="decisions",
            id_column="decision_id",
            object_id=decision.decision_id,
            parent_column="event_id",
            parent_id=decision.event_id,
            status=decision.status.value,
            payload=decision.to_dict(),
        )

    def get_decision(self, decision_id: str) -> Decision:
        row = self._one("decisions", "decision_id", decision_id)
        return Decision.from_dict(json.loads(row["payload"]))

    def update_decision(self, decision: Decision) -> None:
        self._update_status_object(
            "decisions",
            "decision_id",
            decision.decision_id,
            decision.status.value,
            decision.to_dict(),
        )

    def list_decisions(self, event_id: str) -> list[Decision]:
        return self._list_payloads(
            Decision, "decisions", "event_id", event_id, "updated_at"
        )

    def save_human_review(self, review: HumanReview) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO human_reviews(
                    human_review_id, decision_id, payload, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    review.human_review_id,
                    review.decision_id,
                    self._json(review.to_dict()),
                    utc_now(),
                ),
            )

    def register_human_review(
        self,
        review: HumanReview,
    ) -> tuple[HumanReview, bool]:
        """Atomically register the first Human Review for one Decision."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT payload FROM human_reviews
                WHERE decision_id = ?
                ORDER BY created_at, human_review_id
                LIMIT 1
                """,
                (review.decision_id,),
            ).fetchone()
            if existing is not None:
                return (
                    HumanReview.from_dict(json.loads(existing["payload"])),
                    False,
                )

            connection.execute(
                """
                INSERT INTO idempotency_keys(
                    operation, idempotency_key, object_id, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    "submit_human_review",
                    review.decision_id,
                    review.human_review_id,
                    utc_now(),
                ),
            )
            connection.execute(
                """
                INSERT INTO human_reviews(
                    human_review_id, decision_id, payload, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    review.human_review_id,
                    review.decision_id,
                    self._json(review.to_dict()),
                    utc_now(),
                ),
            )
            return review, True

    def list_human_reviews(self, decision_id: str) -> list[HumanReview]:
        return self._list_payloads(
            HumanReview,
            "human_reviews",
            "decision_id",
            decision_id,
            "created_at",
        )

    def save_task(self, task: Task) -> None:
        self._insert_status_object(
            table="tasks",
            id_column="task_id",
            object_id=task.task_id,
            parent_column="source_decision_id",
            parent_id=task.source_decision_id,
            status=task.status.value,
            payload=task.to_dict(),
        )

    def get_task(self, task_id: str) -> Task:
        row = self._one("tasks", "task_id", task_id)
        return Task.from_dict(json.loads(row["payload"]))

    def update_task(self, task: Task) -> None:
        self._update_status_object(
            "tasks",
            "task_id",
            task.task_id,
            task.status.value,
            task.to_dict(),
        )

    def list_tasks(self, decision_id: str) -> list[Task]:
        return self._list_payloads(
            Task,
            "tasks",
            "source_decision_id",
            decision_id,
            "updated_at",
        )

    def register_evidence(
        self, evidence: Evidence, idempotency_key: str
    ) -> bool:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO idempotency_keys(
                        operation, idempotency_key, object_id, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        "submit_evidence",
                        idempotency_key,
                        evidence.evidence_id,
                        utc_now(),
                    ),
                )
            except sqlite3.IntegrityError:
                return False
            connection.execute(
                """
                INSERT INTO evidence(
                    evidence_id, task_id, validation_status, payload, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    evidence.evidence_id,
                    evidence.task_id,
                    evidence.validation_status.value,
                    self._json(evidence.to_dict()),
                    utc_now(),
                ),
            )
            return True

    def has_idempotency_key(self, operation: str, key: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM idempotency_keys
                WHERE operation = ? AND idempotency_key = ?
                """,
                (operation, key),
            ).fetchone()
        return row is not None

    def get_evidence(self, evidence_id: str) -> Evidence:
        row = self._one("evidence", "evidence_id", evidence_id)
        return Evidence.from_dict(json.loads(row["payload"]))

    def update_evidence(self, evidence: Evidence) -> None:
        self._update_status_object(
            "evidence",
            "evidence_id",
            evidence.evidence_id,
            evidence.validation_status.value,
            evidence.to_dict(),
            status_column="validation_status",
        )

    def list_evidence(self, task_id: str) -> list[Evidence]:
        return self._list_payloads(
            Evidence, "evidence", "task_id", task_id, "created_at"
        )

    def register_notification(
        self,
        notification: Notification,
        audit: AuditRecord,
    ) -> Notification:
        """Atomically persist one Notification and its creation audit."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload FROM notifications WHERE decision_id = ?",
                (notification.decision_id,),
            ).fetchone()
            if existing is not None:
                return Notification.from_dict(json.loads(existing["payload"]))
            connection.execute(
                """
                INSERT INTO notifications(
                    notification_id, event_id, trace_id, decision_id,
                    status, payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    notification.notification_id,
                    notification.event_id,
                    notification.trace_id,
                    notification.decision_id,
                    notification.status.value,
                    self._json(notification.to_dict()),
                    notification.created_at,
                ),
            )
            self._insert_audit(connection, audit)
            return notification

    def get_notification(self, notification_id: str) -> Notification:
        row = self._one("notifications", "notification_id", notification_id)
        return Notification.from_dict(json.loads(row["payload"]))

    def find_notification_by_decision(
        self, decision_id: str
    ) -> Notification | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM notifications WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        if row is None:
            return None
        return Notification.from_dict(json.loads(row["payload"]))

    def list_notifications(self, event_id: str) -> list[Notification]:
        return self._list_payloads(
            Notification,
            "notifications",
            "event_id",
            event_id,
            "created_at",
        )

    def save_post_review(self, review: Review) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO post_reviews(
                    review_id, task_id, event_id, payload, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    review.review_id,
                    review.task_id,
                    review.event_id,
                    self._json(review.to_dict()),
                    utc_now(),
                ),
            )

    def list_post_reviews(self, task_id: str) -> list[Review]:
        return self._list_payloads(
            Review, "post_reviews", "task_id", task_id, "created_at"
        )

    def record_audit(self, audit: AuditRecord) -> None:
        with self._connect() as connection:
            self._insert_audit(connection, audit)

    def list_audit(self, trace_id: str) -> list[AuditRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM audit_records
                WHERE trace_id = ?
                ORDER BY sequence
                """,
                (trace_id,),
            ).fetchall()
        return [AuditRecord.from_dict(json.loads(row["payload"])) for row in rows]

    def reset(self) -> None:
        """Delete only records in this explicitly selected database."""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for table in (
                "idempotency_keys",
                "post_reviews",
                "evidence",
                "notifications",
                "human_reviews",
                "tasks",
                "decisions",
                "audit_records",
                "events",
            ):
                connection.execute(f"DELETE FROM {table}")

    def _one(
        self, table: str, id_column: str, object_id: str
    ) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT * FROM {table} WHERE {id_column} = ?",
                (object_id,),
            ).fetchone()
        if row is None:
            raise ObjectNotFoundError(f"{table} object not found: {object_id}")
        return row

    def _insert_status_object(
        self,
        *,
        table: str,
        id_column: str,
        object_id: str,
        parent_column: str,
        parent_id: str,
        status: str,
        payload: dict[str, Any],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                f"""
                INSERT INTO {table}(
                    {id_column}, {parent_column}, status, payload, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (object_id, parent_id, status, self._json(payload), utc_now()),
            )

    def _update_status_object(
        self,
        table: str,
        id_column: str,
        object_id: str,
        status: str,
        payload: dict[str, Any],
        *,
        status_column: str = "status",
    ) -> None:
        time_column = "created_at" if table == "evidence" else "updated_at"
        with self._connect() as connection:
            result = connection.execute(
                f"""
                UPDATE {table}
                SET {status_column} = ?, payload = ?, {time_column} = ?
                WHERE {id_column} = ?
                """,
                (status, self._json(payload), utc_now(), object_id),
            )
            if result.rowcount != 1:
                raise ObjectNotFoundError(
                    f"{table} object not found: {object_id}"
                )

    def _list_payloads(
        self,
        object_class: type[DomainObject],
        table: str,
        parent_column: str,
        parent_id: str,
        order_column: str,
    ) -> list[DomainObject]:
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT payload FROM {table}
                WHERE {parent_column} = ?
                ORDER BY {order_column}
                """,
                (parent_id,),
            ).fetchall()
        return [
            object_class.from_dict(json.loads(row["payload"])) for row in rows
        ]

    def _insert_audit(
        self, connection: sqlite3.Connection, audit: AuditRecord
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_records(
                audit_id, trace_id, object_type, object_id,
                action, payload, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit.audit_id,
                audit.trace_id,
                audit.object_type,
                audit.object_id,
                audit.action,
                self._json(audit.to_dict()),
                audit.timestamp,
            ),
        )
