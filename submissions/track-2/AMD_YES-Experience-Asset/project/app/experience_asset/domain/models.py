"""Strict canonical Experience Asset and runtime contracts."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)

from .enums import (
    ApprovalScope,
    AssetLifecycle,
    ConfirmationState,
    EvidenceStrength,
    ExportFormat,
    ExportState,
    FindingSeverity,
    Milestone,
    MilestoneState,
    PlanStepKind,
    PlanStepStatus,
    PolicyOutcome,
    PrivacyResolution,
    ProgressState,
    QuestionState,
    RetrievalScope,
    ReviewStatus,
    RouteEligibility,
    RouteType,
    SourceAuthorship,
    SourceKind,
    StatementStatus,
    TerminalState,
    ToolExecutionStatus,
    VerificationOutcome,
)

NonEmptyText = Annotated[str, Field(min_length=1)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ContractModel(BaseModel):
    """Base for persisted/public contracts: unknown fields are always rejected."""

    model_config = ConfigDict(extra="forbid")


class SourceSpan(ContractModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    message_id: str | None = None

    @model_validator(mode="after")
    def end_must_follow_start(self) -> SourceSpan:
        if self.end <= self.start:
            raise ValueError("source span end must be greater than start")
        return self


class SourceReference(ContractModel):
    source_id: UUID
    kind: SourceKind
    display_label: NonEmptyText
    original_file_name: str | None = None
    source_hash: Sha256
    local_storage_ref: str | None = None
    source_url: str | None = None
    adapted_provenance_notice: str | None = None
    span: SourceSpan | None = None
    ingested_at: AwareDatetime
    authorship: SourceAuthorship


class Statement(ContractModel):
    statement_id: UUID
    text: NonEmptyText
    status: StatementStatus
    source_refs: list[UUID] = Field(default_factory=list)
    derived_from: list[UUID] = Field(default_factory=list)
    confirmation: ConfirmationState = ConfirmationState.UNCONFIRMED
    evidence_strength: EvidenceStrength = EvidenceStrength.NONE
    sensitivity_tags: list[str] = Field(default_factory=list)
    created_in_version: UUID
    last_changed_in_version: UUID

    @model_validator(mode="after")
    def evidence_requirements(self) -> Statement:
        if self.status is StatementStatus.SOURCE_FACT and not self.source_refs:
            raise ValueError("SOURCE_FACT requires at least one source reference")
        if self.status is StatementStatus.AGENT_INFERENCE and not self.derived_from:
            raise ValueError("material AGENT_INFERENCE requires derived_from")
        return self


class CriticalMoment(ContractModel):
    moment_id: UUID
    order: int = Field(ge=0)
    title: NonEmptyText
    description: NonEmptyText
    cue_statement_ids: list[UUID] = Field(default_factory=list)
    change_statement_ids: list[UUID] = Field(default_factory=list)
    surprise_statement_ids: list[UUID] = Field(default_factory=list)
    conflict_statement_ids: list[UUID] = Field(default_factory=list)


class DecisionRecord(ContractModel):
    decision_id: UUID
    summary: NonEmptyText
    decision_statement_ids: list[UUID] = Field(default_factory=list)
    alternative_statement_ids: list[UUID] = Field(default_factory=list)
    reason_statement_ids: list[UUID] = Field(default_factory=list)
    action_statement_ids: list[UUID] = Field(default_factory=list)
    result_statement_ids: list[UUID] = Field(default_factory=list)
    evidence_statement_ids: list[UUID] = Field(default_factory=list)


class InsightRecord(ContractModel):
    insight_id: UUID
    lesson: NonEmptyText
    support_statement_ids: list[UUID] = Field(default_factory=list)
    counterfactual_statement_ids: list[UUID] = Field(default_factory=list)
    limitation_statement_ids: list[UUID] = Field(default_factory=list)
    counterexample_statement_ids: list[UUID] = Field(default_factory=list)
    applicability_statement_ids: list[UUID] = Field(default_factory=list)


class QuestionRecord(ContractModel):
    question_id: UUID
    question: NonEmptyText
    why_it_matters: NonEmptyText
    milestone: Milestone
    affected_statement_ids: list[UUID] = Field(default_factory=list)
    priority_inputs: dict[str, JsonValue] = Field(default_factory=dict)
    state: QuestionState = QuestionState.OPEN
    answer_source_id: UUID | None = None
    answer_statement_id: UUID | None = None
    created_by_run_id: UUID
    created_in_version_id: UUID
    resolved_by_run_id: UUID | None = None
    resolved_in_version_id: UUID | None = None


class MilestoneArtifact(ContractModel):
    artifact_id: UUID
    artifact_type: NonEmptyText
    asset_id: UUID
    version_id: UUID
    milestone: Milestone
    state: MilestoneState
    statement_ids: list[UUID] = Field(default_factory=list)
    unresolved_question_ids: list[UUID] = Field(default_factory=list)
    generated_by_run_id: UUID
    user_review_status: ReviewStatus = ReviewStatus.NOT_REVIEWED
    created_at: AwareDatetime
    updated_at: AwareDatetime
    invalidated_by_version_id: UUID | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class RouteDecision(ContractModel):
    route: RouteType
    eligibility: RouteEligibility
    reason_codes: list[str] = Field(default_factory=list)
    explanation: NonEmptyText
    supporting_statement_ids: list[UUID] = Field(default_factory=list)
    missing_statement_ids: list[UUID] = Field(default_factory=list)
    canonical_version_id: UUID
    policy_version: NonEmptyText
    model_run_id: UUID | None = None

    @model_validator(mode="after")
    def non_eligible_routes_need_reason(self) -> RouteDecision:
        if (
            self.eligibility in {RouteEligibility.INELIGIBLE, RouteEligibility.BLOCKED}
            and not self.reason_codes
        ):
            raise ValueError("ineligible or blocked route requires reason_codes")
        return self


class PrivacyFinding(ContractModel):
    finding_id: UUID
    category: NonEmptyText
    affected_statement_ids: list[UUID] = Field(default_factory=list)
    affected_source_ids: list[UUID] = Field(default_factory=list)
    severity: FindingSeverity
    explanation: NonEmptyText
    proposed_actions: list[str] = Field(default_factory=list)
    resolution: PrivacyResolution = PrivacyResolution.OPEN
    created_by_run_id: UUID
    resolved_by_run_id: UUID | None = None


class RouteDraft(ContractModel):
    route_draft_id: UUID
    route: RouteType
    language: Literal["zh-CN", "en"]
    canonical_version_id: UUID
    statement_ids: list[UUID]
    content_hash: Sha256
    created_by_run_id: UUID


RETIRED_RELATION_FIELDS: frozenset[str] = frozenset(
    {
        "related_assets",
        "knowledge_card_readiness",
        "relation_candidates",
        "relation_candidate_decisions",
    }
)
"""Snapshot fields that moved to the sidecar relation ledger.

