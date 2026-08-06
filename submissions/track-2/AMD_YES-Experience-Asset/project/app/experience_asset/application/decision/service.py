"""Confirm or decline one exact candidate, fail-closed."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.experience_asset.domain.enums import RelationLifecycle
from app.experience_asset.domain.relation import (
    ConfirmedAssetRelationV1,
    RelationCandidateDecisionV1,
)
from app.experience_asset.observability.retrieval_phase import (
    relation_confirmation_event,
)
from app.experience_asset.persistence import SQLiteAssetRepository
from app.experience_asset.persistence.relation_ledger import (
    DecisionAlreadySettledError,
    StaleBindingError,
)


class DecisionRefused(ValueError):
    """A refused decision, carrying the reason a caller can act on."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class DecisionService:
    def __init__(self, repository: SQLiteAssetRepository) -> None:
        self.repository = repository

    def decide(
        self, asset_id: UUID, candidate_id: UUID, request: RelationCandidateDecisionV1
    ) -> RelationCandidateDecisionV1:
        if request.candidate_id != candidate_id or request.current_asset_id != asset_id:
            raise DecisionRefused(
                "BINDING_MISMATCH",
                "the decision names a different candidate or asset than the request path",
            )
        candidate = self.repository.read_candidate(candidate_id)
        if candidate is None:
            raise DecisionRefused("UNKNOWN_CANDIDATE", "no such candidate")
        if candidate.related_asset_id != request.related_asset_id:
            raise DecisionRefused(
                "BINDING_MISMATCH",
                "the decision names a different related asset than the candidate",
            )

        relation: ConfirmedAssetRelationV1 | None = None
        if request.user_action == "CONFIRM":
            historical = self.repository.get_current(candidate.related_asset_id)
            relation = ConfirmedAssetRelationV1(
                relation_id=uuid4(),
                source_candidate_id=candidate.candidate_id,
                relation_type=candidate.relation_type,
                current_asset_id=candidate.current_asset_id,
                current_version_id=request.current_version_id,
                current_projection_id=candidate.current_projection_id,
                current_knowledge_card_hash=request.current_knowledge_card_hash,
                related_asset_id=candidate.related_asset_id,
                related_version_id=historical.version_id,
                historical_projection_id=candidate.historical_projection_id,
                lifecycle=RelationLifecycle.CONFIRMED,
                confirmed_at=request.decided_at or datetime.now(UTC),
            )
        try:
            settled = self.repository.decide_candidate(
                request, confirmed_relation=relation
            )
        except DecisionAlreadySettledError as exc:
            raise DecisionRefused("ALREADY_SETTLED", str(exc)) from exc
        except StaleBindingError as exc:
            # Refused, never resolved against whatever is current: a mismatch
            # means the caller is acting on state that no longer exists, and
            # proceeding would grant access from a decision the user made about
            # different content.
            raise DecisionRefused("STALE_BINDING", str(exc)) from exc
        # A decline is recorded too. The checker treats an unconfirmed relation
        # as one that must not open detail, and a trace that logged only
        # confirmations could not show that the refusal was ever answered.
        self.repository.record_retrieval_event(
            asset_id,
            relation_confirmation_event(
                related_asset_id=candidate.related_asset_id,
                relation_id=relation.relation_id if relation else None,
                confirmed=settled.user_action == "CONFIRM",
            ),
        )
        return settled

    def authorized_relations(self, asset_id: UUID) -> list[ConfirmedAssetRelationV1]:
        """Re-projected at each policy evaluation, never cached in run state.

        A client-supplied flag would let a request assert its own permission, and
        a value held in a long-running session would keep authorizing a relation
        that has since been invalidated.
        """
        return self.repository.list_confirmed_relations(asset_id)
