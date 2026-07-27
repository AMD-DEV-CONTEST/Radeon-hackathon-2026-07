"""Short-lived, stateless access sessions for the public web application."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass


class SessionTokenError(ValueError):
    """Raised when an access-session token cannot be trusted."""


@dataclass(frozen=True)
class SessionClaims:
    """Validated claims carried by a short-lived access token."""

    session_id: str
    token_id: str
    issued_at: int
    expires_at: int


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except ValueError as exc:
        raise SessionTokenError("Malformed access token") from exc


class SessionTokenManager:
    """Issue and verify compact HMAC tokens without exposing the permanent key."""

    audience = "xianglens-api"

    def __init__(self, permanent_key: str, ttl_minutes: int) -> None:
        if len(permanent_key) < 16:
            raise ValueError("The permanent application key must contain at least 16 characters")
        self._signing_key = hashlib.sha256(
            b"xianglens-access-session-v1\0" + permanent_key.encode("utf-8")
        ).digest()
        self.ttl_seconds = ttl_minutes * 60

    def issue(self, *, now: int | None = None) -> tuple[str, SessionClaims]:
        issued_at = int(time.time() if now is None else now)
        claims = SessionClaims(
            session_id=f"session_{uuid.uuid4().hex}",
            token_id=uuid.uuid4().hex,
            issued_at=issued_at,
            expires_at=issued_at + self.ttl_seconds,
        )
        payload = {
            "aud": self.audience,
            "exp": claims.expires_at,
            "iat": claims.issued_at,
            "jti": claims.token_id,
            "sub": claims.session_id,
            "v": 1,
        }
        encoded_payload = _encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signature = _encode(
            hmac.new(self._signing_key, encoded_payload.encode("ascii"), hashlib.sha256).digest()
        )
        return f"{encoded_payload}.{signature}", claims

    def verify(self, token: str, *, now: int | None = None) -> SessionClaims:
        if not token or len(token) > 2048 or token.count(".") != 1:
            raise SessionTokenError("Malformed access token")
        encoded_payload, supplied_signature = token.split(".", 1)
        expected_signature = _encode(
            hmac.new(self._signing_key, encoded_payload.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(expected_signature, supplied_signature):
            raise SessionTokenError("Invalid access token")
        try:
            payload = json.loads(_decode(encoded_payload))
            session_id = payload["sub"]
            token_id = payload["jti"]
            issued_at = payload["iat"]
            expires_at = payload["exp"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SessionTokenError("Malformed access token") from exc
        if (
            payload.get("aud") != self.audience
            or payload.get("v") != 1
            or not isinstance(session_id, str)
            or not session_id.startswith("session_")
            or not isinstance(token_id, str)
            or not isinstance(issued_at, int)
            or not isinstance(expires_at, int)
        ):
            raise SessionTokenError("Invalid access token claims")
        current_time = int(time.time() if now is None else now)
        if issued_at > current_time + 60 or expires_at <= current_time:
            raise SessionTokenError("Access token expired")
        if expires_at - issued_at != self.ttl_seconds:
            raise SessionTokenError("Invalid access token lifetime")
        return SessionClaims(
            session_id=session_id,
            token_id=token_id,
            issued_at=issued_at,
            expires_at=expires_at,
        )


class SessionIssueLimiter:
    """Small in-process guard; an edge rate limit should still protect production."""

    def __init__(self, limit_per_minute: int) -> None:
        self.limit = limit_per_minute
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def retry_after(self, key: str, *, now: float | None = None) -> int:
        current_time = time.monotonic() if now is None else now
        with self._lock:
            attempts = self._attempts[key]
            while attempts and current_time - attempts[0] >= 60:
                attempts.popleft()
            if len(attempts) >= self.limit:
                return max(1, int(60 - (current_time - attempts[0])))
            attempts.append(current_time)
            return 0
