"""
LaunchKart AI 2.0 — WebSocket Handler

Real-time bidirectional communication for agent execution monitoring.
Clients connect per-launch and receive live agent state updates.
"""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.dependencies import get_ws_user_token

logger = structlog.get_logger(__name__)

router = APIRouter()


class ConnectionManager:
    """Manages active WebSocket connections grouped by launch ID."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, launch_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        if launch_id not in self._connections:
            self._connections[launch_id] = []
        self._connections[launch_id].append(websocket)
        logger.info("WebSocket connected", launch_id=launch_id)

    def disconnect(self, launch_id: str, websocket: WebSocket) -> None:
        if launch_id in self._connections:
            self._connections[launch_id].remove(websocket)
            if not self._connections[launch_id]:
                del self._connections[launch_id]
        logger.info("WebSocket disconnected", launch_id=launch_id)

    async def broadcast(self, launch_id: str, message: dict) -> None:
        """Send a message to all clients watching a specific launch."""
        if launch_id not in self._connections:
            return

        dead_connections = []
        for connection in self._connections[launch_id]:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)

        for conn in dead_connections:
            self.disconnect(launch_id, conn)

    async def send_personal(self, websocket: WebSocket, message: dict) -> None:
        """Send a message to a specific client."""
        await websocket.send_json(message)

    def get_connection_count(self, launch_id: str) -> int:
        return len(self._connections.get(launch_id, []))

    async def broadcast_agent_status(self, launch_id: str, agent_id: str, status: str, progress: int, data: dict | None = None) -> None:
        """Stream agent progress and state."""
        await self.broadcast(launch_id, {
            "type": "agent_status",
            "agent": agent_id,
            "status": status,
            "progress": progress,
            "data": data or {}
        })

    async def broadcast_timeline_event(self, launch_id: str, event: dict) -> None:
        """Stream execution timeline events."""
        await self.broadcast(launch_id, {
            "type": "timeline_event",
            "event": event
        })

    async def broadcast_gpu_metrics(self, launch_id: str, metrics: dict) -> None:
        """Stream GPU telemetry."""
        await self.broadcast(launch_id, {
            "type": "gpu_metrics",
            "metrics": metrics
        })


# Singleton connection manager
manager = ConnectionManager()


@router.websocket("/{launch_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    launch_id: str,
) -> None:
    """WebSocket endpoint for real-time launch monitoring."""

    # Authenticate via query parameter
    try:
        token_payload = await get_ws_user_token(websocket)
    except Exception:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    launch_id_str = str(launch_id)

    await manager.connect(launch_id_str, websocket)
    await manager.send_personal(
        websocket,
        {
            "type": "connected",
            "launch_id": launch_id_str,
            "user_id": token_payload.sub,
            "message": "Connected to launch monitoring",
        },
    )

    try:
        while True:
            # Listen for client messages (ping/pong, commands)
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                msg_type = message.get("type", "")

                if msg_type == "ping":
                    await manager.send_personal(websocket, {"type": "pong"})

            except json.JSONDecodeError:
                await manager.send_personal(
                    websocket,
                    {"type": "error", "message": "Invalid JSON"},
                )

    except WebSocketDisconnect:
        manager.disconnect(launch_id_str, websocket)
    except Exception as e:
        logger.error("WebSocket error", error=str(e), launch_id=launch_id_str)
        manager.disconnect(launch_id_str, websocket)
