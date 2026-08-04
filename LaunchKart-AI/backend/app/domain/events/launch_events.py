"""
LaunchKart AI 2.0 — Domain Events

Event definitions for the event-driven communication between services and agents.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DomainEvent(BaseModel):
    """Base class for all domain events."""

    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)


class LaunchCreatedEvent(DomainEvent):
    """Emitted when a new product launch is created."""

    event_type: str = "launch.created"
    launch_id: UUID
    product_id: UUID
    user_id: UUID


class LaunchStartedEvent(DomainEvent):
    """Emitted when a product launch begins execution."""

    event_type: str = "launch.started"
    launch_id: UUID


class LaunchCompletedEvent(DomainEvent):
    """Emitted when a product launch completes successfully."""

    event_type: str = "launch.completed"
    launch_id: UUID
    duration_seconds: float


class LaunchFailedEvent(DomainEvent):
    """Emitted when a product launch fails."""

    event_type: str = "launch.failed"
    launch_id: UUID
    error: str


class AgentStartedEvent(DomainEvent):
    """Emitted when an agent begins execution."""

    event_type: str = "agent.started"
    launch_id: UUID
    agent_name: str
    task_id: UUID


class AgentProgressEvent(DomainEvent):
    """Emitted when an agent reports progress."""

    event_type: str = "agent.progress"
    launch_id: UUID
    agent_name: str
    task_id: UUID
    step: str
    progress: float  # 0.0 to 1.0


class AgentCompletedEvent(DomainEvent):
    """Emitted when an agent completes execution."""

    event_type: str = "agent.completed"
    launch_id: UUID
    agent_name: str
    task_id: UUID
    confidence: float
    duration_seconds: float


class AgentFailedEvent(DomainEvent):
    """Emitted when an agent fails execution."""

    event_type: str = "agent.failed"
    launch_id: UUID
    agent_name: str
    task_id: UUID
    error: str
    retry_count: int
