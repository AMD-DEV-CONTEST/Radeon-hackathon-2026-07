"""Cross-artifact invalidation orchestration.

This layer decides *what* a mutation means; the repository performs it in one
transaction. Splitting the revocation across transactions would let a crash
land between them, leaving an index row that still grants comparability for
canonical state that no longer exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.experience_asset.domain.enums import (
    ProjectionLifecycle,
    ReadinessLifecycle,
    RelationLifecycle,
)

from .matrix import (
    INVALIDATION_MATRIX,
    REDACTS_COPIED_CONTENT,
    Artifact,
    MutationEvent,
    Outcome,
)

# Which side of the ledger an event walks.
#
# The same physical change is a different event depending on the role the
# changed asset plays: correcting an asset voids the candidates it is the
# subject of, and makes the candidates that merely *refer* to it stale. Walking
# both sides for every event would invalidate a user's confirmed relations on
# an asset they never touched; walking one side for deletion would leave the
# other half of the ledger pointing at content that is gone.
_CURRENT_SIDE = frozenset({MutationEvent.CURRENT_ASSET_CORRECTION})
_RELATED_SIDE = frozenset({MutationEvent.RELATED_ASSET_CHANGE})
_BOTH_SIDES = frozenset(
    {
        MutationEvent.ASSET_DELETION,
        MutationEvent.PRIVACY_NARROWING,
        MutationEvent.PROJECTION_SCHEMA_CHANGE,
    }
)

_RELATION_STATE = {
    Outcome.STALE: RelationLifecycle.STALE,
    Outcome.INVALIDATED: RelationLifecycle.INVALIDATED,
}


@dataclass(frozen=True)
class InvalidationResult:
    """What the mutation actually moved, for the caller to report or log."""

    event: MutationEvent
    asset_id: UUID
    readiness_invalidated: int
    projections_invalidated: int
    candidates_moved: int
    relations_moved: int

    @property
    def touched_nothing(self) -> bool:
        return not any(
            (
                self.readiness_invalidated,
                self.projections_invalidated,
                self.candidates_moved,
                self.relations_moved,
            )
        )


class InvalidationService:
    def __init__(self, repository) -> None:
        self.repository = repository

    def apply(
        self, event: MutationEvent, *, asset_id: UUID, reason: str
    ) -> InvalidationResult:
        """Apply one mutation's whole matrix row, atomically.

        The row is read rather than reimplemented per event, so adding an
        artifact to the matrix without handling it here fails loudly instead of
        leaving that artifact reachable.
        """
        if not reason.strip():
            raise ValueError("invalidation requires a reason")
        row = INVALIDATION_MATRIX[event]
        unknown = set(Artifact) - set(row)
        if unknown:
            raise NotImplementedError(
                f"{event.value} does not state an outcome for {sorted(unknown)}"
            )

        moved = self.repository.invalidate_for_asset_change(
            asset_id,
            reason=reason,
            readiness_lifecycle=(
                ReadinessLifecycle.INVALIDATED.value
                if row[Artifact.READINESS] is Outcome.INVALIDATED
                else None
            ),
            projection_lifecycle=(
                ProjectionLifecycle.INVALIDATED.value
                if row[Artifact.PROJECTION] is Outcome.INVALIDATED
                else None
            ),
            candidate_lifecycle=self._lifecycle(row[Artifact.CANDIDATE]),
            relation_lifecycle=self._lifecycle(row[Artifact.RELATION]),
            match_current_side=event in _CURRENT_SIDE or event in _BOTH_SIDES,
            match_related_side=event in _RELATED_SIDE or event in _BOTH_SIDES,
            redact_copied_content=event in REDACTS_COPIED_CONTENT,
        )
        return InvalidationResult(event=event, asset_id=asset_id, **moved)

    @staticmethod
    def _lifecycle(outcome: Outcome) -> str | None:
        """`None` means "leave this artifact alone", not "no state".

        Returning a default state for `UNCHANGED` is the mistake that makes an
        upgrade of an unrelated component discard relations the user confirmed.
        """
        state = _RELATION_STATE.get(outcome)
        return state.value if state is not None else None
