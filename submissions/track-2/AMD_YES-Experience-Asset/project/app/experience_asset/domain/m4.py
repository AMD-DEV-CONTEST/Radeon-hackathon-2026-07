"""Frozen E5/M4 contracts for the Insight and Boundary Map.

These contracts define the shape of the M4 artifact and its acceptance. They
carry no behaviour: ticket 02 implements generation and editing, ticket 03
implements the readiness transition.

The map deliberately treats boundary content as first class rather than as an
optional enrichment. A lesson drawn from one person's experience, shown without
its limitation and its transfer condition, reads as general advice; the reader
then applies it in a situation the original experience never covered, and the
asset has actively misled them. Requiring the boundary roles is what converts a
personal account into something safe to reuse.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from .enums import MilestoneState, ProgressState, StatementStatus, TerminalState
from .models import ContractModel, NonEmptyText, Sha256

M4ArtifactState = Literal[
    MilestoneState.NEEDS_INPUT,
    MilestoneState.REVIEW_READY,
    MilestoneState.CONFIRMED,
    MilestoneState.COMPLETE_WITH_GAPS,
    MilestoneState.INVALIDATED,
]

InsightRole = Literal[
    "LESSON",
    "SUPPORT",
    "COUNTERFACTUAL",
    "LIMITATION",
    "COUNTEREXAMPLE",
    "APPLICABILITY",
]

REQUIRED_INSIGHT_ROLES: frozenset[str] = frozenset(
    {
        "LESSON",
        "SUPPORT",
        "COUNTERFACTUAL",
        "LIMITATION",
        "COUNTEREXAMPLE",
        "APPLICABILITY",
    }
)

BOUNDARY_INSIGHT_ROLES: frozenset[str] = frozenset(
    {"LIMITATION", "COUNTEREXAMPLE", "APPLICABILITY"}
)
"""Roles that can ground a cross-asset transfer boundary.

