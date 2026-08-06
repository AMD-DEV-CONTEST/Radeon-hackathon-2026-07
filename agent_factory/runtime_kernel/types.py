from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition: str
    next_node: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InterruptPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interrupt_type: str
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)


class ModelInvocationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ai_message: Any | None = None
    assistant_draft: str | None = None
    final_answer: str | None = None
    clarification_question: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    route_decision: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "failed", "interrupted"]
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    interrupt_type: str | None = None
    observation_summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
