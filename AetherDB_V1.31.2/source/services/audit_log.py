"""Simple security audit log.

Logs high-risk operations for security review.
Table created in each database by init_db().
"""

import logging
import sqlite3
from datetime import datetime

log = logging.getLogger(__name__)

TABLE_DDL = """CREATE TABLE IF NOT EXISTS audit_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,
    action TEXT DEFAULT "",
    target TEXT DEFAULT "",
    database_id TEXT DEFAULT "",
    book_id TEXT DEFAULT "",
    success INTEGER DEFAULT 1,
    description TEXT NOT NULL,
    details TEXT DEFAULT "",
    severity TEXT DEFAULT "info",
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)"""

EXTRA_COLUMNS = {
    "action": "TEXT DEFAULT ''",
    "target": "TEXT DEFAULT ''",
    "database_id": "TEXT DEFAULT ''",
    "book_id": "TEXT DEFAULT ''",
    "success": "INTEGER DEFAULT 1",
}


def ensure_table(conn):
    """Ensure audit_log table exists."""
    conn.execute(TABLE_DDL)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(audit_log)").fetchall()}
    for name, ddl in EXTRA_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE audit_log ADD COLUMN {name} {ddl}")
    conn.commit()


def log_event(
    conn,
    event_type: str,
    description: str,
    details: str = "",
    severity: str = "info",
    target: str = "",
    database_id: str = "",
    book_id: str = "",
    success: bool = True,
):
    """Log a security event.

    Args:
        conn: Database connection (must support .execute())
        event_type: e.g. "backup.create", "ai.config.update", "changeset.confirm"
        description: Human-readable description
        details: JSON or other structured details
        severity: "info", "warning", "error", "critical"
    """
    try:
        ensure_table(conn)
        conn.execute(
            "INSERT INTO audit_log (event_type, action, target, database_id, book_id, success, description, details, severity) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_type,
                event_type,
                (target or "")[:300],
                (database_id or "")[:100],
                (book_id or "")[:100],
                1 if success else 0,
                description[:500],
                (details or "")[:2000],
                severity,
            ),
        )
        conn.commit()
        if severity in ("error", "critical"):
            log.warning("AUDIT [%s] %s: %s", severity, event_type, description)
        else:
            log.info("AUDIT [%s] %s: %s", severity, event_type, description)
    except Exception as e:
        log.error("Audit log write failed: %s", e)
