from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(ContractModel):
    document: str = Field(min_length=1, max_length=240)
    section: str = Field(min_length=1, max_length=240)
    excerpt: str = Field(min_length=1, max_length=4000)
    score: float = Field(ge=0)
    source_path: str = Field(min_length=1, max_length=500)


class PlanStep(ContractModel):
    step_id: str = Field(min_length=1, max_length=40)
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict, max_length=20)
    reason: str = Field(min_length=1, max_length=400)
    depends_on: list[str] = Field(default_factory=list, max_length=8)


class AgentPlan(ContractModel):
    objective: str = Field(min_length=1, max_length=500)
    steps: list[PlanStep] = Field(min_length=1, max_length=8)
    response_language: str = Field(default="English", min_length=1, max_length=40)

    @model_validator(mode="after")
    def validate_dependencies(self) -> AgentPlan:
        ids = [step.step_id for step in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError("Plan step IDs must be unique")
        seen: set[str] = set()
        for step in self.steps:
            if len(set(step.depends_on)) != len(step.depends_on):
                raise ValueError(f"Step {step.step_id!r} has duplicate dependencies")
            unknown = set(step.depends_on) - seen
            if unknown:
                raise ValueError(
                    f"Step {step.step_id!r} depends on unknown/future steps: {sorted(unknown)}"
                )
            seen.add(step.step_id)
        return self


class ToolReceipt(ContractModel):
    step_id: str
    tool: str
    status: Literal[
        "ok",
        "needs_input",
        "pending_confirmation",
        "denied",
        "error",
    ]
    summary: str
    data: dict[str, Any] = Field(default_factory=dict, max_length=30)
    confirmation_token: str | None = None
    audit_id: str | None = None


class PendingAction(ContractModel):
    action_id: str = Field(min_length=1, max_length=80)
    step_id: str = Field(min_length=1, max_length=40)
    token: str
    session_id: str
    tool: str
    arguments: dict[str, Any] = Field(max_length=20)
    preview: str
    preview_data: dict[str, Any] = Field(default_factory=dict, max_length=30)
    expires_at: str


class AgentResponse(ContractModel):
    session_id: str
    request_id: str
    answer: str
    plan: AgentPlan
    citations: list[Citation] = Field(default_factory=list)
    receipts: list[ToolReceipt] = Field(default_factory=list)
    pending_actions: list[PendingAction] = Field(default_factory=list)
    model_backend: str
    elapsed_ms: float = Field(ge=0)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    model_calls: list[dict[str, Any]] = Field(default_factory=list, max_length=8)


class ChatRequest(ContractModel):
    session_id: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    request_id: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
        description=(
            "Client-generated idempotency ID. Retries of one logical chat request "
            "must reuse the same value."
        ),
    )
    identity_token: str = Field(min_length=20, max_length=2000)
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized


class ConfirmRequest(ContractModel):
    session_id: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    identity_token: str = Field(min_length=20, max_length=2000)
    confirmation_token: str = Field(min_length=20, max_length=500)


class AuditEvent(ContractModel):
    event_id: str
    occurred_at: str
    actor_ref: str
    role: str
    action: str
    effect: Literal["read", "write", "control"]
    outcome: str
    details: dict[str, Any] = Field(default_factory=dict, max_length=30)
    previous_hash: str
    event_hash: str
    chain_valid: bool = True
