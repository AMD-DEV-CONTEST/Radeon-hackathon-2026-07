"""Automation task service — CRUD, pause/resume, dry-run, audit log."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AutomationTaskStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    RUNNING = "running"


class AutomationTaskType(str, Enum):
    ON_SCHEDULE = "on_schedule"
    ON_EVENT = "on_event"
    ON_DEMAND = "on_demand"


@dataclass
class AutomationTask:
    id: str = ""
    project_id: str = ""
    name: str = ""
    type: str = AutomationTaskType.ON_DEMAND.value
    config_json: str = "{}"
    status: str = AutomationTaskStatus.ACTIVE.value
    created_at: str = ""
    updated_at: str = ""


class AutomationTaskService:
    """Manages automation tasks with full lifecycle and audit."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # DB
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS automation_tasks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'on_demand',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS automation_task_runs (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    run_type TEXT NOT NULL DEFAULT 'real',
                    status TEXT NOT NULL DEFAULT 'pending',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    started_at TEXT,
                    finished_at TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS automation_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, project_id: str, name: str, task_type: str = "on_demand",
               config: dict[str, Any] | None = None) -> AutomationTask:
        task_id = _make_id("auto")
        config_json = json.dumps(config or {})
        now = _now()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT INTO automation_tasks (id, project_id, name, type, config_json, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'active', ?, ?)""",
                (task_id, project_id, name, task_type, config_json, now, now),
            )
            conn.execute(
                "INSERT INTO automation_audit_log (task_id, action, details) VALUES (?, 'created', ?)",
                (task_id, json.dumps({"name": name})),
            )
        return self.get(task_id)

    def get(self, task_id: str) -> AutomationTask:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM automation_tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"Automation task {task_id} not found")
        return _row_to_task(dict(row))

    def project_id_for_task(self, task_id: str) -> str:
        """Return a task's owning project without exposing task data first."""
        return self.get(task_id).project_id

    def list_by_project(self, project_id: str) -> list[AutomationTask]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM automation_tasks WHERE project_id = ? ORDER BY created_at DESC", (project_id,)
            ).fetchall()
        return [_row_to_task(dict(r)) for r in rows]

    def pause(self, task_id: str) -> AutomationTask:
        task = self.get(task_id)
        if task.status == AutomationTaskStatus.PAUSED.value:
            raise ValueError(f"Task {task_id} is already paused")
        if task.status == AutomationTaskStatus.CANCELLED.value:
            raise ValueError(f"Task {task_id} is cancelled, cannot pause")
        now = _now()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "UPDATE automation_tasks SET status = 'paused', updated_at = ? WHERE id = ?", (now, task_id)
            )
            conn.execute(
                "INSERT INTO automation_audit_log (task_id, action, details) VALUES (?, 'paused', '{}')", (task_id,)
            )
        return self.get(task_id)

    def resume(self, task_id: str) -> AutomationTask:
        task = self.get(task_id)
        if task.status == AutomationTaskStatus.ACTIVE.value:
            raise ValueError(f"Task {task_id} is already active")
        if task.status == AutomationTaskStatus.CANCELLED.value:
            raise ValueError(f"Task {task_id} is cancelled, cannot resume")
        now = _now()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "UPDATE automation_tasks SET status = 'active', updated_at = ? WHERE id = ?", (now, task_id)
            )
            conn.execute(
                "INSERT INTO automation_audit_log (task_id, action, details) VALUES (?, 'resumed', '{}')", (task_id,)
            )
        return self.get(task_id)

    def delete(self, task_id: str) -> bool:
        task = self.get(task_id)
        now = _now()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("UPDATE automation_tasks SET status = 'cancelled', updated_at = ? WHERE id = ?", (now, task_id))
            conn.execute(
                "INSERT INTO automation_audit_log (task_id, action, details) VALUES (?, 'cancelled', '{}')", (task_id,)
            )
        return True

    def dry_run(self, task_id: str) -> dict[str, Any]:
        """Simulate execution without side effects."""
        task = self.get(task_id)
        run_id = _make_id("dry")
        config = json.loads(task.config_json) if task.config_json else {}
        result = {
            "run_id": run_id,
            "task_id": task_id,
            "task_name": task.name,
            "run_type": "dry_run",
            "simulated_actions": [f"Would run {task.name} with config: {config}"],
            "status": "simulated",
        }
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT INTO automation_task_runs (id, task_id, run_type, status, result_json, started_at, finished_at)
                   VALUES (?, ?, 'dry_run', 'simulated', ?, ?, ?)""",
                (run_id, task_id, json.dumps(result), _now(), _now()),
            )
            conn.execute(
                "INSERT INTO automation_audit_log (task_id, action, details) VALUES (?, 'dry_run', ?)",
                (task_id, json.dumps(result)),
            )
        return result

    def audit_log(self, task_id: str, limit: int = 50) -> list[dict[str, Any]]:
        # Verify task exists first
        self.get(task_id)
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM automation_audit_log WHERE task_id = ? ORDER BY id DESC LIMIT ?",
                (task_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_runs(self, task_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM automation_task_runs WHERE task_id = ? ORDER BY created_at DESC LIMIT ?",
                (task_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_task(d: dict[str, Any]) -> AutomationTask:
    return AutomationTask(
        id=d.get("id", ""),
        project_id=d.get("project_id", ""),
        name=d.get("name", ""),
        type=d.get("type", "on_demand"),
        config_json=d.get("config_json", "{}"),
        status=d.get("status", "active"),
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
    )
