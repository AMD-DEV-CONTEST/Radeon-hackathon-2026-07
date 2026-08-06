from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Literal, cast

RoleName = Literal["guest", "staff", "admin"]
_BASE64URL_ALPHABET = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)

_DEMO_IDENTITIES: tuple[tuple[str, str, RoleName], ...] = (
    ("Alex (guest, owner)", "guest-alex", "guest"),
    ("Mallory (guest, non-owner)", "guest-mallory", "guest"),
    ("Sofia (hotel staff)", "staff-sofia", "staff"),
)


class IdentityError(ValueError):
    """Raised when a local identity token is malformed, expired, or forged."""


@dataclass(frozen=True, slots=True)
class IdentityClaims:
    user_id: str
    role: RoleName
    expires_at: int = 0


class LocalIdentityProvider:
    """Small HMAC identity boundary for the self-contained competition demo."""

    def __init__(self, secret: str) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("Identity secret must contain at least 32 bytes")
        self._secret = secret.encode("utf-8")

    def issue(
        self,
        *,
        user_id: str,
        role: RoleName,
        ttl_seconds: int = 8 * 60 * 60,
    ) -> str:
        user_id = user_id.strip()
        if not user_id or len(user_id) > 200:
            raise ValueError("user_id must contain 1 to 200 characters")
        if role not in {"guest", "staff", "admin"}:
            raise ValueError("Unsupported identity role")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        now = int(time.time())
        payload = {
            "sub": user_id,
            "role": role,
            "iat": now,
            "exp": now + ttl_seconds,
            "jti": secrets.token_urlsafe(12),
        }
        body = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = _b64encode(hmac.new(self._secret, body, hashlib.sha256).digest())
        return f"{body.decode('ascii')}.{signature.decode('ascii')}"

    def verify(self, token: str) -> IdentityClaims:
        try:
            body_text, signature_text = token.split(".", 1)
            body = body_text.encode("ascii")
            signature = _b64decode(signature_text)
        except (ValueError, UnicodeError) as exc:
            raise IdentityError("Malformed identity token") from exc

        expected = hmac.new(self._secret, body, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise IdentityError("Invalid identity token signature")
        try:
            payload = json.loads(_b64decode(body_text))
            user_id = str(payload["sub"]).strip()
            role = str(payload["role"])
            expires_at = int(payload["exp"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise IdentityError("Invalid identity token payload") from exc
        if role not in {"guest", "staff", "admin"}:
            raise IdentityError("Unsupported identity role")
        if not user_id or len(user_id) > 200:
            raise IdentityError("Invalid identity subject")
        if expires_at <= int(time.time()):
            raise IdentityError("Identity token expired")
        return IdentityClaims(
            user_id=user_id,
            role=cast(RoleName, role),
            expires_at=expires_at,
        )

    def demo_tokens(self, *, include_staff: bool = True) -> dict[str, str]:
        """Issue short-lived local identities; labels make the security demo explicit."""
        return {
            label: self.issue(user_id=user_id, role=role)
            for label, user_id, role in self._demo_identity_specs(
                include_staff=include_staff
            )
        }

    def issue_demo_token(
        self,
        label: str,
        *,
        include_staff: bool = True,
        ttl_seconds: int = 8 * 60 * 60,
        session_scope: str | None = None,
    ) -> str:
        """Issue a fresh token for an allow-listed demo identity."""
        identities = {
            identity_label: (user_id, role)
            for identity_label, user_id, role in self._demo_identity_specs(
                include_staff=include_staff
            )
        }
        try:
            user_id, role = identities[label]
        except KeyError as exc:
            raise IdentityError("Unknown demo identity") from exc
        if session_scope is not None:
            if not session_scope or len(session_scope) > 120:
                raise IdentityError("Invalid demo identity session scope")
            scope = hmac.new(
                self._secret,
                f"radeonstay-demo-session:{session_scope}".encode(),
                hashlib.sha256,
            ).hexdigest()[:20]
            user_id = f"{user_id}-{scope}"
        return self.issue(user_id=user_id, role=role, ttl_seconds=ttl_seconds)

    @staticmethod
    def _demo_identity_specs(
        *, include_staff: bool
    ) -> tuple[tuple[str, str, RoleName], ...]:
        if include_staff:
            return _DEMO_IDENTITIES
        return tuple(item for item in _DEMO_IDENTITIES if item[2] != "staff")


def _b64encode(value: bytes) -> bytes:
    return base64.urlsafe_b64encode(value).rstrip(b"=")


def _b64decode(value: str | bytes) -> bytes:
    raw = value.encode("ascii") if isinstance(value, str) else value
    if not raw or any(character not in _BASE64URL_ALPHABET for character in raw):
        raise ValueError("Invalid base64url segment")
    try:
        decoded = base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))
    except binascii.Error as exc:
        raise ValueError("Invalid base64url segment") from exc
    if not hmac.compare_digest(_b64encode(decoded), raw):
        raise ValueError("Non-canonical base64url segment")
    return decoded
