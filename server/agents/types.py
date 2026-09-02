"""Shared agent types and runtime contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID


class AgentType(StrEnum):
    RESUME = "resume"
    PLANNER = "planner"
    TECHNICAL = "technical"
    BEHAVIORAL = "behavioral"
    FACT_CHECKER = "fact_checker"
    EVALUATION = "evaluation"
    HIRING = "hiring"


class AgentStatus(StrEnum):
    IDLE = "idle"
    STANDBY = "standby"
    RUNNING = "running"
    BUSY = "busy"
    ERROR = "error"


@dataclass(slots=True)
class AgentContext:
    """Input context passed into an agent run."""

    interview_id: UUID | None = None
    candidate_id: UUID | None = None
    resume_id: UUID | None = None
    user_id: UUID | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentResult:
    """Normalized output from an agent run."""

    success: bool
    agent_type: AgentType
    data: dict[str, Any] = field(default_factory=dict)
    message: str | None = None
    error: str | None = None
