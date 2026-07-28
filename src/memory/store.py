"""
SQLite persistence layer for tracking optimization attempts and outcomes.

Schema:
    optimization_attempts (
        id, timestamp, codebase_fingerprint, pattern_type,
        hypothesis, diff_summary, measured_speedup_ratio,
        outcome (accepted/rejected/regressed), notes
    )
"""

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DEFAULT_DB_PATH = "omnikernel_memory.db"


@dataclass
class OptimizationAttempt:
    codebase_fingerprint: str
    pattern_type: str
    hypothesis: str
    diff_summary: str
    measured_speedup_ratio: Optional[float] = None
    outcome: Optional[str] = None   # accepted | rejected | regressed
    notes: Optional[str] = None
    id: Optional[int] = None
    timestamp: Optional[str] = None


def fingerprint_codebase(path: str) -> str:
    """
    Generate a stable fingerprint for a codebase directory or file.
    Uses a hash of relative file paths + sizes (fast, no content read needed).
    """
    p = Path(path)
    if p.is_file():
        stat = p.stat()
        return hashlib.sha256(f"{p.name}:{stat.st_size}".encode()).hexdigest()[:16]

    parts = []
    for f in sorted(p.rglob("*.py")):
        parts.append(f"{f.relative_to(p)}:{f.stat().st_size}")
    content = "\n".join(parts)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class MemoryStore:
    """
    Persists optimization attempts to SQLite and supports history lookup
    so the agent can surface prior outcomes before proposing a new fix.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self.init_db()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def init_db(self) -> None:
        """Create tables from schema.sql if they don't already exist."""
        conn = self._get_conn()
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema_sql)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record_attempt(self, attempt: OptimizationAttempt) -> int:
        """
        Insert a new optimization attempt.
        Returns the newly assigned row id.
        """
        conn = self._get_conn()
        cursor = conn.execute(
            """
            INSERT INTO optimization_attempts
                (codebase_fingerprint, pattern_type, hypothesis,
                 diff_summary, measured_speedup_ratio, outcome, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt.codebase_fingerprint,
                attempt.pattern_type,
                attempt.hypothesis,
                attempt.diff_summary,
                attempt.measured_speedup_ratio,
                attempt.outcome,
                attempt.notes,
            ),
        )
        conn.commit()
        return cursor.lastrowid

    def update_outcome(
        self,
        attempt_id: int,
        outcome: str,
        speedup_ratio: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> None:
        """Update the outcome (accepted/rejected/regressed) after benchmarking."""
        conn = self._get_conn()
        conn.execute(
            """
            UPDATE optimization_attempts
            SET outcome = ?,
                measured_speedup_ratio = COALESCE(?, measured_speedup_ratio),
                notes = COALESCE(?, notes)
            WHERE id = ?
            """,
            (outcome, speedup_ratio, notes, attempt_id),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_history_for_pattern(
        self,
        pattern_type: str,
        codebase_fingerprint: str,
        limit: int = 5,
    ) -> list[dict]:
        """
        Retrieve prior attempts matching this pattern_type on this codebase.
        Used to surface history in the agent's reasoning:
        "last time we tried block-size tuning here, it regressed — here's why this is different."
        """
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT * FROM optimization_attempts
            WHERE pattern_type = ? AND codebase_fingerprint = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (pattern_type, codebase_fingerprint, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_for_codebase(self, codebase_fingerprint: str) -> list[dict]:
        """Fetch all attempts for a given codebase fingerprint."""
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT * FROM optimization_attempts
            WHERE codebase_fingerprint = ?
            ORDER BY timestamp DESC
            """,
            (codebase_fingerprint,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_attempt_by_id(self, attempt_id: int) -> Optional[dict]:
        """Fetch a single attempt by its id."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM optimization_attempts WHERE id = ?",
            (attempt_id,),
        ).fetchone()
        return dict(row) if row else None

    def summarize_history(self, codebase_fingerprint: str) -> str:
        """
        Return a human-readable summary of past attempts for this codebase.
        Injected into the planner's context to inform its reasoning.
        """
        attempts = self.get_all_for_codebase(codebase_fingerprint)
        if not attempts:
            return "No prior optimization attempts recorded for this codebase."

        lines = [f"Prior optimization attempts for this codebase ({len(attempts)} total):"]
        for a in attempts:
            speedup = f"{a['measured_speedup_ratio']:.2f}x" if a["measured_speedup_ratio"] else "unmeasured"
            lines.append(
                f"  [{a['timestamp'][:19]}] pattern={a['pattern_type']!r} "
                f"outcome={a['outcome'] or 'pending'} speedup={speedup} — {a['hypothesis'][:80]}..."
            )
        return "\n".join(lines)
