"""WebSocket business service layer."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from api.websocket.manager import ConnectionManager
from api.websocket.repository import WebSocketRepository
from api.websocket.schema import (
    AgentEventPayload,
    HeartbeatPayload,
    InterviewEventPayload,
    JoinRoomPayload,
    LeaveRoomPayload,
    TranscriptEventPayload,
    WSEnvelope,
    WSMessageType,
    WSRoomType,
    agents_room_id,
    interview_room_id,
    transcript_room_id,
)
from core.logger import logger


class WebSocketService:
    def __init__(
        self,
        manager: ConnectionManager,
        db: Session | None = None,
    ) -> None:
        self.manager = manager
        self.repository = WebSocketRepository(db) if db is not None else None

    async def handle_connect(
        self,
        *,
        connection_id: str,
        user_id: UUID,
    ) -> None:
        await self.manager.send_personal(
            connection_id,
            WSEnvelope(
                type=WSMessageType.SYSTEM,
                payload={
                    "event": "connected",
                    "connection_id": connection_id,
                    "user_id": str(user_id),
                },
            ),
        )

    async def handle_disconnect(self, connection_id: str) -> None:
        info = self.manager.get_connection_info(connection_id)
        rooms = info.rooms if info else []
        await self.manager.disconnect(connection_id)
        for room_id in rooms:
            await self.manager.broadcast_room(
                room_id,
                WSEnvelope(
                    type=WSMessageType.SYSTEM,
                    room_id=room_id,
                    payload={
                        "event": "peer_disconnected",
                        "connection_id": connection_id,
                    },
                ),
            )

    async def handle_message(
        self,
        connection_id: str,
        raw_message: dict[str, Any],
        *,
        user_id: UUID,
    ) -> None:
        try:
            envelope = WSEnvelope.model_validate(raw_message)
        except ValidationError as exc:
            await self._send_error(
                connection_id,
                detail="Invalid websocket message",
                errors=exc.errors(),
            )
            return

        handlers = {
            WSMessageType.HEARTBEAT: self._handle_heartbeat,
            WSMessageType.JOIN_ROOM: self._handle_join_room,
            WSMessageType.LEAVE_ROOM: self._handle_leave_room,
            WSMessageType.TRANSCRIPT: self._handle_transcript,
            WSMessageType.INTERVIEW_EVENT: self._handle_interview_event,
            WSMessageType.AGENT_EVENT: self._handle_agent_event,
        }
        handler = handlers.get(envelope.type)
        if handler is None:
            await self._send_error(
                connection_id,
                detail=f"Unsupported message type: {envelope.type}",
                request_id=envelope.request_id,
            )
            return

        await handler(connection_id, envelope, user_id=user_id)

    async def publish_transcript(
        self,
        payload: TranscriptEventPayload,
        *,
        exclude_connection_id: str | None = None,
    ) -> int:
        room_id = transcript_room_id(payload.interview_id)
        return await self.manager.broadcast_room(
            room_id,
            WSEnvelope(
                type=WSMessageType.TRANSCRIPT,
                room_id=room_id,
                payload=payload.model_dump(mode="json"),
            ),
            exclude_connection_id=exclude_connection_id,
        )

    async def publish_interview_event(
        self,
        payload: InterviewEventPayload,
        *,
        exclude_connection_id: str | None = None,
    ) -> int:
        room_id = interview_room_id(payload.interview_id)
        return await self.manager.broadcast_room(
            room_id,
            WSEnvelope(
                type=WSMessageType.INTERVIEW_EVENT,
                room_id=room_id,
                payload=payload.model_dump(mode="json"),
            ),
            exclude_connection_id=exclude_connection_id,
        )

    async def publish_agent_event(
        self,
        payload: AgentEventPayload,
        *,
        exclude_connection_id: str | None = None,
    ) -> int:
        room_id = agents_room_id(payload.interview_id)
        return await self.manager.broadcast_room(
            room_id,
            WSEnvelope(
                type=WSMessageType.AGENT_EVENT,
                room_id=room_id,
                payload=payload.model_dump(mode="json"),
            ),
            exclude_connection_id=exclude_connection_id,
        )

    async def join_interview_rooms(
        self,
        connection_id: str,
        interview_id: UUID,
        *,
        user_id: UUID,
    ) -> list[str]:
        await self._assert_interview_access(interview_id, user_id)
        room_ids = [
            interview_room_id(interview_id),
            transcript_room_id(interview_id),
            agents_room_id(interview_id),
        ]
        joined: list[str] = []
        for room_id, room_type in (
            (room_ids[0], WSRoomType.INTERVIEW),
            (room_ids[1], WSRoomType.TRANSCRIPT),
            (room_ids[2], WSRoomType.AGENTS),
        ):
            room = await self.manager.join_room(
                connection_id,
                room_id,
                room_type=room_type,
            )
            joined.append(room.room_id)
            await self.manager.send_personal(
                connection_id,
                WSEnvelope(
                    type=WSMessageType.ROOM_JOINED,
                    room_id=room.room_id,
                    payload=room.model_dump(mode="json"),
                ),
            )
        return joined

    async def _handle_heartbeat(
        self,
        connection_id: str,
        envelope: WSEnvelope,
        *,
        user_id: UUID,
    ) -> None:
        _ = user_id
        try:
            payload = HeartbeatPayload.model_validate(envelope.payload)
        except ValidationError:
            payload = HeartbeatPayload()

        heartbeat_at = await self.manager.touch_heartbeat(connection_id)
        await self.manager.send_personal(
            connection_id,
            WSEnvelope(
                type=WSMessageType.HEARTBEAT_ACK,
                request_id=envelope.request_id,
                payload={
                    "server_ts": heartbeat_at.isoformat(),
                    "client_ts": payload.client_ts.isoformat() if payload.client_ts else None,
                },
            ),
        )

    async def _handle_join_room(
        self,
        connection_id: str,
        envelope: WSEnvelope,
        *,
        user_id: UUID,
    ) -> None:
        try:
            payload = JoinRoomPayload.model_validate(envelope.payload)
        except ValidationError as exc:
            await self._send_error(
                connection_id,
                detail="Invalid join_room payload",
                errors=exc.errors(),
                request_id=envelope.request_id,
            )
            return

        if payload.room_type in {
            WSRoomType.INTERVIEW,
            WSRoomType.TRANSCRIPT,
            WSRoomType.AGENTS,
        }:
            interview_id = self._extract_interview_id(payload.room_id)
            if interview_id is not None:
                try:
                    await self._assert_interview_access(interview_id, user_id)
                except PermissionError as exc:
                    await self._send_error(
                        connection_id,
                        detail=str(exc),
                        request_id=envelope.request_id,
                    )
                    return

        room = await self.manager.join_room(
            connection_id,
            payload.room_id,
            room_type=payload.room_type,
        )
        await self.manager.send_personal(
            connection_id,
            WSEnvelope(
                type=WSMessageType.ROOM_JOINED,
                room_id=room.room_id,
                request_id=envelope.request_id,
                payload=room.model_dump(mode="json"),
            ),
        )
        await self.manager.broadcast_room(
            room.room_id,
            WSEnvelope(
                type=WSMessageType.SYSTEM,
                room_id=room.room_id,
                payload={
                    "event": "peer_joined",
                    "connection_id": connection_id,
                    "user_id": str(user_id),
                },
            ),
            exclude_connection_id=connection_id,
        )

    async def _handle_leave_room(
        self,
        connection_id: str,
        envelope: WSEnvelope,
        *,
        user_id: UUID,
    ) -> None:
        _ = user_id
        try:
            payload = LeaveRoomPayload.model_validate(envelope.payload)
        except ValidationError as exc:
            await self._send_error(
                connection_id,
                detail="Invalid leave_room payload",
                errors=exc.errors(),
                request_id=envelope.request_id,
            )
            return

        room = await self.manager.leave_room(connection_id, payload.room_id)
        await self.manager.send_personal(
            connection_id,
            WSEnvelope(
                type=WSMessageType.ROOM_LEFT,
                room_id=payload.room_id,
                request_id=envelope.request_id,
                payload={
                    "room_id": payload.room_id,
                    "remaining_connections": room.connection_count if room else 0,
                },
            ),
        )
        if room is not None:
            await self.manager.broadcast_room(
                payload.room_id,
                WSEnvelope(
                    type=WSMessageType.SYSTEM,
                    room_id=payload.room_id,
                    payload={
                        "event": "peer_left",
                        "connection_id": connection_id,
                    },
                ),
            )

    async def _handle_transcript(
        self,
        connection_id: str,
        envelope: WSEnvelope,
        *,
        user_id: UUID,
    ) -> None:
        try:
            payload = TranscriptEventPayload.model_validate(envelope.payload)
        except ValidationError as exc:
            await self._send_error(
                connection_id,
                detail="Invalid transcript payload",
                errors=exc.errors(),
                request_id=envelope.request_id,
            )
            return

        try:
            await self._assert_interview_access(payload.interview_id, user_id)
        except PermissionError as exc:
            await self._send_error(
                connection_id,
                detail=str(exc),
                request_id=envelope.request_id,
            )
            return

        # Ensure publisher is in transcript room, then broadcast.
        room_id = transcript_room_id(payload.interview_id)
        await self.manager.join_room(
            connection_id,
            room_id,
            room_type=WSRoomType.TRANSCRIPT,
        )
        await self.publish_transcript(payload)

    async def _handle_interview_event(
        self,
        connection_id: str,
        envelope: WSEnvelope,
        *,
        user_id: UUID,
    ) -> None:
        try:
            payload = InterviewEventPayload.model_validate(envelope.payload)
        except ValidationError as exc:
            await self._send_error(
                connection_id,
                detail="Invalid interview_event payload",
                errors=exc.errors(),
                request_id=envelope.request_id,
            )
            return

        try:
            await self._assert_interview_access(payload.interview_id, user_id)
        except PermissionError as exc:
            await self._send_error(
                connection_id,
                detail=str(exc),
                request_id=envelope.request_id,
            )
            return

        room_id = interview_room_id(payload.interview_id)
        await self.manager.join_room(
            connection_id,
            room_id,
            room_type=WSRoomType.INTERVIEW,
        )
        await self.publish_interview_event(payload)

    async def _handle_agent_event(
        self,
        connection_id: str,
        envelope: WSEnvelope,
        *,
        user_id: UUID,
    ) -> None:
        try:
            payload = AgentEventPayload.model_validate(envelope.payload)
        except ValidationError as exc:
            await self._send_error(
                connection_id,
                detail="Invalid agent_event payload",
                errors=exc.errors(),
                request_id=envelope.request_id,
            )
            return

        if payload.interview_id is not None:
            try:
                await self._assert_interview_access(payload.interview_id, user_id)
            except PermissionError as exc:
                await self._send_error(
                    connection_id,
                    detail=str(exc),
                    request_id=envelope.request_id,
                )
                return

        room_id = agents_room_id(payload.interview_id)
        await self.manager.join_room(
            connection_id,
            room_id,
            room_type=WSRoomType.AGENTS,
        )
        await self.publish_agent_event(payload)

    async def _assert_interview_access(self, interview_id: UUID, user_id: UUID) -> None:
        if self.repository is None:
            # Architecture mode without DB session — allow room wiring.
            logger.debug(
                "websocket interview access check skipped (no db) interview_id=%s",
                interview_id,
            )
            return
        if not self.repository.interview_exists_for_user(interview_id, user_id):
            raise PermissionError("Interview not found or access denied")

    @staticmethod
    def _extract_interview_id(room_id: str) -> UUID | None:
        parts = room_id.split(":", maxsplit=1)
        if len(parts) != 2:
            return None
        prefix, value = parts
        if prefix not in {"interview", "transcript", "agents"}:
            return None
        if value == "global":
            return None
        try:
            return UUID(value)
        except ValueError:
            return None

    async def _send_error(
        self,
        connection_id: str,
        *,
        detail: str,
        errors: list[Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        await self.manager.send_personal(
            connection_id,
            WSEnvelope(
                type=WSMessageType.ERROR,
                request_id=request_id,
                payload={
                    "detail": detail,
                    "errors": errors or [],
                },
            ),
        )
