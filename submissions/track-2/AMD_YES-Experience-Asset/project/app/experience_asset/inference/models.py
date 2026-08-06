"""Structured, inert model input/output contracts."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from app.experience_asset.domain.models import ContractModel, NonEmptyText


class SourceExcerpt(ContractModel):
    source_id: UUID
    span_id: NonEmptyText
    text: str


class ToolDefinition(ContractModel):
    name: NonEmptyText
    description: NonEmptyText
    input_schema: dict[str, JsonValue]


class ModelRequest(ContractModel):
    run_id: UUID
    stage: NonEmptyText
    system_policy: NonEmptyText
    canonical_context: dict[str, JsonValue]
    source_excerpts: list[SourceExcerpt] = Field(default_factory=list)
    output_schema: dict[str, JsonValue]
    tools: list[ToolDefinition] = Field(default_factory=list)
    max_output_tokens: int = Field(gt=0, le=4096)
    timeout_seconds: float = Field(gt=0, le=300)


class ProposedStatement(ContractModel):
    text: NonEmptyText
    status: Literal["USER_JUDGMENT", "AGENT_INFERENCE", "UNRESOLVED"]
    source_refs: list[UUID] = Field(default_factory=list)
    derived_from: list[UUID] = Field(default_factory=list)


class ProposedQuestion(ContractModel):
    question: NonEmptyText
    why_it_matters: NonEmptyText
    affected_statement_ids: list[UUID] = Field(default_factory=list)


class ToolCallProposal(ContractModel):
    """A parsed request, never an authorization or executable command."""

    name: NonEmptyText
    arguments: dict[str, JsonValue]
    requested_reason: str | None = None
    permission_granted: Literal[False] = False


class StructuredProposal(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    summary: NonEmptyText
    proposed_statements: list[ProposedStatement] = Field(default_factory=list)
    questions: list[ProposedQuestion] = Field(default_factory=list, max_length=3)
    tool_call_proposals: list[ToolCallProposal] = Field(default_factory=list)


M2SemanticRole = Literal["CUE", "CHANGE", "SURPRISE"]


class M2SemanticRoleAssignment(ContractModel):
    """One untrusted semantic-role proposal bound to an existing statement."""

    statement_id: UUID
    roles: list[M2SemanticRole] = Field(max_length=3)
    # The Runtime acts on roles and source IDs only.  A free-form model
    # explanation is optional metadata, not an authorization or correctness
    # signal; keeping a deterministic default also avoids requesting hidden
    # chain-of-thought from local serving profiles.
    reasoning: NonEmptyText = "Inferred from the supplied source evidence."

    @model_validator(mode="after")
    def roles_are_unique(self) -> M2SemanticRoleAssignment:
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("M2 semantic roles must be unique per statement")
        return self


class M2SemanticRoleProposal(ContractModel):
    """Strict local-model output; the Runtime still validates every reference."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    assignments: list[M2SemanticRoleAssignment] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def statement_ids_are_unique(self) -> M2SemanticRoleProposal:
        statement_ids = [assignment.statement_id for assignment in self.assignments]
        if len(statement_ids) != len(set(statement_ids)):
            raise ValueError("M2 semantic proposal statement IDs must be unique")
        return self


class ModelMetadata(ContractModel):
    server_kind: Literal["vllm", "fake"]
    server_base_url: NonEmptyText
    model_id: NonEmptyText
    response_id: str | None = None
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    elapsed_ms: int = Field(ge=0)
    received_at: AwareDatetime


class ModelResult(ContractModel):
    proposal: StructuredProposal
    metadata: ModelMetadata


class M2SemanticRoleResult(ContractModel):
    proposal: M2SemanticRoleProposal
    metadata: ModelMetadata


M3LedgerRole = Literal["ALTERNATIVE", "REASON", "DECISION", "ACTION", "OBSERVED_RESULT"]


