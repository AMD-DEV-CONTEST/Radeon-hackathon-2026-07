"""
scripts/vanguard_vault.py — Local Knowledge Compounding Telemetry

The Vanguard Vault is Determinex's local compounding intelligence layer.
Over time, it accumulates statistical signals about the patterns appearing
in the user's workspace — without storing any code, content, or personal data.

What it tracks (opt-in, all local, never transmitted):
  - Error pattern distribution (null pointer, borrow violations, schema mismatches)
  - Language/framework frequency (Rust, Go, Python, TypeScript)
  - Failure class frequency (compile, runtime, logic, test)
  - Rosetta routing statistics (which model families are activated most)
  - Session resolution rates (% of sessions that end in successful build)

What it NEVER stores:
  - Source code
  - Error messages verbatim
  - File paths
  - User identity

The accumulation thesis: after 90+ days of continuous use, the vault's
statistical fingerprint reflects the specific complexity profile of the user's
codebase. Re-instantiating a generic cloud agent would require months to rebuild
this fingerprint — making switching costs real and the local advantage durable.

Status: EXPERIMENTAL — requires DETERMINEX_VAULT_ENABLED=1 to activate.
This is deliberate. Ship the infrastructure; let community telemetry prove
the compounding value over time.

Usage:
    vault = VanguardVault()
    vault.record_session(SessionEvent(...))
    print(vault.summary())
    print(vault.compounding_score())  # 0.0–1.0 maturity metric
"""

import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

