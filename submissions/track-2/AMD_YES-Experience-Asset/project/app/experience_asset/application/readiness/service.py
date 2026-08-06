"""The readiness transition: one explicit acceptance, one exact binding."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from app.experience_asset.application.m4.projection import project_m4
from app.experience_asset.domain.enums import MilestoneState
from app.experience_asset.domain.m4 import InsightBoundaryMapV1, M4AcceptRequestV1
from app.experience_asset.domain.relation import KnowledgeCardReadinessRecordV1
from app.experience_asset.observability.retrieval_phase import (
    knowledge_card_ready_event,
)
from app.experience_asset.persistence import (
    AssetNotFoundError,
    SQLiteAssetRepository,
    StorageConflictError,
)
from app.experience_asset.persistence.relation_ledger import StaleBindingError
from app.experience_asset.role_graph import build_role_graph_projection

ReadinessRefusalReason = Literal[
    "NOT_READY",
    "STALE_VERSION",
    "CARD_HASH_MISMATCH",
    "ALREADY_ACCEPTED",
    "STORAGE_CONFLICT",
]

READINESS_REFUSAL_REASONS: tuple[ReadinessRefusalReason, ...] = (
    "NOT_READY",
    "STALE_VERSION",
    "CARD_HASH_MISMATCH",
    "ALREADY_ACCEPTED",
    "STORAGE_CONFLICT",
)
"""Refusals a caller can act on differently.

