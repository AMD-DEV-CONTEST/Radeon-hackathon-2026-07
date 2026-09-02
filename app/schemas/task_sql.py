"""Phase F — SQLite DDL and helpers for task lifecycle tables.

Tables
------
* task          — formal tasks with owner / due / priority / acceptance / deps
* task_change   — event log recording every state transition
* confirmation  — human confirmation requests (pending queue)
* operation_audit — who did what, when
"""

from __future__ import annotations

DDL = """
-- formal task table
CREATE TABLE IF NOT EXISTS task (
    id            TEXT PRIMARY KEY,
    project_id    TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    owner         TEXT,
    due_date      TEXT,
    priority      TEXT,
    acceptance_criteria TEXT,
    dependencies  TEXT,
    source_ref    TEXT,
    status        TEXT    NOT NULL DEFAULT 'pending_confirmation',
    confirmed_by  TEXT,
    confirmed_at  TEXT,
    confirmation_basis TEXT,
    confirmation_notes TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_task_project ON task(project_id);
CREATE INDEX IF NOT EXISTS idx_task_status  ON task(status);

-- event log: every status change is recorded here
CREATE TABLE IF NOT EXISTS task_change (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id       TEXT    NOT NULL,
    project_id    TEXT    NOT NULL,
    from_status   TEXT,
    to_status     TEXT    NOT NULL,
    changed_by    TEXT,
    change_reason TEXT,
    changed_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_task_change_task ON task_change(task_id);
CREATE INDEX IF NOT EXISTS idx_task_change_project ON task_change(project_id);

-- human confirmation requests (pending queue)
CREATE TABLE IF NOT EXISTS confirmation (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id                  TEXT    NOT NULL,
    project_id               TEXT    NOT NULL,
    candidate_title          TEXT    NOT NULL,
    candidate_owner          TEXT,
    candidate_due_date       TEXT,
    candidate_priority       TEXT,
    candidate_acceptance     TEXT,
    candidate_dependencies   TEXT,
    source_ref               TEXT,
    source_kind              TEXT    NOT NULL,
    confidence               REAL    DEFAULT 0.5,
    status                   TEXT    NOT NULL DEFAULT 'pending',
    confirmed_by             TEXT,
    confirmation_basis       TEXT,
    confirmation_notes       TEXT,
    confirmed_at             TEXT,
    created_at               TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_confirmation_project ON confirmation(project_id);
CREATE INDEX IF NOT EXISTS idx_confirmation_status  ON confirmation(status);

-- operation audit trail (human-readable record)
CREATE TABLE IF NOT EXISTS operation_audit (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    TEXT    NOT NULL,
    entity_type   TEXT    NOT NULL,
    entity_id     TEXT    NOT NULL,
    operation     TEXT    NOT NULL,
    operator      TEXT,
    details       TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_op_audit_project ON operation_audit(project_id);
CREATE INDEX IF NOT EXISTS idx_op_audit_entity   ON operation_audit(entity_type, entity_id);

-- dedup helper: stores hashes of previously imported task rows
CREATE TABLE IF NOT EXISTS task_import_fingerprint (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    TEXT    NOT NULL,
    fingerprint   TEXT    NOT NULL,
    task_id       TEXT,
    imported_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_fp_project_hash
    ON task_import_fingerprint(project_id, fingerprint);
"""


# ── well-known task status values ──

TASK_STATUSES = [
    "pending_confirmation",
    "not_started",
    "in_progress",
    "mostly_completed",
    "completed",
    "delayed",
    "cancelled",
]

# allowed transitions: from → [to, ...]
ALLOWED_TRANSITIONS: dict[str, list[str]] = {
    "pending_confirmation": ["not_started", "cancelled"],
    "not_started": ["in_progress", "cancelled", "delayed"],
    "in_progress": ["mostly_completed", "completed", "delayed", "cancelled"],
    "mostly_completed": ["completed", "in_progress", "delayed"],
    "completed": [],
    "delayed": ["in_progress", "completed", "cancelled"],
    "cancelled": [],  # cannot go from cancelled back to completed
}


def is_valid_transition(from_status: str, to_status: str) -> bool:
    """Return True when *from_status* → *to_status* is allowed."""
    allowed = ALLOWED_TRANSITIONS.get(from_status, [])
    return to_status in allowed
