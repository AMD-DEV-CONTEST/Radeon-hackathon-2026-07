"""Runtime validation of one discovery proposal against stored projections.

Every identifier the model returns is checked against a projection the Runtime
supplied. Nothing here trusts a label, a node name or a side attribution — the
model's useful contribution is judging structural correspondence among graphs it
was handed, and anything beyond that is unverifiable by construction.

A rejection is never reported as `NO_MATCH`. No-match is a semantic claim the
system caches; a proposal that failed validation supports no such claim, and
caching it would file a transport accident as a proven absence which stays
invisible until something unrelated moves the fingerprint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.experience_asset.domain.enums import (
    ProjectionEdgeType,
    RelationLifecycle,
    RelationType,
)
from app.experience_asset.domain.relation import (
    RELATION_ADMISSIBILITY,
    RELATION_CONTRACT_VERSION,
    RelationCandidateV1,
    RoleGraphProjectionV1,
)
from app.experience_asset.inference.models import RelationDiscoveryProposal

BOUNDARY_ROLES: frozenset[ProjectionEdgeType] = frozenset(
    {
        ProjectionEdgeType.HAS_LIMITATION,
        ProjectionEdgeType.HAS_APPLICABILITY,
        ProjectionEdgeType.HAS_COUNTEREXAMPLE,
    }
)
"""Roles that can ground a transfer boundary on the current side.