One generic reason would leave the user unable to tell "finish your card" from
"your card changed underneath you", and those have opposite next actions: the
first is work to do, the second is a reload.
"""


class ReadinessRefusal(ValueError):
    """A refused acceptance, carrying a stable reason the UI can branch on."""

    def __init__(self, reason: ReadinessRefusalReason, message: str) -> None:
        super().__init__(message)
        self.reason: ReadinessRefusalReason = reason


class ReadinessService:
    def __init__(self, repository: SQLiteAssetRepository) -> None:
        self.repository = repository

    def read(self, asset_id: UUID) -> KnowledgeCardReadinessRecordV1 | None:
        return self.repository.read_active_readiness(asset_id)

    def accept(
        self, asset_id: UUID, request: M4AcceptRequestV1
    ) -> KnowledgeCardReadinessRecordV1:
        """Turn one explicit acceptance into readiness bound to an exact version.

        Acceptance moves the map into its accepted state and mints readiness
        against the version that records it. The two are one fact: the frozen
        artifact states `CONFIRMED` and `COMPLETE_WITH_GAPS` exist only as the
        result of this action, and readiness that named the pre-acceptance
        version would point at a snapshot whose own milestone still says the map
        was never accepted.
        """
        if request.asset_id != asset_id:
            raise ReadinessRefusal(
                "STALE_VERSION", "the request names a different asset"
            )
        canonical = self.repository.get_current(asset_id)
        try:
            artifact = self.repository.get_current_m4(asset_id)
        except AssetNotFoundError as exc:
            raise ReadinessRefusal(
                "NOT_READY", "there is no Insight and Boundary Map to accept"
            ) from exc

        existing = self.repository.read_active_readiness(asset_id)
        if existing is not None:
            # Idempotent only for the same version. Rebinding a stale acceptance
            # to whatever is current now would grant readiness for content the
            # user never read.
            if existing.version_id == request.expected_canonical_version_id:
                return existing
            raise ReadinessRefusal(
                "ALREADY_ACCEPTED",
                "this card already has an active readiness record for another version",
            )

        if canonical.version_id != request.expected_canonical_version_id:
            raise ReadinessRefusal(
                "STALE_VERSION",
                "the canonical version changed after the card was read",
            )
        if artifact.artifact_id != request.expected_artifact_id:
            raise ReadinessRefusal(
                "STALE_VERSION", "the map changed after the card was read"
            )
        if artifact.state is MilestoneState.INVALIDATED:
            raise ReadinessRefusal(
                "NOT_READY",
                "an invalidated map cannot be accepted; regenerate it first",
            )

        accepted_state = self._accepted_state(artifact, request)
        now = datetime.now(UTC)
        version_id = uuid4()
        accepted = artifact.model_copy(
            update={
                "artifact_id": uuid4(),
                "state": accepted_state,
                # The base names the version this artifact was built on, not the
                # one the acceptance produces; the append rechecks it against the
                # current pointer, and readiness binds to the new snapshot below.
                "base_canonical_version_id": canonical.version_id,
                "updated_at": now,
            }
        )
        snapshot = project_m4(
            canonical,
            accepted,
            version_id=version_id,
            now=now,
            change_kind="M4_ACCEPT",
            change_reason=(
                "User explicitly accepted the Insight and Boundary Map"
                if accepted_state is MilestoneState.CONFIRMED
                else "User explicitly accepted the map together with its visible gaps"
            ),
        )
        try:
            self.repository.append_canonical_and_m4(
                snapshot,
                accepted,
                expected_current_version_id=canonical.version_id,
                expected_current_artifact_id=artifact.artifact_id,
                expected_m3_artifact_id=accepted.base_m3_artifact_id,
            )
        except StorageConflictError as exc:
            raise ReadinessRefusal("STORAGE_CONFLICT", str(exc)) from exc

        readiness = KnowledgeCardReadinessRecordV1(
            readiness_id=uuid4(),
            asset_id=asset_id,
            version_id=snapshot.version_id,
            m4_artifact_id=accepted.artifact_id,
            knowledge_card_hash=self.repository.get_version_content_hash(
                snapshot.version_id
            ),
            milestone_state=accepted_state,
            explicit_user_acceptance=True,
            accepted_gap_statement_ids=list(request.accepted_gap_statement_ids),
            accepted_at=now,
        )
        try:
            recorded = self.repository.record_readiness(readiness)
        except StaleBindingError as exc:
            raise ReadinessRefusal("CARD_HASH_MISMATCH", str(exc)) from exc
        except StorageConflictError as exc:
            raise ReadinessRefusal("STORAGE_CONFLICT", str(exc)) from exc

        # Acceptance is the trigger for projection, because ticket 04's rule is
        # that a projection exists only for a readiness-bound card. Leaving the
        # two unconnected is what made the whole chain look complete while
        # discovery had nothing to compare from: readiness said ready, and the
        # search found no projection for the very card that had just become one.
        projection = self._project(recorded)
        # One event carries both facts because acceptance is the single
        # moment they become true: readiness is minted and the projection
        # activates in the same action.
        self.repository.record_retrieval_event(
            asset_id,
            knowledge_card_ready_event(
                knowledge_card_version=recorded.version_id,
                knowledge_card_hash=recorded.knowledge_card_hash,
                milestone_state=recorded.milestone_state.value,
                projection_id=projection.projection_id,
                projection_hash=projection.projection_hash,
            ),
        )
        return recorded

    def _project(self, readiness: KnowledgeCardReadinessRecordV1):
        snapshot = self.repository.get_version(readiness.version_id)
        artifact = self.repository.get_m4_artifact(readiness.m4_artifact_id)
        projection = build_role_graph_projection(
            asset=snapshot,
            m4_artifact=artifact,
            readiness=readiness,
            created_at=readiness.accepted_at,
        )
        self.repository.activate_projection(projection)
        return projection

    @staticmethod
    def _accepted_state(
        artifact: InsightBoundaryMapV1, request: M4AcceptRequestV1
    ) -> MilestoneState:
        """Match the declared action against the gaps the map actually holds.

        The two are checked against each other rather than one being derived
        from the other. Deriving the action from the gaps would make acceptance
        implicit — the user would be recorded as accepting gaps they were never
        shown — and deriving the gaps from the action would let a `CONFIRM` bury
        the ones that exist.
        """
        gaps = {
            statement.statement_id
            for entry in artifact.entries
            for statement in entry.statements
            if statement.is_visible_gap
        }
        named = set(request.accepted_gap_statement_ids)
        if request.user_action == "CONFIRM":
            if gaps:
                raise ReadinessRefusal(
                    "NOT_READY",
                    "this map holds visible gaps; accept them explicitly or resolve them",
                )
            return MilestoneState.CONFIRMED
        if not gaps:
            raise ReadinessRefusal(
                "NOT_READY",
                "this map holds no visible gaps, so there is nothing to accept with gaps",
            )
        if named != gaps:
            raise ReadinessRefusal(
                "NOT_READY",
                "the accepted gaps do not match the gaps on the map; the record has to "
                "show what the user actually agreed to leave open",
            )
        return MilestoneState.COMPLETE_WITH_GAPS
