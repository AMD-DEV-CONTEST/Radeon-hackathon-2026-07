"""Isolated E4/M3 contracts for the Decision and Evidence Ledger.

These contracts intentionally do not import the unmerged E3 implementation.
They bind to E3 through opaque artifact/version identifiers so preparation can
remain isolated until the E3 gate is accepted.
"""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from .enums import (
    ConfirmationState,
    EvidenceStrength,
    MilestoneState,
    ProgressState,
    StatementStatus,
    TerminalState,
)
from .models import ContractModel, NonEmptyText

M3ArtifactState = Literal[
    MilestoneState.NEEDS_INPUT,
    MilestoneState.REVIEW_READY,
    MilestoneState.CONFIRMED,
    MilestoneState.COMPLETE_WITH_GAPS,
    MilestoneState.INVALIDATED,
]
LedgerRole = Literal[
    "ALTERNATIVE",
    "REASON",
    "DECISION",
    "ACTION",
    "OBSERVED_RESULT",
]
EvidenceDisposition = Literal["SUPPORTED", "CONFLICTING", "UNRESOLVED"]
M3UserAction = Literal["CONFIRM", "MARK_UNRESOLVED"]
M3ProgressStage = Literal[
    "LOAD_CONTEXT",
    "PLAN_LEDGER",
    "VALIDATE_OUTPUT",
    "REPAIR_OUTPUT",
    "EVALUATE_TOOL_POLICY",
    "PERSIST_LEDGER",
    "VERIFY_LEDGER",
    "REPLAN",
    "TERMINAL",
]
M3FailureCode = Literal[
    "UPSTREAM_STALE",
    "INVALID_MODEL_OUTPUT",
    "STRUCTURED_REPAIR_EXHAUSTED",
    "TOOL_NOT_ALLOWLISTED",
    "INVALID_TOOL_ARGUMENTS",
    "FORGED_TOOL_PERMISSION",
    "PERMISSION_DENIED",
    "STORAGE_ERROR",
    "VERIFICATION_FAILED",
    "REPLAN_EXHAUSTED",
    "MODEL_CALL_BUDGET_EXHAUSTED",
    "MODEL_UNAVAILABLE",
    "MODEL_TIMED_OUT",
    "INTERNAL_ERROR",
]

_M3_POLICY_FAILURE_CODES = (
    "TOOL_NOT_ALLOWLISTED",
    "INVALID_TOOL_ARGUMENTS",
    "FORGED_TOOL_PERMISSION",
    "PERMISSION_DENIED",
)
_M3_INVALID_OUTPUT_FAILURE_CODES = (
    "INVALID_MODEL_OUTPUT",
    "STRUCTURED_REPAIR_EXHAUSTED",
    "REPLAN_EXHAUSTED",
    "MODEL_CALL_BUDGET_EXHAUSTED",
)
_M3_TERMINAL_FALLBACK_CODES: dict[TerminalState, M3FailureCode] = {
    TerminalState.POLICY_BLOCKED: "PERMISSION_DENIED",
    TerminalState.INVALID_MODEL_OUTPUT: "INVALID_MODEL_OUTPUT",
    TerminalState.NEEDS_USER_INPUT: "UPSTREAM_STALE",
    TerminalState.MODEL_UNAVAILABLE: "MODEL_UNAVAILABLE",
    TerminalState.TIMED_OUT: "MODEL_TIMED_OUT",
    TerminalState.STORAGE_ERROR: "STORAGE_ERROR",
    TerminalState.INTERNAL_ERROR: "INTERNAL_ERROR",
}


def public_m3_failure_code(
    terminal_state: TerminalState | str,
    finding_codes: list[str],
) -> M3FailureCode:
    """Select one stable public code without exposing Runtime-internal reason names."""

    terminal = TerminalState(terminal_state)
    allowed_for_terminal: tuple[str, ...]
    if terminal is TerminalState.POLICY_BLOCKED:
        allowed_for_terminal = _M3_POLICY_FAILURE_CODES
    elif terminal is TerminalState.INVALID_MODEL_OUTPUT:
        allowed_for_terminal = _M3_INVALID_OUTPUT_FAILURE_CODES
    elif terminal is TerminalState.NEEDS_USER_INPUT:
        allowed_for_terminal = ("UPSTREAM_STALE",)
    elif terminal is TerminalState.MODEL_UNAVAILABLE:
        allowed_for_terminal = ("MODEL_UNAVAILABLE",)
    elif terminal is TerminalState.TIMED_OUT:
        allowed_for_terminal = ("MODEL_TIMED_OUT",)
    elif terminal is TerminalState.STORAGE_ERROR:
        allowed_for_terminal = ("STORAGE_ERROR",)
    else:
        allowed_for_terminal = ("VERIFICATION_FAILED", "INTERNAL_ERROR")

    for preferred in allowed_for_terminal:
        if preferred in finding_codes:
            return cast(M3FailureCode, preferred)
    return _M3_TERMINAL_FALLBACK_CODES.get(terminal, "INTERNAL_ERROR")

