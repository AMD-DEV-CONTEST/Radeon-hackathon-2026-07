"""WebSocket connection manager, room management, and broadcast primitives."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from api.websocket.schema import ConnectionInfo, RoomInfo, WSEnvelope, WSRoomType
from core.logger import logger


@dataclass
class ManagedConnection:
    connection_id: str
    websocket: WebSocket
    user_id: UUID
    connected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_heartbeat_at: datetime | None = None
    rooms: set[str] = field(default_factory=set)


@dataclass
class ManagedRoom:
    room_id: str
    room_type: WSRoomType
    connection_ids: set[str] = field(default_factory=set)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ConnectionManager:
    """In-memory websocket connection and room registry."""

    def __init__(self) -> None:
        self._connections: dict[str, ManagedConnection] = {}
        self._user_connections: dict[UUID, set[str]] = {}
        self._rooms: dict[str, ManagedRoom] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: UUID) -> str:
        await websocket.accept()
        connection_id = uuid4().hex

        async with self._lock:
            self._connections[connection_id] = ManagedConnection(
                connection_id=connection_id,
                websocket=websocket,
                user_id=user_id,
                last_heartbeat_at=datetime.now(UTC),
            )
            self._user_connections.setdefault(user_id, set()).add(connection_id)

        logger.info("websocket connected id=%s user_id=%s", connection_id, user_id)
        return connection_id

    async def disconnect(self, connection_id: str) -> None:
        async with self._lock:
            connection = self._connections.pop(connection_id, None)
            if connection is None:
                return

            user_connections = self._user_connections.get(connection.user_id)
            if user_connections is not None:
                user_connections.discard(connection_id)
                if not user_connections:
                    self._user_connections.pop(connection.user_id, None)

            for room_id in list(connection.rooms):
                room = self._rooms.get(room_id)
                if room is None:
                    continue
                room.connection_ids.discard(connection_id)
                if not room.connection_ids:
                    self._rooms.pop(room_id, None)

        if connection.websocket.client_state == WebSocketState.CONNECTED:
            try:
                await connection.websocket.close()
            except Exception:  # noqa: BLE001 - disconnect must be best-effort
                pass

        logger.info("websocket disconnected id=%s user_id=%s", connection_id, connection.user_id)

    async def join_room(
        self,
        connection_id: str,
        room_id: str,
        *,
        room_type: WSRoomType = WSRoomType.INTERVIEW,
    ) -> RoomInfo:
        async with self._lock:
            connection = self._require_connection(connection_id)
            room = self._rooms.get(room_id)
            if room is None:
                room = ManagedRoom(room_id=room_id, room_type=room_type)
                self._rooms[room_id] = room
            room.connection_ids.add(connection_id)
            connection.rooms.add(room_id)
            return self._room_info(room)

    async def leave_room(self, connection_id: str, room_id: str) -> RoomInfo | None:
        async with self._lock:
            connection = self._connections.get(connection_id)
            if connection is None:
                return None

            connection.rooms.discard(room_id)
            room = self._rooms.get(room_id)
            if room is None:
                return None

            room.connection_ids.discard(connection_id)
            info = self._room_info(room)
            if not room.connection_ids:
                self._rooms.pop(room_id, None)
            return info

    async def touch_heartbeat(self, connection_id: str) -> datetime:
        async with self._lock:
            connection = self._require_connection(connection_id)
            connection.last_heartbeat_at = datetime.now(UTC)
            return connection.last_heartbeat_at

    async def send_personal(self, connection_id: str, message: WSEnvelope | dict[str, Any]) -> bool:
        connection = self._connections.get(connection_id)
        if connection is None:
            return False
        return await self._send(connection, message)

    async def broadcast_room(
        self,
        room_id: str,
        message: WSEnvelope | dict[str, Any],
        *,
        exclude_connection_id: str | None = None,
    ) -> int:
        connection_ids = list(self._rooms.get(room_id).connection_ids) if room_id in self._rooms else []
        sent = 0
        for connection_id in connection_ids:
            if exclude_connection_id and connection_id == exclude_connection_id:
                continue
            if await self.send_personal(connection_id, message):
                sent += 1
        return sent

    async def broadcast_all(
        self,
        message: WSEnvelope | dict[str, Any],
        *,
        exclude_connection_id: str | None = None,
    ) -> int:
        connection_ids = list(self._connections.keys())
        sent = 0
        for connection_id in connection_ids:
            if exclude_connection_id and connection_id == exclude_connection_id:
                continue
            if await self.send_personal(connection_id, message):
                sent += 1
        return sent

    def get_connection(self, connection_id: str) -> ManagedConnection | None:
        return self._connections.get(connection_id)

    def get_connection_info(self, connection_id: str) -> ConnectionInfo | None:
        connection = self._connections.get(connection_id)
        if connection is None:
            return None
        return ConnectionInfo(
            connection_id=connection.connection_id,
            user_id=connection.user_id,
            connected_at=connection.connected_at,
            last_heartbeat_at=connection.last_heartbeat_at,
            rooms=sorted(connection.rooms),
        )

    def get_room_info(self, room_id: str) -> RoomInfo | None:
        room = self._rooms.get(room_id)
        if room is None:
            return None
        return self._room_info(room)

    def list_rooms(self) -> list[RoomInfo]:
        return [self._room_info(room) for room in self._rooms.values()]

    def connection_count(self) -> int:
        return len(self._connections)

    def room_count(self) -> int:
        return len(self._rooms)

    def stale_connection_ids(self, timeout_seconds: int) -> list[str]:
        now = datetime.now(UTC)
        stale: list[str] = []
        for connection_id, connection in self._connections.items():
            heartbeat = connection.last_heartbeat_at or connection.connected_at
            if (now - heartbeat).total_seconds() > timeout_seconds:
                stale.append(connection_id)
        return stale

    async def disconnect_stale(self, timeout_seconds: int) -> list[str]:
        stale_ids = self.stale_connection_ids(timeout_seconds)
        for connection_id in stale_ids:
            await self.disconnect(connection_id)
        return stale_ids

    async def _send(
        self,
        connection: ManagedConnection,
        message: WSEnvelope | dict[str, Any],
    ) -> bool:
        if connection.websocket.client_state != WebSocketState.CONNECTED:
            await self.disconnect(connection.connection_id)
            return False

        payload = message.model_dump(mode="json") if isinstance(message, WSEnvelope) else message
        try:
            await connection.websocket.send_json(payload)
            return True
        except Exception:  # noqa: BLE001 - treat send failures as disconnects
            await self.disconnect(connection.connection_id)
            return False

    def _require_connection(self, connection_id: str) -> ManagedConnection:
        connection = self._connections.get(connection_id)
        if connection is None:
            raise KeyError(f"Unknown connection_id: {connection_id}")
        return connection

    @staticmethod
    def _room_info(room: ManagedRoom) -> RoomInfo:
        return RoomInfo(
            room_id=room.room_id,
            room_type=room.room_type,
            connection_count=len(room.connection_ids),
            connections=sorted(room.connection_ids),
        )


_manager: ConnectionManager | None = None


def get_connection_manager() -> ConnectionManager:
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager


def reset_connection_manager() -> None:
    global _manager
    _manager = None
