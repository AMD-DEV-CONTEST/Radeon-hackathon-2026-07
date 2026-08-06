"""Deterministic bilateral evidence card.

What the user gets after confirming is the comparison they were deciding about:
both sides' canonical content, side by side, with the identifiers that let them
open the underlying material. Not a conclusion about it.

Two canonical statement lists side by side look raw, and summarising them is the
obvious polish. It fails for a specific reason: the summary is a new artifact
produced *after* the confirmation gate, so the user never reviewed it, and it
will read as a faithful description of the relation they did approve while being
free to drift from it. The value here is a surface the user can form their own
judgement on, which is precisely what a generated conclusion would take away.

So the effort goes into deterministic structure instead: each mapped role
labelled with its canonical content, the transfer boundary quoted from its
source, and provenance identifiers on both sides.
"""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from app.experience_asset.domain.enums import (
    EvidenceCardRefusalReason,
    RelationLifecycle,
    RelationType,
)
from app.experience_asset.domain.relation import (
    EVIDENCE_CARD_SCHEMA_VERSION,
    ConfirmedAssetRelationV1,
    EvidenceCardRefusalV1,
    EvidenceCardV1,
    MappedRoleEvidenceV1,
    RelationCandidateV1,
    RoleGraphProjectionV1,
    SideProvenanceV1,
    TransferBoundaryV1,
)

from .detail_read import BoundedDetailRequest, BoundedDetailSet, resolve_bounded_detail

# Ticket 01 owns these shapes; this module composes them. They lived here while
# ticket 01 had no field for the card, which left two structurally identical
# definitions of one contract in two layers — the state where a change to either
# is silently not a change to the other.
EvidenceCardRefusal = EvidenceCardRefusalV1

EvidenceCardResult = EvidenceCardV1 | EvidenceCardRefusal