REQUIRED_LEDGER_ROLES = frozenset(
    {"ALTERNATIVE", "REASON", "DECISION", "ACTION", "OBSERVED_RESULT"}
)


class M3CreateRequestV1(ContractModel):
    """Start M3 only from one exact accepted M2/canonical pair."""

    expected_m2_artifact_id: UUID
    expected_canonical_version_id: UUID


class M3RegenerateRequestV1(M3CreateRequestV1):
    """Regenerate with CAS against the exact invalidated ledger shown to the user."""

    expected_invalidated_artifact_id: UUID


class M3StatementEditV1(ContractModel):
    statement_id: UUID
    text: NonEmptyText
    user_action: M3UserAction | None = None
    unresolved_reason: NonEmptyText | None = None

    @model_validator(mode="after")
    def unresolved_reason_matches_action(self) -> M3StatementEditV1:
        if self.user_action == "MARK_UNRESOLVED" and self.unresolved_reason is None:
            raise ValueError("MARK_UNRESOLVED requires an unresolved reason")
        if self.user_action != "MARK_UNRESOLVED" and self.unresolved_reason is not None:
            raise ValueError("only MARK_UNRESOLVED may include an unresolved reason")
        return self


class M3EditRequestV1(ContractModel):
    expected_artifact_id: UUID
    statements: list[M3StatementEditV1] = Field(min_length=1)

    @model_validator(mode="after")
    def statement_ids_are_unique(self) -> M3EditRequestV1:
        ids = [statement.statement_id for statement in self.statements]
        if len(ids) != len(set(ids)):
            raise ValueError("M3 statement edit IDs must be unique")
        return self


class M3ConfirmRequestV1(ContractModel):
    expected_artifact_id: UUID
    complete_with_gaps: bool = False


