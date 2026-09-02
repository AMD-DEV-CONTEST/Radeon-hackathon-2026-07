"""Email connector — SMTP-backed, rate-limited, template-based."""

from __future__ import annotations

import json
import smtplib
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from app.integrations.base import BaseConnector, ConfirmationRequired, ConnectorResult, ConnectorStatus

# ---------------------------------------------------------------------------
# Rate limiter — sliding-window, in-memory
# ---------------------------------------------------------------------------


class RateLimiter:
    """Simple sliding-window rate limiter per key (e.g. recipient domain)."""

    def __init__(self, max_calls: int = 10, window_seconds: float = 3600.0) -> None:
        self._max: int = max_calls
        self._window: float = window_seconds
        self._buckets: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            bucket = self._buckets.get(key, [])
            bucket = [t for t in bucket if now - t < self._window]
            if len(bucket) >= self._max:
                self._buckets[key] = bucket
                return False
            bucket.append(now)
            self._buckets[key] = bucket
            return True

    def can_allow(self, key: str) -> bool:
        """Check a limit during preview without consuming a send allowance."""
        now = time.time()
        with self._lock:
            bucket = [t for t in self._buckets.get(key, []) if now - t < self._window]
            self._buckets[key] = bucket
            return len(bucket) < self._max

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

REPORT_TEMPLATES: dict[str, str] = {
    "task_report": """<h2>Task Report</h2>
    <p>Project: {project_name}</p>
    <p>Task: {task_name}</p>
    <p>Status: {status}</p>
    <p>Summary: {summary}</p>""",
    "risk_alert": """<h2>Risk Alert</h2>
    <p>Project: {project_name}</p>
    <p>Risk Level: {risk_level}</p>
    <p>Description: {description}</p>""",
    "project_summary": """<h2>Project Summary</h2>
    <p>Project: {project_name}</p>
    <p>Completed Tasks: {completed_tasks}</p>
    <p>Open Risks: {open_risks}</p>
    <p>Overall Status: {overall_status}</p>""",
}


# ---------------------------------------------------------------------------
# Connector
# ---------------------------------------------------------------------------


@dataclass
class EmailPayload:
    recipient: str = ""
    subject: str = ""
    body_html: str = ""
    body_plain: str = ""
    sender: str = "noreply@office-agent.local"


