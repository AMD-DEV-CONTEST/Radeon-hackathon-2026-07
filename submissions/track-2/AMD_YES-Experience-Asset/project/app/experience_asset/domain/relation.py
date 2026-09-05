"""Frozen E5 relation-ledger contracts.

The relation ledger is the sole persistence authority for readiness, role-graph
projections, discovery attempts, candidates, decisions and confirmed relations.
It is a sidecar in the same SQLite database, deliberately separate from the
immutable Experience Asset snapshot.

Why not inside the snapshot: the snapshot is immutable and content-hashed, so
persisting a confirmation there would append a new asset content version and
change the content hash — while GRAG-14 requires that hash to be identical
before and after a relation read. Both cannot hold, which makes the embedded
design unable to satisfy AC-30 non-contamination.

Readiness retires from the snapshot for a different reason. It is created by an
explicit user action after a version exists, so storing it needs a new version;
the version recording readiness would then be permanently one step ahead of the
version judged ready, or self-referential if it points at itself.

These contracts carry no behaviour. Ticket 04 builds projections, ticket 05
validates candidates, ticket 06 owns the attempt envelope, ticket 07 owns
decisions and confirmation, ticket 08 owns the evidence card.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from .enums import (
    DiscoveryFailureClass,
    DiscoveryOutcome,
    EvidenceCardRefusalReason,
    MilestoneState,
    ProjectionEdgeType,
    ProjectionLifecycle,
    ProjectionRootKind,
    ReadinessLifecycle,
    RelationLifecycle,
    RelationType,
)
from .models import ContractModel, NonEmptyText, Sha256

RELATION_CONTRACT_VERSION = "e5-relation/v1"
"""Version stamped onto validated candidates.

It participates in the discovery fingerprint, so tightening an admissibility
rule invalidates cached results rather than silently changing what a cached
`NO_MATCH` meant.
"""

DISCOVERY_INTENT_VERSION = "e5-discovery-intent/v1"
"""Runtime-owned discovery intent, replacing the former free-text query.

Neither the user nor the model can populate or override it. A phrasing-driven
search lets the same pair of assets yield different relations under different
wordings, so a durable relation would degrade into what one sentence returned
once. Reproducibility itself comes from the fingerprint and the idempotent
cache, not from this constant; fixing the intent only removes one source of
variance.
"""

PROJECTION_SCHEMA_VERSION = "e5-role-graph/v1"

EVIDENCE_CARD_SCHEMA_VERSION = "e5-evidence-card/v1"
"""Stamped onto the rendered card so a stored or transported card names the
shape it was built under."""

MAX_MVP_CANDIDATES = 1
"""MVP output cap.

Showing a weak relation costs more than missing a plausible one: it spends the
user's attention, makes an otherwise explainable asset feel less trustworthy,
and can redirect later reasoning toward an experience that was never relevant.
Returning more candidates multiplies that cost rather than repairing it.
"""

ALLOWED_ROOT_EDGES: dict[ProjectionRootKind, frozenset[ProjectionEdgeType]] = {
    ProjectionRootKind.CRITICAL_MOMENT: frozenset(
        {
            ProjectionEdgeType.HAS_CUE,
            ProjectionEdgeType.HAS_CHANGE,
            ProjectionEdgeType.HAS_SURPRISE,
            ProjectionEdgeType.HAS_CONFLICT,
        }
    ),
    ProjectionRootKind.DECISION_RECORD: frozenset(
        {
            ProjectionEdgeType.HAS_ALTERNATIVE,
            ProjectionEdgeType.HAS_REASON,
            ProjectionEdgeType.HAS_ACTION,
            ProjectionEdgeType.HAS_RESULT,
            ProjectionEdgeType.HAS_EVIDENCE,
        }
    ),
    ProjectionRootKind.INSIGHT_RECORD: frozenset(
        {
            ProjectionEdgeType.HAS_SUPPORT,
            ProjectionEdgeType.HAS_COUNTERFACTUAL,
            ProjectionEdgeType.HAS_LIMITATION,
            ProjectionEdgeType.HAS_COUNTEREXAMPLE,
            ProjectionEdgeType.HAS_APPLICABILITY,
        }
    ),
}
"""Which member edges each root record kind may carry.

