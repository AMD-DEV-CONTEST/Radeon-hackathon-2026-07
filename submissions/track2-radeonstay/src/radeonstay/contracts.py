from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Citation(ContractModel):
    document: str = Field(min_length=1, max_length=240)
    section: str = Field(min_length=1, max_length=240)
    excerpt: str = Field(min_length=1, max_length=4000)
    score: float = Field(ge=0)
    source_path: str = Field(min_length=1, max_length=500)
    chunk_id: str | None = Field(default=None, min_length=8, max_length=80)
    corpus_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    support: Literal["direct", "context", "unverified"] = "direct"


class PlanStep(ContractModel):
    step_id: str = Field(min_length=1, max_length=40)
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict, max_length=20)
    reason: str = Field(min_length=1, max_length=400)
    depends_on: list[str] = Field(default_factory=list, max_length=8)


class AgentPlan(ContractModel):
    objective: str = Field(min_length=1, max_length=500)
    steps: list[PlanStep] = Field(min_length=1, max_length=8)
    response_language: Literal["English", "中文"] = "English"

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
                    f"Step {step.step_id!r} depends on unknown/future steps: "
                    f"{sorted(unknown)}"
                )
            seen.add(step.step_id)
        return self


CitationIdentifier = Annotated[
    str,
    Field(min_length=2, max_length=16, pattern=r"^c[1-9][0-9]*$"),
]
MissingFieldName = Annotated[
    str,
    Field(min_length=1, max_length=80, pattern=r"^[A-Za-z][A-Za-z0-9_]*$"),
]
BoundedFactSource = Annotated[str, Field(min_length=1, max_length=100)]
BoundedTiming = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class PlanEnvelope(ContractModel):
    """One constrained model result for planning and evidence selection."""

    plan: AgentPlan
    citation_ids: list[CitationIdentifier] = Field(max_length=3)
    response_language: Literal["English", "中文"]
    missing_fields: list[MissingFieldName] = Field(max_length=12)
    next_action: str | None = Field(max_length=240)

    @model_validator(mode="after")
    def validate_envelope_consistency(self) -> PlanEnvelope:
        if len(set(self.citation_ids)) != len(self.citation_ids):
            raise ValueError("PlanEnvelope citation IDs must be unique")
        if len(set(self.missing_fields)) != len(self.missing_fields):
            raise ValueError("PlanEnvelope missing fields must be unique")
        if self.response_language != self.plan.response_language:
            raise ValueError("PlanEnvelope response language must match its plan")
        return self


class ToolReceipt(ContractModel):
    step_id: str
    tool: str
    status: Literal[
        "ok",
        "needs_input",
        "pending_confirmation",
        "blocked",
        "cancelled",
        "denied",
        "error",
    ]
    summary: str
    data: dict[str, Any] = Field(default_factory=dict, max_length=30)
    audit_id: str | None = None


class PendingAction(ContractModel):
    """Display-safe pending write metadata; capability material stays server-side."""

    action_id: str = Field(min_length=1, max_length=80)
    step_id: str = Field(min_length=1, max_length=40)
    session_id: str
    tool: str
    arguments: dict[str, Any] = Field(max_length=20)
    preview: str
    preview_data: dict[str, Any] = Field(default_factory=dict, max_length=30)
    expires_at: str


class PendingActionView(ContractModel):
    """Minimal resumable preview; arguments and capability material are excluded."""

    action_id: str = Field(min_length=1, max_length=80)
    step_id: str = Field(min_length=1, max_length=40)
    tool: str = Field(min_length=1, max_length=80)
    preview: str = Field(min_length=1, max_length=2000)
    preview_data: dict[str, Any] = Field(default_factory=dict, max_length=30)
    expires_at: str = Field(min_length=1, max_length=80)

    @field_validator("preview_data")
    @classmethod
    def reject_private_preview_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        def contains_private_key(item: Any) -> bool:
            if isinstance(item, dict):
                for key, nested in item.items():
                    normalized = str(key).casefold().replace("-", "_")
                    if normalized.startswith("_binding_") or normalized in {
                        "confirmation_token",
                        "identity_token",
                        "token",
                        "token_hash",
                    }:
                        return True
                    if contains_private_key(nested):
                        return True
            elif isinstance(item, (list, tuple)):
                return any(contains_private_key(nested) for nested in item)
            return False

        if contains_private_key(value):
            raise ValueError("preview_data contains private capability metadata")
        return value


class DeferredActionView(ContractModel):
    """Safe continuation metadata for a write blocked by an earlier preview.

    The original arguments are deliberately excluded: after the prior write is
    confirmed, the model must resolve current state and create a new preview.
    """

    step_id: str = Field(min_length=1, max_length=40)
    tool: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=500)
    target_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )


