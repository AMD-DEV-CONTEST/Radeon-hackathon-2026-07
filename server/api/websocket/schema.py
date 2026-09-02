"""WebSocket message schemas and event contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class WSMessageType(StrEnum):
    # Connection / rooms
    SYSTEM = "system"
    ERROR = "error"
    JOIN_ROOM = "join_room"
    LEAVE_ROOM = "leave_room"
    ROOM_JOINED = "room_joined"
    ROOM_LEFT = "room_left"

    # Heartbeat
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"

    # Live domains
    TRANSCRIPT = "transcript"
    INTERVIEW_EVENT = "interview_event"
    AGENT_EVENT = "agent_event"


class WSRoomType(StrEnum):
    INTERVIEW = "interview"
    TRANSCRIPT = "transcript"
    AGENTS = "agents"
    GLOBAL = "global"


class WSEnvelope(BaseModel):
    """Canonical websocket message envelope."""

    type: WSMessageType
    room_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class JoinRoomPayload(BaseModel):
    room_id: str = Field(min_length=1, max_length=255)
    room_type: WSRoomType = WSRoomType.INTERVIEW

    @field_validator("room_id")
    @classmethod
    def strip_room_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("room_id cannot be empty")
        return cleaned


class LeaveRoomPayload(BaseModel):
    room_id: str = Field(min_length=1, max_length=255)

    @field_validator("room_id")
    @classmethod
    def strip_room_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("room_id cannot be empty")
        return cleaned


class HeartbeatPayload(BaseModel):
    client_ts: datetime | None = None


class TranscriptEventPayload(BaseModel):
    interview_id: UUID
    speaker: str = Field(min_length=1, max_length=50)
    speaker_name: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1)
    sequence: int | None = Field(default=None, ge=0)
    accuracy: float | None = Field(default=None, ge=0, le=100)


class InterviewEventPayload(BaseModel):
    interview_id: UUID
    event: str = Field(min_length=1, max_length=100)
    status: str | None = Field(default=None, max_length=50)
    data: dict[str, Any] = Field(default_factory=dict)


class AgentEventPayload(BaseModel):
    agent: str = Field(min_length=1, max_length=100)
    event: str = Field(min_length=1, max_length=100)
    status: str | None = Field(default=None, max_length=50)
    interview_id: UUID | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class ConnectionInfo(BaseModel):
    connection_id: str
    user_id: UUID
    connected_at: datetime
    last_heartbeat_at: datetime | None = None
    rooms: list[str] = Field(default_factory=list)


class RoomInfo(BaseModel):
    room_id: str
    room_type: WSRoomType
    connection_count: int
    connections: list[str] = Field(default_factory=list)


def interview_room_id(interview_id: UUID | str) -> str:
    return f"interview:{interview_id}"


def transcript_room_id(interview_id: UUID | str) -> str:
    return f"transcript:{interview_id}"


def agents_room_id(interview_id: UUID | str | None = None) -> str:
    if interview_id is None:
        return "agents:global"
    return f"agents:{interview_id}"
