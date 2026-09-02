"""SCM connector — GitHub Issues / Jira stub lifecycle."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.integrations.base import BaseConnector, ConfirmationRequired, ConnectorResult, ConnectorStatus


class SCMTarget(str, Enum):
    GITHUB_ISSUES = "github_issues"
    JIRA = "jira"


class SCMConnector(BaseConnector):
    """Stub SCM connector with full lifecycle. Ready for GitHub/Jira backends."""

    def __init__(self, db_path: str = ":memory:") -> None:
        super().__init__("scm")
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS scm_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target TEXT NOT NULL,
                    operation TEXT NOT NULL DEFAULT 'create',
                    diff_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS scm_confirmations (
                    id TEXT PRIMARY KEY,
                    target TEXT NOT NULL,
                    diff_json TEXT NOT NULL DEFAULT '{}',
                    confirmed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def read(self, **kwargs: Any) -> dict[str, Any]:
        """Read external state — stub returns empty list."""
        self._set_status(ConnectorStatus.READING)
        target = kwargs.get("target", SCMTarget.GITHUB_ISSUES.value)
        return {"target": target, "issues": [], "fetched_at": _now()}

    def preview_diff(self, data: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Preview the change. Raises ConfirmationRequired for the caller to gate."""
        target = data.get("target", SCMTarget.GITHUB_ISSUES.value)
        operation = data.get("operation", "create")
        items = data.get("items", [])

        if not items:
            raise ValueError("items list is required for SCM commit")

        diff = {"target": target, "operation": operation, "items": items}

        # generate confirmation
        confirmation_id = _make_id("scm_confirm")
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO scm_confirmations (id, target, diff_json) VALUES (?, ?, ?)",
                (confirmation_id, target, json.dumps(diff)),
            )

        self._set_status(ConnectorStatus.PREVIEW_READY)
        raise ConfirmationRequired(
            f"SCM {operation} on {target}: {len(items)} item(s) pending. "
            f"Confirmation required. confirmation_id={confirmation_id}",
            details={"confirmation_id": confirmation_id, "diff": diff},
        )

    def execute(self, data: dict[str, Any], confirmation_id: str, **kwargs: Any) -> ConnectorResult:
        """Apply the change after confirmation."""
        self._set_status(ConnectorStatus.EXECUTING)

        target = data.get("target", SCMTarget.GITHUB_ISSUES.value)
        operation = data.get("operation", "create")

        # Verify confirmation exists
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM scm_confirmations WHERE id = ? AND confirmed = 0", (confirmation_id,)
            ).fetchone()
            if row is None:
                self._set_status(ConnectorStatus.FAILED)
                return ConnectorResult(
                    status=ConnectorStatus.FAILED,
                    summary=f"Invalid or already-used confirmation_id: {confirmation_id}",
                )

            expected = json.loads(row["diff_json"])
            submitted = {
                "target": target,
                "operation": operation,
                "items": data.get("items", []),
            }
            if submitted != expected:
                self._set_status(ConnectorStatus.FAILED)
                return ConnectorResult(
                    status=ConnectorStatus.FAILED,
                    summary="Confirmation does not match the previewed SCM change",
                )

            # Mark confirmed
            conn.execute(
                "UPDATE scm_confirmations SET confirmed = 1 WHERE id = ?", (confirmation_id,)
            )

            # Record audit
            diff_json = json.dumps(data.get("items", []))
            conn.execute(
                "INSERT INTO scm_audit (target, operation, diff_json, status) VALUES (?, ?, ?, 'committed')",
                (target, operation, diff_json),
            )

        self._set_status(ConnectorStatus.EXECUTED)
        return ConnectorResult(
            status=ConnectorStatus.EXECUTED,
            summary=f"SCM {operation} committed to {target}",
            details={"target": target, "operation": operation, "confirmation_id": confirmation_id},
        )

    def rollback(self, execution_context: dict[str, Any], **kwargs: Any) -> ConnectorResult:
        """Stub rollback — records intention."""
        self._set_status(ConnectorStatus.ROLLED_BACK)
        target = execution_context.get("target", "unknown")
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO scm_audit (target, operation, diff_json, status) VALUES (?, 'rollback', ?, 'rolled_back')",
                (target, json.dumps(execution_context)),
            )
        return ConnectorResult(
            status=ConnectorStatus.ROLLED_BACK,
            summary=f"Rollback recorded for {target}",
            details=execution_context,
        )

    def audit(self, limit: int = 50) -> list[dict[str, Any]]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM scm_audit ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
