"""Reusable security utilities: password hashing and JWT tokens."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import bcrypt
from jose import JWTError, jwt

from core.config import settings
from core.constants import TOKEN_TYPE_ACCESS, TOKEN_TYPE_REFRESH


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


def hash_token(token: str) -> str:
    """One-way hash for storing refresh tokens at rest."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_jti() -> str:
    return uuid4().hex


def create_token(
    *,
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": generate_jti(),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_access_token(
    subject: str,
    *,
    role: str,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    claims: dict[str, Any] = {"role": role}
    if extra_claims:
        claims.update(extra_claims)
    return create_token(
        subject=subject,
        token_type=TOKEN_TYPE_ACCESS,
        expires_delta=expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.access_token_expire_minutes),
        extra_claims=claims,
    )


def create_refresh_token(
    subject: str,
    *,
    role: str,
    expires_delta: timedelta | None = None,
    jti: str | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, str, datetime]:
    """Return (token, jti, expires_at)."""
    token_jti = jti or generate_jti()
    delta = (
        expires_delta
        if expires_delta is not None
        else timedelta(days=settings.refresh_token_expire_days)
    )
    expires_at = datetime.now(UTC) + delta
    claims: dict[str, Any] = {"role": role, "jti": token_jti}
    if extra_claims:
        claims.update(extra_claims)
    token = create_token(
        subject=subject,
        token_type=TOKEN_TYPE_REFRESH,
        expires_delta=delta,
        extra_claims=claims,
    )
    return token, token_jti, expires_at


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None


def decode_access_token(token: str) -> dict[str, Any] | None:
    payload = decode_token(token)
    if payload is None or payload.get("type") != TOKEN_TYPE_ACCESS:
        return None
    return payload


def decode_refresh_token(token: str) -> dict[str, Any] | None:
    payload = decode_token(token)
    if payload is None or payload.get("type") != TOKEN_TYPE_REFRESH:
        return None
    return payload


def generate_secure_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)