A relation shown without one invites the reader to treat structural similarity
as permission to transfer the lesson wholesale, which is the specific harm the
boundary requirement exists to prevent.
"""


class ProposalRejected(ValueError):
    """The proposal failed a Runtime check; no candidate may be exposed."""

    def __init__(self, defect: str, message: str) -> None:
        super().__init__(message)
        self.defect = defect


def _nodes(projection: RoleGraphProjectionV1) -> dict[str, object]:
    return {node.node_id: node for node in projection.nodes}


def validate_relation_proposal(
    proposal: RelationDiscoveryProposal,
    *,
    current_projection: RoleGraphProjectionV1,
    eligible: dict[UUID, RoleGraphProjectionV1],
    discovery_fingerprint: str,
) -> RelationCandidateV1:
    """Turn a proposal into a candidate, or refuse with a named defect."""

    if proposal.outcome != "CANDIDATE":
        raise ProposalRejected("not-a-candidate", "the proposal claims no candidate")

    # -- the relation label is data, judged here rather than at the parser ----
    try:
        relation_type = RelationType(str(proposal.relation_type))
    except ValueError as exc:
        raise ProposalRejected(
            "forbidden-label",
            "the relation type is outside the six frozen values; a label with no "
            "admissibility rule behind it leaves the user unable to judge what it claims",
        ) from exc

    if proposal.historical_projection_id is None:
        raise ProposalRejected("nonexistent-node", "the proposal names no historical projection")
    historical = eligible.get(proposal.historical_projection_id)
    if historical is None:
        raise ProposalRejected(
            "nonexistent-node",
            "the historical projection was not one of the graphs the Runtime supplied",
        )
    if (
        proposal.related_asset_id is not None
        and proposal.related_asset_id != historical.asset_id
    ):
        raise ProposalRejected(
            "wrong-side-node",
            "the named related asset does not own the named historical projection",
        )
    if historical.asset_id == current_projection.asset_id:
        raise ProposalRejected(
            "wrong-side-node", "an asset cannot be related to itself"
        )

    current_nodes = _nodes(current_projection)
    historical_nodes = _nodes(historical)

    if not proposal.node_mappings:
        raise ProposalRejected("nonexistent-node", "a candidate requires a node mapping")

    mappings = []
    role_pairs: list[tuple[ProjectionEdgeType, ProjectionEdgeType]] = []
    for mapping in proposal.node_mappings:
        current_node = current_nodes.get(mapping.current_node_id)
        historical_node = historical_nodes.get(mapping.historical_node_id)
        # Checked per side. A single "does this id exist anywhere" test would
        # accept a current-side node submitted as the historical one, and the
        # explanation would then describe the user's own asset as the history it
        # is being compared against.
        if current_node is None:
            if mapping.current_node_id in historical_nodes:
                raise ProposalRejected(
                    "wrong-side-node",
                    "a historical node was submitted on the current side",
                )
            raise ProposalRejected(
                "nonexistent-node", "the current-side node is not in the stored projection"
            )
        if historical_node is None:
            if mapping.historical_node_id in current_nodes:
                raise ProposalRejected(
                    "wrong-side-node",
                    "a current node was submitted on the historical side",
                )
            raise ProposalRejected(
                "nonexistent-node",
                "the historical-side node is not in the stored projection",
            )
        mappings.append(
            {
                "current_node_id": current_node.node_id,
                "historical_node_id": historical_node.node_id,
                "current_role": current_node.role,
                "historical_role": historical_node.role,
            }
        )
        if current_node.role is not None and historical_node.role is not None:
            role_pairs.append((current_node.role, historical_node.role))

    # -- admissibility -------------------------------------------------------
    admissible = RELATION_ADMISSIBILITY[relation_type]
    if admissible:
        if not role_pairs or not any(pair in admissible for pair in role_pairs):
            raise ProposalRejected(
                "inadmissible-role-pair",
                f"no mapped role pair is admissible for {relation_type.value}",
            )
    elif any(pair is not None for mapping in mappings for pair in (mapping["current_role"],)):
        # SAME_THEME is a root-to-root claim; a member mapping would assert a
        # correspondence between things of different kinds.
        raise ProposalRejected(
            "inadmissible-role-pair",
            "SAME_THEME requires a root-to-root mapping",
        )

    # -- boundary ------------------------------------------------------------
    boundary_ids = [
        node_id
        for node_id in proposal.current_boundary_node_ids
        if node_id in current_nodes
    ]
    if len(boundary_ids) != len(proposal.current_boundary_node_ids):
        raise ProposalRejected(
            "nonexistent-node", "a boundary node is not in the current projection"
        )
    grounded = [
        node_id
        for node_id in boundary_ids
        if getattr(current_nodes[node_id], "role", None) in BOUNDARY_ROLES
    ]
    if not grounded:
        raise ProposalRejected(
            "missing-boundary",
            "the current side carries no source-grounded transfer boundary; without "
            "one the reader is invited to treat similarity as permission to transfer",
        )

    historical_boundary = [
        node_id
        for node_id in proposal.historical_boundary_node_ids
        if node_id in historical_nodes
    ]
    if len(historical_boundary) != len(proposal.historical_boundary_node_ids):
        raise ProposalRejected(
            "nonexistent-node", "a boundary node is not in the historical projection"
        )

    # -- provenance, rendered by the Runtime rather than proposed ------------
    provenance = []
    for side, projection, node_ids in (
        ("CURRENT", current_projection, [m["current_node_id"] for m in mappings] + grounded),
        (
            "HISTORICAL",
            historical,
            [m["historical_node_id"] for m in mappings] + historical_boundary,
        ),
    ):
        by_node = {entry.node_id: entry for entry in projection.provenance}
        for node_id in dict.fromkeys(node_ids):
            entry = by_node.get(node_id)
            if entry is None:
                continue
            provenance.append(
                {
                    "side": side,
                    "node_id": node_id,
                    "statement_ids": [str(item) for item in entry.statement_ids],
                    "evidence_refs": list(entry.evidence_refs),
                    "source_refs": list(entry.source_refs),
                }
            )
    sides = {entry["side"] for entry in provenance}
    if sides != {"CURRENT", "HISTORICAL"}:
        raise ProposalRejected(
            "one-sided-provenance",
            "a bilateral explanation needs provenance from both sides; one side "
            "alone cannot say which asset a reference belongs to",
        )

    return RelationCandidateV1(
        candidate_id=uuid4(),
        discovery_fingerprint=discovery_fingerprint,
        current_asset_id=current_projection.asset_id,
        current_projection_id=current_projection.projection_id,
        related_asset_id=historical.asset_id,
        historical_projection_id=historical.projection_id,
        relation_type=relation_type,
        # Title and summary are canonical node labels, never model prose.
        title=str(current_nodes[mappings[0]["current_node_id"]].summary_text)[:240],
        summary=str(historical_nodes[mappings[0]["historical_node_id"]].summary_text)[:400],
        node_mappings=mappings,
        current_boundary_node_ids=grounded,
        historical_boundary_node_ids=historical_boundary,
        provenance=provenance,
        validation_contract_version=RELATION_CONTRACT_VERSION,
        lifecycle=RelationLifecycle.PROPOSED,
        detail_included=False,
        created_at=datetime.now(UTC),
    )