There is deliberately no cross-record edge linking a critical moment to a
decision to an insight. Such a link would assert a causal chain that the
canonical records do not state, and the user could not tell the system's
inference apart from their own account.
"""

BOUNDARY_EDGE_TYPES: frozenset[ProjectionEdgeType] = frozenset(
    {
        ProjectionEdgeType.HAS_LIMITATION,
        ProjectionEdgeType.HAS_APPLICABILITY,
        ProjectionEdgeType.HAS_COUNTEREXAMPLE,
    }
)

RELATION_ADMISSIBILITY: dict[
    RelationType, frozenset[tuple[ProjectionEdgeType, ProjectionEdgeType]]
] = {
    RelationType.SAME_THEME: frozenset(),
    RelationType.METHOD_REUSE: frozenset(
        (left, right)
        for left in (ProjectionEdgeType.HAS_ACTION, ProjectionEdgeType.HAS_REASON)
        for right in (
            ProjectionEdgeType.HAS_ACTION,
            ProjectionEdgeType.HAS_APPLICABILITY,
        )
    ),
    RelationType.COUNTEREXAMPLE: frozenset(
        (left, right)
        for left in (
            ProjectionEdgeType.HAS_RESULT,
            ProjectionEdgeType.HAS_LIMITATION,
            ProjectionEdgeType.HAS_COUNTEREXAMPLE,
        )
        for right in (
            ProjectionEdgeType.HAS_SUPPORT,
            ProjectionEdgeType.HAS_ACTION,
            ProjectionEdgeType.HAS_APPLICABILITY,
        )
    ),
    RelationType.SUPPLEMENT: frozenset(
        (left, right)
        for left in (
            ProjectionEdgeType.HAS_EVIDENCE,
            ProjectionEdgeType.HAS_SUPPORT,
            ProjectionEdgeType.HAS_ALTERNATIVE,
        )
        for right in (
            ProjectionEdgeType.HAS_SUPPORT,
            ProjectionEdgeType.HAS_LIMITATION,
            ProjectionEdgeType.HAS_APPLICABILITY,
        )
    ),
    RelationType.PREREQUISITE: frozenset(
        (ProjectionEdgeType.HAS_APPLICABILITY, right)
        for right in (ProjectionEdgeType.HAS_ACTION, ProjectionEdgeType.HAS_RESULT)
    ),
    RelationType.FOLLOW_UP: frozenset(
        (left, right)
        for left in (ProjectionEdgeType.HAS_RESULT, ProjectionEdgeType.HAS_ACTION)
        for right in (
            ProjectionEdgeType.HAS_ACTION,
            ProjectionEdgeType.HAS_APPLICABILITY,
        )
    ),
}
"""Versioned role-pair admissibility table.

`SAME_THEME` carries no role pair because it is a root-to-root claim: the
Runtime requires normalized lexical overlap between two source-grounded root
labels instead. Generic shared words alone are insufficient, since almost any
two experiences share some.
"""

def role_graph_root_node_id(
    *, root_kind: ProjectionRootKind, canonical_record_id: UUID
) -> str:
    """Deterministic identifier for a root node.

    Identifiers derive from the canonical record they project, so rebuilding
    unchanged input reproduces the same graph. A random identifier would change
    the projection hash on every rebuild, invalidating every fingerprint bound
    to it and discarding cached discovery results for no semantic reason.
    """
    return f"{root_kind.value}:{canonical_record_id}"


def role_graph_member_node_id(
    *,
    root_kind: ProjectionRootKind,
    canonical_record_id: UUID,
    role: ProjectionEdgeType,
    display_order: int,
) -> str:
    return (
        f"{root_kind.value}:{canonical_record_id}:{role.value}:{display_order}"
    )


def role_graph_edge_id(
    *, root_node_id: str, member_node_id: str, edge_type: ProjectionEdgeType
) -> str:
    return f"{root_node_id}->{edge_type.value}->{member_node_id}"


def compute_projection_hash(
    *,
    asset_id: UUID,
    version_id: UUID,
    knowledge_card_hash: str,
    projection_schema_version: str,
    nodes: list[RoleGraphNodeV1],
    edges: list[RoleGraphEdgeV1],
    provenance: list[NodeProvenanceV1],
) -> str:
    """Canonical hash over the projection's content.

    The serialization is sorted and field-ordered so two callers building the
    same projection agree. An unspecified hash input would let the stored and
    recomputed values differ for reasons nobody could reproduce, and the
    activation check that compares them would then reject valid projections or
    accept drifted ones depending on read order.
    """
    # Enum members and their raw string values must hash identically: callers
    # reach this function both with validated models and with dicts read
    # straight from JSON, and a hash that depended on which one they held would
    # make the stored and recomputed values disagree for no semantic reason.
    def enum_value(value: object) -> str:
        return str(getattr(value, "value", value)) if value is not None else ""

    payload = {
        "asset_id": str(asset_id),
        "version_id": str(version_id),
        "knowledge_card_hash": knowledge_card_hash,
        "projection_schema_version": projection_schema_version,
        "nodes": sorted(
            [
                [
                    node.node_id,
                    enum_value(node.root_kind),
                    str(node.canonical_record_id),
                    node.is_root,
                    enum_value(node.role),
                    node.display_order,
                    node.summary_text_hash,
                ]
                for node in nodes
            ]
        ),
        "edges": sorted(
            [
                [
                    edge.edge_id,
                    enum_value(edge.edge_type),
                    edge.root_node_id,
                    edge.member_node_id,
                    str(edge.canonical_record_id),
                ]
                for edge in edges
            ]
        ),
        "provenance": sorted(
            [
                [
                    entry.node_id,
                    sorted(str(sid) for sid in entry.statement_ids),
                    sorted(entry.evidence_refs),
                    sorted(entry.source_refs),
                    sorted(entry.span_refs),
                ]
                for entry in provenance
            ]
        ),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


LEGACY_RELATION_VOCABULARY: dict[str, RelationType] = {
    "SIMILAR_SITUATION": RelationType.SAME_THEME,
    "SHARED_METHOD": RelationType.METHOD_REUSE,
}
"""Migration of the pre-E5 fixture vocabulary.