class M3ProgressV1(ContractModel):
    """State-derived progress; it never invents a percentage or ETA."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    stage: M3ProgressStage
    state: ProgressState
    structured_repairs_used: int = Field(ge=0, le=2)
    structured_repair_budget: Literal[2] = 2
    replans_used: int = Field(ge=0, le=1)
    replan_budget: Literal[1] = 1
    model_calls_used: int = Field(ge=0, le=4)
    model_call_budget: Literal[4] = 4
    last_durable_artifact_id: UUID | None = None
    safe_message: NonEmptyText
    occurred_at: AwareDatetime
    terminal_state: TerminalState | None = None

    @model_validator(mode="after")
    def progress_matches_terminal_and_budget_state(self) -> M3ProgressV1:
        is_terminal = self.state is ProgressState.TERMINAL
        if is_terminal != (self.terminal_state is not None):
            raise ValueError(
                "terminal_state must be present exactly when M3 progress is TERMINAL"
            )
        if is_terminal != (self.stage == "TERMINAL"):
            raise ValueError("TERMINAL progress state and stage must agree")
        minimum_calls = self.structured_repairs_used + self.replans_used
        if self.model_calls_used < minimum_calls:
            raise ValueError("repair/re-plan progress cannot exceed model-call evidence")
        return self


class M3FailureV1(ContractModel):
    """Stable public failure contract without raw prompt/tool/private payloads."""

    code: M3FailureCode
    terminal_state: TerminalState
    retryable: bool
    safe_user_message: NonEmptyText
    recovery_action: NonEmptyText
    finding_codes: list[str] = Field(min_length=1)
    occurred_at: AwareDatetime

    @model_validator(mode="after")
    def code_matches_terminal_state(self) -> M3FailureV1:
        policy_codes = {
            "TOOL_NOT_ALLOWLISTED",
            "INVALID_TOOL_ARGUMENTS",
            "FORGED_TOOL_PERMISSION",
            "PERMISSION_DENIED",
        }
        invalid_output_codes = {
            "INVALID_MODEL_OUTPUT",
            "STRUCTURED_REPAIR_EXHAUSTED",
            "REPLAN_EXHAUSTED",
            "MODEL_CALL_BUDGET_EXHAUSTED",
        }
        expected = (
            TerminalState.POLICY_BLOCKED
            if self.code in policy_codes
            else TerminalState.INVALID_MODEL_OUTPUT
            if self.code in invalid_output_codes
            else TerminalState.NEEDS_USER_INPUT
            if self.code == "UPSTREAM_STALE"
            else TerminalState.MODEL_UNAVAILABLE
            if self.code == "MODEL_UNAVAILABLE"
            else TerminalState.TIMED_OUT
            if self.code == "MODEL_TIMED_OUT"
            else TerminalState.STORAGE_ERROR
            if self.code == "STORAGE_ERROR"
            else TerminalState.INTERNAL_ERROR
        )
        if self.terminal_state is not expected:
            raise ValueError(f"{self.code} must map to terminal state {expected.value}")
        return self


class M3RunStatusV1(ContractModel):
    run_id: UUID
    terminal_state: TerminalState
    code: str
    safe_user_message: NonEmptyText
    recovery_action: NonEmptyText
    finding_codes: list[str]
    structured_repairs_used: int = Field(ge=0, le=2)
    replans_used: int = Field(ge=0, le=1)
    model_calls_used: int = Field(ge=0, le=4)


class LedgerStatementV1(ContractModel):
    """One material statement with explicit provenance and evidence status."""

    # Stable canonical Statement.statement_id; upstream evidence IDs stay separate.
    statement_id: UUID
    role: LedgerRole
    text: NonEmptyText
    status: StatementStatus
    evidence_disposition: EvidenceDisposition
    evidence_strength: EvidenceStrength
    confirmation: ConfirmationState = ConfirmationState.UNCONFIRMED
    confirmed_at: AwareDatetime | None = None
    source_moment_ids: list[UUID] = Field(min_length=1)
    source_statement_ids: list[UUID] = Field(default_factory=list)
    derived_from_statement_ids: list[UUID] = Field(default_factory=list)
    unresolved_reason: NonEmptyText | None = None

    @model_validator(mode="after")
    def evidence_and_trust_boundaries_hold(self) -> LedgerStatementV1:
        identity_lists = (
            ("source moment IDs", self.source_moment_ids),
            ("source statement IDs", self.source_statement_ids),
            ("derived statement IDs", self.derived_from_statement_ids),
        )
        for label, values in identity_lists:
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must be unique")

        if self.evidence_disposition == "SUPPORTED":
            confirmed_self_report = (
                self.status is StatementStatus.USER_JUDGMENT
                and self.confirmation is ConfirmationState.CONFIRMED
                and self.evidence_strength is EvidenceStrength.SELF_REPORTED
            )
            if (
                not self.source_statement_ids
                and not self.derived_from_statement_ids
                and not confirmed_self_report
            ):
                raise ValueError("SUPPORTED material statement requires evidence references")
            if self.evidence_strength is EvidenceStrength.NONE:
                raise ValueError("SUPPORTED material statement requires evidence strength")
            if self.unresolved_reason is not None:
                raise ValueError("SUPPORTED material statement cannot carry unresolved_reason")
        elif self.evidence_disposition == "CONFLICTING":
            if len(self.source_statement_ids) < 2:
                raise ValueError("CONFLICTING evidence requires at least two source statements")
            if self.evidence_strength is EvidenceStrength.NONE:
                raise ValueError("CONFLICTING evidence requires evidence strength")
            if self.unresolved_reason is None:
                raise ValueError("CONFLICTING evidence requires an unresolved reason")
        else:
            if self.status is not StatementStatus.UNRESOLVED:
                raise ValueError("UNRESOLVED evidence requires UNRESOLVED statement status")
            if self.evidence_strength is not EvidenceStrength.NONE:
                raise ValueError("UNRESOLVED evidence must use NONE evidence strength")
            if self.unresolved_reason is None:
                raise ValueError("UNRESOLVED evidence requires an unresolved reason")

        if self.status is StatementStatus.SOURCE_FACT and not self.source_statement_ids:
            raise ValueError("SOURCE_FACT requires source statement references")
        if self.status is StatementStatus.AGENT_INFERENCE and not (
            self.derived_from_statement_ids or self.source_statement_ids
        ):
            raise ValueError("AGENT_INFERENCE requires explicit derivation references")
        if self.status is StatementStatus.USER_JUDGMENT and (
            self.confirmation is not ConfirmationState.CONFIRMED
        ):
            raise ValueError("USER_JUDGMENT requires trusted user confirmation")

        if self.confirmation is ConfirmationState.CONFIRMED:
            if self.confirmed_at is None:
                raise ValueError("CONFIRMED statement requires confirmed_at")
        elif self.confirmed_at is not None:
            raise ValueError("only CONFIRMED statement may carry confirmed_at")
        return self


class DecisionLedgerEntryV1(ContractModel):
    decision_id: UUID
    title: NonEmptyText
    source_moment_ids: list[UUID] = Field(min_length=1)
    statements: list[LedgerStatementV1] = Field(min_length=5)

    @model_validator(mode="after")
    def entry_is_complete_or_explicitly_unresolved(self) -> DecisionLedgerEntryV1:
        if len(self.source_moment_ids) != len(set(self.source_moment_ids)):
            raise ValueError("entry source moment IDs must be unique")

        statement_ids = [
            statement.statement_id for statement in self.statements
        ]
        if len(statement_ids) != len(set(statement_ids)):
            raise ValueError("ledger statement IDs must be unique within an entry")

        entry_moments = set(self.source_moment_ids)
        if any(
            not set(statement.source_moment_ids).issubset(entry_moments)
            for statement in self.statements
        ):
            raise ValueError("statement source moments must belong to the ledger entry")

        roles = {statement.role for statement in self.statements}
        missing = REQUIRED_LEDGER_ROLES - roles
        if missing:
            raise ValueError(
                "ledger entry must represent every required role; use an explicit "
                f"UNRESOLVED statement for missing source content: {sorted(missing)}"
            )
        if sum(statement.role == "DECISION" for statement in self.statements) != 1:
            raise ValueError("ledger entry requires exactly one DECISION statement")
        return self


class DecisionEvidenceLedgerV1(ContractModel):
    """Editable M3 artifact bound to one exact accepted M2 state."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    artifact_id: UUID
    asset_id: UUID
    base_m2_artifact_id: UUID
    base_canonical_version_id: UUID
    generated_by_run_id: UUID
    state: M3ArtifactState
    entries: list[DecisionLedgerEntryV1] = Field(min_length=1)
    dependency_moment_ids: list[UUID] = Field(min_length=1)
    dependency_statement_ids: list[UUID] = Field(min_length=0)
    unresolved_question_ids: list[UUID]
    created_at: AwareDatetime
    updated_at: AwareDatetime
    invalidated_by_m2_artifact_id: UUID | None
    invalidated_by_canonical_version_id: UUID | None
    invalidation_reason: NonEmptyText | None
    affected_entry_ids: list[UUID] = Field(default_factory=list)
    affected_dependency_refs: list[str] = Field(default_factory=list)
    reusable_entry_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def ledger_invariants_hold(self) -> DecisionEvidenceLedgerV1:
        for label, values in (
            ("dependency moment IDs", self.dependency_moment_ids),
            ("dependency statement IDs", self.dependency_statement_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must be unique")

        decision_ids = [entry.decision_id for entry in self.entries]
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("ledger decision IDs must be unique")
        ledger_statement_ids = [
            statement.statement_id
            for entry in self.entries
            for statement in entry.statements
        ]
        if len(ledger_statement_ids) != len(set(ledger_statement_ids)):
            raise ValueError("ledger statement IDs must be unique across the ledger")

        dependency_moments = set(self.dependency_moment_ids)
        dependency_statements = set(self.dependency_statement_ids)
        if any(
            not set(entry.source_moment_ids).issubset(dependency_moments)
            for entry in self.entries
        ):
            raise ValueError("entry moments must be declared ledger dependencies")
        if any(
            not set(statement.source_statement_ids).issubset(dependency_statements)
            or not set(statement.derived_from_statement_ids).issubset(
                dependency_statements
            )
            for entry in self.entries
            for statement in entry.statements
        ):
            raise ValueError("statement evidence must be declared ledger dependencies")

        statements = [
            statement for entry in self.entries for statement in entry.statements
        ]
        gaps = [
            statement
            for statement in statements
            if statement.evidence_disposition in {"CONFLICTING", "UNRESOLVED"}
        ]
        unconfirmed = [
            statement
            for statement in statements
            if statement.evidence_disposition != "UNRESOLVED"
            and statement.confirmation is not ConfirmationState.CONFIRMED
        ]
        if self.state is MilestoneState.CONFIRMED and (gaps or unconfirmed):
            raise ValueError("CONFIRMED ledger cannot contain gaps or unconfirmed statements")
        if self.state is MilestoneState.COMPLETE_WITH_GAPS:
            if not gaps:
                raise ValueError("COMPLETE_WITH_GAPS requires a visible gap")
            if unconfirmed:
                raise ValueError(
                    "COMPLETE_WITH_GAPS requires all supported statements to be confirmed"
                )

        invalidation_fields = (
            self.invalidated_by_m2_artifact_id,
            self.invalidated_by_canonical_version_id,
            self.invalidation_reason,
        )
        if self.state is MilestoneState.INVALIDATED:
            if any(value is None for value in invalidation_fields):
                raise ValueError("INVALIDATED ledger requires complete invalidation provenance")
            if self.invalidated_by_m2_artifact_id == self.base_m2_artifact_id:
                raise ValueError("invalidation requires a new M2 artifact")
            if self.invalidated_by_canonical_version_id == self.base_canonical_version_id:
                raise ValueError("invalidation requires a new canonical version")
            entry_ids = set(decision_ids)
            if not self.affected_entry_ids or not set(self.affected_entry_ids).issubset(entry_ids):
                raise ValueError("invalidation requires valid affected entry IDs")
            if not set(self.reusable_entry_ids).issubset(entry_ids):
                raise ValueError("reusable entry IDs must belong to the ledger")
            if set(self.affected_entry_ids) & set(self.reusable_entry_ids):
                raise ValueError("affected and reusable entries must be disjoint")
        elif any(value is not None for value in invalidation_fields):
            raise ValueError("only INVALIDATED ledger may carry invalidation provenance")
        elif self.affected_entry_ids or self.affected_dependency_refs or self.reusable_entry_ids:
            raise ValueError("only INVALIDATED ledger may carry selective invalidation details")
        return self


class M3EvidenceMomentV1(ContractModel):
    """Readable, stable M2 evidence exposed for ledger review."""

    moment_id: UUID
    title: NonEmptyText
    description: NonEmptyText


class M3EvidenceStatementV1(ContractModel):
    """Readable canonical statement plus human-facing source labels."""

    statement_id: UUID
    text: NonEmptyText
    source_labels: list[NonEmptyText] = Field(default_factory=list)


class M3WorkspaceV1(ContractModel):
    artifact: DecisionEvidenceLedgerV1
    is_current: bool
    history_artifact_ids: list[UUID]
    evidence_moments: list[M3EvidenceMomentV1]
    evidence_statements: list[M3EvidenceStatementV1]
    progress: M3ProgressV1
    latest_failure: M3FailureV1 | None = None
    allowed_actions: list[Literal["EDIT", "CONFIRM", "REGENERATE"]]

    @model_validator(mode="after")
    def workspace_actions_match_current_and_failure_state(self) -> M3WorkspaceV1:
        invalid = self.artifact.state is MilestoneState.INVALIDATED
        if invalid == self.is_current:
            raise ValueError("invalidated M3 artifact cannot be presented as current")
        if invalid and self.allowed_actions != ["REGENERATE"]:
            raise ValueError("invalidated M3 workspace allows only REGENERATE")
        moment_ids = {item.moment_id for item in self.evidence_moments}
        statement_ids = {item.statement_id for item in self.evidence_statements}
        if len(moment_ids) != len(self.evidence_moments):
            raise ValueError("M3 workspace evidence moment IDs must be unique")
        if len(statement_ids) != len(self.evidence_statements):
            raise ValueError("M3 workspace evidence statement IDs must be unique")
        if not set(self.artifact.dependency_moment_ids).issubset(moment_ids):
            raise ValueError("M3 workspace must expose every referenced evidence moment")
        if not set(self.artifact.dependency_statement_ids).issubset(statement_ids):
            raise ValueError("M3 workspace must expose every referenced evidence statement")
        if (
            self.latest_failure is not None
            and self.progress.terminal_state is not self.latest_failure.terminal_state
        ):
            raise ValueError("workspace failure must match terminal progress")
        return self
