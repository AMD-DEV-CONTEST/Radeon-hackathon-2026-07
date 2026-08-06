"""The mutation-by-artifact invalidation matrix.

Ticket 09 owns the orchestration nobody else can: which of eight artifacts each
mutation touches, and what state each one moves to. It is written as data
because the alternative is a fresh judgement per event about eight artifacts,
and the artifacts nobody thought of stay live — a permission left granted is
invisible from the outside, unlike a state left wrong.

The outcomes below are *transitions this orchestration performs*, not new
lifecycle vocabulary. Readiness, projection, candidate and relation states are
defined by tickets 03, 04, 06, 07 and 08, and this module only selects among
them. A second definition here would give one record two lifecycle
descriptions, with the applicable one depending on which code path ran.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType


class MutationEvent(StrEnum):
    """The six events BOUNDARIES.md §2 fixed as triggering invalidation."""

    CURRENT_ASSET_CORRECTION = "CURRENT_ASSET_CORRECTION"
    RELATED_ASSET_CHANGE = "RELATED_ASSET_CHANGE"
    ASSET_DELETION = "ASSET_DELETION"
    PRIVACY_NARROWING = "PRIVACY_NARROWING"
    PROJECTION_SCHEMA_CHANGE = "PROJECTION_SCHEMA_CHANGE"
    MODEL_OR_PROMPT_CHANGE = "MODEL_OR_PROMPT_CHANGE"


class Artifact(StrEnum):
    """Everything a mutation can leave behind.

    `INDEX_ELIGIBILITY` and `DETAIL_PERMISSION` are listed separately from the
    records that carry them because they are the two that fail silently: an
    index row still grants comparability for canonical state that no longer
    exists, and a permission still authorizes a detail read from a replayed
    request or another tab.
    """

    READINESS = "READINESS"
    PROJECTION = "PROJECTION"
    INDEX_ELIGIBILITY = "INDEX_ELIGIBILITY"
    ATTEMPT = "ATTEMPT"
    CANDIDATE = "CANDIDATE"
    DECISION = "DECISION"
    RELATION = "RELATION"
    DETAIL_PERMISSION = "DETAIL_PERMISSION"


class Outcome(StrEnum):
    """What this orchestration does to an artifact.

    `STALE` and `INVALIDATED` are distinct on purpose. Stale means the basis of
    a comparison moved and the user must choose to look again; invalidated means
    the thing it described is gone. Collapsing them would either force a user to
    redo work on an asset nobody touched, or leave a relation reachable whose
    subject no longer exists.
    """

    UNCHANGED = "UNCHANGED"
    STALE = "STALE"
    INVALIDATED = "INVALIDATED"
    REVOKED = "REVOKED"
    RETAINED_FOR_AUDIT = "RETAINED_FOR_AUDIT"


def _row(
    *,
    readiness: Outcome,
    projection: Outcome,
    index: Outcome,
    candidate: Outcome,
    relation: Outcome,
    detail: Outcome,
) -> Mapping[Artifact, Outcome]:
    """One matrix row.

    Attempts and decisions are not parameters: they are append-only records of
    what happened, and no event may move them. Deleting or rewriting one would
    make an invalidated relation indistinguishable from one that never existed,
    which is precisely what a reviewer needs to tell apart.
    """
    return MappingProxyType(
        {
            Artifact.READINESS: readiness,
            Artifact.PROJECTION: projection,
            Artifact.INDEX_ELIGIBILITY: index,
            Artifact.ATTEMPT: Outcome.RETAINED_FOR_AUDIT,
            Artifact.CANDIDATE: candidate,
            Artifact.DECISION: Outcome.RETAINED_FOR_AUDIT,
            Artifact.RELATION: relation,
            Artifact.DETAIL_PERMISSION: detail,
        }
    )


INVALIDATION_MATRIX: Mapping[MutationEvent, Mapping[Artifact, Outcome]] = (
    MappingProxyType(
        {
            # The card was accepted against content that no longer exists, so
            # everything downstream of that acceptance is void rather than
            # merely out of date.
            MutationEvent.CURRENT_ASSET_CORRECTION: _row(
                readiness=Outcome.INVALIDATED,
                projection=Outcome.INVALIDATED,
                index=Outcome.REVOKED,
                candidate=Outcome.INVALIDATED,
                relation=Outcome.INVALIDATED,
                detail=Outcome.REVOKED,
            ),
            # GRAG-16. The referencing asset did not change, so its readiness
            # must survive: invalidating it would force the user to redo an
            # acceptance on an asset nobody touched. What moved is the basis of
            # the comparison, so the comparison goes stale and waits for an
            # explicit new discovery.
            MutationEvent.RELATED_ASSET_CHANGE: _row(
                readiness=Outcome.UNCHANGED,
                projection=Outcome.INVALIDATED,
                index=Outcome.REVOKED,
                candidate=Outcome.STALE,
                relation=Outcome.STALE,
                detail=Outcome.REVOKED,
            ),
            # Access ends immediately and does not wait for a new discovery:
            # the subject is gone, so there is nothing for the user to decide
            # about.
            MutationEvent.ASSET_DELETION: _row(
                readiness=Outcome.INVALIDATED,
                projection=Outcome.INVALIDATED,
                index=Outcome.REVOKED,
                candidate=Outcome.INVALIDATED,
                relation=Outcome.INVALIDATED,
                detail=Outcome.REVOKED,
            ),
            # Same revocation as deletion, but the content was not deleted, so
            # the copies inside the ledger are not redacted — see
            # `REDACTS_COPIED_CONTENT` below.
            MutationEvent.PRIVACY_NARROWING: _row(
                readiness=Outcome.INVALIDATED,
                projection=Outcome.INVALIDATED,
                index=Outcome.REVOKED,
                candidate=Outcome.INVALIDATED,
                relation=Outcome.INVALIDATED,
                detail=Outcome.REVOKED,
            ),
            # A mapping validated under one role contract has no defined
            # meaning under another, so old projections stop being comparable
            # while staying readable for audit. The acceptance itself was about
            # the card's content, not its projection, and survives.
            MutationEvent.PROJECTION_SCHEMA_CHANGE: _row(
                readiness=Outcome.UNCHANGED,
                projection=Outcome.INVALIDATED,
                index=Outcome.REVOKED,
                candidate=Outcome.STALE,
                relation=Outcome.STALE,
                detail=Outcome.REVOKED,
            ),
            # Nothing is revoked. A new model, prompt or configuration produces
            # a different discovery fingerprint, so the earlier answer is simply
            # not offered for the new question — the mechanism is the
            # fingerprint, not invalidation. Invalidating here would discard
            # relations the user confirmed, on the grounds that an unrelated
            # component was upgraded.
            MutationEvent.MODEL_OR_PROMPT_CHANGE: _row(
                readiness=Outcome.UNCHANGED,
                projection=Outcome.UNCHANGED,
                index=Outcome.UNCHANGED,
                candidate=Outcome.UNCHANGED,
                relation=Outcome.UNCHANGED,
                detail=Outcome.UNCHANGED,
            ),
        }
    )
)

REDACTS_COPIED_CONTENT: frozenset[MutationEvent] = frozenset({MutationEvent.ASSET_DELETION})
"""Events after which cross-asset copies of the content must not survive.

Only deletion. A candidate holds a title and summary describing the related
asset, and keeping them after that asset is deleted would recreate, inside the
audit trail, exactly the copy the deletion was meant to remove. Identifiers and
hashes stay: they are what makes the record auditable, and they are not the
content.

Privacy narrowing is deliberately absent. It revokes access to content that
still exists and that the user did not ask to erase; redacting the ledger there
would destroy audit detail without any deletion request behind it.
"""