Two live vocabularies would let a fixture-only label reach a user-visible
surface with no admissibility rule behind it, so the old names map onto the
closed set rather than coexisting with it.
"""


class KnowledgeCardReadinessRecordV1(ContractModel):
    """Sidecar readiness record, keyed by asset, version and card hash.

    Binding to an exact version and hash is what makes staleness expressible. If
    readiness pointed at the asset, a later edit would silently inherit every
    relation built on the older text, and the user would see a confirmed
    relation whose stated reason no longer matches what the card says.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    readiness_id: UUID
    asset_id: UUID
    version_id: UUID
    m4_artifact_id: UUID
    knowledge_card_hash: Sha256
    milestone_state: Literal[
        MilestoneState.CONFIRMED, MilestoneState.COMPLETE_WITH_GAPS
    ]
    explicit_user_acceptance: Literal[True] = True
    accepted_gap_statement_ids: list[UUID] = Field(default_factory=list)
    accepted_at: AwareDatetime
    lifecycle: ReadinessLifecycle = ReadinessLifecycle.ACTIVE
    invalidated_at: AwareDatetime | None = None
    invalidation_reason: NonEmptyText | None = None

    @model_validator(mode="after")
    def acceptance_shape_is_consistent(self) -> KnowledgeCardReadinessRecordV1:
        if (
            self.milestone_state is MilestoneState.COMPLETE_WITH_GAPS
            and not self.accepted_gap_statement_ids
        ):
            raise ValueError(
                "gap acceptance must name the accepted gaps so the record shows "
                "what the user agreed to leave open"
            )
        if (
            self.milestone_state is MilestoneState.CONFIRMED
            and self.accepted_gap_statement_ids
        ):
            raise ValueError("a fully confirmed card cannot carry accepted gaps")
        # The lifecycle and the invalidation evidence must agree in both
        # directions. Allowing ACTIVE alongside an invalidation timestamp lets
        # two consumers read the same record as opposite answers to "is this
        # card ready", and no fail-closed gate can be built on that.
        revoked = self.lifecycle in {
            ReadinessLifecycle.STALE,
            ReadinessLifecycle.INVALIDATED,
        }
        if revoked and not (self.invalidation_reason and self.invalidated_at):
            raise ValueError(
                "a stale or invalidated readiness record must carry both an "
                "invalidation time and a reason"
            )
        if not revoked and (self.invalidation_reason or self.invalidated_at):
            raise ValueError(
                "an ACTIVE readiness record cannot carry invalidation evidence; "
                "move the lifecycle to STALE or INVALIDATED instead"
            )
        return self


class RoleGraphNodeV1(ContractModel):
    """One node of a deterministic role-graph projection.

    `summary_text` is bounded and summary-safe. Detailed evidence is deliberately
    absent from the node: the discovery decision does not need it, and including
    it would put historical content into a model prompt before the user has
    agreed to look at that history at all.
    """

    node_id: NonEmptyText
    projection_id: UUID
    root_kind: ProjectionRootKind
    canonical_record_id: UUID
    is_root: bool
    role: ProjectionEdgeType | None = None
    display_order: int = Field(ge=0)
    summary_text: NonEmptyText = Field(max_length=400)
    summary_text_hash: Sha256

    @model_validator(mode="after")
    def role_presence_matches_node_kind(self) -> RoleGraphNodeV1:
        if self.is_root and self.role is not None:
            raise ValueError("a root node carries no member role")
        if not self.is_root and self.role is None:
            raise ValueError("a member node must declare its role")
        if self.role is not None and self.role not in ALLOWED_ROOT_EDGES[self.root_kind]:
            raise ValueError(
                f"role {self.role} is not admissible under root kind {self.root_kind}"
            )

        # The declared hash must actually be the hash of the declared text.
        #
        # `compute_projection_hash` covers `summary_text_hash`, not the text, so
        # without this check the chain is broken at its root: the summary a node
        # carries is what reaches the FTS index and the model prompt, and it
        # could be replaced entirely while the node hash, the projection hash,
        # the discovery fingerprint and the cache key all report the input
        # unchanged. A cached CANDIDATE or NO_MATCH would then be reused for
        # content nobody compared, and injected text would ride through the
        # content-integrity boundary untouched.
        expected = hashlib.sha256(self.summary_text.encode("utf-8")).hexdigest()
        if self.summary_text_hash != expected:
            raise ValueError(
                "summary_text_hash is not the SHA-256 of summary_text; the node "
                "declares a hash for content it does not carry, so every hash "
                "derived from it would attest to the wrong text"
            )
        return self


