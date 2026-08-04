from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Literal, cast


RoleName = Literal["guest", "staff", "admin"]


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
        tokens = {
            "Alex (guest, owner)": self.issue(
                user_id="guest-alex",
                role="guest",
            ),
            "Mallory (guest, non-owner)": self.issue(
                user_id="guest-mallory",
                role="guest",
            ),
        }
        if include_staff:
            tokens["Sofia (hotel staff)"] = self.issue(
                user_id="staff-sofia",
                role="staff",
            )
        return tokens


def _b64encode(value: bytes) -> bytes:
    return base64.urlsafe_b64encode(value).rstrip(b"=")


def _b64decode(value: str | bytes) -> bytes:
    raw = value.encode("ascii") if isinstance(value, str) else value
    return base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))
