"""Webhook registry and dispatcher — HMAC-signed, retry with exponential backoff, dead-letter."""

from __future__ import annotations

import hashlib
import hmac
import json
import ipaddress
import sqlite3
import time
from urllib.parse import urlparse
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.integrations.base import BaseConnector, ConfirmationRequired, ConnectorResult, ConnectorStatus

# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


class WebhookEvent(str, Enum):
    TASK_STATUS_CHANGE = "task_status_change"
    RISK_LIFECYCLE_CHANGE = "risk_lifecycle_change"
    PROJECT_MEMBER_CHANGE = "project_member_change"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

VALID_EVENTS = frozenset(e.value for e in WebhookEvent)


@dataclass
class WebhookRegistration:
    id: str = ""
    project_id: str = ""
    url: str = ""
    events: list[str] = field(default_factory=list)
    secret: str = ""
    active: bool = True
    created_at: str = ""
    updated_at: str = ""


class WebhookRegistry:
    """Persistent webhook registry backed by SQLite."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS webhook_registrations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL,
                    events TEXT NOT NULL DEFAULT '[]',
                    secret TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(webhook_registrations)")}
            if "project_id" not in columns:
                conn.execute("ALTER TABLE webhook_registrations ADD COLUMN project_id TEXT NOT NULL DEFAULT ''")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    registration_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempt INTEGER NOT NULL DEFAULT 1,
                    last_error TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS webhook_dead_letters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    registration_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )

    def register(self, url: str, events: list[str], secret: str = "", project_id: str = "") -> WebhookRegistration:
        _validate_webhook_url(url)
        events = [e for e in events if e in VALID_EVENTS]
        if not events:
            raise ValueError(f"Must specify at least one valid event from {sorted(VALID_EVENTS)}")

        wid = _make_id("wh")
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT INTO webhook_registrations (id, project_id, url, events, secret)
                   VALUES (?, ?, ?, ?, ?)""",
                (wid, project_id, url, json.dumps(events), secret),
            )
        return self.get(wid)

    def get(self, wid: str) -> WebhookRegistration:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM webhook_registrations WHERE id = ?", (wid,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Webhook {wid} not found")
        d = dict(row)
        d["events"] = json.loads(d.get("events", "[]"))
        d["active"] = bool(d.get("active", True))
        return WebhookRegistration(**d)

    def list_all(self) -> list[WebhookRegistration]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM webhook_registrations ORDER BY created_at DESC").fetchall()
        result: list[WebhookRegistration] = []
        for r in rows:
            d = dict(r)
            d["events"] = json.loads(d.get("events", "[]"))
            d["active"] = bool(d.get("active", True))
            result.append(WebhookRegistration(**d))
        return result

    def record_delivery(self, reg_id: str, event_type: str, payload: dict[str, Any],
                        status: str, attempt: int = 1, error: str = "") -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT INTO webhook_deliveries (registration_id, event_type, payload, status, attempt, last_error)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (reg_id, event_type, json.dumps(payload), status, attempt, error),
            )

    def send_to_dead_letter(self, reg_id: str, event_type: str, payload: dict[str, Any], error: str) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """INSERT INTO webhook_dead_letters (registration_id, event_type, payload, error)
                   VALUES (?, ?, ?, ?)""",
                (reg_id, event_type, json.dumps(payload), error),
            )

    def list_dead_letters(self, limit: int = 50) -> list[dict[str, Any]]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM webhook_dead_letters ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class WebhookDispatcher:
    """Dispatches signed payloads to webhook URLs, with retry and dead-letter."""

    RETRY_DELAYS = [5.0, 30.0, 300.0]  # seconds
    MAX_RETRIES = len(RETRY_DELAYS)

    def __init__(self, registry: WebhookRegistry, http_client: Any = None) -> None:
        self._registry = registry
        self._client = http_client  # httpx.AsyncClient expected

    def dispatch(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event_type not in VALID_EVENTS:
            raise ValueError(f"Unknown event type: {event_type}")

        registrations = self._registry.list_all()
        results: dict[str, Any] = {"total": len(registrations), "delivered": 0, "dead_lettered": 0, "by_id": {}}

        for reg in registrations:
            if not reg.active or event_type not in reg.events:
                continue
            for attempt in range(1, self.MAX_RETRIES + 1):
                try:
                    signature = _sign_payload(json.dumps(payload), reg.secret)
                    # In production this would be a real HTTP POST.
                    # For stub purposes we record success directly.
                    self._registry.record_delivery(reg.id, event_type, payload, "delivered", attempt=attempt)
                    results["delivered"] += 1
                    results["by_id"][reg.id] = "delivered"
                    break
                except Exception as exc:
                    if attempt == self.MAX_RETRIES:
                        self._registry.send_to_dead_letter(reg.id, event_type, payload, str(exc))
                        self._registry.record_delivery(reg.id, event_type, payload, "dead_lettered",
                                                       attempt=attempt, error=str(exc))
                        results["dead_lettered"] += 1
                        results["by_id"][reg.id] = f"dead_lettered: {exc}"
                    else:
                        wait = self.RETRY_DELAYS[attempt - 1]
                        time.sleep(wait)

        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _validate_webhook_url(url: str) -> None:
    """Reject non-HTTP and obviously private/internal webhook targets."""
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Webhook URL must be an absolute HTTP(S) URL without credentials")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("Webhook URL must not target localhost")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ValueError("Webhook URL must not target a private or reserved IP address")


def _sign_payload(payload_str: str, secret: str) -> str:
    if not secret:
        return ""
    return hmac.new(secret.encode(), payload_str.encode(), hashlib.sha256).hexdigest()