class M3ProposedStatement(ContractModel):
    role: M3LedgerRole
    text: NonEmptyText
    source_moment_ids: list[UUID] = Field(min_length=1)
    source_statement_ids: list[UUID] = Field(default_factory=list)
    derived_from_statement_ids: list[UUID] = Field(default_factory=list)
    unresolved_reason: NonEmptyText | None = None


class M3ProposedEntry(ContractModel):
    prior_decision_id: UUID | None = None
    title: NonEmptyText
    source_moment_ids: list[UUID] = Field(min_length=1)
    statements: list[M3ProposedStatement] = Field(min_length=5)


class M3LedgerProposal(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    entries: list[M3ProposedEntry] = Field(min_length=1)
    tool_call_proposals: list[ToolCallProposal] = Field(default_factory=list)


class M3LedgerResult(ContractModel):
    proposal: M3LedgerProposal
    metadata: ModelMetadata


M4InsightRole = Literal[
    "LESSON",
    "SUPPORT",
    "COUNTERFACTUAL",
    "LIMITATION",
    "COUNTEREXAMPLE",
    "APPLICABILITY",
]


class M4ProposedStatement(ContractModel):
    """One proposed role statement, either grounded or declared as a gap.

    The proposal shape mirrors the durable contract's two-state rule rather than
    allowing a third, silent one: a statement carries canonical citations, or it
    carries a gap reason. A proposal permitted to return neither would render as
    a finished lesson with nothing behind it.
    """

    role: M4InsightRole
    text: NonEmptyText
    source_statement_ids: list[UUID] = Field(default_factory=list)
    source_decision_ids: list[UUID] = Field(default_factory=list)
    gap_reason: NonEmptyText | None = None


class M4ProposedEntry(ContractModel):
    prior_insight_id: UUID | None = None
    title: NonEmptyText
    source_decision_ids: list[UUID] = Field(min_length=1)
    statements: list[M4ProposedStatement] = Field(min_length=6)


class M4MapProposal(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    entries: list[M4ProposedEntry] = Field(min_length=1)
    tool_call_proposals: list[ToolCallProposal] = Field(default_factory=list)


class M4MapResult(ContractModel):
    proposal: M4MapProposal
    metadata: ModelMetadata


class ProposedRelationMapping(ContractModel):
    """One node correspondence the model proposes, by identifier only."""

    current_node_id: NonEmptyText
    historical_node_id: NonEmptyText


class RelationDiscoveryProposal(ContractModel):
    """One batch comparison of the current graph against the eligible ones.

    The model returns identifiers and a relation label, never prose that reaches
    the user. Title, summary, boundary text and provenance are rendered by the
    Runtime from the validated projections: model prose promoted into a durable
    candidate becomes a claim the user attributes to their own evidence, with
    nothing behind it.

    `relation_type` is free text on purpose. Constraining it here would turn a
    forbidden label into a parse error and file it as malformed output, when the
    frozen scenario requires it to surface as a Runtime validation rejection —
    the label is data the Runtime judges, not a transport fault.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    outcome: Literal["CANDIDATE", "NO_MATCH"]
    related_asset_id: UUID | None = None
    historical_projection_id: UUID | None = None
    relation_type: str | None = None
    node_mappings: list[ProposedRelationMapping] = Field(default_factory=list)
    current_boundary_node_ids: list[str] = Field(default_factory=list)
    historical_boundary_node_ids: list[str] = Field(default_factory=list)
    reason: str | None = None
    """Retained for audit only. Never rendered and never persisted on a candidate."""


class RelationDiscoveryResult(ContractModel):
    proposal: RelationDiscoveryProposal
    metadata: ModelMetadata


class ModelClientError(RuntimeError):
    """Base local-inference adapter error."""


class ModelUnavailable(ModelClientError):
    """Local server cannot serve the request."""


class ModelTimedOut(ModelClientError):
    """Local request exceeded its explicit timeout."""


class InvalidModelOutput(ModelClientError):
    """Local model returned data outside the frozen structured contract."""