class RoleGraphEdgeV1(ContractModel):
    """A membership edge: this root record has this member in this role."""

    edge_id: NonEmptyText
    projection_id: UUID
    edge_type: ProjectionEdgeType
    root_node_id: NonEmptyText
    member_node_id: NonEmptyText
    canonical_record_id: UUID

    @model_validator(mode="after")
    def edge_connects_distinct_nodes(self) -> RoleGraphEdgeV1:
        if self.root_node_id == self.member_node_id:
            raise ValueError("an edge cannot connect a node to itself")
        return self


class NodeProvenanceV1(ContractModel):
    """Canonical references behind one node.

    At least one statement reference is required for any node that can appear in
    a candidate. A node without one could be shown to the user as part of an
    explanation while resting on nothing they can open and check.
    """

    node_id: NonEmptyText
    projection_id: UUID
    statement_ids: list[UUID] = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    span_refs: list[str] = Field(default_factory=list)


class RoleGraphProjectionV1(ContractModel):
    """Deterministic read-only projection over accepted canonical records.

    Rebuilding unchanged input reproduces the same content and the same
    `projection_hash`. Without that, a rebuild would change every fingerprint
    bound to it and discard cached discovery results for no semantic reason.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    projection_id: UUID
    asset_id: UUID
    version_id: UUID
    knowledge_card_hash: Sha256
    projection_schema_version: Literal["e5-role-graph/v1"] = PROJECTION_SCHEMA_VERSION
    projection_hash: Sha256
    lifecycle: ProjectionLifecycle
    nodes: list[RoleGraphNodeV1] = Field(default_factory=list)
    edges: list[RoleGraphEdgeV1] = Field(default_factory=list)
    provenance: list[NodeProvenanceV1] = Field(default_factory=list)
    created_at: AwareDatetime
    invalidated_at: AwareDatetime | None = None
    invalidation_reason: NonEmptyText | None = None

    @model_validator(mode="after")
    def projection_is_internally_consistent(self) -> RoleGraphProjectionV1:
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("node IDs must be unique within a projection")
        by_id = {node.node_id: node for node in self.nodes}
        known = set(node_ids)

        edge_ids = [edge.edge_id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("edge IDs must be unique within a projection")

        # Every part must belong to *this* projection. Without the check a row
        # carrying another projection's identifier reads as a member of this
        # graph, so a candidate could be explained with evidence from a graph
        # nobody compared.
        for node in self.nodes:
            if node.projection_id != self.projection_id:
                raise ValueError(
                    f"node {node.node_id} belongs to projection "
                    f"{node.projection_id}, not {self.projection_id}"
                )
        for entry in self.provenance:
            if entry.projection_id != self.projection_id:
                raise ValueError(
                    f"provenance for {entry.node_id} belongs to a different projection"
                )

        for edge in self.edges:
            if edge.projection_id != self.projection_id:
                raise ValueError(
                    f"edge {edge.edge_id} belongs to a different projection"
                )
            if edge.root_node_id not in known or edge.member_node_id not in known:
                raise ValueError("every edge must connect nodes present in the projection")
            root = by_id[edge.root_node_id]
            member = by_id[edge.member_node_id]
            if not root.is_root:
                raise ValueError(f"edge {edge.edge_id} does not start at a root node")
            if member.is_root:
                raise ValueError(f"edge {edge.edge_id} points at another root node")
            if member.role is not edge.edge_type:
                raise ValueError(
                    f"edge {edge.edge_id} declares {edge.edge_type} but its member "
                    f"node carries role {member.role}; the label and the structure "
                    "would then describe different things"
                )
            if edge.edge_type not in ALLOWED_ROOT_EDGES[root.root_kind]:
                raise ValueError(
                    f"{edge.edge_type} is not admissible under root kind {root.root_kind}"
                )
            # Membership holds within one canonical record. A cross-record edge
            # would assert a link the canonical records never state.
            if not (
                root.canonical_record_id
                == member.canonical_record_id
                == edge.canonical_record_id
            ):
                raise ValueError(
                    f"edge {edge.edge_id} spans more than one canonical record"
                )

        provenance_nodes = {entry.node_id for entry in self.provenance}
        if not provenance_nodes.issubset(known):
            raise ValueError("provenance must reference nodes present in the projection")
        if len(provenance_nodes) != len(self.provenance):
            raise ValueError("provenance entries must be unique per node")

        if self.lifecycle is ProjectionLifecycle.ACTIVE:
            missing = known - provenance_nodes
            if missing:
                raise ValueError(
                    "an ACTIVE projection requires provenance for every node; a "
                    "partially built projection that is already eligible would "
                    f"yield an unexplainable candidate: {sorted(missing)[:3]}"
                )
            orphans = {
                node.node_id
                for node in self.nodes
                if not node.is_root
            } - {edge.member_node_id for edge in self.edges}
            if orphans:
                raise ValueError(
                    "an ACTIVE projection cannot hold member nodes with no edge; "
                    f"they would be reachable by identifier but unexplainable: "
                    f"{sorted(orphans)[:3]}"
                )

        # The stored hash is what activation compares against. If it is simply
        # accepted, a projection whose content drifted from its inputs still
        # presents itself as the projection those inputs produced.
        recomputed = compute_projection_hash(
            asset_id=self.asset_id,
            version_id=self.version_id,
            knowledge_card_hash=self.knowledge_card_hash,
            projection_schema_version=self.projection_schema_version,
            nodes=self.nodes,
            edges=self.edges,
            provenance=self.provenance,
        )
        if recomputed != self.projection_hash:
            raise ValueError(
                "projection_hash does not match the canonical content hash; the "
                "projection has drifted from the inputs it claims to represent"
            )

        revoked = self.lifecycle in {
            ProjectionLifecycle.STALE,
            ProjectionLifecycle.INVALIDATED,
        }
        if revoked and not (self.invalidation_reason and self.invalidated_at):
            raise ValueError(
                "a stale or invalidated projection must carry both an "
                "invalidation time and a reason"
            )
        if not revoked and (self.invalidation_reason or self.invalidated_at):
            raise ValueError(
                "an active or building projection cannot carry invalidation evidence"
            )
        return self


class DiscoveryFingerprintV1(ContractModel):
    """Canonical inputs of one discovery request.

    The field set is frozen here rather than in ticket 05 or 06 so that both
    implement one agreed shape. Left to either, two callers serializing the same
    logical input could produce different fingerprints, and the cache would stop
    working while still appearing correct.

    Model, prompt and configuration identity are included on purpose: the same
    graphs under a different model produce a different judgement, so an upgraded
    model must not keep serving the previous model's cached `NO_MATCH`.
    """

    fingerprint_schema_version: Literal["e5-fingerprint/v1"] = "e5-fingerprint/v1"
    current_asset_id: UUID
    current_version_id: UUID
    current_knowledge_card_hash: Sha256
    current_projection_hash: Sha256
    eligible_projection_hashes: list[Sha256] = Field(min_length=1)
    model_identity: NonEmptyText
    model_revision: NonEmptyText
    prompt_version: NonEmptyText
    role_contract_version: NonEmptyText
    validation_contract_version: NonEmptyText
    discovery_intent_version: NonEmptyText
    inference_parameters_hash: Sha256
    prefilter_config_version: NonEmptyText

    @model_validator(mode="after")
    def eligible_hashes_are_sorted_and_unique(self) -> DiscoveryFingerprintV1:
        if len(self.eligible_projection_hashes) != len(
            set(self.eligible_projection_hashes)
        ):
            raise ValueError("eligible projection hashes must be unique")
        if self.eligible_projection_hashes != sorted(self.eligible_projection_hashes):
            raise ValueError(
                "eligible projection hashes must be sorted; an unsorted list makes "
                "the same logical corpus hash differently depending on read order"
            )
        return self


class DiscoveryAttemptV1(ContractModel):
    """One reserved discovery attempt.

    The attempt is reserved durably before inference so that a process dying
    mid-flight is recovered or safely marked retryable rather than assumed
    successful.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    attempt_id: UUID
    run_id: UUID
    asset_id: UUID
    discovery_fingerprint: Sha256
    current_projection_id: UUID
    eligible_set_hash: Sha256
    attempt_number: int = Field(ge=1)
    outcome: DiscoveryOutcome
    failure_class: DiscoveryFailureClass | None = None
    candidate_id: UUID | None = None
    lease_expires_at: AwareDatetime | None = None
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    elapsed_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def outcome_and_payload_agree(self) -> DiscoveryAttemptV1:
        if self.outcome is DiscoveryOutcome.CANDIDATE and self.candidate_id is None:
            raise ValueError("a CANDIDATE outcome must reference its candidate")
        if self.outcome is not DiscoveryOutcome.CANDIDATE and self.candidate_id:
            raise ValueError("only a CANDIDATE outcome may reference a candidate")
        if (
            self.outcome is DiscoveryOutcome.TECHNICAL_FAILURE
            and self.failure_class is None
        ):
            raise ValueError(
                "a technical failure must record its safe failure class; without "
                "it the attempt cannot be distinguished from a semantic result "
                "during audit"
            )
        if (
            self.outcome is not DiscoveryOutcome.TECHNICAL_FAILURE
            and self.failure_class is not None
        ):
            raise ValueError("only a technical failure carries a failure class")

        # A RUNNING attempt without a lease can never be reclaimed: recovery
        # works by finding expired leases, so a reservation with no expiry is
        # invisible to it and blocks its fingerprint forever.
        if self.outcome is DiscoveryOutcome.RUNNING:
            if self.lease_expires_at is None:
                raise ValueError(
                    "a RUNNING attempt must hold a lease, or expired-reservation "
                    "recovery can never reclaim it"
                )
            if self.finished_at is not None:
                raise ValueError("a RUNNING attempt has not finished")
        else:
            # Terminal outcomes are settled in both directions: a settled
            # attempt still holding a lease would be recovered as if it were
            # in flight, and one with no finish time cannot be aged or audited.
            if self.finished_at is None:
                raise ValueError(f"a terminal {self.outcome} attempt must record finished_at")
            if self.lease_expires_at is not None:
                raise ValueError(
                    "a settled attempt must release its lease, or recovery would "
                    "treat a finished attempt as still in flight"
                )
        return self


