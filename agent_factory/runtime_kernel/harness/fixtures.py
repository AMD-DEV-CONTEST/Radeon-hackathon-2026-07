from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FixtureBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    model_service: object | None = None
    tool_registry: object | None = None
    memory_store: object | None = None
    checkpointer: object | None = None
    approval_responses: list[dict[str, Any]] = Field(default_factory=list)


class HarnessScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    input_text: str
    user_config: dict[str, Any] = Field(default_factory=dict)
    agent_config: dict[str, Any] = Field(default_factory=dict)
    session_config: dict[str, Any] = Field(default_factory=dict)
    resume_payload: dict[str, Any] = Field(default_factory=dict)
    resume_after_interrupt: bool = False
    assertions: list[dict[str, Any]] = Field(default_factory=list)


class HarnessScenarioResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    status: str
    error: dict[str, str] | None = None
    assertion_results: list[dict[str, Any]] = Field(default_factory=list)
    final_answer: str | None = None
    final_state_snapshot: dict[str, Any] = Field(default_factory=dict)
    event_log: list[dict[str, Any]] = Field(default_factory=list)
    trace_summary: dict[str, Any] | None = None