Ticket 05 requires a candidate to resolve at least one current-side boundary
node through one of these roles. A relation shown without a boundary invites the
reader to treat structural similarity as permission to transfer the lesson
wholesale.
"""

M4UserAction = Literal["CONFIRM", "ACCEPT_WITH_GAPS", "MARK_GAP"]

M4ProgressStage = Literal[
    "LOAD_CONTEXT",
    "PLAN_INSIGHTS",
    "VALIDATE_OUTPUT",
    "REPAIR_OUTPUT",
    "PERSIST_MAP",
    "VERIFY_MAP",
    "REPLAN",
    "TERMINAL",
]

M4FailureCode = Literal[
    "UPSTREAM_STALE",
    "INVALID_MODEL_OUTPUT",
    "STRUCTURED_REPAIR_EXHAUSTED",
    "MODEL_CONTEXT_BUDGET_EXCEEDED",
    "PERMISSION_DENIED",
    "STORAGE_ERROR",
    "MODEL_UNAVAILABLE",
    "MODEL_TIMED_OUT",
]


class InsightStatementV1(ContractModel):
    """One role-bearing statement inside an insight entry.

    A statement is either grounded in canonical M3 evidence or explicitly marked
    as a visible gap. There is no third state: an ungrounded statement that does
    not declare itself a gap renders identically to a supported one, and the
    reader has no signal that something is missing.
    """

    statement_id: UUID
    role: InsightRole
    text: NonEmptyText = Field(max_length=1200)
    status: StatementStatus
    source_statement_ids: list[UUID] = Field(default_factory=list)
    source_decision_ids: list[UUID] = Field(default_factory=list)
    is_visible_gap: bool = False
    gap_reason: NonEmptyText | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def gap_and_grounding_are_consistent(self) -> InsightStatementV1:
        grounded = bool(self.source_statement_ids or self.source_decision_ids)
        if self.is_visible_gap:
            if grounded:
                raise ValueError(
                    "a visible gap cannot also cite canonical sources; cite the "
                    "sources and drop the gap flag, or keep the gap and drop the "
                    "citations"
                )
            if not self.gap_reason:
                raise ValueError("a visible gap requires an explicit gap_reason")
            if self.status is not StatementStatus.UNRESOLVED:
                raise ValueError("a visible gap must carry UNRESOLVED status")
            return self
        if self.gap_reason is not None:
            raise ValueError("gap_reason is only meaningful on a visible gap")
        if not grounded:
            raise ValueError(
                "a non-gap statement must cite at least one canonical statement "
                "or decision; otherwise it presents an unsupported claim with the "
                "same authority as a grounded one"
            )
        return self


class InsightEntryV1(ContractModel):
    """One lesson together with the boundary that makes it safe to reuse."""

    insight_id: UUID
    title: NonEmptyText = Field(max_length=240)
    source_decision_ids: list[UUID] = Field(min_length=1)
    statements: list[InsightStatementV1] = Field(min_length=6)

    @model_validator(mode="after")
    def entry_covers_every_role(self) -> InsightEntryV1:
        if len(self.source_decision_ids) != len(set(self.source_decision_ids)):
            raise ValueError("entry source decision IDs must be unique")

        statement_ids = [statement.statement_id for statement in self.statements]
        if len(statement_ids) != len(set(statement_ids)):
            raise ValueError("insight statement IDs must be unique within an entry")

        entry_decisions = set(self.source_decision_ids)
        for statement in self.statements:
            if not set(statement.source_decision_ids).issubset(entry_decisions):
                raise ValueError(
                    "statement source decisions must belong to the insight entry"
                )

        roles = {statement.role for statement in self.statements}
        missing = REQUIRED_INSIGHT_ROLES - roles
        if missing:
            raise ValueError(
                "insight entry must represent every role; use an explicit visible "
                f"gap for missing source content: {sorted(missing)}"
            )
        if sum(statement.role == "LESSON" for statement in self.statements) != 1:
            raise ValueError("insight entry requires exactly one LESSON statement")
        return self


class InsightBoundaryMapV1(ContractModel):
    """Editable M4 artifact bound to one exact accepted M3 state."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    artifact_id: UUID
    asset_id: UUID
    base_m3_artifact_id: UUID
    base_canonical_version_id: UUID
    generated_by_run_id: UUID
    state: M4ArtifactState
    entries: list[InsightEntryV1] = Field(min_length=1)
    dependency_decision_ids: list[UUID] = Field(min_length=1)
    dependency_statement_ids: list[UUID] = Field(default_factory=list)
    unresolved_question_ids: list[UUID] = Field(default_factory=list)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    invalidated_by_m3_artifact_id: UUID | None = None
    invalidated_by_canonical_version_id: UUID | None = None
    invalidation_reason: NonEmptyText | None = None
    affected_insight_ids: list[UUID] = Field(default_factory=list)
    reusable_insight_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def map_invariants_hold(self) -> InsightBoundaryMapV1:
        for label, values in (
            ("dependency decision IDs", self.dependency_decision_ids),
            ("dependency statement IDs", self.dependency_statement_ids),
            ("affected insight IDs", self.affected_insight_ids),
            ("reusable insight IDs", self.reusable_insight_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must be unique")

        insight_ids = [entry.insight_id for entry in self.entries]
        if len(insight_ids) != len(set(insight_ids)):
            raise ValueError("insight IDs must be unique within the map")

        known = set(insight_ids)
        for label, values in (
            ("affected insight IDs", self.affected_insight_ids),
            ("reusable insight IDs", self.reusable_insight_ids),
        ):
            if not set(values).issubset(known):
                raise ValueError(f"{label} must reference insights in this map")

        declared = set(self.dependency_decision_ids)
        for entry in self.entries:
            if not set(entry.source_decision_ids).issubset(declared):
                raise ValueError(
                    "every entry source decision must appear in dependency_decision_ids "
                    "so that an upstream correction has a mechanical invalidation trigger"
                )

        has_gap = any(
            statement.is_visible_gap
            for entry in self.entries
            for statement in entry.statements
        )
        if self.state is MilestoneState.CONFIRMED and has_gap:
            raise ValueError(
                "a map holding visible gaps cannot be CONFIRMED; use "
                "COMPLETE_WITH_GAPS so the acceptance records what was missing"
            )
        if self.state is MilestoneState.COMPLETE_WITH_GAPS and not has_gap:
            raise ValueError(
                "COMPLETE_WITH_GAPS requires at least one visible gap; otherwise "
                "the state overstates what the user was asked to accept"
            )
        if self.state is MilestoneState.INVALIDATED and not self.invalidation_reason:
            raise ValueError("an invalidated map must record why it was invalidated")
        return self


class M4CreateRequestV1(ContractModel):
    asset_id: UUID
    expected_m3_artifact_id: UUID
    expected_canonical_version_id: UUID


class M4RegenerateRequestV1(M4CreateRequestV1):
    expected_invalidated_artifact_id: UUID


class M4StatementEditV1(ContractModel):
    statement_id: UUID
    text: NonEmptyText | None = Field(default=None, max_length=1200)
    status: StatementStatus | None = None
    source_statement_ids: list[UUID] | None = None
    source_decision_ids: list[UUID] | None = None
    is_visible_gap: bool | None = None
    gap_reason: NonEmptyText | None = Field(default=None, max_length=240)


class M4EditRequestV1(ContractModel):
    asset_id: UUID
    expected_artifact_id: UUID
    edits: list[M4StatementEditV1] = Field(min_length=1)

    @model_validator(mode="after")
    def edits_target_distinct_statements(self) -> M4EditRequestV1:
        ids = [edit.statement_id for edit in self.edits]
        if len(ids) != len(set(ids)):
            raise ValueError("each statement may be edited at most once per request")
        return self


class M4AcceptRequestV1(ContractModel):
    """Explicit acceptance of the map.

    Acceptance is the only declared source of readiness. A weaker trigger — for
    instance treating "no unresolved questions" as agreement — would attach
    readiness to a card the user never said was finished, and every downstream
    relation inherits that binding.
    """

    asset_id: UUID
    expected_artifact_id: UUID
    expected_canonical_version_id: UUID
    user_action: Literal["CONFIRM", "ACCEPT_WITH_GAPS"]
    accepted_gap_statement_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def gap_acceptance_names_its_gaps(self) -> M4AcceptRequestV1:
        if self.user_action == "ACCEPT_WITH_GAPS" and not self.accepted_gap_statement_ids:
            raise ValueError(
                "accepting with gaps must name the gaps being accepted, so the "
                "record shows what the user actually agreed to leave open"
            )
        if self.user_action == "CONFIRM" and self.accepted_gap_statement_ids:
            raise ValueError(
                "CONFIRM cannot carry accepted gaps; use ACCEPT_WITH_GAPS"
            )
        if len(self.accepted_gap_statement_ids) != len(
            set(self.accepted_gap_statement_ids)
        ):
            raise ValueError("accepted gap statement IDs must be unique")
        return self


class M4ProgressV1(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: UUID
    asset_id: UUID
    sequence: int = Field(ge=0)
    stage: M4ProgressStage
    state: ProgressState
    message: NonEmptyText
    occurred_at: AwareDatetime


class M4FailureV1(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: UUID
    asset_id: UUID
    failure_code: M4FailureCode
    terminal_state: TerminalState
    retryable: bool
    safe_user_message: NonEmptyText
    last_durable_artifact_id: UUID | None = None
    occurred_at: AwareDatetime


class M4RunStatusV1(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: UUID
    asset_id: UUID
    state: ProgressState
    progress: M4ProgressV1 | None = None
    failure: M4FailureV1 | None = None


class M4EvidenceStatementV1(ContractModel):
    """Read-only projection of one canonical statement behind an insight."""

    statement_id: UUID
    text: NonEmptyText
    status: StatementStatus
    source_refs: list[str] = Field(default_factory=list)


class M4WorkspaceV1(ContractModel):
    """Composed read model for the M4 workspace.

    Evidence is included so the user can open what a lesson rests on. Without
    the drill-down they can only accept or reject a lesson on its plausibility,
    which is exactly the judgement the evidence exists to replace.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    asset_id: UUID
    canonical_version_id: UUID
    canonical_content_hash: Sha256
    map: InsightBoundaryMapV1 | None = None
    evidence_statements: list[M4EvidenceStatementV1] = Field(default_factory=list)
    run_status: M4RunStatusV1 | None = None