def compute_evidence_card_hash(
    *,
    relation_id: UUID,
    relation_type: RelationType,
    current_knowledge_card_hash: str,
    mapped_roles: list[MappedRoleEvidenceV1],
    boundaries: list[TransferBoundaryV1],
    provenance: list[SideProvenanceV1],
) -> str:
    """Canonical hash over the card's content.

    Sorted and field-ordered for the same reason `compute_projection_hash` is:
    two callers rendering the same relation must agree, and an unspecified hash
    input would make a determinism test pass or fail on read order.

    Labels enter as their hashes, not their text, so the hash is stable under
    encoding differences in transport while still changing if the quoted content
    changes.
    """

    def enum_value(value: object) -> str:
        return str(getattr(value, "value", value)) if value is not None else ""

    payload = {
        "card_schema_version": EVIDENCE_CARD_SCHEMA_VERSION,
        "relation_id": str(relation_id),
        "relation_type": enum_value(relation_type),
        "current_knowledge_card_hash": current_knowledge_card_hash,
        "mapped_roles": sorted(
            [
                [
                    role.current_node_id,
                    role.historical_node_id,
                    enum_value(role.current_role),
                    enum_value(role.historical_role),
                    role.current_label_hash,
                    role.historical_label_hash,
                ]
                for role in mapped_roles
            ]
        ),
        "boundaries": sorted(
            [
                [
                    boundary.side,
                    boundary.node_id,
                    enum_value(boundary.role),
                    boundary.content_hash,
                ]
                for boundary in boundaries
            ]
        ),
        "provenance": sorted(
            [
                [
                    entry.side,
                    str(entry.asset_id),
                    str(entry.projection_id),
                    sorted(entry.node_ids),
                    sorted(str(value) for value in entry.statement_ids),
                    sorted(entry.evidence_refs),
                    sorted(entry.source_refs),
                    sorted(entry.span_refs),
                ]
                for entry in provenance
            ]
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def render_evidence_card(
    *,
    relation: ConfirmedAssetRelationV1,
    candidate: RelationCandidateV1,
    current_projection: RoleGraphProjectionV1,
    historical_projection: RoleGraphProjectionV1,
    historical_read_permitted: bool = True,
) -> EvidenceCardResult:
    """Render the card, or refuse with a typed reason.

    Pure application code: no model call, no generated text, no advice. Every
    string on the card is copied from a projection node the user can open.
    """
    if relation.lifecycle is not RelationLifecycle.CONFIRMED:
        # The lifecycle reaches here both as a validated enum member and as the
        # raw string a dict-loaded row carries, and the refusal must read the
        # same either way — a crash while explaining a revoked relation would
        # turn a fail-closed path into a 500.
        lifecycle = getattr(relation.lifecycle, "value", relation.lifecycle)
        return EvidenceCardRefusal(
            reason=EvidenceCardRefusalReason.RELATION_NOT_LIVE,
            detail=(
                f"relation is {lifecycle}; a revoked relation "
                "carries no read grant, and rendering it anyway would serve "
                "content the user's confirmation no longer covers"
            ),
        )

    if not historical_read_permitted:
        return EvidenceCardRefusal(
            reason=EvidenceCardRefusalReason.PERMISSION_REVOKED,
            detail=(
                "read permission on the historical asset has been withdrawn; "
                "the card is refused whole rather than rendered without the "
                "historical side"
            ),
        )

    mismatch = _binding_mismatch(
        relation=relation,
        candidate=candidate,
        current_projection=current_projection,
        historical_projection=historical_projection,
    )
    if mismatch is not None:
        return EvidenceCardRefusal(
            reason=EvidenceCardRefusalReason.BINDING_MISMATCH,
            detail=mismatch,
        )

    closure = BoundedDetailRequest.from_candidate(candidate)
    current_detail = resolve_bounded_detail(current_projection, closure.current_node_ids)
    historical_detail = resolve_bounded_detail(
        historical_projection, closure.historical_node_ids
    )

    refusal = _refuse_incomplete(current_detail, historical_detail)
    if refusal is not None:
        return refusal

    current_nodes = {node.node_id: node for node in current_projection.nodes}
    historical_nodes = {node.node_id: node for node in historical_projection.nodes}

    mapped_roles: list[MappedRoleEvidenceV1] = []
    for mapping in candidate.node_mappings:
        current_node = current_nodes[mapping.current_node_id]
        historical_node = historical_nodes[mapping.historical_node_id]
        mapped_roles.append(
            MappedRoleEvidenceV1(
                current_node_id=mapping.current_node_id,
                historical_node_id=mapping.historical_node_id,
                current_role=mapping.current_role,
                historical_role=mapping.historical_role,
                current_label=current_node.summary_text,
                historical_label=historical_node.summary_text,
                current_label_hash=current_node.summary_text_hash,
                historical_label_hash=historical_node.summary_text_hash,
            )
        )

    boundaries: list[TransferBoundaryV1] = []
    for node_id in candidate.current_boundary_node_ids:
        node = current_nodes[node_id]
        boundaries.append(
            TransferBoundaryV1(
                side="CURRENT",
                node_id=node_id,
                role=node.role,
                content=node.summary_text,
                content_hash=node.summary_text_hash,
            )
        )
    for node_id in candidate.historical_boundary_node_ids:
        node = historical_nodes[node_id]
        boundaries.append(
            TransferBoundaryV1(
                side="HISTORICAL",
                node_id=node_id,
                role=node.role,
                content=node.summary_text,
                content_hash=node.summary_text_hash,
            )
        )

    provenance = [
        SideProvenanceV1(
            side="CURRENT",
            asset_id=relation.current_asset_id,
            projection_id=relation.current_projection_id,
            node_ids=list(closure.current_node_ids),
            statement_ids=list(current_detail.statement_ids),
            evidence_refs=list(current_detail.evidence_refs),
            source_refs=list(current_detail.source_refs),
            span_refs=list(current_detail.span_refs),
        ),
        SideProvenanceV1(
            side="HISTORICAL",
            asset_id=relation.related_asset_id,
            projection_id=relation.historical_projection_id,
            node_ids=list(closure.historical_node_ids),
            statement_ids=list(historical_detail.statement_ids),
            evidence_refs=list(historical_detail.evidence_refs),
            source_refs=list(historical_detail.source_refs),
            span_refs=list(historical_detail.span_refs),
        ),
    ]

    return EvidenceCardV1(
        relation_id=relation.relation_id,
        relation_type=relation.relation_type,
        current_asset_id=relation.current_asset_id,
        current_version_id=relation.current_version_id,
        current_knowledge_card_hash=relation.current_knowledge_card_hash,
        related_asset_id=relation.related_asset_id,
        related_version_id=relation.related_version_id,
        mapped_roles=mapped_roles,
        boundaries=boundaries,
        provenance=provenance,
        card_hash=compute_evidence_card_hash(
            relation_id=relation.relation_id,
            relation_type=relation.relation_type,
            current_knowledge_card_hash=relation.current_knowledge_card_hash,
            mapped_roles=mapped_roles,
            boundaries=boundaries,
            provenance=provenance,
        ),
    )


def _binding_mismatch(
    *,
    relation: ConfirmedAssetRelationV1,
    candidate: RelationCandidateV1,
    current_projection: RoleGraphProjectionV1,
    historical_projection: RoleGraphProjectionV1,
) -> str | None:
    """Recheck every binding the confirmation was made against.

    A mismatch fails closed rather than being resolved against whatever is
    current, because resolving it silently would render content the user
    approved a different comparison for.
    """
    if candidate.candidate_id != relation.source_candidate_id:
        return (
            "the supplied candidate is not the proposal this relation was "
            "confirmed from"
        )
    if current_projection.projection_id != relation.current_projection_id:
        return "current projection does not match the relation's binding"
    if historical_projection.projection_id != relation.historical_projection_id:
        return "historical projection does not match the relation's binding"
    if current_projection.asset_id != relation.current_asset_id:
        return "current projection belongs to a different asset"
    if historical_projection.asset_id != relation.related_asset_id:
        return "historical projection belongs to a different asset"
    if current_projection.knowledge_card_hash != relation.current_knowledge_card_hash:
        return (
            "the current Knowledge Card hash has moved since confirmation; the "
            "comparison the user approved was against different content"
        )
    return None


def _refuse_incomplete(
    current_detail: BoundedDetailSet,
    historical_detail: BoundedDetailSet,
) -> EvidenceCardRefusal | None:
    """Turn any gap in the approved closure into a whole-card refusal."""
    missing_nodes = [
        *current_detail.missing_node_ids,
        *historical_detail.missing_node_ids,
    ]
    if missing_nodes:
        return EvidenceCardRefusal(
            reason=EvidenceCardRefusalReason.CONTENT_UNAVAILABLE,
            detail=(
                "content named by the approved comparison is deleted or "
                "privacy-restricted; the card is refused rather than rendered "
                "with the remainder"
            ),
            unresolved_node_ids=missing_nodes,
        )

    unbacked = [
        *current_detail.nodes_without_provenance,
        *historical_detail.nodes_without_provenance,
    ]
    if unbacked:
        return EvidenceCardRefusal(
            reason=EvidenceCardRefusalReason.PARTIAL_PROVENANCE,
            detail=(
                "a node in the approved comparison carries no provenance; a card "
                "missing half its provenance still looks authoritative, so it is "
                "refused instead"
            ),
            unresolved_node_ids=unbacked,
        )

    for detail in (current_detail, historical_detail):
        if not detail.statement_ids:
            return EvidenceCardRefusal(
                reason=EvidenceCardRefusalReason.MISSING_REFERENCES,
                detail=(
                    "one side resolved to no statements at all, so there is "
                    "nothing on that side the user could open and check"
                ),
            )
    return None
