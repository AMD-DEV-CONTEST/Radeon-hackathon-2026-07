from __future__ import annotations

from collections import Counter
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from policyseal.agent.checkpoints import CopilotThreadCheckpoint
from policyseal.agent.copilot_graph import CopilotReply
from policyseal.agent.schemas import ReviewIntent
from policyseal.agent.tools import ExceptionDraft
from policyseal.application.analysis import AnalysisResult
from policyseal.application.simulations import SimulationResult
from policyseal.domain.enums import (
    Action,
    ApprovalStatus,
    Channel,
    Classification,
    ContentCategory,
    FileKind,
    Purpose,
    RecipientProfile,
    RevisionStatus,
)
from policyseal.domain.models import (
    ApprovalRecord,
    DisclosureContext,
    PolicyDecision,
    RevisionStageEvent,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorBody(ApiModel):
    code: str
    message: str


class ContextInput(ApiModel):
    recipient: RecipientProfile
    organization: str = Field(min_length=1, max_length=240)
    recipient_id: str = Field(min_length=1, max_length=240)
    purpose: Purpose
    channel: Channel
    classification: Classification
    policy_version: str = Field(default="1.0.0", min_length=1, max_length=40)

    def to_domain(self) -> DisclosureContext:
        return DisclosureContext(**self.model_dump())


class ContextResponse(ContextInput):
    sha256: str

    @classmethod
    def from_domain(cls, context: DisclosureContext) -> ContextResponse:
        return cls(
            recipient=context.recipient,
            organization=context.organization,
            recipient_id=context.recipient_id,
            purpose=context.purpose,
            channel=context.channel,
            classification=context.classification,
            policy_version=context.policy_version,
            sha256=context.sha256,
        )


class DecisionResponse(ApiModel):
    region_id: str
    location: str
    category: ContentCategory
    action: Action
    rule_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    reason_code: str
    reason: str
    policy_version: str
    transform: str | None

    @classmethod
    def from_domain(cls, decision: PolicyDecision, *, location: str) -> DecisionResponse:
        return cls(
            region_id=decision.region_id,
            location=location,
            category=decision.category,
            action=decision.action,
            rule_ids=decision.rule_ids,
            evidence_ids=decision.evidence_ids,
            reason_code=decision.reason_code,
            reason=decision.reason,
            policy_version=decision.policy_version,
            transform=decision.transform,
        )


class RevisionResponse(ApiModel):
    id: str
    task_id: str
    revision_number: int
    status: RevisionStatus
    context: ContextResponse
    source_sha256: str
    policy_sha256: str
    output_sha256: str | None
    decision_manifest_sha256: str | None
    created_at: datetime
    action_counts: dict[str, int]
    decisions: tuple[DecisionResponse, ...]

    @classmethod
    def from_result(cls, result: AnalysisResult) -> RevisionResponse:
        locations = {region.id: region.location for region in result.regions}
        decisions = tuple(
            DecisionResponse.from_domain(decision, location=locations[decision.region_id])
            for decision in result.decisions
        )
        counts = Counter(decision.action.value for decision in result.decisions)
        revision = result.revision
        return cls(
            id=revision.id,
            task_id=revision.task_id,
            revision_number=revision.revision_number,
            status=revision.status,
            context=ContextResponse.from_domain(revision.context),
            source_sha256=revision.source_sha256,
            policy_sha256=revision.policy_sha256,
            output_sha256=revision.output_sha256,
            decision_manifest_sha256=revision.decision_manifest_sha256,
            created_at=revision.created_at,
            action_counts=dict(sorted(counts.items())),
            decisions=decisions,
        )


class TaskResponse(ApiModel):
    id: str
    requester_id: str
    file_kind: FileKind
    source_sha256: str
    created_at: datetime
    revisions: tuple[RevisionResponse, ...]


class StageEventResponse(ApiModel):
    revision_id: str
    sequence: int
    stage: str
    status: str
    occurred_at: datetime

    @classmethod
    def from_domain(cls, event: RevisionStageEvent) -> StageEventResponse:
        return cls(
            revision_id=event.revision_id,
            sequence=event.sequence,
            stage=event.stage,
            status=event.status,
            occurred_at=event.occurred_at,
        )


class SimulationRequest(ApiModel):
    context: ContextInput


class SimulationResponse(ApiModel):
    id: str
    task_id: str
    base_revision_id: str
    context: ContextResponse
    status: RevisionStatus
    action_counts: dict[str, int]
    decisions: tuple[DecisionResponse, ...]
    downloadable: bool

    @classmethod
    def from_domain(
        cls,
        simulation: SimulationResult,
        *,
        locations: dict[str, str],
    ) -> SimulationResponse:
        counts = Counter(decision.action.value for decision in simulation.decisions)
        return cls(
            id=simulation.id,
            task_id=simulation.task_id,
            base_revision_id=simulation.base_revision_id,
            context=ContextResponse.from_domain(simulation.context),
            status=simulation.status,
            action_counts=dict(sorted(counts.items())),
            decisions=tuple(
                DecisionResponse.from_domain(
                    decision,
                    location=locations[decision.region_id],
                )
                for decision in simulation.decisions
            ),
            downloadable=simulation.downloadable,
        )


class ReviewRegionResponse(ApiModel):
    region_id: str
    location: str
    order: int
    category: ContentCategory
    source_text: str
    output_preview: str | None
    action: Action
    rule_ids: tuple[str, ...]
    rule_reasons: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    reason_code: str
    transform: str | None


class EvidenceRecordResponse(ApiModel):
    id: str
    title: str
    tags: tuple[str, ...]
    excerpt: str


class ReviewResponse(ApiModel):
    revision_id: str
    task_id: str
    file_kind: FileKind
    regions: tuple[ReviewRegionResponse, ...]
    evidence: tuple[EvidenceRecordResponse, ...]
    preview_urls: tuple[str, ...]


class FormalContextRequest(ApiModel):
    simulation_id: str
    actor: str


class ApprovalRequestInput(ApiModel):
    actor: str


class ApprovalResolveInput(ApiModel):
    actor: str
    expected_binding_sha256: str | None = None
    reason_code: str | None = None


class ApprovalResponse(ApiModel):
    id: str
    revision_id: str
    status: ApprovalStatus
    binding_sha256: str
    requester_id: str
    reviewer_id: str | None
    expires_at: datetime
    consumed: bool
    reason_code: str | None

    @classmethod
    def from_domain(cls, approval: ApprovalRecord) -> ApprovalResponse:
        return cls(
            id=approval.id,
            revision_id=approval.revision_id,
            status=approval.status,
            binding_sha256=approval.binding_sha256,
            requester_id=approval.requester_id,
            reviewer_id=approval.reviewer_id,
            expires_at=approval.expires_at,
            consumed=approval.consumed,
            reason_code=approval.reason_code,
        )


class DeletionResponse(ApiModel):
    task_id: str
    revision_count: int
    source_sha256: str
    deletion_fingerprint: str
    status: str = "deleted"


class CopilotThreadInput(ApiModel):
    task_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    display_reference: str | None = Field(default=None, min_length=1, max_length=120)


class CopilotThreadResponse(ApiModel):
    thread_id: str
    task_id: str
    revision_id: str
    display_reference: str
    turn_count: int

    @classmethod
    def from_domain(cls, thread: CopilotThreadCheckpoint) -> CopilotThreadResponse:
        return cls(
            thread_id=thread.thread_id,
            task_id=thread.task_id,
            revision_id=thread.revision_id,
            display_reference=thread.display_reference,
            turn_count=len(thread.turns),
        )


class CopilotMessageInput(ApiModel):
    task_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=1_000)


