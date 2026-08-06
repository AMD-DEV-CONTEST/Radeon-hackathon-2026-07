"""Frozen persistence interface for the relation ledger.

Ticket 01 freezes the operations, their typed conflicts and their transaction
postconditions. Tickets 04, 06, 07, 08 and 09 implement parts of this one
interface rather than each inventing its own.

Left unfrozen, four Wave-1 branches would each design "reserve an attempt" and
"activate a projection" separately, and the differences would not be textual
conflicts a merge could surface — they would be four incompatible ideas of when
a write is durable, discovered only at integration. That is precisely the
integration fork ticket 01 exists to prevent.

Nothing here executes. There is no implementation in this module on purpose: an
implementation now would be behaviour inside a contract-freeze ticket, and the
reviewer could no longer evaluate the contract as one decision.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.experience_asset.domain.relation import (
    ConfirmedAssetRelationV1,
    DiscoveryAttemptV1,
    DiscoveryFingerprintV1,
    KnowledgeCardReadinessRecordV1,
    RelationCandidateDecisionV1,
    RelationCandidateV1,
    RoleGraphProjectionV1,
)


class LedgerConflictError(Exception):
    """A write lost a race or contradicted durable state.

    Typed rather than a bare exception so callers can distinguish "retry may
    help" from "the caller's assumption is wrong". A generic error forces every
    caller to guess, and the safe guess — retry — is the wrong one for a binding
    conflict, which will fail identically forever.
    """

    retryable: bool = False


class StaleBindingError(LedgerConflictError):
    """The request names a version, hash or projection that is no longer current.

    Never retryable: the caller acted on state that has since changed, so a
    retry would repeat the same mismatch. Resolving it silently against current
    state would grant access based on a decision the user made about different
    content.
    """

    retryable = False


class ProjectionHashMismatchError(LedgerConflictError):
    """A projection's stored and recomputed hashes disagree.

    The projection has drifted from the inputs it claims to represent, so
    comparing against it would produce a candidate explained by content nobody
    can reproduce.
    """

    retryable = False


class ReservationHeldError(LedgerConflictError):
    """Another caller holds the reservation for this discovery fingerprint.

    Retryable as an observation — the caller should attach to the running
    attempt rather than start a second one. Two simultaneous clicks otherwise
    produce two model calls and two candidate rows for one logical question, and
    whichever commits last silently becomes the answer.
    """

    retryable = True


class DecisionAlreadySettledError(LedgerConflictError):
    """The candidate already carries a decision.

    Repeating the same decision is idempotent; submitting the opposite one is
    refused rather than overwriting, so the audit trail records what the user
    actually decided and when.
    """

    retryable = False


class RelationLedgerRepository(Protocol):
    """The ledger's write and read surface.

    Every method that mutates state does so in one transaction and rechecks its
    bindings inside that transaction. Checking before the transaction and
    writing after would leave a window where a concurrent invalidation is missed
    — and an invalidation that is missed does not fail loudly, it silently
    leaves access open.
    """

    # -- readiness (ticket 03) --------------------------------------------
    def record_readiness(
        self, readiness: KnowledgeCardReadinessRecordV1
    ) -> KnowledgeCardReadinessRecordV1:
        """Persist one explicit acceptance.

        Postcondition: exactly one ACTIVE readiness row exists for the asset,
        version and card hash. Raises `StaleBindingError` if the named version
        or M4 artifact is not current for that asset.
        """

    def read_active_readiness(
        self, asset_id: UUID
    ) -> KnowledgeCardReadinessRecordV1 | None:
        """Return the active readiness record, or None when the card is not ready."""

    # -- projections (ticket 04) ------------------------------------------
    def activate_projection(self, projection: RoleGraphProjectionV1) -> None:
        """Write nodes, edges, provenance and index rows, then activate.

        Postcondition: the projection is ACTIVE only if every node, edge and
        provenance row committed and the recomputed hash equals the stored hash.
        A projection that becomes eligible before its provenance is complete
        would yield a candidate that cannot be explained, so activation is the
        last statement in the transaction, never the first.

        Raises `ProjectionHashMismatchError` on drift.
        """

    def invalidate_projection(
        self, projection_id: UUID, *, reason: str
    ) -> None:
        """Move a projection out of ACTIVE and drop its index rows.

        Postcondition: within the same transaction the projection is no longer
        eligible and no summary row for it remains searchable. Split across two
        transactions, a crash between them leaves an index row granting a match
        for canonical state that no longer exists.
        """

    def list_eligible_projections(
        self, *, current_asset_id: UUID
    ) -> list[RoleGraphProjectionV1]:
        """Active, ready, non-deleted, locally permitted, and not the current asset."""

    # -- attempts (ticket 06) ---------------------------------------------
    def reserve_attempt(
        self,
        attempt: DiscoveryAttemptV1,
        *,
        fingerprint: DiscoveryFingerprintV1,
        lease_seconds: int,
    ) -> DiscoveryAttemptV1:
        """Reserve one attempt for a fingerprint before inference runs.

        The fingerprint's canonical inputs are persisted in the same
        transaction. Passing only the digest leaves the repository unable to
        record what produced it, so a cached result could never be traced back
        to the model, prompt and configuration it came from — and after a
        restart nothing could distinguish a legitimate cache hit from a stale
        entry whose inputs have since changed.

        Postcondition: at most one un-expired reservation exists per
        fingerprint, and the reservation is durable before any model call. A
        process that dies mid-flight therefore leaves a reservation that can be
        recovered or marked retryable, instead of an outcome that has to be
        assumed.

        Raises `ReservationHeldError` when another caller holds it.
        """

    def settle_attempt(
        self,
        attempt: DiscoveryAttemptV1,
        *,
        candidate: RelationCandidateV1 | None = None,
    ) -> None:
        """Record the terminal outcome of a reserved attempt, with its candidate.

        The candidate is settled here rather than through a separate call
        because the two writes are one fact. Split across transactions, a crash
        between them leaves either a CANDIDATE attempt pointing at a candidate
        that does not exist, or an orphan candidate with no successful attempt —
        and neither is detectable afterwards without comparing the two tables.

        Postcondition: at most one durable semantic result (CANDIDATE or
        NO_MATCH) exists per fingerprint; a CANDIDATE outcome and its candidate
        commit together; the reservation lease is released. Technical failures
        are retained for audit and are never reusable as a semantic result —
        reusing one would let a brief outage permanently erase a relation that
        may well exist.

        Raises `LedgerConflictError` when `attempt.outcome is CANDIDATE` and no
        candidate is supplied, or vice versa.
        """

    def read_settled_result(
        self, discovery_fingerprint: str
    ) -> DiscoveryAttemptV1 | None:
        """Return the cached semantic result for a fingerprint, if any."""

    def read_fingerprint_inputs(
        self, discovery_fingerprint: str
    ) -> DiscoveryFingerprintV1 | None:
        """Return the canonical inputs a fingerprint was computed from.

        Audit needs this: without it the digest is a number nobody can
        re-derive, so "the same input returns the same answer" cannot be
        checked against what the input actually was.
        """

    def recover_expired_reservations(self) -> int:
        """Resolve reservations whose lease expired, returning how many.

        Postcondition: an expired reservation becomes retryable, never
        successful. Assuming success would publish a candidate nobody validated.
        """

    # -- candidates and decisions (tickets 05, 07) ------------------------
    def decide_candidate(
        self,
        decision: RelationCandidateDecisionV1,
        *,
        confirmed_relation: ConfirmedAssetRelationV1 | None,
    ) -> None:
        """Record a decision and, on CONFIRM, create the relation atomically.

        Postcondition: a confirmed decision and its durable relation commit
        together. Split, a confirmed decision could exist with no relation
        record, and whether detail access worked would depend on which half
        committed.

        Raises `StaleBindingError` on any binding mismatch and
        `DecisionAlreadySettledError` on a conflicting second decision.
        """

    def list_confirmed_relations(
        self, *, current_asset_id: UUID, current_version_id: UUID
    ) -> list[ConfirmedAssetRelationV1]:
        """Return the live confirmed relations for one exact asset version.

        Public serialization needs this. Without a listing operation the only
        way to compose an export is to already know each relation id, so the
        caller with nothing to look up would emit an empty relation list — and
        the output would claim there are no relations when the ledger holds
        several, with nothing in the call to reveal the difference.

        Stale and invalidated relations are excluded: they are not relations of
        this version any more.
        """

    def read_confirmed_relation(
        self, *, relation_id: UUID, current_asset_id: UUID
    ) -> ConfirmedAssetRelationV1 | None:
        """Return the confirmed relation, re-projected from durable state.

        Authorization reads this, never a client-supplied flag and never a value
        cached in run state: a long-running run would otherwise keep authorizing
        detail reads from a set projected before the user corrected a bound
        asset.
        """

    # -- invalidation (ticket 09) -----------------------------------------
    def invalidate_for_asset_change(
        self, asset_id: UUID, *, reason: str
    ) -> None:
        """Revoke everything derived from an asset that changed.

        Postcondition: in one transaction, readiness, projections, index rows,
        candidates, decisions' access and confirmed relations bound to the old
        version are no longer usable, while the decision and attempt events
        remain readable for audit. Revoking in the interface layer only would
        leave the permission intact underneath, where a replayed request or
        another tab still reaches it.
        """
