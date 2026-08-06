"""The bounded detail read.

The user confirmed one comparison. That confirmation authorises reading the
historical material reachable from the validated mapping and the boundary
package — and nothing else. An unrestricted read of the confirmed asset would
turn one approved comparison into a general search over that history, which is
more than the user agreed to, and the difference would be invisible in the
rendered card.

Reachability is therefore computed from the relation's own package rather than
from the asset: the mapped node identifiers plus the boundary node identifiers
name the nodes, and each node's stored provenance names the statements,
evidence, sources and spans behind it. Nothing outside that closure is read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from app.experience_asset.domain.relation import (
    NodeProvenanceV1,
    RelationCandidateV1,
    RoleGraphProjectionV1,
)


@dataclass(frozen=True)
class BoundedDetailRequest:
    """The exact node closure one confirmed relation authorises, per side."""

    current_node_ids: tuple[str, ...]
    historical_node_ids: tuple[str, ...]

    @classmethod
    def from_candidate(cls, candidate: RelationCandidateV1) -> BoundedDetailRequest:
        """Derive the closure from the validated package the user confirmed.

        Mapped nodes and boundary nodes are both included: the mapping is what
        the relation claims, and the boundary is the condition under which the
        claim transfers. Dropping the boundary would leave a card that states a
        correspondence without the limit that makes it safe to reuse.
        """
        current = [mapping.current_node_id for mapping in candidate.node_mappings]
        current.extend(candidate.current_boundary_node_ids)
        historical = [mapping.historical_node_id for mapping in candidate.node_mappings]
        historical.extend(candidate.historical_boundary_node_ids)
        return cls(
            current_node_ids=tuple(_ordered_unique(current)),
            historical_node_ids=tuple(_ordered_unique(historical)),
        )


@dataclass(frozen=True)
class BoundedDetailSet:
    """Everything the card is allowed to quote, and what could not be resolved.

    `missing_node_ids` and `nodes_without_provenance` are carried rather than
    dropped. A card missing half its provenance still looks authoritative, so
    the caller needs the gap as data in order to refuse instead of rendering a
    partial card that reads as complete.
    """

    provenance_by_node: dict[str, NodeProvenanceV1]
    statement_ids: tuple[UUID, ...]
    evidence_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    span_refs: tuple[str, ...]
    missing_node_ids: tuple[str, ...] = field(default=())
    nodes_without_provenance: tuple[str, ...] = field(default=())

    @property
    def is_complete(self) -> bool:
        return not self.missing_node_ids and not self.nodes_without_provenance


def resolve_bounded_detail(
    projection: RoleGraphProjectionV1,
    node_ids: tuple[str, ...],
) -> BoundedDetailSet:
    """Resolve one side's closure against its stored projection.

    Reads only the named nodes. A node that the projection does not carry, or
    carries without provenance, is reported rather than skipped — silently
    skipping it is what produces the authoritative-looking partial card.
    """
    nodes_by_id = {node.node_id: node for node in projection.nodes}
    provenance_by_id = {entry.node_id: entry for entry in projection.provenance}

    resolved: dict[str, NodeProvenanceV1] = {}
    missing: list[str] = []
    without_provenance: list[str] = []

    statement_ids: list[UUID] = []
    evidence_refs: list[str] = []
    source_refs: list[str] = []
    span_refs: list[str] = []

    for node_id in node_ids:
        if node_id not in nodes_by_id:
            missing.append(node_id)
            continue
        entry = provenance_by_id.get(node_id)
        if entry is None:
            without_provenance.append(node_id)
            continue
        resolved[node_id] = entry
        statement_ids.extend(entry.statement_ids)
        evidence_refs.extend(entry.evidence_refs)
        source_refs.extend(entry.source_refs)
        span_refs.extend(entry.span_refs)

    return BoundedDetailSet(
        provenance_by_node=resolved,
        statement_ids=tuple(_ordered_unique(statement_ids)),
        evidence_refs=tuple(_ordered_unique(evidence_refs)),
        source_refs=tuple(_ordered_unique(source_refs)),
        span_refs=tuple(_ordered_unique(span_refs)),
        missing_node_ids=tuple(missing),
        nodes_without_provenance=tuple(without_provenance),
    )


def _ordered_unique[T](values: list[T]) -> list[T]:
    """De-duplicate while keeping first-seen order.

    Order is part of the card's determinism: the same relation must render the
    same bytes, and a set would make the reference lists depend on hash seeding.
    """
    seen: set[T] = set()
    out: list[T] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
