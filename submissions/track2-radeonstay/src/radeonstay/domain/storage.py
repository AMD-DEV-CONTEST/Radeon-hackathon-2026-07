from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import (
    AuditEntry,
    ConfirmationRequired,
    ConflictError,
    IdempotencyConflict,
    JourneyStateSnapshot,
    PermissionDenied,
    PersistedSessionAuditEvent,
    Role,
    ToolEffect,
    UserContext,
    ValidationError,
)

CURRENT_SCHEMA_VERSION = 7
AUDIT_GENESIS_HASH = "0" * 64
AUDIT_KEY_ID_METADATA_KEY = "session_audit_hmac_key_id"
AUDIT_CATALOG_METADATA_KEY = "session_audit_catalog_hmac"
_AUDIT_KEY_ID_CONTEXT = b"radeonstay/session-audit-key-id/v1"
_AUDIT_ROW_CONTEXT = "radeonstay/session-audit-row/v1"
_AUDIT_HEAD_CONTEXT = "radeonstay/session-audit-head/v1"
_AUDIT_CATALOG_CONTEXT = "radeonstay/session-audit-catalog/v1"
_JOURNEY_STATE_CONTEXT = "radeonstay/journey-state/v1"
_LOWER_HEX_CHARS = frozenset("0123456789abcdef")
_MAX_SESSION_ID_CHARS = 160
_MAX_PERSISTED_JSON_BYTES = 256 * 1024
_REQUIRED_SCHEMA_COLUMNS = {
    "rooms": frozenset(
        {"room_type", "capacity", "nightly_rate_cents", "inventory"}
    ),
    "bookings": frozenset(
        {
            "booking_id",
            "user_id",
            "room_type",
            "check_in",
            "check_out",
            "guests",
            "total_cents",
            "currency",
            "status",
            "hold_expires_at",
            "created_at",
            "updated_at",
        }
    ),
    "service_tickets": frozenset(
        {
            "ticket_id",
            "booking_id",
            "created_by",
            "category",
            "description",
            "status",
            "created_at",
            "updated_at",
        }
    ),
    "memory_consent": frozenset({"user_id", "enabled", "updated_at"}),
    "user_preferences": frozenset(
        {"user_id", "preference_key", "preference_value", "updated_at"}
    ),
    "confirmation_tokens": frozenset(
        {
            "token_hash",
            "actor_ref",
            "tool_name",
            "payload_hash",
            "expires_at",
            "used_at",
        }
    ),
    "idempotency_records": frozenset(
        {
            "actor_ref",
            "tool_name",
            "idempotency_key",
            "payload_hash",
            "response_json",
            "created_at",
        }
    ),
    "audit_log": frozenset(
        {
            "audit_id",
            "occurred_at",
            "actor_ref",
            "role",
            "action",
            "effect",
            "resource_type",
            "resource_id",
            "outcome",
            "details_json",
        }
    ),
    "journey_state": frozenset(
        {
            "session_id",
            "actor_ref",
            "version",
            "state_json",
            "updated_at",
            "state_hmac",
        }
    ),
    "session_audit_events": frozenset(
        {
            "session_id",
            "sequence",
            "actor_ref",
            "occurred_at",
            "event_json",
            "row_hmac",
        }
    ),
    "session_audit_heads": frozenset(
        {
            "session_id",
            "actor_ref",
            "event_count",
            "last_event_hash",
            "updated_at",
            "head_hmac",
        }
    ),
    "security_metadata": frozenset(
        {"metadata_key", "metadata_value", "updated_at"}
    ),
}
_REQUIRED_PRIMARY_KEYS = {
    "rooms": ("room_type",),
    "bookings": ("booking_id",),
    "service_tickets": ("ticket_id",),
    "memory_consent": ("user_id",),
    "user_preferences": ("user_id", "preference_key"),
    "confirmation_tokens": ("token_hash",),
    "idempotency_records": ("actor_ref", "tool_name", "idempotency_key"),
    "audit_log": ("audit_id",),
    "journey_state": ("session_id",),
    "session_audit_events": ("session_id", "sequence"),
    "session_audit_heads": ("session_id",),
    "security_metadata": ("metadata_key",),
}

DEFAULT_ROOMS = (
    ("standard", 2, 12_900, 8),
    ("deluxe", 3, 18_900, 5),
    ("suite", 4, 29_900, 2),
)

_SENSITIVE_AUDIT_KEYS = {
    "access_token",
    "address",
    "api_key",
    "authorization",
    "confirmation_token",
    "cookie",
    "description",
    "email",
    "full_name",
    "guest_name",
    "name",
    "notes",
    "password",
    "phone",
    "preference_value",
    "private_key",
    "prompt",
    "refresh_token",
    "secret",
    "session_token",
    "ssh_key",
    "token",
    "token_hash",
    "user_id",
    "value",
}
_SAFE_AUDIT_TOKEN_METRIC_KEYS = frozenset(
    {
        "completion_tokens",
        "max_tokens",
        "prompt_tokens",
        "total_tokens",
    }
)
_SENSITIVE_AUDIT_ASSIGNMENT_PATTERN = re.compile(
    r"\b([A-Za-z0-9_-]*(?:access[_-]?token|api[_-]?key|authorization|"
    r"confirmation[_-]?token|identity[_-]?token|password|refresh[_-]?token|"
    r"private[_-]?key|secret|session[_-]?token|ssh[_-]?key))"
    r"(\s*[:=]\s*)((?:bearer\s+)?[^\s,;&<>]+)",
    flags=re.IGNORECASE,
)
_BEARER_AUDIT_TOKEN_PATTERN = re.compile(
    r"\bbearer\s+[A-Za-z0-9._~+/=-]+",
    flags=re.IGNORECASE,
)


def _is_sensitive_audit_key(key: object) -> bool:
    normalized = str(key).casefold().replace("-", "_")
    if normalized in _SAFE_AUDIT_TOKEN_METRIC_KEYS:
        return False
    if normalized in _SENSITIVE_AUDIT_KEYS:
        return True
    return any(
        marker in normalized
        for marker in (
            "_api_key",
            "_credential",
            "_password",
            "_private_key",
            "_secret",
            "_ssh_key",
            "_token",
            "private_key_",
            "ssh_key_",
            "token_",
        )
    )


