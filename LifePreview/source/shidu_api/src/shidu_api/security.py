"""Short-lived, same-origin artifact URL signing."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
from collections.abc import Callable
from uuid import UUID


_OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_PURPOSES = frozenset(
    {"video", "subtitle", "cover", "share_card", "reference"}
)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    if not value or len(value) > 2048 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("artifact token is invalid")
    try:
        return base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError) as exc:
        raise ValueError("artifact token is invalid") from exc


@dataclass(frozen=True, slots=True)
class SignedArtifact:
    owner: str
    artifact_id: UUID
    purpose: str
    expires_at: datetime


class ArtifactTokenSigner:
    """HMAC signer whose token contains no storage locator or credential."""

    def __init__(
        self,
        secret: bytes,
        *,
        ttl_seconds: int = 300,
        clock: Callable[[], datetime] | None = None,
        previous_secrets: tuple[bytes, ...] = (),
    ) -> None:
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError("artifact signing secret must contain at least 32 bytes")
        if not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 900:
            raise ValueError("artifact token ttl must be between 1 and 900 seconds")
        if any(
            not isinstance(item, bytes) or len(item) < 32
            for item in previous_secrets
        ):
            raise ValueError(
                "previous artifact signing secrets must contain at least 32 bytes"
            )
        secrets = (secret, *previous_secrets)
        key_ids = tuple(
            hashlib.sha256(item).hexdigest()[:16] for item in secrets
        )
        if len(set(key_ids)) != len(key_ids):
            raise ValueError("artifact signing secrets must be distinct")
        self._secret = secret
        self._key_id = key_ids[0]
        self._verification_keys = dict(zip(key_ids, secrets, strict=True))
        self._ttl_seconds = ttl_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _validate_owner(owner: str) -> str:
        if not isinstance(owner, str) or _OWNER_RE.fullmatch(owner) is None:
            raise ValueError("artifact owner is invalid")
        return owner

    @staticmethod
    def _validate_purpose(purpose: str) -> str:
        if purpose not in _PURPOSES:
            raise ValueError("artifact purpose is invalid")
        return purpose

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("artifact signing clock must be timezone-aware")
        return now.astimezone(timezone.utc)

    def issue(self, *, owner: str, artifact_id: UUID, purpose: str) -> str:
        owner = self._validate_owner(owner)
        purpose = self._validate_purpose(purpose)
        if not isinstance(artifact_id, UUID):
            raise ValueError("artifact id is invalid")
        now = self._now()
        payload = {
            "artifact_id": str(artifact_id),
            "exp": int(now.timestamp()) + self._ttl_seconds,
            "iat": int(now.timestamp()),
            "kid": self._key_id,
            "owner": owner,
            "purpose": purpose,
            "v": 1,
        }
        body = json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        signature = hmac.new(self._secret, body, hashlib.sha256).digest()
        return f"{_b64encode(body)}.{_b64encode(signature)}"

    def verify(
        self, token: str, *, expected_purpose: str | None = None
    ) -> SignedArtifact:
        if not isinstance(token, str) or len(token) > 4096 or token.count(".") != 1:
            raise ValueError("artifact token is invalid")
        encoded_body, encoded_signature = token.split(".", 1)
        body = _b64decode(encoded_body)
        signature = _b64decode(encoded_signature)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("artifact token is invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("artifact token is invalid")
        try:
            verification_key = self._verification_keys[str(payload["kid"])]
        except KeyError as exc:
            raise ValueError("artifact token is invalid") from exc
        expected = hmac.new(
            verification_key, body, hashlib.sha256
        ).digest()
        if len(signature) != len(expected) or not hmac.compare_digest(
            signature, expected
        ):
            raise ValueError("artifact token is invalid")
        if not isinstance(payload, dict) or set(payload) != {
            "artifact_id", "exp", "iat", "kid", "owner", "purpose", "v"
        }:
            raise ValueError("artifact token is invalid")
        if payload.get("v") != 1 or isinstance(payload.get("exp"), bool) or isinstance(payload.get("iat"), bool):
            raise ValueError("artifact token is invalid")
        try:
            artifact_id = UUID(str(payload["artifact_id"]))
            expires = int(payload["exp"])
            issued = int(payload["iat"])
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError("artifact token is invalid") from exc
        owner = self._validate_owner(payload.get("owner"))
        purpose = self._validate_purpose(payload.get("purpose"))
        now = int(self._now().timestamp())
        if issued > now + 30 or expires <= issued or expires - issued > 900:
            raise ValueError("artifact token is invalid")
        if expires <= now:
            raise ValueError("artifact token has expired")
        if expected_purpose is not None and purpose != self._validate_purpose(expected_purpose):
            raise ValueError("artifact token purpose does not match")
        return SignedArtifact(
            owner=owner,
            artifact_id=artifact_id,
            purpose=purpose,
            expires_at=datetime.fromtimestamp(expires, tz=timezone.utc),
        )


__all__ = ["ArtifactTokenSigner", "SignedArtifact"]
