"""WebSocket authentication helpers."""

from __future__ import annotations

from uuid import UUID

from fastapi import WebSocket, status
from sqlalchemy.orm import Session

from api.auth.repository import AuthRepository
from core.security import decode_access_token
from models.user import User


class WebSocketAuthError(Exception):
    def __init__(self, detail: str, code: int = status.WS_1008_POLICY_VIOLATION) -> None:
        super().__init__(detail)
        self.detail = detail
        self.code = code


def authenticate_websocket_token(token: str | None, db: Session) -> User:
    if not token:
        raise WebSocketAuthError("Missing authentication token")

    payload = decode_access_token(token)
    if payload is None:
        raise WebSocketAuthError("Invalid or expired token")

    subject = payload.get("sub")
    if subject is None:
        raise WebSocketAuthError("Invalid token subject")

    try:
        user_id = UUID(str(subject))
    except ValueError as exc:
        raise WebSocketAuthError("Invalid token subject") from exc

    user = AuthRepository(db).get_user_by_id(user_id)
    if user is None or not user.is_active:
        raise WebSocketAuthError("User not found or inactive")
    return user


async def reject_websocket(websocket: WebSocket, *, code: int, reason: str) -> None:
    # Accept-then-close is the portable rejection path for Starlette websockets.
    await websocket.accept()
    await websocket.close(code=code, reason=reason[:123])
