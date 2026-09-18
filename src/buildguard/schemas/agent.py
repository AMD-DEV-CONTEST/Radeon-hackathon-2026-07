"""Agent conversation and planning schemas."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from buildguard.schemas.common import RecordSchema, Status, StrictSchema


class AgentMessage(RecordSchema):
    session_id: str
    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(min_length=1, max_length=100_000)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class PlanStep(StrictSchema):
    step_id: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=2000)
    tool_name: str | None = Field(default=None, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False
    status: Status = Status.PENDING


class TaskPlan(RecordSchema):
    goal: str = Field(min_length=1, max_length=4000)
    steps: list[PlanStep] = Field(min_length=1)
    status: Status = Status.PENDING


class AgentTask(RecordSchema):
    session_id: str
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1, max_length=4000)
    status: Status = Status.PENDING
    plan: TaskPlan | None = None
    completed_at: datetime | None = None