class RelationNodeMappingV1(ContractModel):
    """One bilateral node correspondence proposed by the model.

    The model returns only supplied node identifiers. It cannot return new
    facts, nodes, edges, provenance, scores or titles, because the Runtime can
    validate an identifier against a stored projection but cannot validate an
    invented claim.

    A role of `None` on both sides marks a root-to-root mapping, which is what
    `SAME_THEME` claims. Roles must be absent or present together: a mapping
    that pairs a root with a member describes a correspondence between things
    of different kinds, and no relation type defines what that would mean.
    """

    current_node_id: NonEmptyText
    historical_node_id: NonEmptyText
    current_role: ProjectionEdgeType | None = None
    historical_role: ProjectionEdgeType | None = None

    @model_validator(mode="after")
    def roles_are_absent_or_present_together(self) -> RelationNodeMappingV1:
        if (self.current_role is None) != (self.historical_role is None):
            raise ValueError(
                "a mapping must pair two roots or two members, not one of each"
            )
        return self

    @property
    def is_root_mapping(self) -> bool:
        return self.current_role is None


class RelationProvenanceRefV1(ContractModel):
    """Side-attributed provenance.

    The side is explicit because a flat reference list cannot say which asset a
    reference belongs to, and a bilateral explanation that cannot be attributed
    to both sides is not bilateral.
    """

    side: Literal["CURRENT", "HISTORICAL"]
    node_id: NonEmptyText
    statement_ids: list[UUID] = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class RelationCandidateV1(ContractModel):
    """A validated cross-asset candidate.

    This replaces the pre-E5 fixture shape, which carried a free-text
    `proposed_relation` and a flat provenance list and could not express a fixed
    relation type, bilateral mapping, boundary nodes, projection bindings,
    fingerprint or lifecycle. Extending it is a breaking change to a symbol the
    E5→E6 handoff manifest freezes, and E6 needs the new shape before it lands.

    `detail_included` is pinned false: the candidate view never carries
    historical detail, because showing the detail before the decision would make
    the confirmation choice moot.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    candidate_id: UUID
    discovery_fingerprint: Sha256
    current_asset_id: UUID
    current_projection_id: UUID
    related_asset_id: UUID
    historical_projection_id: UUID
    relation_type: RelationType
    title: NonEmptyText
    summary: NonEmptyText
    node_mappings: list[RelationNodeMappingV1] = Field(min_length=1)
    current_boundary_node_ids: list[NonEmptyText] = Field(min_length=1)
    historical_boundary_node_ids: list[NonEmptyText] = Field(default_factory=list)
    provenance: list[RelationProvenanceRefV1] = Field(min_length=2)
    validation_contract_version: NonEmptyText = RELATION_CONTRACT_VERSION
    lifecycle: RelationLifecycle = RelationLifecycle.PROPOSED
    detail_included: Literal[False] = False
    created_at: AwareDatetime

    @model_validator(mode="after")
    def candidate_package_is_complete(self) -> RelationCandidateV1:
        if self.current_asset_id == self.related_asset_id:
            raise ValueError("a relation must hold between two distinct assets")

        sides = {ref.side for ref in self.provenance}
        if sides != {"CURRENT", "HISTORICAL"}:
            raise ValueError(
                "provenance must be present on both sides; one-sided provenance "
                "cannot support a bilateral explanation"
            )

        if self.relation_type is RelationType.SAME_THEME:
            # SAME_THEME is a root-to-root claim about subject matter. Skipping
            # the check entirely — as an empty admissibility table invites —
            # would let it accept any role pair at all, so it would become the
            # label a proposal falls back to when no other rule fits, which is
            # exactly the escape hatch the closed vocabulary exists to remove.
            # Lexical overlap between the two root labels is checked by the
            # Runtime against stored projections; the contract requires only
            # that the mapping actually be root-to-root.
            if not any(mapping.is_root_mapping for mapping in self.node_mappings):
                raise ValueError(
                    "SAME_THEME requires at least one root-to-root mapping"
                )
        else:
            allowed = RELATION_ADMISSIBILITY[self.relation_type]
            if any(mapping.is_root_mapping for mapping in self.node_mappings):
                raise ValueError(
                    f"{self.relation_type} is a role-level relation and cannot "
                    "carry a root-to-root mapping"
                )
            if not any(
                (mapping.current_role, mapping.historical_role) in allowed
                for mapping in self.node_mappings
            ):
                raise ValueError(
                    f"no mapping satisfies the role rule for {self.relation_type}"
                )

        if len(set(self.current_boundary_node_ids)) != len(
            self.current_boundary_node_ids
        ):
            raise ValueError("current boundary node IDs must be unique")
        return self


class RelationCandidateDecisionV1(ContractModel):
    """The user's explicit decision about one exact candidate.

    Every binding the decision was made against is carried so that a request
    arriving with a stale card version fails closed rather than being resolved
    against whatever is current. Resolving it silently would grant access based
    on a decision the user made about different content.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    decision_id: UUID
    candidate_id: UUID
    current_asset_id: UUID
    current_version_id: UUID
    current_knowledge_card_hash: Sha256
    related_asset_id: UUID
    user_action: Literal["CONFIRM", "DECLINE"]
    decided_at: AwareDatetime


