"""SQLite-backed multi-turn ops memory and audit trail."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterator

_SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    turn INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    event TEXT NOT NULL,
    detail TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id, turn);
"""


class OpsMemory:
    def __init__(self, db_path: str | Path = "runtime/radeonpilot.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Gradio serves handlers from worker threads, so the connection must be
        # shareable; serialize writes with a lock.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def next_turn(self, session_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(turn), 0) + 1 FROM turns WHERE session_id = ?", (session_id,)
            ).fetchone()
            return int(row[0])

    def add_turn(self, session_id: str, turn: int, role: str, content: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO turns (session_id, turn, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, turn, role, content, time.time()),
            )
            self._conn.commit()

    def history(self, session_id: str) -> list[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT turn, role, content FROM turns WHERE session_id = ? ORDER BY turn", (session_id,)
        )
        return [{"turn": turn, "role": role, "content": content} for turn, role, content in cursor]

    def snapshot(self, session_id: str, kind: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO snapshots (session_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (session_id, kind, json.dumps(payload), time.time()),
            )
            self._conn.commit()

    def latest_snapshot(self, session_id: str, kind: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT payload FROM snapshots WHERE session_id = ? AND kind = ? ORDER BY id DESC LIMIT 1",
            (session_id, kind),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def audit(self, session_id: str | None, event: str, detail: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit (session_id, event, detail, created_at) VALUES (?, ?, ?, ?)",
                (session_id, event, detail, time.time()),
            )
            self._conn.commit()

    def audit_tail(self, limit: int = 25) -> Iterator[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT session_id, event, detail, created_at FROM audit ORDER BY id DESC LIMIT ?", (limit,)
        )
        for session_id, event, detail, created_at in cursor:
            yield {"session_id": session_id, "event": event, "detail": detail, "created_at": created_at}
