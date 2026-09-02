"""CI/CD trigger connector — triggers quality benchmarks on file change."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from app.integrations.base import BaseConnector, ConfirmationRequired, ConnectorResult, ConnectorStatus


class CITriggerConnector(BaseConnector):
    """Stub CI trigger with full lifecycle. Triggers a benchmark on file change."""

    def __init__(self, db_path: str = ":memory:") -> None:
        super().__init__("ci_trigger")
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS ci_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger_type TEXT NOT NULL DEFAULT 'benchmark',
                    project_id TEXT NOT NULL DEFAULT '',
                    files TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS ci_confirmations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL DEFAULT '',
                    files TEXT NOT NULL DEFAULT '[]',
                    confirmed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def read(self, **kwargs: Any) -> dict[str, Any]:
        self._set_status(ConnectorStatus.READING)
        return {"recent_triggers": self.audit()[:10]}

    def preview_diff(self, data: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        project_id = data.get("project_id", "")
        files = data.get("files", [])

        self._set_status(ConnectorStatus.PREVIEW_READY)

        diff = {
            "trigger_type": "benchmark",
            "project_id": project_id,
            "files": files,
            "estimated_duration": "~120s",
        }

        confirmation_id = _make_id("ci_confirm")
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO ci_confirmations (id, project_id, files) VALUES (?, ?, ?)",
                (confirmation_id, project_id, json.dumps(files)),
            )

        raise ConfirmationRequired(
            f"CI benchmark on project {project_id}: {len(files)} file(s) changed. "
            f"Confirmation required. confirmation_id={confirmation_id}",
            details={"confirmation_id": confirmation_id, "diff": diff},
        )

    def execute(self, data: dict[str, Any], confirmation_id: str, **kwargs: Any) -> ConnectorResult:
        self._set_status(ConnectorStatus.EXECUTING)

        project_id = data.get("project_id", "")
        files = data.get("files", [])

        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM ci_confirmations WHERE id = ? AND confirmed = 0", (confirmation_id,)
            ).fetchone()
            if row is None:
                self._set_status(ConnectorStatus.FAILED)
                return ConnectorResult(
                    status=ConnectorStatus.FAILED,
                    summary=f"Invalid or already-used confirmation_id: {confirmation_id}",
                )

            conn.execute("UPDATE ci_confirmations SET confirmed = 1 WHERE id = ?", (confirmation_id,))
            conn.execute(
                "INSERT INTO ci_audit (trigger_type, project_id, files, status) VALUES ('benchmark', ?, ?, 'triggered')",
                (project_id, json.dumps(files)),
            )

        self._set_status(ConnectorStatus.EXECUTED)
        return ConnectorResult(
            status=ConnectorStatus.EXECUTED,
            summary=f"CI benchmark triggered for project {project_id}",
            details={"project_id": project_id, "files": files},
        )

    def rollback(self, execution_context: dict[str, Any], **kwargs: Any) -> ConnectorResult:
        self._set_status(ConnectorStatus.ROLLED_BACK)
        return ConnectorResult(
            status=ConnectorStatus.ROLLED_BACK,
            summary="CI trigger cannot be undone. Marked for audit.",
            details=execution_context,
        )

    def audit(self, limit: int = 50) -> list[dict[str, Any]]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM ci_audit ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def _make_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}"