class CopilotCitationResponse(ApiModel):
    location: str
    category: ContentCategory
    action: Action
    rule_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]


class CopilotReplyResponse(ApiModel):
    thread_id: str
    task_id: str
    revision_id: str
    turn_number: int
    intent: ReviewIntent
    text: str
    citations: tuple[CopilotCitationResponse, ...]
    simulation_id: str | None
    exception_draft_id: str | None
    model_dependent: bool

    @classmethod
    def from_domain(cls, reply: CopilotReply) -> CopilotReplyResponse:
        return cls(
            thread_id=reply.thread_id,
            task_id=reply.task_id,
            revision_id=reply.revision_id,
            turn_number=reply.turn_number,
            intent=reply.intent,
            text=reply.text,
            citations=tuple(
                CopilotCitationResponse(
                    location=citation.location,
                    category=citation.category,
                    action=citation.action,
                    rule_ids=citation.rule_ids,
                    evidence_ids=citation.evidence_ids,
                )
                for citation in reply.citations
            ),
            simulation_id=reply.simulation_id,
            exception_draft_id=reply.exception_draft_id,
            model_dependent=reply.model_dependent,
        )


class ExceptionSubmitInput(ApiModel):
    actor: str = Field(min_length=1, max_length=240)


class ExceptionDraftResponse(ApiModel):
    id: str
    task_id: str
    revision_id: str
    location: str
    category: ContentCategory
    rule_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    status: str
    submitted: bool

    @classmethod
    def from_domain(cls, draft: ExceptionDraft) -> ExceptionDraftResponse:
        return cls(
            id=draft.id,
            task_id=draft.task_id,
            revision_id=draft.revision_id,
            location=draft.location,
            category=draft.category,
            rule_ids=draft.rule_ids,
            evidence_ids=draft.evidence_ids,
            status=draft.status,
            submitted=draft.submitted,
        )


class ExceptionSubmissionResponse(ApiModel):
    draft: ExceptionDraftResponse
    approval: ApprovalResponse
