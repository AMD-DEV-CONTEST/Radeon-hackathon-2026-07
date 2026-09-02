"""WebSocket API routes for realtime interview architecture."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from api.websocket.auth import (
    WebSocketAuthError,
    authenticate_websocket_token,
    reject_websocket,
)
from api.websocket.manager import ConnectionManager, get_connection_manager
from api.websocket.schema import WSEnvelope, WSMessageType
from api.websocket.service import WebSocketService
from core.config import settings
from core.logger import logger
from db.database import get_db

router = APIRouter(prefix="/ws", tags=["websocket"])


def get_ws_manager() -> ConnectionManager:
    """Provide the process-wide websocket connection manager."""
    return get_connection_manager()


def get_websocket_service(
    db: Annotated[Session, Depends(get_db)],
    manager: Annotated[ConnectionManager, Depends(get_ws_manager)],
) -> WebSocketService:
    """Construct a request-scoped websocket service (repository + manager)."""
    return WebSocketService(manager, db)


async def _run_socket_loop(
    *,
    websocket: WebSocket,
    service: WebSocketService,
    connection_id: str,
    user_id: UUID,
) -> None:
    await service.handle_connect(connection_id=connection_id, user_id=user_id)
    try:
        while True:
            raw_message: dict[str, Any] = await websocket.receive_json()
            await service.handle_message(
                connection_id,
                raw_message,
                user_id=user_id,
            )
    except WebSocketDisconnect:
        logger.info("websocket client disconnected connection_id=%s", connection_id)
    finally:
        await service.handle_disconnect(connection_id)


@router.websocket("/live")
async def websocket_live(
    websocket: WebSocket,
    db: Annotated[Session, Depends(get_db)],
    manager: Annotated[ConnectionManager, Depends(get_ws_manager)],
    service: Annotated[WebSocketService, Depends(get_websocket_service)],
    token: Annotated[str | None, Query()] = None,
) -> None:
    """General realtime socket. Clients join rooms via join_room messages."""
    try:
        user = authenticate_websocket_token(token, db)
    except WebSocketAuthError as exc:
        await reject_websocket(websocket, code=exc.code, reason=exc.detail)
        return

    connection_id = await manager.connect(websocket, user.id)
    await _run_socket_loop(
        websocket=websocket,
        service=service,
        connection_id=connection_id,
        user_id=user.id,
    )


@router.websocket("/interview/{interview_id}")
async def websocket_live_interview(
    websocket: WebSocket,
    interview_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    manager: Annotated[ConnectionManager, Depends(get_ws_manager)],
    service: Annotated[WebSocketService, Depends(get_websocket_service)],
    token: Annotated[str | None, Query()] = None,
) -> None:
    """Live interview socket. Auto-joins interview/transcript/agent rooms."""
    try:
        user = authenticate_websocket_token(token, db)
    except WebSocketAuthError as exc:
        await reject_websocket(websocket, code=exc.code, reason=exc.detail)
        return

    connection_id = await manager.connect(websocket, user.id)

    try:
        await service.handle_connect(connection_id=connection_id, user_id=user.id)
        joined = await service.join_interview_rooms(
            connection_id,
            interview_id,
            user_id=user.id,
        )
        await manager.send_personal(
            connection_id,
            WSEnvelope(
                type=WSMessageType.SYSTEM,
                payload={
                    "event": "interview_rooms_ready",
                    "interview_id": str(interview_id),
                    "rooms": joined,
                    "heartbeat_interval_seconds": settings.ws_heartbeat_interval_seconds,
                },
            ),
        )

        while True:
            raw_message: dict[str, Any] = await websocket.receive_json()
            await service.handle_message(
                connection_id,
                raw_message,
                user_id=user.id,
            )
    except WebSocketDisconnect:
        logger.info(
            "websocket interview disconnected connection_id=%s interview_id=%s",
            connection_id,
            interview_id,
        )
    except PermissionError as exc:
        await manager.send_personal(
            connection_id,
            WSEnvelope(
                type=WSMessageType.ERROR,
                payload={"detail": str(exc)},
            ),
        )
        await manager.disconnect(connection_id)
    finally:
        if manager.get_connection(connection_id) is not None:
            await service.handle_disconnect(connection_id)
