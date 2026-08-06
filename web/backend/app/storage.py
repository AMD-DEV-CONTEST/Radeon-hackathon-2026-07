"""SQLite-backed job storage (stdlib sqlite3, thread-safe)."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class JobStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # RLock: update() calls get() while holding the lock (re-entrant).
        self._lock = threading.RLock()
        # One shared connection, guarded by self._lock. check_same_thread=False
        # because the job worker touches it from a worker thread.
        self._conn = self._connect()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_updated ON jobs(updated_at DESC)"
            )
            self._conn.commit()

    def create(self, job: dict[str, Any]) -> None:
        payload = json.dumps(job, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO jobs (id, payload, updated_at) VALUES (?, ?, ?)",
                (job["id"], payload, job.get("updated_at", "")),
            )
            self._conn.commit()

    def update(self, job_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            job = self.get(job_id)
            if job is None:
                return None
            job.update(patch)
            self.create(job)
            return job

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def list(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM jobs ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [json.loads(r["payload"]) for r in rows]

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()
        return int(row["n"])
