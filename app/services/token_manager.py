"""Token manager — server-side encrypted storage. Never exposes tokens in logs.

Uses AES-256-GCM via cryptography. Tokens are scoped to service + project.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
import uuid
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class TokenManager:
    """Secure token storage with encryption at rest."""

    def __init__(self, db_path: str = ":memory:", secret: str | None = None) -> None:
        self._db_path = db_path
        # A randomly generated key would make persisted tokens unrecoverable
        # after a restart.  Deployment must provide a stable secret instead.
        key_material = secret or os.environ.get("PROJECTPACK_INTEGRATION_KEY")
        if not key_material:
            raise ValueError(
                "TokenManager requires PROJECTPACK_INTEGRATION_KEY or an explicit secret"
            )
        self._aesgcm = AESGCM(hashlib.sha256(key_material.encode("utf-8")).digest())
        self._init_db()

    # ------------------------------------------------------------------
    # DB
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS tokens (
                    id TEXT PRIMARY KEY,
                    service TEXT NOT NULL,
                    project_id TEXT NOT NULL DEFAULT '',
                    encrypted_value TEXT NOT NULL,
                    label TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(self, service: str, token_value: str,
              project_id: str = "", label: str = "") -> str:
        """Encrypt and store a token. Returns the token id."""
        token_id = _make_id("tok")
        nonce = os.urandom(12)
        ciphertext = self._aesgcm.encrypt(nonce, token_value.encode(), None)
        # store base64(nonce || ciphertext)
        blob = base64.b64encode(nonce + ciphertext).decode()
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO tokens (id, service, project_id, encrypted_value, label) VALUES (?, ?, ?, ?, ?)",
                (token_id, service, project_id, blob, label),
            )
        return token_id

    def retrieve(self, token_id: str) -> str | None:
        """Decrypt and return the stored token. Returns None if not found."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM tokens WHERE id = ?", (token_id,)).fetchone()
        if row is None:
            return None
        return self._decrypt(row["encrypted_value"])

    def list_tokens(self, service: str = "", project_id: str = "") -> list[dict[str, Any]]:
        """List token metadata — value is NEVER included."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            if service and project_id:
                rows = conn.execute(
                    "SELECT id, service, project_id, label, created_at, updated_at FROM tokens "
                    "WHERE service = ? AND project_id = ? ORDER BY created_at DESC",
                    (service, project_id),
                ).fetchall()
            elif service:
                rows = conn.execute(
                    "SELECT id, service, project_id, label, created_at, updated_at FROM tokens "
                    "WHERE service = ? ORDER BY created_at DESC",
                    (service,),
                ).fetchall()
            elif project_id:
                rows = conn.execute(
                    "SELECT id, service, project_id, label, created_at, updated_at FROM tokens "
                    "WHERE project_id = ? ORDER BY created_at DESC",
                    (project_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, service, project_id, label, created_at, updated_at FROM tokens "
                    "ORDER BY created_at DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, token_id: str) -> bool:
        """Delete a token. Returns True if deleted, False if not found."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("DELETE FROM tokens WHERE id = ?", (token_id,))
            return cursor.rowcount > 0

    def sanitize_for_log(self, value: str) -> str:
        """Redact token-like strings for safe logging."""
        if not value:
            return value
        return value[:4] + "****" + value[-4:] if len(value) > 8 else "****"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _decrypt(self, blob: str) -> str:
        raw = base64.b64decode(blob)
        nonce, ciphertext = raw[:12], raw[12:]
        return self._aesgcm.decrypt(nonce, ciphertext, None).decode()


def _make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"
