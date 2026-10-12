"""
SQLite audit log — structured security event logging.

Persists every security decision with full explainability chain.
Survives restarts. Powers the dashboard analytics and pattern memory.
"""

from __future__ import annotations

import json
import sqlite3
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from warden.tiers.base import SecurityEvent

logger = logging.getLogger(__name__)


class AuditLog:
    """Persistent security event audit log backed by SQLite."""

    def __init__(self, db_path: str = "warden_audit.db"):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

    def initialize(self) -> bool:
        """Create database and tables if they don't exist."""
        try:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._create_tables()
            logger.info(f"Audit log initialized: {self.db_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize audit log: {e}")
            return False

    def _create_tables(self):
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                input_preview TEXT,
                source TEXT,
                trust_level TEXT,
                tier_reached INTEGER,
                decision TEXT NOT NULL,
                confidence REAL,
                latency_ms REAL,
                explanation_chain TEXT,
                user_override INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT NOT NULL,
                end_time TEXT,
                total_checks INTEGER DEFAULT 0,
                blocks INTEGER DEFAULT 0,
                flags INTEGER DEFAULT 0,
                allows INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS patterns (
                input_hash TEXT PRIMARY KEY,
                first_seen TEXT NOT NULL,
                times_seen INTEGER DEFAULT 1,
                last_decision TEXT,
                auto_block INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_events_hash ON events(input_hash);
            CREATE INDEX IF NOT EXISTS idx_events_decision ON events(decision);
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
        """)
        self._conn.commit()

    def log_event(self, event: SecurityEvent) -> int:
        """Log a security event. Returns the event ID."""
        if not self._conn:
            return -1

        timestamp = event.timestamp or datetime.now(timezone.utc).isoformat()
        
        with self._lock:
            cursor = self._conn.cursor()

            cursor.execute("""
                INSERT INTO events (timestamp, input_hash, input_preview, source,
                                  trust_level, tier_reached, decision, confidence,
                                  latency_ms, explanation_chain, user_override)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                timestamp,
                event.input_hash,
                event.input_preview[:200],
                event.source,
                event.trust_level,
                event.tier_reached,
                event.decision,
                event.confidence,
                event.latency_ms,
                json.dumps(event.explanation_chain),
                1 if event.user_override else 0,
            ))

            # Update pattern tracker
            cursor.execute("""
                INSERT INTO patterns (input_hash, first_seen, times_seen, last_decision)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(input_hash) DO UPDATE SET
                    times_seen = times_seen + 1,
                    last_decision = ?
            """, (event.input_hash, timestamp, event.decision, event.decision))

            self._conn.commit()
            return cursor.lastrowid

    def mark_auto_block(self, input_hash: str, reason: str = "") -> bool:
        """Mark a pattern for automatic blocking."""
        if not self._conn:
            return False
        
        with self._lock:
            cursor = self._conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute("""
                INSERT INTO patterns (input_hash, first_seen, times_seen, last_decision, auto_block)
                VALUES (?, ?, 1, 'block', 1)
                ON CONFLICT(input_hash) DO UPDATE SET auto_block = 1
            """, (input_hash, now))
            self._conn.commit()
            return cursor.rowcount > 0

    def sweep_repeat_offenders(self, threshold: int = 3) -> int:
        """Scan across sessions and mark any pattern exceeding the block threshold as auto-blocked."""
        if not self._conn:
            return 0
            
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("""
                UPDATE patterns 
                SET auto_block = 1 
                WHERE last_decision = 'block' 
                  AND times_seen >= ? 
                  AND auto_block = 0
            """, (threshold,))
            self._conn.commit()
            return cursor.rowcount

    def is_known_blocked(self, input_hash: str) -> bool:
        """Check if this input hash has been auto-blocked before."""
        if not self._conn:
            return False
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT auto_block FROM patterns WHERE input_hash = ? AND auto_block = 1",
            (input_hash,)
        )
        return cursor.fetchone() is not None

    def is_known_safe(self, input_hash: str) -> bool:
        """Check if this input hash was previously allowed 3+ times."""
        if not self._conn:
            return False
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT times_seen FROM patterns WHERE input_hash = ? AND last_decision = 'allow' AND times_seen >= 3",
            (input_hash,)
        )
        return cursor.fetchone() is not None

    def get_pattern_count(self, input_hash: str) -> int:
        """Get the number of times a pattern has been seen across all processes."""
        if not self._conn:
            return 0
        cursor = self._conn.cursor()
        cursor.execute("SELECT times_seen FROM patterns WHERE input_hash = ?", (input_hash,))
        row = cursor.fetchone()
        return row["times_seen"] if row else 0

    def get_recent_events(self, limit: int = 50) -> list[dict]:
        """Get recent security events for dashboard display."""
        if not self._conn:
            return []
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> dict:
        """Get summary statistics for the dashboard."""
        if not self._conn:
            return {}
        cursor = self._conn.cursor()
        cursor.execute("SELECT COUNT(*) as total FROM events")
        total = cursor.fetchone()["total"]
        cursor.execute("SELECT decision, COUNT(*) as count FROM events GROUP BY decision")
        by_decision = {row["decision"]: row["count"] for row in cursor.fetchall()}
        return {"total_events": total, "by_decision": by_decision}

    def close(self):
        if self._conn:
            self._conn.close()
