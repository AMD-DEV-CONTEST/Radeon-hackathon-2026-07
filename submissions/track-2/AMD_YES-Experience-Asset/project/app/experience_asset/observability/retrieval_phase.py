"""Retrieval-phase events, emitted by the product path into a frozen shape.

The contract is `qa/schema/retrieval_phase_trace.schema.json` and the invariants
are `qa/scripts/check_retrieval_phase.py`. Neither is defined here; this module
only builds events that satisfy them. Writing a second definition of the shape is
how two producers end up disagreeing while both look correct.

Nothing here carries content. Every field is an identifier, a hash, a scope or a
boolean, because the trace is published as sanitized evidence and a single free
text field would make the whole artifact unpublishable.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

RETRIEVAL_TRACE_SCHEMA_VERSION = "retrieval-phase-trace/v1"

RetrievalEventType = Literal[
    "current_source_retrieval",
    "current_card_changed",
    "knowledge_card_ready",
    "relation_candidate_search",
    "relation_confirmation",
    "relation_detail_retrieval",
    "relation_no_match",
]

RetrievalScopeName = Literal["current_asset", "cross_asset_summary", "cross_asset_detail"]


def knowledge_card_ready_event(
    *,
    knowledge_card_version: UUID,
    knowledge_card_hash: str,
    milestone_state: str,
    projection_id: UUID | None = None,
    projection_hash: str | None = None,
) -> dict:
    """Ticket 03 criterion 9, and ticket 04 criterion 10.

    Criterion 10 asks for projection and index state to be observable "through
    the retrieval trace or readiness status". Acceptance is the moment both
    become true — readiness is minted and the projection activates in the same
    action — so the projection identity rides this event rather than needing an
    event type the frozen vocabulary does not have.
    """
    event: dict = {
        "event_type": "knowledge_card_ready",
        "knowledge_card_version": str(knowledge_card_version),
        "knowledge_card_hash": knowledge_card_hash,
        "milestone_state": milestone_state,
        "explicit_user_acceptance": True,
    }
    if projection_id is not None:
        event["projection_id"] = str(projection_id)
    if projection_hash is not None:
        event["projection_hash"] = projection_hash
    return event


def candidate_search_event(
    *,
    related_asset_id: UUID | None,
    eligible_count: int,
    discovery_fingerprint: str,
) -> dict:
    return {
        "event_type": "relation_candidate_search",
        "scope": "cross_asset_summary",
        "detail_included": False,
        "eligible_count": eligible_count,
        "discovery_fingerprint": discovery_fingerprint,
        **({"related_asset_id": str(related_asset_id)} if related_asset_id else {}),
    }


def candidate_search_denied_event(*, denial_reason: str) -> dict:
    """A refused attempt, which is not a retrieval and must not read as one.

    Ticket 03 criterion 9 requires the denial reason on the record. The frozen
    vocabulary has no way to say "refused", and a plain `relation_candidate_search`
    before readiness is exactly what the checker flags CRITICAL — correctly, for
    a search that ran. This event says the opposite happened: nothing was read,
    nothing was sent to a model, and the reason is on the record.

    The extra keys are admitted by `additionalProperties: true` on the event
    schema, so no schema change is involved. The checker gains one rule.
    """
    return {
        "event_type": "relation_candidate_search",
        "scope": "cross_asset_summary",
        "detail_included": False,
        "denied": True,
        "denial_reason": denial_reason,
    }


def no_match_event(*, discovery_fingerprint: str) -> dict:
    return {
        "event_type": "relation_no_match",
        "scope": "cross_asset_summary",
        "detail_included": False,
        "discovery_fingerprint": discovery_fingerprint,
    }


def relation_confirmation_event(
    *, related_asset_id: UUID, relation_id: UUID | None, confirmed: bool
) -> dict:
    return {
        "event_type": "relation_confirmation",
        "related_asset_id": str(related_asset_id),
        "confirmed": confirmed,
        **({"relation_id": str(relation_id)} if relation_id else {}),
    }


def detail_retrieval_event(
    *,
    related_asset_id: UUID,
    relation_id: UUID,
    knowledge_card_version: UUID,
    provenance_refs: list[str],
    current_statements_hash_before: str,
    current_statements_hash_after: str,
) -> dict:
    """Ticket 08 criterion 8.

    The two hashes are carried rather than a single "unchanged" boolean. A
    boolean is a claim the emitter makes about itself; two hashes are a fact a
    reader can check, and the checker does check them against each other.
    """
    return {
        "event_type": "relation_detail_retrieval",
        "scope": "cross_asset_detail",
        "detail_included": True,
        "related_asset_id": str(related_asset_id),
        "relation_id": str(relation_id),
        "knowledge_card_version": str(knowledge_card_version),
        "provenance_refs": provenance_refs,
        "mutated_current_statements": False,
        "current_statements_hash_before": current_statements_hash_before,
        "current_statements_hash_after": current_statements_hash_after,
    }


def current_card_changed_event(*, knowledge_card_version: UUID | None = None) -> dict:
    """Emitted when the card moves, which resets readiness in the checker.

    Without it a trace would show a card ready, then a search, with nothing in
    between explaining why the readiness the search relied on had gone.
    """
    return {
        "event_type": "current_card_changed",
        **(
            {"knowledge_card_version": str(knowledge_card_version)}
            if knowledge_card_version
            else {}
        ),
    }
