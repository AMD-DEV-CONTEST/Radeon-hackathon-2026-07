from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Mapping

from .models import (
    AuditEntry,
    ConfirmationRequired,
    IdempotencyConflict,
    PermissionDenied,
    Role,
    ToolEffect,
    UserContext,
)


DEFAULT_ROOMS = (
    ("standard", 2, 12_900, 8),
    ("deluxe", 3, 18_900, 5),
    ("suite", 4, 29_900, 2),
)

_SENSITIVE_AUDIT_KEYS = {
    "address",
    "description",
    "email",
    "full_name",
    "guest_name",
    "name",
    "notes",
    "phone",
    "preference_value",
    "prompt",
    "user_id",
    "value",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_utc(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat(timespec="seconds")


def stable_hash(data: Any) -> str:
    encoded = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def actor_reference(user_id: str) -> str:
    return f"usr_{hashlib.sha256(user_id.encode('utf-8')).hexdigest()[:16]}"


def minimize_audit_details(details: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep operational metadata while dropping likely PII and free text."""

    def clean(value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return value[:80]
        if isinstance(value, Mapping):
            return {
                str(key): clean(item)
                for key, item in value.items()
                if str(key).lower() not in _SENSITIVE_AUDIT_KEYS
            }
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value[:20]]
        return str(value)[:80]

    return clean(details or {})


class HotelStore:
    """SQLite persistence with nested atomic transactions and privacy-safe audit."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self.connection = sqlite3.connect(
            str(database), isolation_level=None, check_same_thread=False
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        if str(database) != ":memory:":
            self.connection.execute("PRAGMA journal_mode = WAL")
            self.connection.execute("PRAGMA synchronous = NORMAL")
        self._lock = threading.RLock()
        self._local = threading.local()

    def close(self) -> None:
        self.connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            depth = int(getattr(self._local, "depth", 0))
            savepoint = f"domain_sp_{depth}"
            if depth == 0:
                self.connection.execute("BEGIN IMMEDIATE")
            else:
                self.connection.execute(f"SAVEPOINT {savepoint}")
            self._local.depth = depth + 1
            try:
                yield self.connection
            except Exception:
                if depth == 0:
                    self.connection.rollback()
                else:
                    self.connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    self.connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            else:
                if depth == 0:
                    self.connection.commit()
                else:
                    self.connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            finally:
                self._local.depth = depth

    def initialize(self, *, seed: bool = True) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS rooms (
            room_type TEXT PRIMARY KEY,
            capacity INTEGER NOT NULL CHECK (capacity > 0),
            nightly_rate_cents INTEGER NOT NULL CHECK (nightly_rate_cents >= 0),
            inventory INTEGER NOT NULL CHECK (inventory >= 0)
        );
        CREATE TABLE IF NOT EXISTS bookings (
            booking_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            room_type TEXT NOT NULL REFERENCES rooms(room_type),
            check_in TEXT NOT NULL,
            check_out TEXT NOT NULL,
            guests INTEGER NOT NULL CHECK (guests > 0),
            total_cents INTEGER NOT NULL CHECK (total_cents >= 0),
            currency TEXT NOT NULL DEFAULT 'CNY',
            status TEXT NOT NULL CHECK (status IN ('held', 'confirmed', 'cancelled')),
            hold_expires_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_bookings_overlap
            ON bookings(room_type, check_in, check_out, status);
        CREATE INDEX IF NOT EXISTS idx_bookings_owner ON bookings(user_id);
        CREATE TABLE IF NOT EXISTS service_tickets (
            ticket_id TEXT PRIMARY KEY,
            booking_id TEXT NOT NULL REFERENCES bookings(booking_id),
            created_by TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memory_consent (
            user_id TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id TEXT NOT NULL,
            preference_key TEXT NOT NULL,
            preference_value TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, preference_key)
        );
        CREATE TABLE IF NOT EXISTS confirmation_tokens (
            token_hash TEXT PRIMARY KEY,
            actor_ref TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT
        );
        CREATE TABLE IF NOT EXISTS idempotency_records (
            actor_ref TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (actor_ref, tool_name, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            actor_ref TEXT NOT NULL,
            role TEXT NOT NULL,
            action TEXT NOT NULL,
            effect TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id TEXT,
            outcome TEXT NOT NULL,
            details_json TEXT NOT NULL
        );
        """
        # sqlite3.executescript() controls its own transaction boundary. Keep it
        # outside the explicit seed transaction so rollback semantics stay honest.
        with self._lock:
            self.connection.executescript(schema)
        with self.transaction() as connection:
            if seed:
                connection.executemany(
                    """
                    INSERT INTO rooms(room_type, capacity, nightly_rate_cents, inventory)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(room_type) DO NOTHING
                    """,
                    DEFAULT_ROOMS,
                )
            now = iso_utc()
            retention_cutoff = iso_utc(utc_now() - timedelta(days=30))
            connection.execute(
                "DELETE FROM confirmation_tokens WHERE used_at IS NOT NULL OR expires_at < ?",
                (now,),
            )
            connection.execute(
                "DELETE FROM idempotency_records WHERE created_at < ?",
                (retention_cutoff,),
            )
            connection.execute(
                """
                UPDATE bookings SET status = 'cancelled', updated_at = ?
                WHERE status = 'held' AND hold_expires_at <= ?
                """,
                (now, now),
            )

    def create_confirmation(
        self,
        context: UserContext,
        tool_name: str,
        payload_hash: str,
        *,
        ttl_seconds: int = 300,
        preview: Mapping[str, Any] | None = None,
    ) -> ConfirmationRequired:
        token = secrets.token_urlsafe(24)
        expires = utc_now() + timedelta(seconds=ttl_seconds)
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO confirmation_tokens(
                    token_hash, actor_ref, tool_name, payload_hash, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    stable_hash(token),
                    actor_reference(context.user_id),
                    tool_name,
                    payload_hash,
                    iso_utc(expires),
                ),
            )
        return ConfirmationRequired(token, iso_utc(expires), preview)

    def consume_confirmation(
        self,
        context: UserContext,
        tool_name: str,
        payload_hash: str,
        token: str,
    ) -> None:
        row = self.connection.execute(
            "SELECT * FROM confirmation_tokens WHERE token_hash = ?",
            (stable_hash(token),),
        ).fetchone()
        valid = (
            row is not None
            and row["actor_ref"] == actor_reference(context.user_id)
            and row["tool_name"] == tool_name
            and row["payload_hash"] == payload_hash
            and row["used_at"] is None
            and datetime.fromisoformat(row["expires_at"]) >= utc_now()
        )
        if not valid:
            raise PermissionDenied(
                "confirmation token is invalid, expired, mismatched, or its authoritative "
                "preview terms changed; request a fresh preview"
            )
        self.connection.execute(
            "UPDATE confirmation_tokens SET used_at = ? WHERE token_hash = ?",
            (iso_utc(), stable_hash(token)),
        )

    def get_idempotent_response(
        self,
        context: UserContext,
        tool_name: str,
        idempotency_key: str,
        payload_hash: str,
    ) -> str | None:
        row = self.connection.execute(
            """
            SELECT payload_hash, response_json FROM idempotency_records
            WHERE actor_ref = ? AND tool_name = ? AND idempotency_key = ?
            """,
            (actor_reference(context.user_id), tool_name, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != payload_hash:
            raise IdempotencyConflict(
                "idempotency key was already used with a different request"
            )
        return str(row["response_json"])

    def save_idempotent_response(
        self,
        context: UserContext,
        tool_name: str,
        idempotency_key: str,
        payload_hash: str,
        response_json: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO idempotency_records(
                actor_ref, tool_name, idempotency_key, payload_hash,
                response_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                actor_reference(context.user_id),
                tool_name,
                idempotency_key,
                payload_hash,
                response_json,
                iso_utc(),
            ),
        )

    def audit(
        self,
        context: UserContext,
        *,
        action: str,
        effect: ToolEffect,
        resource_type: str,
        resource_id: str | None = None,
        outcome: str = "success",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO audit_log(
                occurred_at, actor_ref, role, action, effect, resource_type,
                resource_id, outcome, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                iso_utc(),
                actor_reference(context.user_id),
                context.role.value,
                action,
                effect.value,
                resource_type,
                resource_id,
                outcome,
                json.dumps(
                    minimize_audit_details(details),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )

    def list_audit(self, context: UserContext, *, limit: int = 100) -> tuple[AuditEntry, ...]:
        if context.role not in {Role.STAFF, Role.ADMIN}:
            raise PermissionDenied("staff role required")
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM audit_log ORDER BY audit_id DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return tuple(
            AuditEntry(
                occurred_at=row["occurred_at"],
                actor_ref=row["actor_ref"],
                role=row["role"],
                action=row["action"],
                effect=row["effect"],
                resource_type=row["resource_type"],
                resource_id=row["resource_id"],
                outcome=row["outcome"],
                details=json.loads(row["details_json"]),
            )
            for row in rows
        )