Named once so the read-path shim and its tests cannot drift apart on which
fields are tolerated.
"""


# Relation state — readiness, related-asset links, candidates and decisions —
# no longer lives on the Experience Asset snapshot. It moved to the sidecar
# relation ledger in `domain/relation.py`, which is the sole persistence
# authority for it.
#
# The snapshot is immutable and content-hashed, so persisting a confirmation
# here would append a new asset content version and change the content hash,
# while GRAG-14 requires that hash to be identical before and after a relation
# read. The two requirements cannot both hold.
#
# Readiness moved for a second reason: it is created by an explicit user action
# after a version exists, so storing it needs a new version, which would leave
# the version recording readiness permanently one step ahead of the version
# judged ready — or self-referential if it points at itself.
#
# `relation.RelationWorkspaceV1` composes the same information read-only for API
# consumers. Those views are never serialized back into the snapshot, so a
# relation read cannot change the snapshot JSON or its content hash.


class ApprovalRecord(ContractModel):
    approval_id: UUID
    scope: ApprovalScope = ApprovalScope.SHAREABLE_EXPORT
    user_action: NonEmptyText
    approved_at: AwareDatetime
    asset_id: UUID
    version_id: UUID
    route: RouteType
    language: Literal["zh-CN", "en"]
    route_draft_hash: Sha256
    privacy_review_hash: Sha256
    finding_resolutions: dict[str, PrivacyResolution]


class ExportRecord(ContractModel):
    export_id: UUID
    asset_id: UUID
    version_id: UUID
    route: RouteType
    route_draft_hash: Sha256
    format: ExportFormat
    file_hash: Sha256
    path: NonEmptyText
    created_at: AwareDatetime
    state: ExportState


class VersionLineage(ContractModel):
    version_id: UUID
    parent_version_id: UUID | None = None
    schema_version: Literal["1.0.0"] = "1.0.0"
    change_kind: NonEmptyText
    change_reason: NonEmptyText
    created_at: AwareDatetime
    derived_by_run_id: UUID | None = None


class ExperienceAssetV1(ContractModel):
    """Complete canonical JSON snapshot stored for each immutable version."""

    asset_id: UUID
    version_id: UUID
    schema_version: Literal["1.0.0"] = "1.0.0"
    lifecycle: AssetLifecycle = AssetLifecycle.ACTIVE
    current_milestone: Milestone = Milestone.M1
    created_at: AwareDatetime
    updated_at: AwareDatetime
    sources: list[SourceReference] = Field(default_factory=list)
    context: str = ""
    goal: str = ""
    constraints: list[str] = Field(default_factory=list)
    user_intent: str = ""
    statements: list[Statement] = Field(default_factory=list)
    critical_moments: list[CriticalMoment] = Field(default_factory=list)
    decisions: list[DecisionRecord] = Field(default_factory=list)
    insights: list[InsightRecord] = Field(default_factory=list)
    unresolved_questions: list[QuestionRecord] = Field(default_factory=list)
    milestone_states: dict[Milestone, MilestoneState]
    milestone_artifacts: list[MilestoneArtifact] = Field(default_factory=list)
    route_decisions: list[RouteDecision]
    privacy_findings: list[PrivacyFinding] = Field(default_factory=list)
    route_drafts: list[RouteDraft] = Field(default_factory=list)
    approvals: list[ApprovalRecord] = Field(default_factory=list)
    exports: list[ExportRecord] = Field(default_factory=list)
    lineage: VersionLineage
    derivation_metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def drop_retired_relation_fields(cls, data: Any) -> Any:
        """Load snapshots written before relation state moved to the ledger.

        Every snapshot persisted before that change carries the four retired
        keys, and `ContractModel` forbids unknown fields — so without this the
        upgrade would make all existing accepted history unreadable.

        Rewriting the stored JSON instead is not an option: `content_hash` is
        computed from the snapshot, so stripping keys on disk would either
        change every version's hash or leave the stored hash disagreeing with
        its content, and accepted history must never be rewritten.

        Empty values are dropped silently because nothing is lost: no code path
        ever populated these fields, so every historical row holds the declared
        defaults. A non-empty value is a different situation — silently
        discarding real relation state is precisely the data loss this shim
        exists to prevent, and it would be undetectable afterwards, so it fails
        loudly instead. Recovering such a row means projecting its relation
        state into the ledger first.
        """
        if not isinstance(data, dict):
            return data
        present = [field for field in RETIRED_RELATION_FIELDS if field in data]
        if not present:
            return data

        # Every check runs before anything is removed, and removal happens on a
        # copy. Popping from the caller's dict would make validation
        # non-idempotent: a rejected payload would come back stripped, so a
        # retry or a second validator would see different data than the caller
        # passed, and the populated fields this branch exists to protect would
        # be gone from the object a log or a later migration reads.
        # Only the exact pre-E5 defaults are droppable. Testing truthiness
        # instead would silently swallow `{}`, `""`, `False` and `0` — malformed
        # values that are not the old shape at all, so accepting them hides a
        # corrupt snapshot behind a compatibility path meant for a known shape.
        populated: list[str] = []
        malformed: list[str] = []
        for field in present:
            value = data[field]
            if field == "knowledge_card_readiness":
                if value is None:
                    continue
                if isinstance(value, dict):
                    populated.append(field)
                else:
                    malformed.append(field)
                continue
            if value == [] and isinstance(value, list):
                continue
            if isinstance(value, list):
                populated.append(field)
            else:
                malformed.append(field)
        if malformed:
            raise ValueError(
                f"retired fields {sorted(malformed)} hold values that are not the "
                "pre-E5 shape; the snapshot is malformed rather than merely old, "
                "and dropping them would hide that"
            )
        if populated:
            raise ValueError(
                "snapshot carries relation state in retired fields "
                f"{sorted(populated)}; that state now lives in the relation "
                "ledger and must be projected there before the snapshot can be "
                "read, rather than being dropped"
            )
        return {
            key: value
            for key, value in data.items()
            if key not in RETIRED_RELATION_FIELDS
        }

    @model_validator(mode="after")
    def validate_snapshot_integrity(self) -> ExperienceAssetV1:
        if self.version_id != self.lineage.version_id:
            raise ValueError("snapshot version_id must match lineage version_id")
        if set(self.milestone_states) != set(Milestone):
            raise ValueError("milestone_states must contain exactly M1 through M5")
        routes = [decision.route for decision in self.route_decisions]
        if len(routes) != len(set(routes)) or set(routes) != set(RouteType):
            raise ValueError("route_decisions must contain each of the five routes exactly once")

        source_ids = {source.source_id for source in self.sources}
        statement_ids = {statement.statement_id for statement in self.statements}
        if len(statement_ids) != len(self.statements):
            raise ValueError("statement IDs must be unique")
        for statement in self.statements:
            if not set(statement.source_refs).issubset(source_ids):
                raise ValueError(f"statement {statement.statement_id} references an unknown source")
            if not set(statement.derived_from).issubset(statement_ids):
                raise ValueError(
                    f"statement {statement.statement_id} derives from an unknown statement"
                )
        for artifact in self.milestone_artifacts:
            if artifact.asset_id != self.asset_id:
                raise ValueError("milestone artifact asset_id does not match snapshot")
            if not set(artifact.statement_ids).issubset(statement_ids):
                raise ValueError("milestone artifact references an unknown statement")
        for decision in self.decisions:
            references = (
                decision.decision_statement_ids
                + decision.alternative_statement_ids
                + decision.reason_statement_ids
                + decision.action_statement_ids
                + decision.result_statement_ids
                + decision.evidence_statement_ids
            )
            if not set(references).issubset(statement_ids):
                raise ValueError("decision references an unknown canonical statement")
        return self


class ProgressEventV1(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    event_id: UUID
    run_id: UUID
    asset_id: UUID | None = None
    version_id: UUID | None = None
    sequence: int = Field(ge=0)
    stage: NonEmptyText
    state: ProgressState
    percent: float | None = Field(default=None, ge=0, le=100)
    percent_basis: Literal["milestones_done/milestones_total"] | None = None
    milestones_done: int | None = Field(default=None, ge=0)
    milestones_total: int | None = Field(default=None, gt=0)
    internal_completed_units: int | None = Field(default=None, ge=0)
    internal_total_units: int | None = Field(default=None, gt=0)
    eta_seconds: float | None = Field(default=None, ge=0)
    eta_basis: str | None = None
    eta_history_sample_size: int | None = Field(default=None, ge=0)
    message: NonEmptyText
    occurred_at: AwareDatetime
    terminal_state: TerminalState | None = None

    @model_validator(mode="after")
    def progress_is_state_derived(self) -> ProgressEventV1:
        if self.percent is None:
            if any(
                value is not None
                for value in (
                    self.percent_basis,
                    self.milestones_done,
                    self.milestones_total,
                )
            ):
                raise ValueError("indeterminate progress must omit public percentage basis fields")
        else:
            if self.percent_basis != "milestones_done/milestones_total":
                raise ValueError("percent requires the frozen milestone-count basis")
            if self.milestones_done is None or self.milestones_total is None:
                raise ValueError("percent requires milestones_done and milestones_total")
            if self.milestones_done > self.milestones_total:
                raise ValueError("milestones_done cannot exceed milestones_total")
            expected = round(100 * self.milestones_done / self.milestones_total)
            if abs(self.percent - expected) > 1:
                raise ValueError("percent must be derived from milestone counts")
        if (
            self.internal_completed_units is not None
            and self.internal_total_units is not None
            and self.internal_completed_units > self.internal_total_units
        ):
            raise ValueError("internal completed units cannot exceed internal total units")
        if self.eta_seconds is not None and (
            not self.eta_basis
            or self.eta_history_sample_size is None
            or self.eta_history_sample_size < 3
        ):
            raise ValueError("ETA requires a named basis and at least three comparable runs")
        if (self.state is ProgressState.TERMINAL) != (self.terminal_state is not None):
            raise ValueError("terminal_state must be present exactly when state is TERMINAL")
        return self


class WorkPlanStepV1(ContractModel):
    step_id: UUID
    step_kind: PlanStepKind
    reason: NonEmptyText
    dependency_step_ids: list[UUID] = Field(default_factory=list)
    required_evidence_refs: list[str] = Field(default_factory=list)
    required_permission: str | None = None
    status: PlanStepStatus = PlanStepStatus.PENDING
    stop_condition: NonEmptyText


class WorkPlanV1(ContractModel):
    plan_id: UUID
    run_id: UUID
    milestone: Milestone
    goal: NonEmptyText
    steps: list[WorkPlanStepV1] = Field(min_length=1, max_length=12)
    revision: int = Field(ge=1)
    created_at: AwareDatetime
    revised_at: AwareDatetime

    @model_validator(mode="after")
    def dependencies_must_be_prior_plan_steps(self) -> WorkPlanV1:
        known: set[UUID] = set()
        for step in self.steps:
            if not set(step.dependency_step_ids).issubset(known):
                raise ValueError("plan steps may depend only on earlier steps")
            known.add(step.step_id)
        return self


class RetrievedEvidenceReference(ContractModel):
    retrieval_id: UUID
    scope: RetrievalScope
    asset_id: UUID
    version_id: UUID | None = None
    source_id: UUID | None = None
    span_id: str | None = None
    related_asset_id: UUID | None = None
    provenance_ref: NonEmptyText
    content_hash: Sha256
    no_match: bool = False


class RuntimeToolCallProposal(ContractModel):
    proposal_id: UUID
    name: NonEmptyText
    arguments: dict[str, JsonValue]
    base_version_id: UUID
    knowledge_card_version_id: UUID | None = None
    knowledge_card_hash: Sha256 | None = None
    proposed_at: AwareDatetime
    permission_granted: Literal[False] = False

    @model_validator(mode="after")
    def knowledge_card_binding_is_complete(self) -> RuntimeToolCallProposal:
        if (self.knowledge_card_version_id is None) != (
            self.knowledge_card_hash is None
        ):
            raise ValueError(
                "Knowledge Card proposal binding requires both version and hash"
            )
        return self


class ConfirmedRelationBinding(ContractModel):
    """One exact user-confirmed relation-to-asset access binding."""

    relation_id: UUID
    related_asset_id: UUID


class PolicyDecision(ContractModel):
    decision_id: UUID
    run_id: UUID
    proposal_id: UUID
    outcome: PolicyOutcome
    reason_codes: list[str] = Field(min_length=1)
    policy_version: NonEmptyText
    decided_at: AwareDatetime


class ToolExecutionRecord(ContractModel):
    execution_id: UUID
    run_id: UUID
    proposal_id: UUID
    policy_decision_id: UUID
    tool_name: NonEmptyText
    sanitized_argument_hash: Sha256
    status: ToolExecutionStatus
    observation_refs: list[str] = Field(default_factory=list)
    error_class: str | None = None
    started_at: AwareDatetime
    finished_at: AwareDatetime


class VerificationReport(ContractModel):
    verification_id: UUID
    run_id: UUID
    execution_id: UUID | None = None
    outcome: VerificationOutcome
    checks: dict[str, bool]
    finding_codes: list[str] = Field(default_factory=list)
    safe_summary: NonEmptyText
    verified_at: AwareDatetime


class AgentRunStateV1(ContractModel):
    """Per-run agent state.

    The relation fields below are a **read-only permission snapshot**, projected
    from the relation ledger at each policy evaluation — the same pattern as
    `permission_snapshot`. They are never the authority for relation state.

    Treating them as authoritative fails in two ways. Two concurrent runs on one
    asset would hold independent relation sets with no reconciliation, so
    whichever wrote last would win. Worse, a long-running run would keep
    authorizing detail reads from a set projected before the user corrected a
    bound asset — the exact stale access GRAG-16 exists to catch. Re-projecting
    at each evaluation keeps the permission decision tied to current canonical
    state.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: UUID
    asset_id: UUID
    base_version_id: UUID
    command_id: UUID
    user_goal: NonEmptyText
    acceptance_checks: list[str] = Field(min_length=1)
    permission_snapshot: dict[str, bool]
    current_milestone: Milestone
    work_plan: WorkPlanV1
    retrieval_scope: RetrievalScope
    knowledge_card_version_id: UUID | None = None
    knowledge_card_hash: Sha256 | None = None
    relation_candidate_ids: list[UUID] = Field(default_factory=list)
    confirmed_relation_ids: list[UUID] = Field(default_factory=list)
    confirmed_relation_source_candidate_ids: list[UUID] = Field(default_factory=list)
    confirmed_related_asset_ids: list[UUID] = Field(default_factory=list)
    confirmed_relation_bindings: list[ConfirmedRelationBinding] = Field(
        default_factory=list
    )
    retrieved_evidence: list[RetrievedEvidenceReference] = Field(default_factory=list)
    tool_proposals: list[RuntimeToolCallProposal] = Field(default_factory=list)
    policy_decisions: list[PolicyDecision] = Field(default_factory=list)
    tool_executions: list[ToolExecutionRecord] = Field(default_factory=list)
    structured_proposal_hash: Sha256 | None = None
    validation_findings: list[str] = Field(default_factory=list)
    verification_report: VerificationReport | None = None
    step_budget: int = Field(gt=0)
    model_call_budget: int = Field(gt=0)
    retry_budget: int = Field(ge=0)
    steps_used: int = Field(ge=0)
    model_calls_used: int = Field(ge=0)
    retries_used: int = Field(ge=0)
    model_id: NonEmptyText
    server_base_url: NonEmptyText
    last_durable_version_id: UUID
    terminal_state: TerminalState | None = None
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def budgets_and_retrieval_scope_hold(self) -> AgentRunStateV1:
        if self.work_plan.run_id != self.run_id:
            raise ValueError("work plan must belong to the Agent run")
        if self.steps_used > self.step_budget:
            raise ValueError("step budget exceeded")
        if self.model_calls_used > self.model_call_budget:
            raise ValueError("model-call budget exceeded")
        if self.retries_used > self.retry_budget:
            raise ValueError("retry budget exceeded")
        if (self.knowledge_card_version_id is None) != (
            self.knowledge_card_hash is None
        ):
            raise ValueError("Knowledge Card readiness requires both version and hash")
        if (
            self.knowledge_card_version_id is not None
            and self.knowledge_card_version_id != self.base_version_id
        ):
            raise ValueError("Knowledge Card readiness is stale for the base version")
        if (
            self.relation_candidate_ids
            or self.confirmed_relation_ids
            or self.confirmed_related_asset_ids
            or self.confirmed_relation_bindings
        ) and self.knowledge_card_version_id is None:
            raise ValueError(
                "relation candidates and confirmations require current card readiness"
            )
        # A confirmed relation carries its own identifier plus a reference to
        # the candidate it came from, so relation IDs are not candidate IDs and
        # a subset check between them would reject every valid confirmation.
        # Checking the *source candidate* preserves the original intent —
        # nothing can be confirmed which was never proposed in this run.
        if len(self.confirmed_relation_source_candidate_ids) != len(
            self.confirmed_relation_ids
        ):
            raise ValueError(
                "every confirmed relation must name the candidate it came from"
            )
        if not set(self.confirmed_relation_source_candidate_ids).issubset(
            set(self.relation_candidate_ids)
        ):
            raise ValueError(
                "a confirmed relation must originate from a candidate proposed in "
                "this run"
            )
        if set(self.confirmed_relation_ids) & set(self.relation_candidate_ids):
            raise ValueError(
                "relation IDs and candidate IDs are distinct identifier spaces; "
                "reusing one as the other hides which object a binding refers to"
            )
        if bool(self.confirmed_relation_ids) != bool(
            self.confirmed_related_asset_ids
        ):
            raise ValueError(
                "confirmed relations and related assets must be invalidated together"
            )
        binding_pairs = {
            (binding.relation_id, binding.related_asset_id)
            for binding in self.confirmed_relation_bindings
        }
        if len(binding_pairs) != len(self.confirmed_relation_bindings):
            raise ValueError("confirmed relation bindings must be unique")
        if binding_pairs and (
            {relation_id for relation_id, _ in binding_pairs}
            != set(self.confirmed_relation_ids)
            or {asset_id for _, asset_id in binding_pairs}
            != set(self.confirmed_related_asset_ids)
        ):
            raise ValueError(
                "confirmed relation bindings must exactly pair confirmed IDs and assets"
            )
        if self.retrieval_scope is RetrievalScope.CROSS_ASSET_SUMMARY and (
            not self.knowledge_card_version_id or not self.knowledge_card_hash
        ):
            raise ValueError("cross-asset summary retrieval requires Knowledge Card readiness")
        if (
            self.retrieval_scope is RetrievalScope.CROSS_ASSET_DETAIL
            and (
                not self.confirmed_relation_ids
                or not self.confirmed_related_asset_ids
            )
        ):
            raise ValueError(
                "cross-asset detail retrieval requires a confirmed relation and asset"
            )
        proposal_ids = {proposal.proposal_id for proposal in self.tool_proposals}
        decision_ids = {decision.decision_id for decision in self.policy_decisions}
        execution_ids = {execution.execution_id for execution in self.tool_executions}
        for decision in self.policy_decisions:
            if decision.run_id != self.run_id or decision.proposal_id not in proposal_ids:
                raise ValueError("policy decision must reference this run and a known proposal")
        for execution in self.tool_executions:
            if (
                execution.run_id != self.run_id
                or execution.proposal_id not in proposal_ids
                or execution.policy_decision_id not in decision_ids
            ):
                raise ValueError(
                    "tool execution must reference this run, proposal, and policy decision"
                )
        if self.verification_report:
            if self.verification_report.run_id != self.run_id:
                raise ValueError("verification report must belong to this run")
            if (
                self.verification_report.execution_id is not None
                and self.verification_report.execution_id not in execution_ids
            ):
                raise ValueError("verification report references an unknown execution")
        if self.terminal_state is not None and self.verification_report is None:
            raise ValueError("terminal Agent state requires a verification report")
        return self


class TerminalResultV1(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: UUID
    state: TerminalState
    last_durable_version_id: UUID | None = None
    retryable: bool
    safe_user_message: NonEmptyText
    internal_error_class: str | None = None
    elapsed_ms: int = Field(ge=0)
    model_call_count: int = Field(ge=0)
    recovery_action: NonEmptyText
    finished_at: AwareDatetime


class HealthStatusV1(ContractModel):
    service: Literal["experience-asset-agent"] = "experience-asset-agent"
    status: Literal["ok", "degraded"]
    app_version: NonEmptyText
    canonical_schema_version: Literal["1.0.0"] = "1.0.0"
    database: Literal["ok", "unavailable", "not_configured"]
    inference_mode: Literal["local_only"] = "local_only"
    model_endpoint: NonEmptyText
    model_profile: NonEmptyText
    gpu_viability: Literal["VERIFIED", "NOT_VERIFIED", "BLOCKED"]
    checked_at: AwareDatetime


def model_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Expose one stable schema-generation entry point for contract export."""

    return model.model_json_schema(mode="validation")