class ConfirmedAssetRelationV1(ContractModel):
    """A durable bilateral relation created by an explicit confirmation.

    `relation_id` is distinct from `source_candidate_id`: the relation is a new
    durable object, while the candidate is the proposal it came from. Ticket 07
    checks the source candidate against the run's candidate set, which preserves
    the original intent — nothing can be confirmed which was never proposed —
    without requiring the two identifiers to be the same value.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    relation_id: UUID
    source_candidate_id: UUID
    relation_type: RelationType
    current_asset_id: UUID
    current_version_id: UUID
    current_projection_id: UUID
    current_knowledge_card_hash: Sha256
    related_asset_id: UUID
    related_version_id: UUID
    historical_projection_id: UUID
    # PROPOSED and DECLINED belong to a candidate's life, not to a confirmed
    # relation: this entity only exists because a confirmation happened, and it
    # is required to carry `confirmed_at`. Allowing them would let a row assert
    # both that it was confirmed and that it never was.
    lifecycle: Literal[
        RelationLifecycle.CONFIRMED,
        RelationLifecycle.STALE,
        RelationLifecycle.INVALIDATED,
    ]
    confirmed_at: AwareDatetime
    invalidated_at: AwareDatetime | None = None
    invalidation_reason: NonEmptyText | None = None

    @model_validator(mode="after")
    def confirmed_relation_is_consistent(self) -> ConfirmedAssetRelationV1:
        if self.relation_id == self.source_candidate_id:
            raise ValueError(
                "a confirmed relation carries its own identifier distinct from the "
                "candidate it came from"
            )
        if self.current_asset_id == self.related_asset_id:
            raise ValueError("a relation must hold between two distinct assets")
        # The same two-way invariant readiness uses. Previously only one
        # direction was checked, so the model accepted CONFIRMED alongside an
        # invalidation timestamp while the SQL CHECK rejected it: the in-memory
        # object said the relation was usable and the database refused to store
        # it, and two consumers could reach opposite conclusions about whether
        # access had been revoked.
        revoked = self.lifecycle in {
            RelationLifecycle.STALE,
            RelationLifecycle.INVALIDATED,
        }
        if revoked and not (self.invalidation_reason and self.invalidated_at):
            raise ValueError(
                "a stale or invalidated relation must carry both an invalidation "
                "time and a reason"
            )
        if not revoked and (self.invalidation_reason or self.invalidated_at):
            raise ValueError(
                "a live relation cannot carry invalidation evidence; move the "
                "lifecycle to STALE or INVALIDATED instead"
            )
        return self


class MappedRoleEvidenceV1(ContractModel):
    """One bilateral correspondence, labelled with both sides' canonical text.

    The labels are the projections' own `summary_text`, copied verbatim. They
    are not regenerated, reworded or truncated: the text the user can open must
    be the text the card shows, or the card is describing something the evidence
    does not say.
    """

    current_node_id: NonEmptyText
    historical_node_id: NonEmptyText
    current_role: ProjectionEdgeType | None = None
    historical_role: ProjectionEdgeType | None = None
    current_label: NonEmptyText
    historical_label: NonEmptyText
    current_label_hash: Sha256
    historical_label_hash: Sha256


class TransferBoundaryV1(ContractModel):
    """The condition under which the relation transfers, quoted from its source.

    A lesson drawn from one person's experience, presented without its
    limitation and its transfer condition, reads as general advice. The user
    then applies it in a situation the original experience never covered, and
    the asset has actively misled them. So the boundary is quoted with the node
    it came from rather than paraphrased into the card's own voice.
    """

    side: Literal["CURRENT", "HISTORICAL"]
    node_id: NonEmptyText
    role: ProjectionEdgeType | None = None
    content: NonEmptyText
    content_hash: Sha256


class SideProvenanceV1(ContractModel):
    """One side's provenance identifiers.

    The side is explicit for the same reason it is explicit on the candidate: a
    flat reference list cannot say which asset a reference belongs to, and a
    bilateral explanation that cannot be attributed to both sides is not
    bilateral.
    """

    side: Literal["CURRENT", "HISTORICAL"]
    asset_id: UUID
    projection_id: UUID
    node_ids: list[str] = Field(min_length=1)
    statement_ids: list[UUID] = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    span_refs: list[str] = Field(default_factory=list)


class EvidenceCardV1(ContractModel):
    """The rendered bilateral comparison for one confirmed relation.

    Composed on read like the workspace that carries it, and never serialized
    back into the Experience Asset snapshot — so producing it cannot change the
    snapshot JSON, the statement hash, or the Knowledge Card hash.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    card_schema_version: Literal["e5-evidence-card/v1"] = EVIDENCE_CARD_SCHEMA_VERSION
    outcome: Literal["RENDERED"] = "RENDERED"
    relation_id: UUID
    relation_type: RelationType
    current_asset_id: UUID
    current_version_id: UUID
    current_knowledge_card_hash: Sha256
    related_asset_id: UUID
    related_version_id: UUID
    mapped_roles: list[MappedRoleEvidenceV1] = Field(min_length=1)
    boundaries: list[TransferBoundaryV1] = Field(min_length=1)
    provenance: list[SideProvenanceV1] = Field(min_length=2)
    card_hash: Sha256


