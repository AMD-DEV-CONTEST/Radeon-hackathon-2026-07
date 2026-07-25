"""SQLite-backed threads, consent, memory, and audit state."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class SQLiteStore:
    """Authoritative storage for state that requires consent and deletion."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS threads (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS images (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                    path TEXT NOT NULL UNIQUE,
                    original_name TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS consents (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL,
                    proposed_text TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'approved', 'rejected')),
                    created_at TEXT NOT NULL,
                    decided_at TEXT
                );

                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    source_thread_id TEXT NOT NULL,
                    consent_id TEXT NOT NULL UNIQUE REFERENCES consents(id),
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_images_thread ON images(thread_id);
                CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id, active);

                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT,
                    event_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def create_thread(self, user_id: str) -> dict[str, Any]:
        thread_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO threads(id, user_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (thread_id, user_id, now, now),
            )
        return self.get_thread(thread_id) or {}

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            return _row_dict(
                connection.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
            )

    def delete_thread(self, thread_id: str) -> list[str]:
        with self._connect() as connection:
            paths = [
                row["path"]
                for row in connection.execute(
                    "SELECT path FROM images WHERE thread_id = ?", (thread_id,)
                ).fetchall()
            ]
            connection.execute(
                """
                DELETE FROM memories WHERE consent_id IN (
                    SELECT id FROM consents WHERE thread_id = ?
                )
                """,
                (thread_id,),
            )
            connection.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
        return paths

    def forget_user(self, user_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            paths = [
                row["path"]
                for row in connection.execute(
                    """
                    SELECT images.path FROM images
                    JOIN threads ON images.thread_id = threads.id
                    WHERE threads.user_id = ?
                    """,
                    (user_id,),
                ).fetchall()
            ]
            thread_count = connection.execute(
                "SELECT COUNT(*) FROM threads WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
            memory_count = connection.execute(
                "SELECT COUNT(*) FROM memories WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
            connection.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM threads WHERE user_id = ?", (user_id,))
            connection.execute(
                """
                INSERT INTO audit_events(id, thread_id, event_type, summary, created_at)
                VALUES (?, NULL, 'forget_me_completed', ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    (
                        f"Deleted {thread_count} thread(s), {len(paths)} image record(s), "
                        f"and {memory_count} memory record(s)."
                    ),
                    _now(),
                ),
            )
        return {
            "user_id": user_id,
            "threads_deleted": thread_count,
            "images_deleted": len(paths),
            "memories_deleted": memory_count,
            "paths": paths,
        }

    def add_image(
        self,
        *,
        image_id: str,
        thread_id: str,
        path: Path,
        original_name: str,
        mime_type: str,
        width: int,
        height: int,
        digest: str,
    ) -> dict[str, Any]:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO images(
                    id, thread_id, path, original_name, mime_type, width, height, sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    image_id,
                    thread_id,
                    str(path),
                    original_name,
                    mime_type,
                    width,
                    height,
                    digest,
                    now,
                ),
            )
            connection.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id))
        return self.get_image(thread_id, image_id) or {}

    def get_image(self, thread_id: str, image_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            return _row_dict(
                connection.execute(
                    "SELECT * FROM images WHERE id = ? AND thread_id = ?",
                    (image_id, thread_id),
                ).fetchone()
            )

    def get_images(self, thread_id: str, image_ids: list[str]) -> list[dict[str, Any]]:
        return [
            image
            for image_id in image_ids
            if (image := self.get_image(thread_id, image_id)) is not None
        ]

    def list_images(self, thread_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM images WHERE thread_id = ? ORDER BY created_at",
                (thread_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_message(self, thread_id: str, role: str, content: str) -> None:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO messages(id, thread_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (uuid.uuid4().hex, thread_id, role, content, now),
            )
            connection.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id))

    def list_messages(self, thread_id: str, limit: int = 12) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content, created_at FROM messages
                WHERE thread_id = ? ORDER BY created_at DESC LIMIT ?
                """,
                (thread_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def start_run(self, thread_id: str, request: dict[str, Any]) -> str:
        run_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs(id, thread_id, status, request_json, created_at)
                VALUES (?, ?, 'running', ?, ?)
                """,
                (run_id, thread_id, json.dumps(request), _now()),
            )
        return run_id

    def finish_run(self, run_id: str, status: str, result: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE runs SET status = ?, result_json = ?, completed_at = ? WHERE id = ?
                """,
                (status, json.dumps(result), _now(), run_id),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["request"] = json.loads(result.pop("request_json"))
        raw_result = result.pop("result_json")
        result["result"] = json.loads(raw_result) if raw_result else None
        return result

    def list_runs(self, thread_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM runs WHERE thread_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (thread_id, limit),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["request"] = json.loads(item.pop("request_json"))
            raw_result = item.pop("result_json")
            item["result"] = json.loads(raw_result) if raw_result else None
            results.append(item)
        return results

    def create_memory_proposal(
        self, *, thread_id: str, user_id: str, text: str, memory_type: str
    ) -> dict[str, Any]:
        thread = self.get_thread(thread_id)
        if thread is None or thread["user_id"] != user_id:
            raise ValueError("Thread does not belong to this user")
        consent_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO consents(
                    id, thread_id, user_id, proposed_text, memory_type, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (consent_id, thread_id, user_id, text, memory_type, now),
            )
        return self.get_consent(consent_id) or {}

    def get_consent(self, consent_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            return _row_dict(
                connection.execute("SELECT * FROM consents WHERE id = ?", (consent_id,)).fetchone()
            )

    def decide_consent(
        self, consent_id: str, action: str, edited_text: str | None = None
    ) -> dict[str, Any] | None:
        consent = self.get_consent(consent_id)
        if consent is None:
            return None
        if consent["status"] != "pending":
            raise ValueError("Consent has already been decided")
        status = "approved" if action == "approve" else "rejected"
        text = edited_text or consent["proposed_text"]
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE consents SET status = ?, proposed_text = ?, decided_at = ? WHERE id = ?
                """,
                (status, text, now, consent_id),
            )
            if status == "approved":
                connection.execute(
                    """
                    INSERT INTO memories(
                        id, user_id, text, memory_type, source_thread_id,
                        consent_id, active, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        uuid.uuid4().hex,
                        consent["user_id"],
                        text,
                        consent["memory_type"],
                        consent["thread_id"],
                        consent_id,
                        now,
                    ),
                )
        return self.get_consent(consent_id)

    def list_memories(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM memories WHERE user_id = ? AND active = 1
                ORDER BY created_at DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [{**dict(row), "active": bool(row["active"])} for row in rows]

    def delete_memory(self, memory_id: str, user_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE memories SET active = 0, text = '[deleted]' WHERE id = ? AND user_id = ?",
                (memory_id, user_id),
            )
        return cursor.rowcount == 1

    def audit(self, event_type: str, summary: str, thread_id: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audit_events(id, thread_id, event_type, summary, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (uuid.uuid4().hex, thread_id, event_type, summary[:500], _now()),
            )
