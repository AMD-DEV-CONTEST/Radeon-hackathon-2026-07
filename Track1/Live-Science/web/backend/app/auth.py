"""Bearer-token authentication for the public Live-Science deployment.

Radeon Cloud's rc-tunnel exposes a public URL reachable from the internet, and
the platform requires the app itself to enforce login. Every /api/* endpoint
except /api/v1/auth/login requires either an `Authorization: Bearer <token>`
header or an `access_token` query parameter (used for <video>/<img>/<a>
artifacts, which cannot send custom headers).
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.config import AUTH_ENABLED, AUTH_TOKEN

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)


class LoginResponse(BaseModel):
    ok: bool
    token: str


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="missing or invalid access token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_token(request: Request, authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency enforcing authentication on protected routes."""
    if not AUTH_ENABLED:
        return
    provided: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        provided = authorization.split(" ", 1)[1].strip()
    if not provided:
        provided = request.query_params.get("access_token")
    if not provided or not secrets.compare_digest(provided.strip(), AUTH_TOKEN):
        raise _unauthorized()


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest) -> LoginResponse:
    if not AUTH_ENABLED:
        return LoginResponse(ok=True, token=req.token)
    if secrets.compare_digest(req.token.strip(), AUTH_TOKEN):
        return LoginResponse(ok=True, token=AUTH_TOKEN)
    raise _unauthorized()