def _redact_sensitive_audit_text(value: str) -> str:
    redacted = _SENSITIVE_AUDIT_ASSIGNMENT_PATTERN.sub(
        lambda match: match.group(1) + match.group(2) + "[REDACTED]",
        value,
    )
    return _BEARER_AUDIT_TOKEN_PATTERN.sub("Bearer [REDACTED]", redacted)


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_utc(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat(timespec="seconds")


def stable_hash(data: Any) -> str:
    encoded = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _audit_key_bytes(audit_secret: str | bytes) -> bytes:
    if isinstance(audit_secret, str):
        encoded = audit_secret.encode("utf-8")
    elif isinstance(audit_secret, bytes):
        encoded = audit_secret
    else:
        raise TypeError("audit_secret must be text or bytes")
    if len(encoded) < 32:
        raise ValueError("audit_secret must contain at least 32 bytes")
    return encoded


def audit_key_id(audit_secret: str | bytes) -> str:
    """Derive a non-secret, domain-separated identifier for one audit key."""

    digest = hmac.new(
        _audit_key_bytes(audit_secret),
        _AUDIT_KEY_ID_CONTEXT,
        hashlib.sha256,
    ).hexdigest()
    return f"hmac-sha256:{digest}"


def sign_session_audit_payload(
    audit_secret: str | bytes,
    payload: Mapping[str, Any],
) -> str:
    """Return the canonical HMAC used by persisted session audit events."""

    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(_audit_key_bytes(audit_secret), encoded, hashlib.sha256).hexdigest()


def session_audit_row_hmac(
    audit_secret: str | bytes,
    *,
    session_id: str,
    sequence: int,
    actor_ref: str,
    occurred_at: str,
    event_hash: str,
) -> str:
    """Authenticate SQLite row identity around the already signed event payload."""

    payload = {
        "context": _AUDIT_ROW_CONTEXT,
        "session_id": session_id,
        "sequence": sequence,
        "actor_ref": actor_ref,
        "occurred_at": occurred_at,
        "event_hash": event_hash,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(_audit_key_bytes(audit_secret), encoded, hashlib.sha256).hexdigest()


def session_audit_head_hmac(
    audit_secret: str | bytes,
    *,
    session_id: str,
    actor_ref: str,
    event_count: int,
    last_event_hash: str,
    updated_at: str,
) -> str:
    """Authenticate the durable head of one complete session audit chain."""

    payload = {
        "context": _AUDIT_HEAD_CONTEXT,
        "session_id": session_id,
        "actor_ref": actor_ref,
        "event_count": event_count,
        "last_event_hash": last_event_hash,
        "updated_at": updated_at,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(_audit_key_bytes(audit_secret), encoded, hashlib.sha256).hexdigest()


def session_audit_catalog_hmac(
    audit_secret: str | bytes,
    heads: list[Mapping[str, Any]],
) -> str:
    """Authenticate the exact set of session heads, including an empty catalog."""

    normalized = [
        {
            "session_id": str(head["session_id"]),
            "actor_ref": str(head["actor_ref"]),
            "event_count": int(head["event_count"]),
            "last_event_hash": str(head["last_event_hash"]),
            "updated_at": str(head["updated_at"]),
            "head_hmac": str(head["head_hmac"]),
        }
        for head in sorted(heads, key=lambda item: str(item["session_id"]))
    ]
    encoded = json.dumps(
        {"context": _AUDIT_CATALOG_CONTEXT, "heads": normalized},
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(_audit_key_bytes(audit_secret), encoded, hashlib.sha256).hexdigest()


def journey_state_hmac(
    audit_secret: str | bytes,
    *,
    session_id: str,
    actor_ref: str,
    version: int,
    state_json: str,
    updated_at: str,
) -> str:
    """Authenticate one identity-bound Journey snapshot and its version."""

    encoded = json.dumps(
        {
            "context": _JOURNEY_STATE_CONTEXT,
            "session_id": session_id,
            "actor_ref": actor_ref,
            "version": version,
            "state_json": state_json,
            "updated_at": updated_at,
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(_audit_key_bytes(audit_secret), encoded, hashlib.sha256).hexdigest()


def actor_reference(user_id: str) -> str:
    return f"usr_{hashlib.sha256(user_id.encode('utf-8')).hexdigest()[:16]}"


def _validated_session_id(session_id: str) -> str:
    value = session_id.strip() if isinstance(session_id, str) else ""
    if not value or len(value) > _MAX_SESSION_ID_CHARS:
        raise ValidationError(
            f"session_id must contain 1 to {_MAX_SESSION_ID_CHARS} characters"
        )
    return value


def _validated_owner_ref(owner_ref: str) -> str:
    value = owner_ref.strip() if isinstance(owner_ref, str) else ""
    if not value or len(value) > 128:
        raise ValidationError("owner_ref must contain 1 to 128 characters")
    return value


def _encode_json_object(value: Mapping[str, Any], *, label: str) -> str:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{label} must be a JSON object")
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} must contain only JSON-compatible values") from exc
    if len(encoded.encode("utf-8")) > _MAX_PERSISTED_JSON_BYTES:
        raise ValidationError(
            f"{label} exceeds the {_MAX_PERSISTED_JSON_BYTES}-byte persistence limit"
        )
    return encoded


def minimize_audit_details(details: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep operational metadata while dropping likely PII and free text."""

    def clean(value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return _redact_sensitive_audit_text(value)[:80]
        if isinstance(value, Mapping):
            return {
                str(key): clean(item)
                for key, item in value.items()
                if not _is_sensitive_audit_key(key)
            }
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value[:20]]
        return str(value)[:80]

    return clean(details or {})


class HotelStore:
    """SQLite persistence with nested atomic transactions and privacy-safe audit."""

    def __init__(
        self,
        database: str | Path = ":memory:",
        *,
        audit_secret: str,
    ) -> None:
        self._audit_key = _audit_key_bytes(audit_secret)
        self.connection = sqlite3.connect(
            str(database), isolation_level=None, check_same_thread=False
        )
        self.connection.row_factory = sqlite3.Row
        try:
            version = self.schema_version
            if version > CURRENT_SCHEMA_VERSION:
                raise RuntimeError(
                    "database schema is newer than this RadeonStay build: "
                    f"{version} > {CURRENT_SCHEMA_VERSION}"
                )
            if version >= 4:
                self._assert_audit_key_binding()
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.execute("PRAGMA busy_timeout = 5000")
            if str(database) != ":memory:":
                self.connection.execute("PRAGMA journal_mode = WAL")
                self.connection.execute("PRAGMA synchronous = NORMAL")
        except Exception:
            self.connection.close()
            raise
        self._lock = threading.RLock()
        self._local = threading.local()

    def close(self) -> None:
        self.connection.close()

    @property
    def schema_version(self) -> int:
        row = self.connection.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row is not None else 0

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
                try:
                    if depth == 0:
                        self._commit_transaction()
                    else:
                        self.connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                except Exception:
                    # A failed COMMIT can leave SQLite inside the transaction.
                    # Restore a reusable connection before propagating the error;
                    # callers must never apply in-memory state for this attempt.
                    try:
                        if depth == 0:
                            self.connection.rollback()
                        else:
                            self.connection.execute(
                                f"ROLLBACK TO SAVEPOINT {savepoint}"
                            )
                            self.connection.execute(
                                f"RELEASE SAVEPOINT {savepoint}"
                            )
                    except sqlite3.Error:
                        pass
                    raise
            finally:
                self._local.depth = depth

    def _commit_transaction(self) -> None:
        """Commit one outer transaction; kept separate for fault injection."""

        self.connection.commit()

    def initialize(self, *, seed: bool = True) -> None:
        """Create the legacy baseline and apply every additive schema migration."""

        version = self.schema_version
        if version > CURRENT_SCHEMA_VERSION:
            raise RuntimeError(
                "database schema is newer than this RadeonStay build: "
                f"{version} > {CURRENT_SCHEMA_VERSION}"
            )
        if version == CURRENT_SCHEMA_VERSION:
            # A database that already claims the current version must be
            # structurally complete before any CREATE IF NOT EXISTS statement
            # could silently recreate a missing table.
            self._validate_schema()

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
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
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
        self._migrate_schema()
        self._validate_schema()
        self._assert_audit_key_binding()
        self._verify_all_session_audit_chains()
        self._verify_all_journey_snapshots()
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
                """
                DELETE FROM confirmation_tokens
                WHERE used_at IS NOT NULL OR expires_at < ?
                """,
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

    def _migrate_schema(self) -> None:
        migrations = {
            1: self._migrate_to_v1,
            2: self._migrate_to_v2,
            3: self._migrate_to_v3,
            4: self._migrate_to_v4,
            5: self._migrate_to_v5,
            6: self._migrate_to_v6,
            7: self._migrate_to_v7,
        }
        while True:
            with self.transaction() as connection:
                row = connection.execute("PRAGMA user_version").fetchone()
                version = int(row[0]) if row is not None else 0
                if version > CURRENT_SCHEMA_VERSION:
                    raise RuntimeError(
                        "database schema is newer than this RadeonStay build: "
                        f"{version} > {CURRENT_SCHEMA_VERSION}"
                    )
                if version == CURRENT_SCHEMA_VERSION:
                    return
                target = version + 1
                migrations[target](connection)
                connection.execute(f"PRAGMA user_version = {target}")

    def _validate_schema(self) -> None:
        """Fail closed when a current database lacks required structures."""

        with self._lock:
            for table, required in _REQUIRED_SCHEMA_COLUMNS.items():
                table_info = self.connection.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
                columns = {str(row["name"]) for row in table_info}
                missing = sorted(required - columns)
                if missing:
                    raise RuntimeError(
                        f"database schema is missing {table} columns: {missing}"
                    )
                observed_primary_key = tuple(
                    str(row["name"])
                    for row in sorted(table_info, key=lambda item: int(item["pk"]))
                    if int(row["pk"]) > 0
                )
                expected_primary_key = _REQUIRED_PRIMARY_KEYS[table]
                if observed_primary_key != expected_primary_key:
                    raise RuntimeError(
                        f"database schema has invalid {table} primary key"
                    )

    @staticmethod
    def _migrate_to_v1(connection: sqlite3.Connection) -> None:
        """Mark the additive baseline created by ``initialize``."""

        del connection

    @staticmethod
    def _migrate_to_v2(connection: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(service_tickets)")
        }
        if "updated_at" not in columns:
            connection.execute(
                "ALTER TABLE service_tickets "
                "ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''"
            )
        connection.execute(
            """
            UPDATE service_tickets
            SET updated_at = created_at
            WHERE updated_at = ''
            """
        )

    @staticmethod
    def _migrate_to_v3(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS journey_state (
                session_id TEXT PRIMARY KEY,
                actor_ref TEXT NOT NULL,
                version INTEGER NOT NULL CHECK (version > 0),
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS session_audit_events (
                session_id TEXT NOT NULL,
                sequence INTEGER NOT NULL CHECK (sequence > 0),
                actor_ref TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                event_json TEXT NOT NULL,
                PRIMARY KEY (session_id, sequence)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_session_audit_actor
            ON session_audit_events(actor_ref, session_id, sequence)
            """
        )

    def _migrate_to_v4(self, connection: sqlite3.Connection) -> None:
        """Bind v3 history to the configured key only after full-chain verification."""

        self._verify_all_session_audit_chains(connection=connection)
        connection.execute(
            """
            CREATE TABLE security_metadata (
                metadata_key TEXT PRIMARY KEY,
                metadata_value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO security_metadata(metadata_key, metadata_value, updated_at)
            VALUES (?, ?, ?)
            """,
            (
                AUDIT_KEY_ID_METADATA_KEY,
                audit_key_id(self._audit_key),
                iso_utc(),
            ),
        )

    def _migrate_to_v5(self, connection: sqlite3.Connection) -> None:
        """Bind every persisted audit row to its session, order, owner, and time."""

        self._assert_audit_key_binding()
        self._verify_all_session_audit_chains(
            connection=connection,
            require_row_hmac=False,
        )
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(session_audit_events)")
        }
        if "row_hmac" not in columns:
            connection.execute(
                "ALTER TABLE session_audit_events "
                "ADD COLUMN row_hmac TEXT NOT NULL DEFAULT ''"
            )
        rows = connection.execute(
            """
            SELECT session_id, sequence, actor_ref, occurred_at, event_json
            FROM session_audit_events
            ORDER BY session_id, sequence
            """
        ).fetchall()
        for row in rows:
            try:
                event = json.loads(str(row["event_json"]))
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    "persisted session audit event is not valid JSON"
                ) from exc
            event_hash = event.get("event_hash") if isinstance(event, dict) else None
            if (
                not isinstance(event_hash, str)
                or len(event_hash) != 64
                or not set(event_hash) <= _LOWER_HEX_CHARS
            ):
                raise RuntimeError("persisted session audit hash is invalid")
            row_hmac = session_audit_row_hmac(
                self._audit_key,
                session_id=str(row["session_id"]),
                sequence=int(row["sequence"]),
                actor_ref=str(row["actor_ref"]),
                occurred_at=str(row["occurred_at"]),
                event_hash=event_hash,
            )
            connection.execute(
                """
                UPDATE session_audit_events SET row_hmac = ?
                WHERE session_id = ? AND sequence = ?
                """,
                (row_hmac, str(row["session_id"]), int(row["sequence"])),
            )
        self._verify_all_session_audit_chains(
            connection=connection,
            require_row_hmac=True,
        )

    def _migrate_to_v6(self, connection: sqlite3.Connection) -> None:
        """Anchor every session head and the exact global head catalog."""

        self._assert_audit_key_binding()
        self._verify_all_session_audit_chains(
            connection=connection,
            require_row_hmac=True,
            require_head_catalog=False,
        )
        connection.execute(
            """
            CREATE TABLE session_audit_heads (
                session_id TEXT PRIMARY KEY,
                actor_ref TEXT NOT NULL,
                event_count INTEGER NOT NULL CHECK (event_count > 0),
                last_event_hash TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                head_hmac TEXT NOT NULL
            )
            """
        )
        last_rows = connection.execute(
            """
            SELECT event.session_id, event.sequence, event.actor_ref,
                   event.occurred_at, event.event_json
            FROM session_audit_events AS event
            INNER JOIN (
                SELECT session_id, MAX(sequence) AS last_sequence
                FROM session_audit_events GROUP BY session_id
            ) AS tail
              ON tail.session_id = event.session_id
             AND tail.last_sequence = event.sequence
            ORDER BY event.session_id
            """
        ).fetchall()
        heads: list[dict[str, Any]] = []
        for row in last_rows:
            try:
                event = json.loads(str(row["event_json"]))
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    "persisted session audit event is not valid JSON"
                ) from exc
            event_hash = event.get("event_hash") if isinstance(event, dict) else None
            if (
                not isinstance(event_hash, str)
                or len(event_hash) != 64
                or not set(event_hash) <= _LOWER_HEX_CHARS
            ):
                raise RuntimeError("persisted session audit hash is invalid")
            head = self._audit_head_record(
                session_id=str(row["session_id"]),
                actor_ref=str(row["actor_ref"]),
                event_count=int(row["sequence"]),
                last_event_hash=event_hash,
                updated_at=str(row["occurred_at"]),
            )
            heads.append(head)
            connection.execute(
                """
                INSERT INTO session_audit_heads(
                    session_id, actor_ref, event_count, last_event_hash,
                    updated_at, head_hmac
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    head["session_id"],
                    head["actor_ref"],
                    head["event_count"],
                    head["last_event_hash"],
                    head["updated_at"],
                    head["head_hmac"],
                ),
            )
        connection.execute(
            """
            INSERT INTO security_metadata(metadata_key, metadata_value, updated_at)
            VALUES (?, ?, ?)
            """,
            (
                AUDIT_CATALOG_METADATA_KEY,
                "hmac-sha256:" + session_audit_catalog_hmac(self._audit_key, heads),
                iso_utc(),
            ),
        )
        self._verify_all_session_audit_chains(
            connection=connection,
            require_row_hmac=True,
            require_head_catalog=True,
        )

    def _migrate_to_v7(self, connection: sqlite3.Connection) -> None:
        """Authenticate every minimized Journey snapshot without rebuilding it."""

        self._assert_audit_key_binding()
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(journey_state)")
        }
        if "state_hmac" not in columns:
            connection.execute(
                "ALTER TABLE journey_state "
                "ADD COLUMN state_hmac TEXT NOT NULL DEFAULT ''"
            )
        rows = connection.execute(
            """
            SELECT session_id, actor_ref, version, state_json, updated_at
            FROM journey_state
            """
        ).fetchall()
        for row in rows:
            state_hmac = journey_state_hmac(
                self._audit_key,
                session_id=str(row["session_id"]),
                actor_ref=str(row["actor_ref"]),
                version=int(row["version"]),
                state_json=str(row["state_json"]),
                updated_at=str(row["updated_at"]),
            )
            connection.execute(
                "UPDATE journey_state SET state_hmac = ? WHERE session_id = ?",
                (state_hmac, str(row["session_id"])),
            )

    def assert_audit_key_matches(self, audit_secret: str | bytes) -> None:
        """Reject a service whose in-memory signing key differs from SQLite."""

        candidate = _audit_key_bytes(audit_secret)
        if not hmac.compare_digest(self._audit_key, candidate):
            raise RuntimeError("configured audit key does not match the persistence key")
        self._assert_audit_key_binding(candidate)

    def _assert_audit_key_binding(self, audit_key: bytes | None = None) -> None:
        expected = audit_key_id(audit_key or self._audit_key)
        try:
            row = self.connection.execute(
                """
                SELECT metadata_value FROM security_metadata
                WHERE metadata_key = ?
                """,
                (AUDIT_KEY_ID_METADATA_KEY,),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise RuntimeError("database audit-key metadata is unavailable") from exc
        stored = str(row["metadata_value"]) if row is not None else ""
        stored_digest = stored.removeprefix("hmac-sha256:")
        valid_format = (
            stored.startswith("hmac-sha256:")
            and len(stored_digest) == 64
            and set(stored_digest) <= _LOWER_HEX_CHARS
        )
        if not valid_format or not hmac.compare_digest(stored, expected):
            raise RuntimeError("configured audit key does not match database metadata")

    def _validated_session_audit_event_hash(
        self,
        event: Mapping[str, Any],
        *,
        expected_previous: str,
    ) -> str:
        previous_hash = event.get("previous_hash")
        event_hash = event.get("event_hash")
        if (
            not isinstance(previous_hash, str)
            or not isinstance(event_hash, str)
            or len(previous_hash) != 64
            or len(event_hash) != 64
            or not set(previous_hash) <= _LOWER_HEX_CHARS
            or not set(event_hash) <= _LOWER_HEX_CHARS
        ):
            raise RuntimeError("persisted session audit hash is invalid")
        if previous_hash != expected_previous:
            raise RuntimeError("persisted session audit chain is disconnected")
        payload = dict(event)
        payload.pop("event_hash", None)
        payload.pop("chain_valid", None)
        try:
            expected_hash = sign_session_audit_payload(self._audit_key, payload)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "persisted session audit payload cannot be authenticated"
            ) from exc
        if not hmac.compare_digest(event_hash, expected_hash):
            raise RuntimeError("persisted session audit signature is invalid")
        return event_hash

    def _audit_head_record(
        self,
        *,
        session_id: str,
        actor_ref: str,
        event_count: int,
        last_event_hash: str,
        updated_at: str,
    ) -> dict[str, Any]:
        if event_count < 1:
            raise RuntimeError("persisted session audit head count is invalid")
        if (
            len(last_event_hash) != 64
            or not set(last_event_hash) <= _LOWER_HEX_CHARS
        ):
            raise RuntimeError("persisted session audit head hash is invalid")
        return {
            "session_id": session_id,
            "actor_ref": actor_ref,
            "event_count": event_count,
            "last_event_hash": last_event_hash,
            "updated_at": updated_at,
            "head_hmac": session_audit_head_hmac(
                self._audit_key,
                session_id=session_id,
                actor_ref=actor_ref,
                event_count=event_count,
                last_event_hash=last_event_hash,
                updated_at=updated_at,
            ),
        }

    def _verify_audit_head_catalog(
        self,
        source: sqlite3.Connection,
        computed_heads: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        try:
            rows = source.execute(
                """
                SELECT session_id, actor_ref, event_count, last_event_hash,
                       updated_at, head_hmac
                FROM session_audit_heads ORDER BY session_id
                """
            ).fetchall()
            metadata = source.execute(
                """
                SELECT metadata_value FROM security_metadata
                WHERE metadata_key = ?
                """,
                (AUDIT_CATALOG_METADATA_KEY,),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise RuntimeError(
                "persisted session audit head catalog is unavailable"
            ) from exc

        stored_heads: list[dict[str, Any]] = []
        for row in rows:
            head = {
                "session_id": str(row["session_id"]),
                "actor_ref": str(row["actor_ref"]),
                "event_count": int(row["event_count"]),
                "last_event_hash": str(row["last_event_hash"]),
                "updated_at": str(row["updated_at"]),
                "head_hmac": str(row["head_hmac"]),
            }
            expected_head = self._audit_head_record(
                session_id=head["session_id"],
                actor_ref=head["actor_ref"],
                event_count=head["event_count"],
                last_event_hash=head["last_event_hash"],
                updated_at=head["updated_at"],
            )
            if not hmac.compare_digest(head["head_hmac"], expected_head["head_hmac"]):
                raise RuntimeError(
                    "persisted session audit head authentication is invalid"
                )
            stored_heads.append(head)

        stored_by_session = {
            str(head["session_id"]): head for head in stored_heads
        }
        if computed_heads is not None:
            if set(stored_by_session) != set(computed_heads):
                raise RuntimeError("persisted session audit head set is invalid")
            for session_id, computed in computed_heads.items():
                stored = stored_by_session[session_id]
                for field in (
                    "actor_ref",
                    "event_count",
                    "last_event_hash",
                    "updated_at",
                    "head_hmac",
                ):
                    if stored[field] != computed[field]:
                        raise RuntimeError(
                            "persisted session audit head does not match event history"
                        )

        stored_catalog = str(metadata["metadata_value"]) if metadata is not None else ""
        observed_digest = stored_catalog.removeprefix("hmac-sha256:")
        valid_format = (
            stored_catalog.startswith("hmac-sha256:")
            and len(observed_digest) == 64
            and set(observed_digest) <= _LOWER_HEX_CHARS
        )
        expected_catalog = session_audit_catalog_hmac(
            self._audit_key,
            stored_heads,
        )
        if not valid_format or not hmac.compare_digest(
            observed_digest,
            expected_catalog,
        ):
            raise RuntimeError(
                "persisted session audit catalog authentication is invalid"
            )
        return stored_by_session

    def _refresh_audit_catalog(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT session_id, actor_ref, event_count, last_event_hash,
                   updated_at, head_hmac
            FROM session_audit_heads ORDER BY session_id
            """
        ).fetchall()
        heads = [dict(row) for row in rows]
        catalog = "hmac-sha256:" + session_audit_catalog_hmac(
            self._audit_key,
            heads,
        )
        cursor = connection.execute(
            """
            UPDATE security_metadata
            SET metadata_value = ?, updated_at = ?
            WHERE metadata_key = ?
            """,
            (catalog, iso_utc(), AUDIT_CATALOG_METADATA_KEY),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("persisted session audit catalog metadata is missing")

    def _verify_all_session_audit_chains(
        self,
        *,
        connection: sqlite3.Connection | None = None,
        require_row_hmac: bool | None = None,
        require_head_catalog: bool | None = None,
    ) -> None:
        """Verify every persisted chain from the fixed genesis hash."""

        source = connection or self.connection
        if require_row_hmac is None:
            require_row_hmac = self.schema_version >= 5
        if require_head_catalog is None:
            require_head_catalog = self.schema_version >= 6
        columns = {
            str(row["name"])
            for row in source.execute("PRAGMA table_info(session_audit_events)")
        }
        has_row_hmac = "row_hmac" in columns
        if require_row_hmac and not has_row_hmac:
            raise RuntimeError("persisted session audit row authentication is missing")
        row_hmac_projection = "row_hmac" if has_row_hmac else "'' AS row_hmac"
        try:
            rows = source.execute(
                f"""
                SELECT session_id, sequence, actor_ref, occurred_at, event_json
                       , {row_hmac_projection}
                FROM session_audit_events
                ORDER BY session_id, sequence
                """
            )
            current_session: str | None = None
            current_owner: str | None = None
            expected_sequence = 1
            expected_previous = AUDIT_GENESIS_HASH
            computed_heads: dict[str, dict[str, Any]] = {}
            for row in rows:
                session_id = str(row["session_id"])
                if session_id != current_session:
                    current_session = session_id
                    current_owner = str(row["actor_ref"])
                    expected_sequence = 1
                    expected_previous = AUDIT_GENESIS_HASH
                sequence = int(row["sequence"])
                if sequence != expected_sequence or str(row["actor_ref"]) != current_owner:
                    raise RuntimeError(
                        "persisted session audit sequence or owner is invalid"
                    )
                try:
                    event = json.loads(str(row["event_json"]))
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        "persisted session audit event is not valid JSON"
                    ) from exc
                if not isinstance(event, dict):
                    raise RuntimeError(
                        "persisted session audit event is not a JSON object"
                    )
                event_hash = self._validated_session_audit_event_hash(
                    event,
                    expected_previous=expected_previous,
                )
                if str(row["occurred_at"]) != event.get("occurred_at"):
                    raise RuntimeError(
                        "persisted session audit row time does not match its signed event"
                    )
                if require_row_hmac:
                    expected_row_hmac = session_audit_row_hmac(
                        self._audit_key,
                        session_id=session_id,
                        sequence=sequence,
                        actor_ref=str(row["actor_ref"]),
                        occurred_at=str(row["occurred_at"]),
                        event_hash=event_hash,
                    )
                    observed_row_hmac = str(row["row_hmac"])
                    if not hmac.compare_digest(observed_row_hmac, expected_row_hmac):
                        raise RuntimeError(
                            "persisted session audit row authentication is invalid; "
                            "audit head set is invalid"
                        )
                computed_heads[session_id] = self._audit_head_record(
                    session_id=session_id,
                    actor_ref=str(row["actor_ref"]),
                    event_count=sequence,
                    last_event_hash=event_hash,
                    updated_at=str(row["occurred_at"]),
                )
                expected_previous = event_hash
                expected_sequence += 1
            if require_head_catalog:
                self._verify_audit_head_catalog(source, computed_heads)
        except sqlite3.DatabaseError as exc:
            raise RuntimeError("persisted session audit is unavailable") from exc

    def _verify_session_audit_chain(
        self,
        connection: sqlite3.Connection,
        session_id: str,
    ) -> None:
        """Verify the global head catalog and one complete active session chain."""

        stored_heads = self._verify_audit_head_catalog(connection)
        rows = connection.execute(
            """
            SELECT session_id, sequence, actor_ref, occurred_at, event_json, row_hmac
            FROM session_audit_events
            WHERE session_id = ?
            ORDER BY sequence
            """,
            (session_id,),
        ).fetchall()
        events = self._persisted_audit_events_from_rows(rows)
        stored_head = stored_heads.get(session_id)
        if not events:
            if stored_head is not None:
                raise RuntimeError("persisted session audit head set is invalid")
            return
        last = events[-1]
        last_event_hash = last.event.get("event_hash")
        if not isinstance(last_event_hash, str):
            raise RuntimeError("persisted session audit hash is invalid")
        computed_head = self._audit_head_record(
            session_id=session_id,
            actor_ref=last.actor_ref,
            event_count=last.sequence,
            last_event_hash=last_event_hash,
            updated_at=last.occurred_at,
        )
        if stored_head is None:
            raise RuntimeError("persisted session audit head set is invalid")
        for field in (
            "actor_ref",
            "event_count",
            "last_event_hash",
            "updated_at",
            "head_hmac",
        ):
            if stored_head[field] != computed_head[field]:
                raise RuntimeError(
                    "persisted session audit head does not match event history"
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
        token_hash = stable_hash(token)
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM confirmation_tokens WHERE token_hash = ?",
                (token_hash,),
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
            cursor = connection.execute(
                """
                UPDATE confirmation_tokens SET used_at = ?
                WHERE token_hash = ? AND used_at IS NULL
                """,
                (iso_utc(), token_hash),
            )
            if cursor.rowcount != 1:
                raise PermissionDenied(
                    "confirmation token was already consumed; request a fresh preview"
                )

    def invalidate_confirmation(self, context: UserContext, token: str) -> bool:
        """Invalidate one unused actor-owned token without revealing token existence."""

        token_hash = stable_hash(token)
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE confirmation_tokens SET used_at = ?
                WHERE token_hash = ? AND actor_ref = ? AND used_at IS NULL
                """,
                (iso_utc(), token_hash, actor_reference(context.user_id)),
            )
            return cursor.rowcount == 1

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

    def _journey_snapshot_from_row(
        self,
        row: sqlite3.Row,
    ) -> JourneyStateSnapshot:
        session_id = str(row["session_id"])
        actor_ref = str(row["actor_ref"])
        version = int(row["version"])
        state_json = str(row["state_json"])
        updated_at = str(row["updated_at"])
        observed_hmac = str(row["state_hmac"])
        expected_hmac = journey_state_hmac(
            self._audit_key,
            session_id=session_id,
            actor_ref=actor_ref,
            version=version,
            state_json=state_json,
            updated_at=updated_at,
        )
        if (
            len(observed_hmac) != 64
            or not set(observed_hmac) <= _LOWER_HEX_CHARS
            or not hmac.compare_digest(observed_hmac, expected_hmac)
        ):
            raise RuntimeError("persisted journey state authentication is invalid")
        try:
            state = json.loads(state_json)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "persisted journey state is not valid JSON"
            ) from exc
        if not isinstance(state, dict):
            raise RuntimeError("persisted journey state is not a JSON object")
        return JourneyStateSnapshot(
            session_id=session_id,
            actor_ref=actor_ref,
            version=version,
            payload=state,
            updated_at=updated_at,
        )

    def load_journey_snapshot(
        self,
        session_id: str,
        owner_ref: str,
    ) -> JourneyStateSnapshot | None:
        """Load an identity-bound structured journey snapshot, if one exists."""

        session_id = _validated_session_id(session_id)
        owner_ref = _validated_owner_ref(owner_ref)
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM journey_state WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        if row["actor_ref"] != owner_ref:
            raise PermissionDenied("journey state belongs to a different identity")
        return self._journey_snapshot_from_row(row)

    def _verify_all_journey_snapshots(
        self,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        source = connection or self.connection
        try:
            rows = source.execute(
                "SELECT * FROM journey_state ORDER BY session_id"
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise RuntimeError("persisted journey state is unavailable") from exc
        for row in rows:
            self._journey_snapshot_from_row(row)

    def save_journey_snapshot(
        self,
        session_id: str,
        owner_ref: str,
        payload: Mapping[str, Any],
        *,
        expected_version: int | None = None,
    ) -> JourneyStateSnapshot:
        """Upsert a snapshot with optional optimistic version enforcement."""

        session_id = _validated_session_id(session_id)
        owner_ref = _validated_owner_ref(owner_ref)
        encoded = _encode_json_object(payload, label="journey snapshot")
        if expected_version is not None and expected_version < 0:
            raise ValidationError("expected_version cannot be negative")
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM journey_state WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            audit_owner = connection.execute(
                """
                SELECT actor_ref FROM session_audit_events
                WHERE session_id = ? ORDER BY sequence LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            if row is not None and row["actor_ref"] != owner_ref:
                raise PermissionDenied("journey state belongs to a different identity")
            if row is not None:
                self._journey_snapshot_from_row(row)
            if audit_owner is not None and audit_owner["actor_ref"] != owner_ref:
                raise PermissionDenied("session audit belongs to a different identity")
            current_version = int(row["version"]) if row is not None else 0
            if expected_version is not None and expected_version != current_version:
                raise ConflictError(
                    "journey state version changed; reload before saving"
                )
            next_version = current_version + 1
            updated_at = iso_utc()
            state_hmac = journey_state_hmac(
                self._audit_key,
                session_id=session_id,
                actor_ref=owner_ref,
                version=next_version,
                state_json=encoded,
                updated_at=updated_at,
            )
            connection.execute(
                """
                INSERT INTO journey_state(
                    session_id, actor_ref, version, state_json, updated_at, state_hmac
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    version = excluded.version,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at,
                    state_hmac = excluded.state_hmac
                """,
                (
                    session_id,
                    owner_ref,
                    next_version,
                    encoded,
                    updated_at,
                    state_hmac,
                ),
            )
        return JourneyStateSnapshot(
            session_id=session_id,
            actor_ref=owner_ref,
            version=next_version,
            payload=dict(payload),
            updated_at=updated_at,
        )

    def append_session_audit_event(
        self,
        session_id: str,
        context: UserContext,
        event: Mapping[str, Any],
        *,
        session_owner_ref: str | None = None,
    ) -> PersistedSessionAuditEvent:
        """Append one ordered event after validating its HMAC chain link."""

        session_id = _validated_session_id(session_id)
        encoded = _encode_json_object(event, label="session audit event")
        requester_ref = actor_reference(context.user_id)
        owner_ref = _validated_owner_ref(session_owner_ref or requester_ref)
        occurred_at = event.get("occurred_at")
        if not isinstance(occurred_at, str) or not occurred_at:
            raise ValidationError("session audit event must contain occurred_at")
        with self.transaction() as connection:
            # Validate the authenticated global head set and this session's full
            # chain. Startup/readiness retain the more expensive all-session scan.
            self._verify_session_audit_chain(connection, session_id)
            state_owner = connection.execute(
                "SELECT actor_ref FROM journey_state WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            existing = connection.execute(
                """
                SELECT MIN(sequence) AS first_sequence,
                       MAX(sequence) AS last_sequence,
                       COUNT(*) AS event_count,
                       MIN(actor_ref) AS minimum_actor_ref,
                       MAX(actor_ref) AS maximum_actor_ref
                FROM session_audit_events WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            event_count = int(existing["event_count"] if existing is not None else 0)
            if event_count > 0 and (
                int(existing["first_sequence"]) != 1
                or int(existing["last_sequence"]) != event_count
                or existing["minimum_actor_ref"] != existing["maximum_actor_ref"]
            ):
                raise RuntimeError(
                    "persisted session audit sequence or owner is invalid"
                )
            existing_owner_ref = (
                str(existing["minimum_actor_ref"]) if event_count > 0 else None
            )
            expected_previous = AUDIT_GENESIS_HASH
            if event_count > 0:
                previous_row = connection.execute(
                    """
                    SELECT event_json FROM session_audit_events
                    WHERE session_id = ? AND sequence = ?
                    """,
                    (session_id, event_count),
                ).fetchone()
                try:
                    previous_event = json.loads(str(previous_row["event_json"]))
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        "persisted session audit event is not valid JSON"
                    ) from exc
                if not isinstance(previous_event, dict) or not isinstance(
                    previous_event.get("event_hash"), str
                ):
                    raise RuntimeError("persisted session audit hash is invalid")
                expected_previous = str(previous_event["event_hash"])
            event_hash = self._validated_session_audit_event_hash(
                event,
                expected_previous=expected_previous,
            )
            if state_owner is not None and state_owner["actor_ref"] != owner_ref:
                raise PermissionDenied("journey state belongs to a different identity")
            if existing_owner_ref is not None and existing_owner_ref != owner_ref:
                raise PermissionDenied("session audit belongs to a different identity")
            if (
                owner_ref != requester_ref
                and state_owner is None
                and existing_owner_ref is None
            ):
                raise PermissionDenied(
                    "cannot create a session audit for a different identity"
                )
            sequence = event_count + 1
            row_hmac = session_audit_row_hmac(
                self._audit_key,
                session_id=session_id,
                sequence=sequence,
                actor_ref=owner_ref,
                occurred_at=occurred_at,
                event_hash=event_hash,
            )
            connection.execute(
                """
                INSERT INTO session_audit_events(
                    session_id, sequence, actor_ref, occurred_at, event_json, row_hmac
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    sequence,
                    owner_ref,
                    occurred_at,
                    encoded,
                    row_hmac,
                ),
            )
            head = self._audit_head_record(
                session_id=session_id,
                actor_ref=owner_ref,
                event_count=sequence,
                last_event_hash=event_hash,
                updated_at=occurred_at,
            )
            connection.execute(
                """
                INSERT INTO session_audit_heads(
                    session_id, actor_ref, event_count, last_event_hash,
                    updated_at, head_hmac
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    actor_ref = excluded.actor_ref,
                    event_count = excluded.event_count,
                    last_event_hash = excluded.last_event_hash,
                    updated_at = excluded.updated_at,
                    head_hmac = excluded.head_hmac
                """,
                (
                    head["session_id"],
                    head["actor_ref"],
                    head["event_count"],
                    head["last_event_hash"],
                    head["updated_at"],
                    head["head_hmac"],
                ),
            )
            self._refresh_audit_catalog(connection)
        return PersistedSessionAuditEvent(
            session_id=session_id,
            sequence=sequence,
            actor_ref=owner_ref,
            occurred_at=occurred_at,
            event=dict(event),
        )

    def _persisted_audit_events_from_rows(
        self,
        rows: list[sqlite3.Row],
    ) -> tuple[PersistedSessionAuditEvent, ...]:
        events: list[PersistedSessionAuditEvent] = []
        current_session: str | None = None
        current_owner: str | None = None
        expected_sequence = 1
        expected_previous = AUDIT_GENESIS_HASH
        for row in rows:
            session_id = str(row["session_id"])
            if session_id != current_session:
                current_session = session_id
                current_owner = str(row["actor_ref"])
                expected_sequence = 1
                expected_previous = AUDIT_GENESIS_HASH
            if (
                int(row["sequence"]) != expected_sequence
                or str(row["actor_ref"]) != current_owner
            ):
                raise RuntimeError(
                    "persisted session audit sequence or owner is invalid"
                )
            try:
                payload = json.loads(str(row["event_json"]))
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    "persisted session audit event is not valid JSON"
                ) from exc
            if not isinstance(payload, dict):
                raise RuntimeError("persisted session audit event is not a JSON object")
            event_hash = self._validated_session_audit_event_hash(
                payload,
                expected_previous=expected_previous,
            )
            if str(row["occurred_at"]) != payload.get("occurred_at"):
                raise RuntimeError(
                    "persisted session audit row time does not match its signed event"
                )
            expected_row_hmac = session_audit_row_hmac(
                self._audit_key,
                session_id=session_id,
                sequence=int(row["sequence"]),
                actor_ref=str(row["actor_ref"]),
                occurred_at=str(row["occurred_at"]),
                event_hash=event_hash,
            )
            if not hmac.compare_digest(str(row["row_hmac"]), expected_row_hmac):
                raise RuntimeError(
                    "persisted session audit row authentication is invalid"
                )
            events.append(
                PersistedSessionAuditEvent(
                    session_id=session_id,
                    sequence=int(row["sequence"]),
                    actor_ref=str(row["actor_ref"]),
                    occurred_at=str(row["occurred_at"]),
                    event=payload,
                )
            )
            expected_previous = event_hash
            expected_sequence += 1
        return tuple(events)

    def _load_all_session_audit_events(
        self,
    ) -> tuple[PersistedSessionAuditEvent, ...]:
        """Internal startup read of every event; no public authorization boundary."""

        with self.transaction() as connection:
            self._verify_all_session_audit_chains(connection=connection)
            rows = connection.execute(
                """
                SELECT session_id, sequence, actor_ref, occurred_at, event_json, row_hmac
                FROM session_audit_events
                ORDER BY session_id, sequence
                """
            ).fetchall()
        return self._persisted_audit_events_from_rows(rows)

    def _load_full_session_audit_events(
        self,
        session_id: str,
        context: UserContext,
    ) -> tuple[PersistedSessionAuditEvent, ...]:
        """Internal authorized read of one complete chain from sequence one."""

        session_id = _validated_session_id(session_id)
        with self.transaction() as connection:
            self._verify_session_audit_chain(connection, session_id)
            rows = connection.execute(
                """
                SELECT session_id, sequence, actor_ref, occurred_at, event_json, row_hmac
                FROM session_audit_events
                WHERE session_id = ?
                ORDER BY sequence
                """,
                (session_id,),
            ).fetchall()
        events = self._persisted_audit_events_from_rows(rows)
        if not events:
            return ()
        if (
            events[0].actor_ref != actor_reference(context.user_id)
            and not context.is_staff
        ):
            raise PermissionDenied("session audit belongs to a different identity")
        return events

    def list_session_audit_events(
        self,
        session_id: str,
        context: UserContext,
        *,
        limit: int = 500,
    ) -> tuple[PersistedSessionAuditEvent, ...]:
        """Return the recent API-compatible window in ascending order."""

        bounded_limit = max(1, min(int(limit), 2_000))
        events = self._load_full_session_audit_events(session_id, context)
        return events[-bounded_limit:]

    def assert_session_audit_integrity(self) -> None:
        """Fail closed on persisted audit or Journey-state tampering."""

        with self.transaction() as connection:
            self._verify_all_session_audit_chains(connection=connection)
            self._verify_all_journey_snapshots(connection=connection)

    def session_audit_integrity_report(self) -> dict[str, Any]:
        """Verify all authenticated history and return only bounded aggregate proof."""

        with self.transaction() as connection:
            self._verify_all_session_audit_chains(connection=connection)
            self._verify_all_journey_snapshots(connection=connection)
            event_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM session_audit_events"
                ).fetchone()[0]
            )
            session_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM session_audit_heads"
                ).fetchone()[0]
            )
        return {
            "ok": True,
            "schema_version": self.schema_version,
            "event_count": event_count,
            "session_count": session_count,
            "event_hmac": True,
            "row_hmac": True,
            "head_catalog_hmac": True,
            "journey_state_hmac": True,
        }

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