class EvidenceCardRefusalV1(ContractModel):
    """A typed refusal the caller renders as itself.

    Discriminated from the card by `outcome`, so a consumer cannot mistake a
    refusal for an empty card. That distinction is the point: a partially
    rendered card reads as complete, which is exactly the failure the refusal
    exists to prevent.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    outcome: Literal["REFUSED"] = "REFUSED"
    reason: EvidenceCardRefusalReason
    detail: NonEmptyText
    unresolved_node_ids: list[str] = Field(default_factory=list)
    unresolved_refs: list[str] = Field(default_factory=list)


class RelationWorkspaceV1(ContractModel):
    """Read-only composition of relation state for the API.

    This is what replaces the retired snapshot fields for consumers. It is
    composed on read and never serialized back into the Experience Asset
    snapshot, so a relation read cannot change the snapshot JSON or its content
    hash.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    asset_id: UUID
    canonical_version_id: UUID
    readiness: KnowledgeCardReadinessRecordV1 | None = None
    discovery_outcome: DiscoveryOutcome = DiscoveryOutcome.NOT_READY
    failure_class: DiscoveryFailureClass | None = None
    candidates: list[RelationCandidateV1] = Field(default_factory=list)
    decisions: list[RelationCandidateDecisionV1] = Field(default_factory=list)
    confirmed_relations: list[ConfirmedAssetRelationV1] = Field(default_factory=list)
    # The evidence read is the only operation that populates this. It is
    # optional rather than a separate response model because the card is
    # relation state composed on read, which is what this model already is;
    # splitting it out would make the front end fetch one relation surface
    # through two shapes. The four operations that produce no card leave it
    # null.
    evidence_card: EvidenceCardV1 | EvidenceCardRefusalV1 | None = None

    @model_validator(mode="after")
    def workspace_respects_the_mvp_cap(self) -> RelationWorkspaceV1:
        if len(self.candidates) > MAX_MVP_CANDIDATES:
            raise ValueError(
                "the MVP exposes at most one candidate; a longer list would spend "
                "the user's attention on weaker comparisons rather than the "
                "strongest defensible one"
            )
        if (
            self.discovery_outcome is DiscoveryOutcome.CANDIDATE
            and not self.candidates
        ):
            raise ValueError("a CANDIDATE outcome must expose its candidate")
        if self.discovery_outcome is DiscoveryOutcome.NO_MATCH and self.candidates:
            raise ValueError("a NO_MATCH outcome cannot expose a candidate")
        if (
            self.discovery_outcome is DiscoveryOutcome.TECHNICAL_FAILURE
            and self.failure_class is None
        ):
            raise ValueError("a technical failure must expose its safe failure class")
        return self
