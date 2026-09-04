from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from policyseal.agent.retrieval import EvidenceDocument, HybridEvidenceRetriever
from policyseal.application.simulations import SimulationService
from policyseal.domain.enums import Action, ContentCategory, RevisionStatus
from policyseal.domain.models import DisclosureContext, PolicyDecision
from policyseal.storage.repositories import PolicySealRepository


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    region_id: str
    location: str
    category: ContentCategory
    action: Action
    rule_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    reason_code: str
    reason: str
    transform: str | None


@dataclass(frozen=True, slots=True)
class ReviewSnapshot:
    task_id: str
    revision_id: str
    revision_number: int
    context: DisclosureContext
    status: RevisionStatus
    decisions: tuple[ReviewDecision, ...]


@dataclass(frozen=True, slots=True)
class ReviewSimulation:
    id: str
    task_id: str
    base_revision_id: str
    context: DisclosureContext
    status: RevisionStatus
    decisions: tuple[ReviewDecision, ...]


@dataclass(frozen=True, slots=True)
class ExceptionDraft:
    id: str
    task_id: str
    revision_id: str
    location: str
    category: ContentCategory
    rule_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    status: str = "draft"
    submitted: bool = False


class ReviewTools:
    """Controlled read-only tools plus local, non-submitting draft creation."""

    def __init__(
        self,
        repository: PolicySealRepository,
        simulations: SimulationService,
        retriever: HybridEvidenceRetriever,
    ) -> None:
        self.repository = repository
        self.simulations = simulations
        self.retriever = retriever
        self._exception_drafts: dict[str, ExceptionDraft] = {}

    def snapshot(self, task_id: str, revision_id: str) -> ReviewSnapshot:
        task = self.repository.get_task(task_id)
        revision = self.repository.get_revision(revision_id)
        if revision.task_id != task.id:
            raise KeyError("revision does not belong to the requested task")
        return ReviewSnapshot(
            task_id=task.id,
            revision_id=revision.id,
            revision_number=revision.revision_number,
            context=revision.context,
            status=revision.status,
            decisions=self._decisions(revision.id),
        )

    def simulate(self, task_id: str, context: DisclosureContext) -> ReviewSimulation:
        simulation = self.simulations.simulate(task_id, context)
        return ReviewSimulation(
            id=simulation.id,
            task_id=simulation.task_id,
            base_revision_id=simulation.base_revision_id,
            context=simulation.context,
            status=simulation.status,
            decisions=self._review_decisions(
                simulation.base_revision_id,
                simulation.decisions,
            ),
        )

    def evidence(self, evidence_id: str) -> EvidenceDocument:
        return self.retriever.get(evidence_id)

    def create_exception_draft(
        self,
        snapshot: ReviewSnapshot,
        decision: ReviewDecision,
    ) -> ExceptionDraft:
        draft = ExceptionDraft(
            id=f"exception-draft-{uuid.uuid4().hex}",
            task_id=snapshot.task_id,
            revision_id=snapshot.revision_id,
            location=decision.location,
            category=decision.category,
            rule_ids=decision.rule_ids,
            evidence_ids=decision.evidence_ids,
        )
        self._exception_drafts[draft.id] = draft
        return draft

    def get_exception_draft(self, draft_id: str) -> ExceptionDraft:
        try:
            return self._exception_drafts[draft_id]
        except KeyError as error:
            raise KeyError("exception draft does not exist") from error

    def mark_exception_submitted(self, draft_id: str) -> ExceptionDraft:
        draft = self.get_exception_draft(draft_id)
        if draft.submitted:
            raise ValueError("exception draft was already submitted")
        submitted = replace(draft, status="submitted", submitted=True)
        self._exception_drafts[draft_id] = submitted
        return submitted

    def delete_task(self, task_id: str) -> None:
        for draft_id in tuple(self._exception_drafts):
            if self._exception_drafts[draft_id].task_id == task_id:
                del self._exception_drafts[draft_id]

    def _decisions(self, revision_id: str) -> tuple[ReviewDecision, ...]:
        return self._review_decisions(
            revision_id,
            self.repository.list_decisions(revision_id),
        )

    def _review_decisions(
        self,
        revision_id: str,
        decisions: tuple[PolicyDecision, ...],
    ) -> tuple[ReviewDecision, ...]:
        locations = {
            region.id: region.location for region in self.repository.list_regions(revision_id)
        }
        return tuple(
            ReviewDecision(
                region_id=decision.region_id,
                location=locations[decision.region_id],
                category=decision.category,
                action=decision.action,
                rule_ids=decision.rule_ids,
                evidence_ids=decision.evidence_ids,
                reason_code=decision.reason_code,
                reason=decision.reason,
                transform=decision.transform,
            )
            for decision in decisions
        )


__all__ = [
    "ExceptionDraft",
    "ReviewDecision",
    "ReviewSimulation",
    "ReviewSnapshot",
    "ReviewTools",
]