_ENABLED = os.environ.get("DETERMINEX_VAULT_ENABLED", "").strip().lower() in ("1", "true", "yes")
_DEFAULT_DB = Path("determinex_vault.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       REAL    NOT NULL,
    session_id      TEXT    NOT NULL,
    language        TEXT    DEFAULT '',
    framework       TEXT    DEFAULT '',
    error_class     TEXT    DEFAULT '',   -- compile / runtime / logic / test / none
    error_pattern   TEXT    DEFAULT '',   -- normalized pattern type (no content)
    resolved        INTEGER DEFAULT 0,   -- 1 = session ended in success
    build_attempts  INTEGER DEFAULT 1,
    rosetta_family  TEXT    DEFAULT '',  -- which rosetta family was used
    dag_steps       INTEGER DEFAULT 0,
    duration_sec    REAL    DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS language_stats (
    language    TEXT PRIMARY KEY,
    count       INTEGER DEFAULT 0,
    last_seen   REAL    DEFAULT 0
);

CREATE TABLE IF NOT EXISTS error_pattern_stats (
    pattern     TEXT PRIMARY KEY,
    count       INTEGER DEFAULT 0,
    resolved    INTEGER DEFAULT 0,
    last_seen   REAL    DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_vault_timestamp   ON session_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_vault_language     ON session_events(language);
CREATE INDEX IF NOT EXISTS idx_vault_error_class  ON session_events(error_class);
"""


# ---------------------------------------------------------------------------
# EVENTS
# ---------------------------------------------------------------------------

# Normalized error pattern labels (never store actual error text)
ERROR_PATTERNS = {
    # Rust
    "rust_borrow_conflict",
    "rust_lifetime_mismatch",
    "rust_type_mismatch",
    "rust_trait_not_implemented",
    "rust_move_after_use",
    # Go
    "go_nil_deref",
    "go_interface_mismatch",
    "go_goroutine_leak",
    "go_channel_deadlock",
    "go_import_cycle",
    # Python
    "py_attribute_error",
    "py_import_error",
    "py_type_error",
    "py_key_error",
    "py_index_error",
    # TypeScript
    "ts_property_missing",
    "ts_type_mismatch",
    "ts_null_check",
    "ts_module_not_found",
    # General
    "schema_mismatch",
    "api_signature_violation",
    "dag_cycle",
    "test_assertion_failure",
    "build_timeout",
    "unknown",
}


@dataclass
class SessionEvent:
    """
    A single Determinex session's statistical fingerprint.
    Contains NO source code, NO file paths, NO error text verbatim.
    """

    session_id: str
    language: str = ""  # "rust", "go", "python", "typescript", etc.
    framework: str = ""  # "axum", "gin", "fastapi", etc.
    error_class: str = "none"  # "compile", "runtime", "logic", "test", "none"
    error_pattern: str = "unknown"  # normalized label from ERROR_PATTERNS
    resolved: bool = True
    build_attempts: int = 1
    rosetta_family: str = ""  # which rosetta family routing was used
    dag_steps: int = 0  # how many DAG steps the session required
    duration_sec: float = 0.0

    def validate(self):
        """Ensure no raw content leaked into pattern field."""
        if self.error_pattern not in ERROR_PATTERNS:
            self.error_pattern = "unknown"
        return self


# ---------------------------------------------------------------------------
# VAULT
# ---------------------------------------------------------------------------


class VanguardVault:
    """
    Opt-in local telemetry store for the compounding intelligence layer.

    When DETERMINEX_VAULT_ENABLED=0 (default), all methods are no-ops.
    When DETERMINEX_VAULT_ENABLED=1, events are recorded to a local sqlite DB.
    Nothing leaves the machine. No network calls. DETERMINEX_OFFLINE has no effect
    on the vault — it is always local.
    """

    def __init__(self, db_path: Path = _DEFAULT_DB, force_enable: bool = False):
        self.enabled = _ENABLED or force_enable
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

        if self.enabled:
            self._init_db()
            print(
                f"[VanguardVault] EXPERIMENTAL — tracking enabled. "
                f"DB: {self.db_path} | No content stored.",
                flush=True,
            )
        else:
            print(
                "[VanguardVault] Inactive (set DETERMINEX_VAULT_ENABLED=1 to enable). "
                "This is the local compounding intelligence layer.",
                flush=True,
            )

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)

    # ── Write ─────────────────────────────────────────────────────────────────

    def record_session(self, event: SessionEvent) -> bool:
        """
        Record a session statistical event.
        No-op if vault is disabled.
        Returns True if recorded, False if skipped.
        """
        if not self.enabled or self._conn is None:
            return False

        event.validate()

        now = time.time()
        self._conn.execute(
            """INSERT INTO session_events
               (timestamp, session_id, language, framework, error_class, error_pattern,
                resolved, build_attempts, rosetta_family, dag_steps, duration_sec)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                now,
                event.session_id,
                event.language,
                event.framework,
                event.error_class,
                event.error_pattern,
                1 if event.resolved else 0,
                event.build_attempts,
                event.rosetta_family,
                event.dag_steps,
                event.duration_sec,
            ),
        )

        # Update aggregated stats
        self._conn.execute(
            """INSERT INTO language_stats (language, count, last_seen)
               VALUES (?, 1, ?)
               ON CONFLICT(language) DO UPDATE SET count=count+1, last_seen=?""",
            (event.language, now, now),
        )
        if event.error_pattern != "none":
            self._conn.execute(
                """INSERT INTO error_pattern_stats (pattern, count, resolved, last_seen)
                   VALUES (?, 1, ?, ?)
                   ON CONFLICT(pattern) DO UPDATE SET
                       count=count+1,
                       resolved=resolved+?,
                       last_seen=?""",
                (
                    event.error_pattern,
                    1 if event.resolved else 0,
                    now,
                    1 if event.resolved else 0,
                    now,
                ),
            )
        return True

    # ── Read ──────────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Return a statistical summary of accumulated vault data."""
        if not self.enabled or self._conn is None:
            return {"enabled": False, "message": "Set DETERMINEX_VAULT_ENABLED=1 to activate."}

        total = self._conn.execute(
            "SELECT COUNT(*), SUM(resolved), AVG(build_attempts), AVG(duration_sec) FROM session_events"
        ).fetchone()

        lang_dist = dict(
            self._conn.execute(
                "SELECT language, count FROM language_stats ORDER BY count DESC LIMIT 10"
            ).fetchall()
        )

        error_dist = dict(
            self._conn.execute(
                "SELECT pattern, count FROM error_pattern_stats ORDER BY count DESC LIMIT 10"
            ).fetchall()
        )

        resolution_rate = (total[1] or 0) / max(total[0] or 1, 1)
        days_active = self._days_active()

        return {
            "enabled": True,
            "total_sessions": total[0] or 0,
            "resolution_rate": round(resolution_rate, 3),
            "avg_build_attempts": round(total[2] or 0, 2),
            "avg_duration_sec": round(total[3] or 0, 1),
            "days_active": days_active,
            "language_dist": lang_dist,
            "error_pattern_dist": error_dist,
            "compounding_score": round(self.compounding_score(), 3),
        }

    def compounding_score(self) -> float:
        """
        A 0.0–1.0 metric representing vault maturity.

        Score components:
          - Volume (sessions accumulated): 0–40 pts
          - Diversity (language/error breadth): 0–30 pts
          - Longevity (days active): 0–30 pts

        At 6 months of daily use (~180 days, ~500+ sessions):
          score approaches 0.85–1.0, representing a deeply personalized instance.

        At launch (day 1): score is 0.0.
        """
        if not self.enabled or self._conn is None:
            return 0.0

        total_sessions = (
            self._conn.execute("SELECT COUNT(*) FROM session_events").fetchone()[0] or 0
        )

        n_languages = (
            self._conn.execute("SELECT COUNT(*) FROM language_stats WHERE count >= 3").fetchone()[0]
            or 0
        )

        n_patterns = (
            self._conn.execute(
                "SELECT COUNT(*) FROM error_pattern_stats WHERE count >= 2"
            ).fetchone()[0]
            or 0
        )

        days = self._days_active()

        # Volume: log-scaled, 500 sessions → 40 pts
        import math

        volume_score = min(40.0, 40.0 * math.log1p(total_sessions) / math.log1p(500))
        # Diversity: 10+ languages/patterns → 30 pts
        diversity_score = min(30.0, (n_languages + n_patterns) / 20 * 30)
        # Longevity: 180 days → 30 pts
        longevity_score = min(30.0, days / 180 * 30)

        return (volume_score + diversity_score + longevity_score) / 100.0

    def _days_active(self) -> int:
        """Number of calendar days with at least one session."""
        if not self._conn:
            return 0
        rows = self._conn.execute(
            "SELECT DISTINCT date(timestamp, 'unixepoch') FROM session_events"
        ).fetchall()
        return len(rows)

    def purge_older_than_days(self, days: int) -> int:
        """Delete sessions older than `days` days. Returns row count."""
        if not self.enabled or self._conn is None:
            return 0
        cutoff = time.time() - days * 86400
        cur = self._conn.execute("DELETE FROM session_events WHERE timestamp < ?", (cutoff,))
        return cur.rowcount

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ---------------------------------------------------------------------------
# SELF-TEST
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uuid

    print("[VanguardVault] Self-test (force_enable=True)...", flush=True)

    import os as _os
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    with VanguardVault(db_path=db_path, force_enable=True) as vault:
        # Simulate 30 days of sessions
        import random

        languages = ["rust", "go", "python", "typescript"]
        patterns = list(ERROR_PATTERNS)[:8]
        for i in range(120):
            vault.record_session(
                SessionEvent(
                    session_id=str(uuid.uuid4()),
                    language=random.choice(languages),
                    framework=random.choice(["axum", "gin", "fastapi", "express"]),
                    error_class=random.choice(["compile", "runtime", "logic", "none"]),
                    error_pattern=random.choice(patterns),
                    resolved=random.random() > 0.2,
                    build_attempts=random.randint(1, 5),
                    rosetta_family=random.choice(["mistral", "qwen", "llama"]),
                    dag_steps=random.randint(1, 8),
                    duration_sec=random.uniform(10, 300),
                )
            )

        summary = vault.summary()
        print(json.dumps(summary, indent=2))
        assert summary["total_sessions"] == 120
        assert summary["compounding_score"] >= 0.0
        assert summary["compounding_score"] <= 1.0
        print(
            f"\n[VanguardVault] Compounding score after 120 sessions: {summary['compounding_score']:.3f}"
        )

    _os.unlink(db_path)
    print("[VanguardVault] Self-test passed.", flush=True)