class RepreviewActionView(ContractModel):
    """Persisted, capability-free metadata for rebuilding one cancelled/stale write."""

    step_id: str = Field(min_length=1, max_length=40)
    tool: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=500)
    target_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )


class RecoveryImpactView(ContractModel):
    """Privacy-minimized before/after evidence for disruption recovery."""

    status: Literal[
        "previewed",
        "stay_confirmed",
        "transport_pending",
        "complete",
        "needs_repreview",
        "cancelled",
    ]
    booking_id: str = Field(min_length=1, max_length=80)
    prior_check_in: str | None = Field(default=None, max_length=40)
    prior_check_out: str | None = Field(default=None, max_length=40)
    proposed_check_in: str | None = Field(default=None, max_length=40)
    proposed_check_out: str | None = Field(default=None, max_length=40)
    prior_total_cents: int | None = Field(default=None, ge=0)
    proposed_total_cents: int | None = Field(default=None, ge=0)
    price_delta_cents: int | None = None
    currency: str = Field(default="CNY", min_length=3, max_length=8)
    ticket_id: str | None = Field(default=None, max_length=80)
    current_ticket_status: str | None = Field(default=None, max_length=40)
    proposed_ticket_status: str | None = Field(default=None, max_length=40)
    confirmed_ticket_updated_at: str | None = Field(default=None, max_length=64)
    confirmed_ticket_state_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    description_changed: bool | None = None
    external_service_price: Literal["not_quoted"] = "not_quoted"
    policy_chunk_ids: list[str] = Field(default_factory=list, max_length=8)
    policy_corpus_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )

    @field_validator("policy_chunk_ids")
    @classmethod
    def validate_policy_chunk_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Recovery policy chunk IDs must be unique")
        if any(not 8 <= len(item) <= 80 for item in value):
            raise ValueError("Recovery policy chunk IDs must be bounded")
        return value

    def has_complete_stay_evidence(
        self,
        *,
        active_booking_id: str | None = None,
    ) -> bool:
        """Require a coherent, price-bound before/after stay impact."""

        if active_booking_id is not None and self.booking_id != active_booking_id:
            return False
        if self.status not in {
            "stay_confirmed",
            "transport_pending",
            "complete",
        }:
            return False
        if not all(
            (
                self.prior_check_in,
                self.prior_check_out,
                self.proposed_check_in,
                self.proposed_check_out,
            )
        ):
            return False
        try:
            prior_check_in = date.fromisoformat(str(self.prior_check_in))
            prior_check_out = date.fromisoformat(str(self.prior_check_out))
            proposed_check_in = date.fromisoformat(str(self.proposed_check_in))
            proposed_check_out = date.fromisoformat(str(self.proposed_check_out))
        except ValueError:
            return False
        if (
            prior_check_out <= prior_check_in
            or proposed_check_out <= proposed_check_in
        ):
            return False
        if (
            self.prior_total_cents is None
            or self.proposed_total_cents is None
            or self.price_delta_cents is None
            or self.price_delta_cents
            != self.proposed_total_cents - self.prior_total_cents
        ):
            return False
        return bool(self.policy_chunk_ids and self.policy_corpus_sha256)

    def has_complete_transport_evidence(
        self,
        *,
        active_booking_id: str | None = None,
    ) -> bool:
        """Require a confirmed transport binding on top of stay evidence."""

        if self.status != "complete" or not self.has_complete_stay_evidence(
            active_booking_id=active_booking_id
        ):
            return False
        current_status = (self.current_ticket_status or "").casefold()
        proposed_status = (self.proposed_ticket_status or "").casefold()
        return bool(
            self.ticket_id
            and current_status
            and proposed_status in {"open", "in_progress"}
            and self.confirmed_ticket_updated_at
            and self.confirmed_ticket_state_sha256
            and (
                self.description_changed is True
                or current_status != proposed_status
            )
            and self.external_service_price == "not_quoted"
        )


class SafetyHandoffView(ContractModel):
    """Verified staff handoff for a safety need that automation cannot resolve."""

    status: Literal[
        "previewed",
        "recorded",
        "needs_repreview",
        "cancelled",
    ]
    purpose: Literal["allergy_staff_handoff"] = "allergy_staff_handoff"
    booking_id: str = Field(min_length=1, max_length=80)
    ticket_id: str | None = Field(default=None, max_length=80)
    ticket_status: str | None = Field(default=None, max_length=40)
    ticket_updated_at: str | None = Field(default=None, max_length=64)
    ticket_state_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    policy_chunk_ids: list[str] = Field(default_factory=list, max_length=8)
    policy_corpus_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
    )
    human_followup_required: Literal[True] = True

    @field_validator("policy_chunk_ids")
    @classmethod
    def validate_policy_chunk_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Safety handoff policy chunk IDs must be unique")
        if any(not 8 <= len(item) <= 80 for item in value):
            raise ValueError("Safety handoff policy chunk IDs must be bounded")
        return value

    @model_validator(mode="after")
    def validate_recorded_binding(self) -> SafetyHandoffView:
        bound_fields = (
            self.ticket_id,
            self.ticket_status,
            self.ticket_updated_at,
            self.ticket_state_sha256,
        )
        if self.status == "recorded" and not all(bound_fields):
            raise ValueError(
                "A recorded safety handoff requires a complete ticket binding"
            )
        if self.status == "recorded" and self.ticket_status not in {
            "open",
            "in_progress",
        }:
            raise ValueError(
                "A recorded safety handoff requires an active staff ticket"
            )
        if self.status == "recorded" and (
            not self.policy_chunk_ids or self.policy_corpus_sha256 is None
        ):
            raise ValueError(
                "A recorded safety handoff requires current policy evidence"
            )
        return self