class EmailConnector(BaseConnector):
    """Sends templated emails via SMTP, with rate-limiting and audit."""

    _db_path: str = ":memory:"
    _rate_limiter: RateLimiter
    _smtp_host: str = "localhost"
    _smtp_port: int = 1025

    def __init__(
        self,
        db_path: str = ":memory:",
        smtp_host: str = "localhost",
        smtp_port: int = 1025,
        rate_max: int = 10,
    ) -> None:
        super().__init__("email")
        self._db_path = db_path
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._rate_limiter = RateLimiter(max_calls=rate_max)
        self._init_db()

    # ------------------------------------------------------------------
    # DB
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS email_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recipient TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body_preview TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'sent',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS email_confirmations (
                    id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    confirmed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def read(self, **kwargs: Any) -> dict[str, Any]:
        self._set_status(ConnectorStatus.READING)
        audit = self.audit()
        return {"recent_sends": len(audit), "last_entries": audit[:10]}

    def preview_diff(self, data: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        report_type: str = data.get("type", "task_report")
        recipient: str = data.get("recipient", "")
        subject: str = data.get("subject", "Office Agent Report")

        if not recipient:
            raise ValueError("recipient is required for email")

        domain = recipient.split("@")[-1] if "@" in recipient else recipient
        if not self._rate_limiter.can_allow(domain):
            raise ConfirmationRequired(
                f"Rate limit reached for domain {domain}. Max {self._rate_limiter._max} emails/hour.",
                details={"domain": domain, "retry_after_seconds": 3600},
            )

        template = REPORT_TEMPLATES.get(report_type, REPORT_TEMPLATES["task_report"])
        body_html = template.format_map({k: str(v) for k, v in data.items()})

        diff = {
            "type": report_type,
            "recipient": recipient,
            "subject": subject,
            "body_preview": body_html[:200],
            "sender": data.get("sender", "noreply@office-agent.local"),
        }
        confirmation_id = f"email_confirm_{uuid.uuid4().hex}"
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO email_confirmations (id, payload_json) VALUES (?, ?)",
                (confirmation_id, json.dumps(data)),
            )
        diff["confirmation_id"] = confirmation_id
        self._set_status(ConnectorStatus.PREVIEW_READY)
        return diff

    def execute(self, data: dict[str, Any], confirmation_id: str, **kwargs: Any) -> ConnectorResult:
        self._set_status(ConnectorStatus.EXECUTING)

        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            confirmation = conn.execute(
                "SELECT payload_json FROM email_confirmations WHERE id = ? AND confirmed = 0",
                (confirmation_id,),
            ).fetchone()
            if confirmation is None:
                self._set_status(ConnectorStatus.FAILED)
                return ConnectorResult(ConnectorStatus.FAILED, "Invalid or already-used confirmation_id")
            confirmed_data = json.loads(confirmation["payload_json"])
            if confirmed_data != data:
                self._set_status(ConnectorStatus.FAILED)
                return ConnectorResult(ConnectorStatus.FAILED, "Confirmation does not match the previewed email")
            conn.execute("UPDATE email_confirmations SET confirmed = 1 WHERE id = ?", (confirmation_id,))

        recipient = data.get("recipient", "")
        subject = data.get("subject", "Office Agent Report")
        report_type = data.get("type", "task_report")
        sender = data.get("sender", "noreply@office-agent.local")
        template = REPORT_TEMPLATES.get(report_type, REPORT_TEMPLATES["task_report"])
        body_html = template.format_map({k: str(v) for k, v in data.items()})
        body_plain = data.get("body_plain", "")
        domain = recipient.split("@")[-1] if "@" in recipient else recipient
        if not self._rate_limiter.allow(domain):
            self._set_status(ConnectorStatus.FAILED)
            return ConnectorResult(ConnectorStatus.FAILED, f"Rate limit reached for domain {domain}")

        try:
            self._send_email(sender, recipient, subject, body_html, body_plain)
            self._record_audit(recipient, subject, body_html, "sent")
            self._set_status(ConnectorStatus.EXECUTED)
            return ConnectorResult(
                status=ConnectorStatus.EXECUTED,
                summary=f"Email sent to {recipient}",
                details={"recipient": recipient, "subject": subject},
            )
        except Exception as exc:
            self._record_audit(recipient, subject, body_html, f"failed: {exc}")
            self._set_status(ConnectorStatus.FAILED)
            return ConnectorResult(
                status=ConnectorStatus.FAILED,
                summary=f"Email failed: {exc}",
                details={"recipient": recipient, "error": str(exc)},
            )

    def rollback(self, execution_context: dict[str, Any], **kwargs: Any) -> ConnectorResult:
        # Email is not reversible, rollback means marking as retracted in logs
        self._set_status(ConnectorStatus.ROLLED_BACK)
        return ConnectorResult(
            status=ConnectorStatus.ROLLED_BACK,
            summary="Email delivery cannot be undone. Logged retraction.",
            details=execution_context,
        )

    def audit(self, limit: int = 50) -> list[dict[str, Any]]:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM email_audit ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send_email(self, sender: str, recipient: str, subject: str, html: str, plain: str = "") -> None:
        msg = MIMEMultipart("alternative")
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = subject
        if plain:
            msg.attach(MIMEText(plain, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=10) as server:
            server.sendmail(sender, [recipient], msg.as_string())

    def _record_audit(self, recipient: str, subject: str, body: str, status: str) -> None:
        preview = body[:200] if body else ""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO email_audit (recipient, subject, body_preview, status) VALUES (?, ?, ?, ?)",
                (recipient, subject, preview, status),
            )
