"""The bounded detail read, with its retrieval-phase event.

Ticket 08 criterion 8 asks the trace to record the bounded access, its
provenance references, and the unchanged current-statement hash. The three
belong together in one function rather than three call sites: an emitter that
runs beside the read instead of around it can report a hash it never compared,
and the invariant the event exists to prove would be asserted by the same code
that could violate it.

The HTTP handler still raises the typed not-implemented, because
`RelationWorkspaceV1` has no field the card can occupy — that contract change is
on `e5/t01-evidence-card-field`. This function is what the handler calls when it
lands, and it is exercised directly until then.
"""

from __future__ import annotations

from uuid import UUID

from app.experience_asset.domain.relation import (
    ConfirmedAssetRelationV1,
    RelationCandidateV1,
    RoleGraphProjectionV1,
)
from app.experience_asset.observability.retrieval_phase import detail_retrieval_event
from app.experience_asset.persistence import SQLiteAssetRepository

from .card import EvidenceCardRefusal, EvidenceCardResult, render_evidence_card
from .detail_read import resolve_bounded_detail


def read_evidence_card_traced(
    repository: SQLiteAssetRepository,
    *,
    relation: ConfirmedAssetRelationV1,
    candidate: RelationCandidateV1,
    current_projection: RoleGraphProjectionV1,
    historical_projection: RoleGraphProjectionV1,
) -> EvidenceCardResult:
    """Render the card and record the access, or refuse and record nothing.

    A refusal emits no event on purpose. The trace's job is to say what was
    read; logging a read that did not happen would put a `cross_asset_detail`
    event on the record for an access the gate refused, and the checker would
    then be validating a fiction.
    """
    before = repository.get_version_content_hash(relation.current_version_id)

    result = render_evidence_card(
        relation=relation,
        candidate=candidate,
        current_projection=current_projection,
        historical_projection=historical_projection,
    )
    if isinstance(result, EvidenceCardRefusal):
        return result

    provenance_refs = _provenance_refs(
        historical_projection,
        tuple(item.historical_node_id for item in result.mapped_roles),
    )
    after = repository.get_version_content_hash(relation.current_version_id)

    repository.record_retrieval_event(
        relation.current_asset_id,
        detail_retrieval_event(
            related_asset_id=relation.related_asset_id,
            relation_id=relation.relation_id,
            knowledge_card_version=relation.current_version_id,
            provenance_refs=provenance_refs,
            current_statements_hash_before=before,
            current_statements_hash_after=after,
        ),
    )
    return result


def _provenance_refs(
    projection: RoleGraphProjectionV1, node_ids: tuple[str, ...]
) -> list[str]:
    """Identifiers only — the trace is published, so it carries no content."""
    detail = resolve_bounded_detail(projection, node_ids)
    return [
        f"asset:{projection.asset_id}/projection:{projection.projection_id}"
        f"/statement:{statement_id}"
        for statement_id in detail.statement_ids
    ]


def bounded_read_asset_id(relation: ConfirmedAssetRelationV1) -> UUID:
    return relation.current_asset_id
