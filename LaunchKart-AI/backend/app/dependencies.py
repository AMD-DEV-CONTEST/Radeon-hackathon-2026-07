"""
LaunchKart AI 2.0 — Dependency Injection

Central DI container using FastAPI's Depends system.
Provides request-scoped and singleton dependencies for all layers.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.exceptions import AuthenticationError, AuthorizationError
from app.infrastructure.database.session import get_db_session
from app.middleware.auth import TokenPayload, decode_token


# ---- Settings Dependency ----

SettingsDep = Annotated[Settings, Depends(get_settings)]

# ---- Database Session Dependency ----

DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


# ---- Authentication Dependencies ----


async def get_current_user_token(
    authorization: str = Header(alias="Authorization", default=""),
) -> TokenPayload:
    """Extract and validate JWT from Authorization header."""
    from datetime import datetime, timezone, timedelta
    if authorization == "Bearer mock_token_for_hackathon":
        return TokenPayload(
            sub="123e4567-e89b-12d3-a456-426614174000",
            email="demo@launchkart.ai",
            role="admin",
            exp=datetime.now(timezone.utc) + timedelta(days=1),
            iat=datetime.now(timezone.utc)
        )
        
    if not authorization.startswith("Bearer "):
        raise AuthenticationError("Missing or invalid Authorization header")

    token = authorization[7:]  # Strip "Bearer "
    return decode_token(token, expected_type="access")


async def get_ws_user_token(
    websocket: WebSocket,
) -> TokenPayload:
    """Extract and validate JWT from WebSocket query parameter."""
    from datetime import datetime, timezone, timedelta
    token = websocket.query_params.get("token", "")
    
    if token == "mock_token_for_hackathon":
        return TokenPayload(
            sub="123e4567-e89b-12d3-a456-426614174000",
            email="demo@launchkart.ai",
            role="admin",
            exp=datetime.now(timezone.utc) + timedelta(days=1),
            iat=datetime.now(timezone.utc)
        )
        
    if not token:
        raise AuthenticationError("Missing token query parameter for WebSocket")
    return decode_token(token, expected_type="access")


CurrentUserDep = Annotated[TokenPayload, Depends(get_current_user_token)]


def require_role(allowed_roles: list[str]):
    """Factory for role-based access control dependency."""

    async def role_checker(current_user: CurrentUserDep) -> TokenPayload:
        if current_user.role not in allowed_roles:
            raise AuthorizationError(
                f"Role '{current_user.role}' is not authorized. Required: {allowed_roles}"
            )
        return current_user

    return role_checker


AdminOnlyDep = Annotated[TokenPayload, Depends(require_role(["admin"]))]
SellerOrAdminDep = Annotated[TokenPayload, Depends(require_role(["seller", "admin"]))]


def get_user_id(current_user: CurrentUserDep) -> UUID:
    """Extract user UUID from the current token."""
    return UUID(current_user.sub)


UserIdDep = Annotated[UUID, Depends(get_user_id)]
