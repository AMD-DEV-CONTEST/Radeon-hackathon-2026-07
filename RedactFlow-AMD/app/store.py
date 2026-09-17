from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def put_document(self, document_id: str, name: str, content: str) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO documents(id, name, content) VALUES (?, ?, ?)",
                (document_id, name, content),
            )

    def list_documents(self) -> list[dict[str, str]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, name, content, created_at FROM documents ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def remember(self, kind: str, payload: dict) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO memories(kind, payload) VALUES (?, ?)",
                (kind, json.dumps(payload, ensure_ascii=False)),
            )

    def recent_memories(self, limit: int = 20) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT kind, payload, created_at FROM memories ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "kind": row["kind"],
                "payload": json.loads(row["payload"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def put_plan(self, plan_id: str, payload: dict) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO plans(id, payload) VALUES (?, ?)",
                (plan_id, json.dumps(payload, ensure_ascii=False)),
            )

    def get_plan(self, plan_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM plans WHERE id = ?", (plan_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

