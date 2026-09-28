from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException

from app.core.config import demo_auth_enabled


def require_demo_auth(authorization: str | None = Header(default=None)) -> None:
    """Protect demo routes without logging or persisting the ephemeral token."""
    if not demo_auth_enabled():
        return
    expected = os.getenv("DEMO_AUTH_TOKEN", "")
    supplied = ""
    if authorization and authorization.startswith("Bearer "):
        supplied = authorization[7:]
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
