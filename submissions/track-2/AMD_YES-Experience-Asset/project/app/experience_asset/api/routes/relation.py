"""Cross-asset relation API — routes registered, handlers owned elsewhere.

Four user-level operations: start discovery for an exact ready card, read the
discovery status or result, decide an exact candidate, and read the confirmed
relation's evidence comparison.

Handler ownership is split so that Wave-1 work does not collide. Ticket 08 fills
in the evidence read; tickets 05 and 07 fill in discovery and decision in later
waves. Each ticket adds handler bodies inside its own operation and leaves the
module structure alone — restructuring would put two branches into conflict over
a file the contract freeze already fixed.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.experience_asset.api.routes.not_implemented import (
    NOT_IMPLEMENTED_RESPONSES,
    not_implemented,
)
from app.experience_asset.application.decision import (
    DecisionRefused,
    DecisionService,
)
from app.experience_asset.application.discovery import (
    DiscoveryService,
    DiscoveryUnavailable,
)
from app.experience_asset.application.readiness import ReadinessService
from app.experience_asset.application.relation_evidence import read_evidence_card_traced
from app.experience_asset.domain.enums import DiscoveryOutcome
from app.experience_asset.domain.relation import (
    RelationCandidateDecisionV1,
    RelationWorkspaceV1,
)
from app.experience_asset.inference import ModelClient
from app.experience_asset.observability.retrieval_phase import (
    candidate_search_denied_event,
)
from app.experience_asset.persistence import SQLiteAssetRepository
from app.experience_asset.tools.contracts import (
    ConfirmedRelatedEvidenceArguments,
    RelatedCandidateDiscoveryArguments,
)


def build_relation_router(
    repository: SQLiteAssetRepository, model_client: ModelClient | None = None
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/relations", tags=["relations"])
    readiness_service = ReadinessService(repository)
    decisions = DecisionService(repository)
    discovery = (
        DiscoveryService(repository, model_client) if model_client else None
    )

    def workspace(asset_id: UUID, **overrides) -> RelationWorkspaceV1:
        return RelationWorkspaceV1(
            asset_id=asset_id,
            canonical_version_id=repository.get_current(asset_id).version_id,
            readiness=readiness_service.read(asset_id),
            confirmed_relations=repository.list_confirmed_relations(asset_id),
            **overrides,
        )

    @router.post(
        "/assets/{asset_id}/discovery",
        response_model=RelationWorkspaceV1,
        status_code=202,
        responses=NOT_IMPLEMENTED_RESPONSES,
    )
    async def start_discovery(
        asset_id: UUID, request: RelatedCandidateDiscoveryArguments
    ) -> RelationWorkspaceV1:
        """Start one summary-only discovery for an exact ready card.

        Discovery runs only from an explicit user action. Before exact readiness
        it is denied with a typed reason and performs no cross-asset read and no
        model call — doing the read and discarding it would already have exposed
        historical material to the model and spent the budget, so the denial has
        to happen before the work rather than after.
        """
        # Ticket 03 owns this gate and nothing past it. The readiness lookup is
        # the first statement in the handler on purpose: any eligibility listing
        # or corpus read placed above it would already have touched another
        # asset's history by the time the denial returned.
        readiness = readiness_service.read(asset_id)
        if readiness is None:
            repository.record_retrieval_event(
                asset_id,
                candidate_search_denied_event(
                    denial_reason=DiscoveryOutcome.NOT_READY.value
                ),
            )
            raise HTTPException(
                409,
                {
                    "reason": DiscoveryOutcome.NOT_READY.value,
                    "message": (
                        "this card is not ready; accept the Insight and Boundary "
                        "Map before comparing it with anything"
                    ),
                },
            )
        # Readiness existing is not enough — it has to be readiness for the card
        # the caller is holding. A request naming a superseded version or hash
        # would otherwise be answered against whatever is current, and the user
        # would get a comparison of content they were not looking at.
        if (
            request.asset_id != asset_id
            or request.knowledge_card_version_id != readiness.version_id
            or request.knowledge_card_hash != readiness.knowledge_card_hash
        ):
            repository.record_retrieval_event(
                asset_id,
                candidate_search_denied_event(
                    denial_reason=DiscoveryOutcome.STALE.value
                ),
            )
            raise HTTPException(
                409,
                {
                    "reason": DiscoveryOutcome.STALE.value,
                    "message": (
                        "the request names a card version or hash that is not the "
                        "active ready one; reload before comparing"
                    ),
                },
            )
        if discovery is None:
            raise not_implemented("05", "cross-asset discovery")
        try:
            result = await discovery.discover(asset_id)
        except DiscoveryUnavailable as exc:
            raise HTTPException(
                409, {"reason": exc.outcome.value, "message": str(exc)}
            ) from exc
        return workspace(
            asset_id,
            discovery_outcome=result.outcome,
            failure_class=result.failure_class,
            candidates=(
                [repository.read_candidate(result.candidate_id)]
                if result.candidate_id
                else []
            ),
        )

    @router.get(
        "/assets/{asset_id}/discovery",
        response_model=RelationWorkspaceV1,
        responses=NOT_IMPLEMENTED_RESPONSES,
    )
    async def read_discovery(asset_id: UUID) -> RelationWorkspaceV1:
        """Read the current discovery outcome for this asset.

        The outcome is one of six discriminated states. `NO_MATCH` is a semantic
        claim and is cached; `TECHNICAL_FAILURE` is not, because caching an
        outage as an answer would permanently erase a relation that may exist.
        """
        # The not-ready state is answered here rather than deferred with the
        # rest: it is what the UI derives its lock from, and a lock computed
        # locally would disagree with the backend the moment the card changes in
        # another tab, leaving the user an action that fails when clicked.
        readiness = readiness_service.read(asset_id)
        if readiness is None:
            return workspace(asset_id, discovery_outcome=DiscoveryOutcome.NOT_READY)
        settled = repository.read_latest_attempt(asset_id)
        if settled is None:
            # Ready, never searched. Reporting NO_MATCH here would claim a
            # comparison that never ran.
            return workspace(asset_id, discovery_outcome=DiscoveryOutcome.NOT_READY)
        return workspace(
            asset_id,
            discovery_outcome=settled.outcome,
            failure_class=settled.failure_class,
            candidates=(
                [repository.read_candidate(settled.candidate_id)]
                if settled.candidate_id
                else []
            ),
        )

    @router.post(
        "/assets/{asset_id}/candidates/{candidate_id}/decision",
        response_model=RelationWorkspaceV1,
        status_code=201,
        responses=NOT_IMPLEMENTED_RESPONSES,
    )
    async def decide(
        asset_id: UUID,
        candidate_id: UUID,
        request: RelationCandidateDecisionV1,
    ) -> RelationWorkspaceV1:
        """Confirm or decline one exact candidate.

        Every binding the decision was made against is carried and rechecked. A
        mismatch fails closed rather than being resolved against whatever is
        current, because resolving it silently would grant access based on a
        decision the user made about different content.
        """
        try:
            decision = decisions.decide(asset_id, candidate_id, request)
        except DecisionRefused as exc:
            raise HTTPException(
                409, {"reason": exc.reason, "message": str(exc)}
            ) from exc
        candidate = repository.read_candidate(candidate_id)
        return workspace(
            asset_id,
            discovery_outcome=(
                DiscoveryOutcome.CANDIDATE
                if decision.user_action == "CONFIRM"
                else DiscoveryOutcome.NO_MATCH
            ),
            # The declined candidate is still returned, carrying its DECLINED
            # lifecycle. Dropping it here would hide the card without removing
            # the decision behind it, and the next load would present it again.
            candidates=[candidate] if candidate else [],
            decisions=[decision],
        )

    @router.post(
        "/assets/{asset_id}/relations/{relation_id}/evidence",
        response_model=RelationWorkspaceV1,
        responses=NOT_IMPLEMENTED_RESPONSES,
    )
    async def read_confirmed_evidence(
        asset_id: UUID,
        relation_id: UUID,
        request: ConfirmedRelatedEvidenceArguments,
    ) -> RelationWorkspaceV1:
        """Read the deterministic bilateral evidence card for a confirmed relation.

        The card is rendered by application code from canonical content, with no
        second model call. A generated summary would be a new artifact produced
        after the confirmation gate — never reviewed by the user, free to drift
        from the relation they approved, and reading as a faithful description
        of it.

        Every input to the authorization decision is re-read here from durable
        state. The request names what the caller believes; rendering from those
        values would let a replayed or hand-edited request assert a binding the
        ledger never recorded.
        """
        if request.asset_id != asset_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": "BINDING_MISMATCH",
                    "detail": "the request names a different asset than the path",
                },
            )
        relation = repository.read_confirmed_relation(relation_id)
        if relation is None or relation.current_asset_id != asset_id:
            # Four situations, one answer on purpose: never confirmed, declined,
            # invalidated, and belonging to someone else's asset. Separating
            # them here would let a caller probe for which relations exist on
            # assets they cannot read.
            raise HTTPException(
                status_code=404,
                detail={
                    "reason": "RELATION_NOT_LIVE",
                    "detail": "no live confirmed relation for this asset",
                },
            )
        candidate = repository.read_candidate(relation.source_candidate_id)
        if candidate is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": "CONTENT_UNAVAILABLE",
                    "detail": "the candidate this relation was confirmed from is gone",
                },
            )
        card = read_evidence_card_traced(
            repository,
            relation=relation,
            candidate=candidate,
            current_projection=repository.read_projection(relation.current_projection_id),
            historical_projection=repository.read_projection(
                relation.historical_projection_id
            ),
        )
        # A refusal rides back inside the workspace with a 200 rather than being
        # raised. It is an answer about this relation, and an error status would
        # make a considered refusal indistinguishable from a transport fault.
        return workspace(asset_id, evidence_card=card)

    return router