class GuestNeedView(ContractModel):
    """One guest-visible need backed only by verified local evidence."""

    key: Literal[
        "room",
        "late_arrival",
        "allergy",
        "transfer",
        "child_seat",
        "quiet_room",
        "delay_recovery",
        "privacy",
    ]
    label: str = Field(min_length=1, max_length=80)
    status: Literal[
        "requested",
        "grounded",
        "previewed",
        "confirmed",
        "human_followup",
    ]
    summary: str = Field(min_length=1, max_length=240)
    source_refs: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("source_refs")
    @classmethod
    def validate_need_source_refs(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Guest need source references must be unique")
        if any(not 1 <= len(item) <= 160 for item in value):
            raise ValueError("Guest need source references must be bounded")
        return value


class AuthorityClaimView(ContractModel):
    """A rendered factual claim and the exact authority that supports it."""

    section: Literal["conclusion", "result", "confirmation", "policy"]
    claim: str = Field(min_length=1, max_length=500)
    source_ref: str = Field(min_length=1, max_length=160)
    source_type: Literal["policy", "receipt", "user_fact", "control"]


class JourneyOutcomeView(ContractModel):
    """Cumulative, deterministic business outcomes for the current journey."""

    authoritative_read_count: int = Field(default=0, ge=0, le=500)
    confirmed_write_count: int = Field(default=0, ge=0, le=100)
    active_preview_count: int = Field(default=0, ge=0, le=1)
    cross_user_result_count: int = Field(default=0, ge=0, le=100)
    human_followup_count: int = Field(default=0, ge=0, le=20)


class JourneyView(ContractModel):
    revision: int = Field(default=1, ge=1)
    phase: Literal[
        "planning",
        "ready",
        "awaiting_confirmation",
        "needs_input",
        "recovering",
        "complete",
        "cancelled",
        "error",
    ] = "planning"
    active_booking_id: str | None = Field(default=None, max_length=80)
    candidate_booking_ids: list[str] = Field(default_factory=list, max_length=20)
    known_facts: dict[str, Any] = Field(default_factory=dict, max_length=30)
    missing_fields: list[str] = Field(default_factory=list, max_length=20)
    completed_steps: list[str] = Field(default_factory=list, max_length=50)
    pending_action_ids: list[str] = Field(default_factory=list, max_length=20)
    pending_action_previews: list[PendingActionView] = Field(
        default_factory=list,
        max_length=1,
    )
    deferred_action: DeferredActionView | None = None
    repreview_action: RepreviewActionView | None = None
    recovery_impact: RecoveryImpactView | None = None
    safety_handoff: SafetyHandoffView | None = None
    guest_needs: list[GuestNeedView] = Field(default_factory=list, max_length=8)
    authority_map: list[AuthorityClaimView] = Field(default_factory=list, max_length=20)
    outcome: JourneyOutcomeView = Field(default_factory=JourneyOutcomeView)
    next_action: str | None = Field(default=None, max_length=500)
    resumable: bool = True
    updated_at: str | None = None

    @model_validator(mode="after")
    def validate_pending_action_previews(self) -> JourneyView:
        preview_ids = [item.action_id for item in self.pending_action_previews]
        if len(set(preview_ids)) != len(preview_ids):
            raise ValueError("pending action preview IDs must be unique")
        if set(preview_ids) - set(self.pending_action_ids):
            raise ValueError(
                "pending action previews must reference pending action IDs"
            )
        return self


class ActionCard(ContractModel):
    """A display-safe action projection. Capability tokens never belong here."""

    action_id: str = Field(min_length=1, max_length=80)
    step_id: str = Field(min_length=1, max_length=40)
    tool: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    status: Literal[
        "planned",
        "running",
        "succeeded",
        "awaiting_confirmation",
        "blocked",
        "failed",
        "cancelled",
        "needs_repreview",
    ]
    effect: Literal["read", "write", "control"]
    summary: str = Field(min_length=1, max_length=2000)
    expires_at: str | None = None
    can_confirm: bool = False
    can_cancel: bool = False
    can_repreview: bool = False


class GroundingProof(ContractModel):
    applicable: bool = True
    verified: bool = False
    claim_count: int = Field(default=0, ge=0, le=100)
    unsupported_count: int = Field(default=0, ge=0, le=100)
    source_refs: list[str] = Field(default_factory=list, max_length=40)
    claims: list[AuthorityClaimView] = Field(default_factory=list, max_length=20)
    renderer: Literal["deterministic-template", "not-applicable"] = (
        "deterministic-template"
    )
    rebuilt: bool = False

    @field_validator("source_refs")
    @classmethod
    def validate_source_refs(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Grounding source references must be unique")
        if any(not 1 <= len(item) <= 160 for item in value):
            raise ValueError("Grounding source references must be bounded")
        return value


class PrivacyProof(ContractModel):
    mode: Literal["full_refusal", "partitioned"]
    unsafe_scope_detected: bool = True
    unsafe_scope_refused: bool = True
    safe_scope_completed: bool = False
    model_invoked: bool = False
    read_tool_count: int = Field(default=0, ge=0, le=20)
    business_write_count: int = Field(default=0, ge=0, le=20)
    cross_user_result_count: int = Field(default=0, ge=0, le=20)
    owner_scoped_result_count: int = Field(default=0, ge=0, le=100)
    scope_verified: bool = False
    identity_scope: Literal["owner_only", "staff", "admin", "unknown"] = "unknown"
    secret_retained: bool = False
    audit_chain_valid: bool = False
    blocked_categories: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("blocked_categories")
    @classmethod
    def validate_blocked_categories(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Blocked privacy categories must be unique")
        if any(not 1 <= len(item) <= 80 for item in value):
            raise ValueError("Blocked privacy categories must be bounded")
        return value


class TrustCard(ContractModel):
    operation_scope: Literal["agent_request", "deterministic_local_tool"] = (
        "agent_request"
    )
    local_only: bool = True
    model_backend: str = Field(min_length=1, max_length=240)
    schema_constrained: bool = False
    thinking_enabled: bool | None = None
    citations_verified: bool = False
    citation_count: int = Field(default=0, ge=0)
    timings_ms: dict[str, BoundedTiming] = Field(default_factory=dict, max_length=10)
    tool_receipt_count: int = Field(default=0, ge=0, le=8)
    fact_sources: list[BoundedFactSource] = Field(default_factory=list, max_length=12)
    write_status: Literal[
        "none",
        "awaiting_confirmation",
        "blocked",
        "cancelled",
        "completed",
        "failed",
    ] = "none"
    writes_require_confirmation: bool = True
    audit_chain_valid: bool = True
    journey_state_verified: bool = True
    grounding: GroundingProof = Field(default_factory=GroundingProof)
    privacy: PrivacyProof | None = None
    runtime_proof: dict[str, Any] = Field(default_factory=dict, max_length=48)


class SessionProjection(ContractModel):
    """Owner-scoped, display-safe state used to resume and refresh the judge UI."""

    journey: JourneyView
    actions: list[ActionCard] = Field(default_factory=list, max_length=20)


class StageTrace(ContractModel):
    stage: Literal[
        "retrieval",
        "memory",
        "planning",
        "validation",
        "tools",
        "answer",
        "complete",
    ]
    status: Literal["planned", "running", "succeeded", "failed", "blocked"]
    elapsed_ms: float | None = Field(default=None, ge=0)
    detail: str | None = Field(default=None, max_length=240)


class AgentResponse(ContractModel):
    session_id: str
    request_id: str
    answer: str
    plan: AgentPlan
    citations: list[Citation] = Field(default_factory=list)
    receipts: list[ToolReceipt] = Field(default_factory=list)
    pending_actions: list[PendingAction] = Field(default_factory=list, max_length=1)
    model_backend: str
    elapsed_ms: float = Field(ge=0)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    model_calls: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    journey: JourneyView = Field(default_factory=JourneyView)
    actions: list[ActionCard] = Field(default_factory=list, max_length=20)
    trust: TrustCard | None = None
    stage_trace: list[StageTrace] = Field(default_factory=list, max_length=12)


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
    confirmation_token: str | None = Field(
        default=None,
        min_length=20,
        max_length=500,
        repr=False,
    )
    action_id: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def require_confirmation_handle(self) -> ConfirmRequest:
        if self.confirmation_token is None and self.action_id is None:
            raise ValueError("confirmation_token or action_id is required")
        return self


class CancelActionRequest(ContractModel):
    session_id: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    identity_token: str = Field(min_length=20, max_length=2000)
    confirmation_token: str | None = Field(
        default=None,
        min_length=20,
        max_length=500,
        repr=False,
    )
    action_id: str = Field(min_length=1, max_length=80)


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
