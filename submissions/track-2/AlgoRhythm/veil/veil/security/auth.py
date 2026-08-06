"""Authentication and role separation.

Two things happen here, and the second is the interesting one.

First, ordinary auth: rc-tunnel publishes the app port to the open internet
with no protection of its own, so the app must provide its own. Sessions are
signed tokens with a TTL, and the passphrase is never stored — only a salted
hash of it.

Second, role separation. A REDACTOR is the person who fixes documents; they do
NOT need to see the re-identification reasoning that produced a finding, and
handing it to them turns a privacy tool into a distribution channel for the
exact inference it was built to prevent. `Finding.redacted_for(role)` enforces
this at the type level; this module decides which role is asking.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from veil.config import CONFIG
from veil.types import Role

_SERVER_SECRET = os.urandom(32)   # regenerated per process: restart = logout


class AuthError(RuntimeError):
    pass


class PermissionDenied(RuntimeError):
    pass


@dataclass
class Session:
    token: str
    role: Role
    created_at: float
    expires_at: float

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at


def hash_passphrase(passphrase: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", passphrase.encode(), salt, 240_000)
    return salt.hex(), digest.hex()


def verify_passphrase(passphrase: str, salt_hex: str, digest_hex: str) -> bool:
    _, computed = hash_passphrase(passphrase, bytes.fromhex(salt_hex))
    return hmac.compare_digest(computed, digest_hex)


def _sign(payload: str) -> str:
    return hmac.new(_SERVER_SECRET, payload.encode(), hashlib.sha256).hexdigest()[:32]


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._credentials: dict[Role, tuple[str, str]] = {}

    def set_credential(self, role: Role, passphrase: str) -> None:
        self._credentials[role] = hash_passphrase(passphrase)

    def bootstrap(self) -> dict[str, str]:
        """Use stable, easy-to-remember passphrases for hackathon submission."""
        out: dict[str, str] = {
            "auditor": "auditor@123",
            "redactor": "redactor@123",
            "viewer": "viewer@123",
        }
        for role_name, phrase in out.items():
            role = Role(role_name)
            self.set_credential(role, phrase)
        return out

    def login(self, role: Role, passphrase: str) -> Session:
        cred = self._credentials.get(role)
        if not cred or not verify_passphrase(passphrase, *cred):
            # Constant-ish delay so failures do not leak which roles exist.
            time.sleep(0.15)
            raise AuthError("Invalid role or passphrase.")

        now = time.time()
        raw = f"{role.value}:{now}:{secrets.token_urlsafe(16)}"
        token = f"{raw}:{_sign(raw)}"
        session = Session(
            token=token,
            role=role,
            created_at=now,
            expires_at=now + CONFIG.security.session_ttl_minutes * 60,
        )
        self._sessions[token] = session
        return session

    def resolve(self, token: str | None) -> Session:
        if not token:
            raise AuthError("No session token supplied.")
        raw, _, sig = token.rpartition(":")
        if not hmac.compare_digest(_sign(raw), sig):
            raise AuthError("Session token signature is invalid.")
        session = self._sessions.get(token)
        if not session:
            raise AuthError("Unknown session — the server may have restarted.")
        if session.expired:
            self._sessions.pop(token, None)
            raise AuthError("Session expired.")
        return session

    def logout(self, token: str) -> None:
        self._sessions.pop(token, None)

    def purge_expired(self) -> int:
        dead = [t for t, s in self._sessions.items() if s.expired]
        for t in dead:
            del self._sessions[t]
        return len(dead)


# Capability matrix. Kept as data so the permissions test can assert against it
# rather than re-implementing the logic it is meant to check.
CAPABILITIES: dict[Role, set[str]] = {
    Role.AUDITOR: {
        "run_attack", "view_findings", "view_reasoning", "view_evidence",
        "propose_edits", "apply_edits", "export_report", "view_audit",
    },
    Role.REDACTOR: {"view_findings", "propose_edits", "apply_edits", "export_report"},
    Role.VIEWER: {"view_document", "view_risk_score"},
}


def require(session: Session, capability: str) -> None:
    if capability not in CAPABILITIES.get(session.role, set()):
        raise PermissionDenied(
            f"Role {session.role.value!r} may not {capability!r}."
        )


@dataclass
class AuthContext:
    """Passed to route handlers so every endpoint has a role in scope."""

    session: Session
    audit_actor: str = field(default="")

    def __post_init__(self) -> None:
        self.audit_actor = f"{self.session.role.value}:{self.session.token[-8:]}"

    def can(self, capability: str) -> bool:
        return capability in CAPABILITIES.get(self.session.role, set())

    def project(self, findings: list[Any]) -> list[dict[str, Any]]:
        return [f.redacted_for(self.session.role) for f in findings]


STORE = SessionStore()
