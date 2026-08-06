"""The checked-in E5 fixtures must stay valid against the frozen contracts.

Wave-1 tickets build against these files instead of inventing their own inputs.
A fixture that silently drifts from the contract is worse than a missing one: an
Agent would build correctly against a shape the backend never accepts, and the
mismatch would surface only when the real producer landed.

These tests also check consistency *between* fixtures — a candidate that maps a
node no projection contains would validate on its own while describing something
that cannot exist.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.experience_asset.domain.enums import (
    DiscoveryOutcome,
    ProjectionEdgeType,
    RelationType,
)
from app.experience_asset.domain.m4 import BOUNDARY_INSIGHT_ROLES, InsightBoundaryMapV1
from app.experience_asset.domain.relation import (
    BOUNDARY_EDGE_TYPES,
    LEGACY_RELATION_VOCABULARY,
    MAX_MVP_CANDIDATES,
    RELATION_ADMISSIBILITY,
    ConfirmedAssetRelationV1,
    DiscoveryAttemptV1,
    DiscoveryFingerprintV1,
    KnowledgeCardReadinessRecordV1,
    RelationCandidateDecisionV1,
    RelationCandidateV1,
    RoleGraphProjectionV1,
)

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "contracts" / "examples" / "e5"
INSTANCE = FIXTURE_DIR / "instance"
SCENARIO = FIXTURE_DIR / "scenario"

INSTANCE_MODELS = {
    "m4-insight-boundary-map.json": InsightBoundaryMapV1,
    "knowledge-card-readiness.json": KnowledgeCardReadinessRecordV1,
    "role-graph-projection-current.json": RoleGraphProjectionV1,
    "role-graph-projection-historical.json": RoleGraphProjectionV1,
    "discovery-fingerprint.json": DiscoveryFingerprintV1,
    "discovery-attempt.json": DiscoveryAttemptV1,
    "relation-candidate.json": RelationCandidateV1,
    "relation-candidate-decision.json": RelationCandidateDecisionV1,
    "confirmed-asset-relation.json": ConfirmedAssetRelationV1,
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("filename,model", sorted(INSTANCE_MODELS.items()))
def test_every_instance_fixture_validates(filename, model) -> None:
    model.model_validate(load(INSTANCE / filename))


def test_every_intermediate_artifact_has_a_worked_instance() -> None:
    """Wave 1 needs a concrete input for each artifact it consumes.

    A missing one is not a cosmetic gap: the consuming ticket's Agent would
    fabricate the shape, and for ticket 08 that means designing the bilateral
    provenance structure it exists to render correctly.
    """
    present = {path.name for path in INSTANCE.glob("*.json")}
    assert present == set(INSTANCE_MODELS)


def test_candidate_maps_nodes_that_the_projections_actually_contain() -> None:
    candidate = RelationCandidateV1.model_validate(load(INSTANCE / "relation-candidate.json"))
    current = RoleGraphProjectionV1.model_validate(
        load(INSTANCE / "role-graph-projection-current.json")
    )
    historical = RoleGraphProjectionV1.model_validate(
        load(INSTANCE / "role-graph-projection-historical.json")
    )
    current_nodes = {node.node_id: node for node in current.nodes}
    historical_nodes = {node.node_id: node for node in historical.nodes}

    for mapping in candidate.node_mappings:
        assert mapping.current_node_id in current_nodes
        assert mapping.historical_node_id in historical_nodes
        # A node's declared role must match the projection, or the relation
        # would claim a correspondence between roles that are not there.
        assert current_nodes[mapping.current_node_id].role == mapping.current_role
        assert (
            historical_nodes[mapping.historical_node_id].role == mapping.historical_role
        )

    for node_id in candidate.current_boundary_node_ids:
        assert node_id in current_nodes
    for node_id in candidate.historical_boundary_node_ids:
        assert node_id in historical_nodes


def test_candidate_boundary_resolves_through_a_boundary_role() -> None:
    """A candidate without a source-grounded boundary must abstain.

    Shown without one, structural similarity reads as permission to transfer the
    lesson into a situation the original experience never covered.
    """
    candidate = RelationCandidateV1.model_validate(load(INSTANCE / "relation-candidate.json"))
    current = RoleGraphProjectionV1.model_validate(
        load(INSTANCE / "role-graph-projection-current.json")
    )
    roles = {node.node_id: node.role for node in current.nodes}
    assert candidate.current_boundary_node_ids
    for node_id in candidate.current_boundary_node_ids:
        assert roles[node_id] in BOUNDARY_EDGE_TYPES


def test_candidate_satisfies_its_relation_role_rule() -> None:
    candidate = RelationCandidateV1.model_validate(load(INSTANCE / "relation-candidate.json"))
    allowed = RELATION_ADMISSIBILITY[candidate.relation_type]
    assert any(
        (mapping.current_role, mapping.historical_role) in allowed
        for mapping in candidate.node_mappings
    )


def test_candidate_provenance_is_bilateral_and_grounded() -> None:
    candidate = RelationCandidateV1.model_validate(load(INSTANCE / "relation-candidate.json"))
    sides = {ref.side for ref in candidate.provenance}
    assert sides == {"CURRENT", "HISTORICAL"}
    for ref in candidate.provenance:
        assert ref.statement_ids, "a provenance reference with no statement is unopenable"


def test_confirmed_relation_keeps_identifier_spaces_distinct() -> None:
    """Reusing one identifier as the other hides which object a binding names."""
    relation = ConfirmedAssetRelationV1.model_validate(
        load(INSTANCE / "confirmed-asset-relation.json")
    )
    candidate = RelationCandidateV1.model_validate(load(INSTANCE / "relation-candidate.json"))
    assert relation.source_candidate_id == candidate.candidate_id
    assert relation.relation_id != relation.source_candidate_id


def test_candidate_carries_no_historical_detail() -> None:
    """Detail before the decision would make the confirmation choice moot."""
    raw = load(INSTANCE / "relation-candidate.json")
    assert raw["detail_included"] is False
    assert "reason" not in raw, "model prose is not a durable candidate field"
    assert "proposed_relation" not in raw, "the relation type is a closed enum"


def test_m4_map_ships_the_boundary_with_the_lesson() -> None:
    """A lesson without its limitation and transfer condition reads as advice.

    The reader then applies it where the original experience never went, which
    is worse than having no lesson at all.
    """
    card = InsightBoundaryMapV1.model_validate(load(INSTANCE / "m4-insight-boundary-map.json"))
    for entry in card.entries:
        roles = {statement.role for statement in entry.statements}
        assert BOUNDARY_INSIGHT_ROLES.issubset(roles)


def test_readiness_binds_an_exact_version_and_card_hash() -> None:
    """Binding to the asset instead would let a later edit inherit old relations."""
    readiness = KnowledgeCardReadinessRecordV1.model_validate(
        load(INSTANCE / "knowledge-card-readiness.json")
    )
    card = InsightBoundaryMapV1.model_validate(load(INSTANCE / "m4-insight-boundary-map.json"))
    assert readiness.m4_artifact_id == card.artifact_id
    assert readiness.version_id == card.base_canonical_version_id
    assert readiness.explicit_user_acceptance is True


def test_fingerprint_covers_model_and_configuration_identity() -> None:
    """The same graphs under a different model produce a different judgement.

    Omitting model identity would keep serving the previous model's cached
    no-match, so an upgrade would be invisible exactly where it mattered.
    """
    fingerprint = DiscoveryFingerprintV1.model_validate(
        load(INSTANCE / "discovery-fingerprint.json")
    )
    assert fingerprint.model_identity
    assert fingerprint.model_revision
    assert fingerprint.prompt_version
    assert fingerprint.inference_parameters_hash
    assert fingerprint.prefilter_config_version
    assert fingerprint.eligible_projection_hashes == sorted(
        fingerprint.eligible_projection_hashes
    )


def test_scenarios_cover_positive_no_match_and_invalid_proposal() -> None:
    present = {path.name for path in SCENARIO.glob("*.json")}
    assert {
        "cross-topic-positive.json",
        "hard-negative-corpus.json",
        "invalid-false-association.json",
    }.issubset(present)


def test_positive_scenario_expects_exactly_one_candidate() -> None:
    scenario = load(SCENARIO / "cross-topic-positive.json")
    assert scenario["expected_outcome"] == DiscoveryOutcome.CANDIDATE.value
    assert scenario["expected_candidate_count"] == MAX_MVP_CANDIDATES
    assert scenario["expected_relation_type"] in {t.value for t in RelationType}


def test_hard_negative_is_a_semantic_result_not_a_failure() -> None:
    """Caching an outage as no-match would erase a relation that may well exist."""
    scenario = load(SCENARIO / "hard-negative-corpus.json")
    assert scenario["expected_outcome"] == DiscoveryOutcome.NO_MATCH.value
    assert scenario["expected_candidate_count"] == 0
    assert scenario["must_not_be"] == DiscoveryOutcome.TECHNICAL_FAILURE.value


def test_invalid_proposal_is_a_failure_not_a_no_match() -> None:
    """A malformed response supports no semantic claim, so it must not be cached."""
    scenario = load(SCENARIO / "invalid-false-association.json")
    assert scenario["expected_outcome"] == DiscoveryOutcome.TECHNICAL_FAILURE.value
    assert scenario["must_not_be"] == DiscoveryOutcome.NO_MATCH.value
    assert scenario["expected_candidate_count"] == 0
    defects = {proposal["id"] for proposal in scenario["invalid_proposals"]}
    assert {
        "forbidden-label",
        "nonexistent-node",
        "wrong-side-node",
        "missing-boundary",
        "one-sided-provenance",
        "inadmissible-role-pair",
    }.issubset(defects)
    for proposal in scenario["invalid_proposals"]:
        assert proposal["why_rejected"], "a rejection without a reason teaches nothing"


def test_hard_negative_is_hard_at_the_role_level() -> None:
    """The negative must survive the role filter and be rejected on meaning.

    Role-pair admissibility is a necessary condition, not the judgement. If the
    hard negative failed the role rules too, it would be an *easy* negative: a
    validator that never consulted meaning at all would still abstain on it, and
    the fixture would prove nothing about the thing it exists to exercise.

    So the assertion is deliberately the demanding direction — the negative
    shares at least one admissible role pair with the current asset, leaving
    abstention to rest on semantics.
    """
    current = RoleGraphProjectionV1.model_validate(
        load(INSTANCE / "role-graph-projection-current.json")
    )
    negative = RoleGraphProjectionV1.model_validate(
        load(SCENARIO / "hard-negative-projection.json")
    )
    current_roles = {node.role for node in current.nodes if node.role}
    negative_roles = {node.role for node in negative.nodes if node.role}
    admissible_pairs = {
        (left, right)
        for relation, allowed in RELATION_ADMISSIBILITY.items()
        if relation is not RelationType.SAME_THEME
        for left in current_roles
        for right in negative_roles
        if (left, right) in allowed
    }
    assert admissible_pairs, (
        "the hard negative shares no admissible role pair, so it would be "
        "rejected mechanically and would never test semantic abstention"
    )
    assert ProjectionEdgeType.HAS_ACTION in current_roles


def test_no_fixture_uses_the_retired_relation_vocabulary() -> None:
    """Two live vocabularies would put an undefined label on a user surface."""
    blob = "".join(
        path.read_text(encoding="utf-8") for path in FIXTURE_DIR.rglob("*.json")
    )
    for legacy in LEGACY_RELATION_VOCABULARY:
        assert legacy not in blob
