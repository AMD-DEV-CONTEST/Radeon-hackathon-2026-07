"""
LaunchKart AI 2.0 — JWT Authentication Middleware

Validates JWT tokens and extracts user information from requests.
Supports both Bearer token and WebSocket query parameter authentication.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from app.config import get_settings
from app.exceptions import InvalidTokenError, TokenExpiredError

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class TokenPayload(BaseModel):
    """JWT token payload schema."""

    sub: str  # user ID
    email: str
    role: str
    exp: datetime
    iat: datetime
    token_type: str = "access"


class TokenPair(BaseModel):
    """Access + refresh token pair."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    user_id: UUID,
    email: str,
    role: str,
) -> str:
    """Create a JWT access token."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": expire,
        "iat": now,
        "token_type": "access",
    }

    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(
    user_id: UUID,
    email: str,
    role: str,
) -> str:
    """Create a JWT refresh token with longer expiry."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.jwt_refresh_token_expire_days)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": expire,
        "iat": now,
        "token_type": "refresh",
    }

    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_token_pair(user_id: UUID, email: str, role: str) -> TokenPair:
    """Create both access and refresh tokens."""
    settings = get_settings()
    return TokenPair(
        access_token=create_access_token(user_id, email, role),
        refresh_token=create_refresh_token(user_id, email, role),
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


def decode_token(token: str, expected_type: str = "access") -> TokenPayload:
    """Decode and validate a JWT token."""
    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as e:
        if "expired" in str(e).lower():
            raise TokenExpiredError() from e
        raise InvalidTokenError() from e

    token_type = payload.get("token_type", "access")
    if token_type != expected_type:
        raise InvalidTokenError()

    return TokenPayload(**payload)
