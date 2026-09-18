"""SQLite-backed local case memory and append-only audit log."""

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Union


DatabasePath = Union[str, Path]


class CaseMemory:
    def __init__(self, database_path: DatabasePath) -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            self.database_path, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._initialize()

    def _initialize(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_case_id
                    ON messages(case_id, id);

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_case_id
                    ON audit_events(case_id, id);
                """
            )

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    def record_message(self, case_id: str, role: str, content: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO messages(case_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (case_id, role, content, self._timestamp()),
            )

    def record_event(
        self, case_id: str, event_type: str, payload: Dict[str, Any]
    ) -> None:
        serialized = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO audit_events(
                    case_id, event_type, payload, created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (case_id, event_type, serialized, self._timestamp()),
            )

    def history(self, case_id: str) -> List[Dict[str, Any]]:
        with self._lock, closing(
            self._connection.execute(
                """
                SELECT role, content, created_at
                FROM messages
                WHERE case_id = ?
                ORDER BY id
                """,
                (case_id,),
            )
        ) as cursor:
            return [dict(row) for row in cursor.fetchall()]

    def audit(self, case_id: str) -> List[Dict[str, Any]]:
        with self._lock, closing(
            self._connection.execute(
                """
                SELECT event_type, payload, created_at
                FROM audit_events
                WHERE case_id = ?
                ORDER BY id
                """,
                (case_id,),
            )
        ) as cursor:
            events = []
            for row in cursor.fetchall():
                event = dict(row)
                event["payload"] = json.loads(event["payload"])
                events.append(event)
            return events

    def close(self) -> None:
        with self._lock:
            self._connection.close()
