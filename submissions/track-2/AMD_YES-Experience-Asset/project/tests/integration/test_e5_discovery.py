"""Ticket 05 — one explicit search returns zero or one validated candidate.

The inputs are ticket 01's frozen scenarios, so these assert the outcomes the
contract freeze declared rather than outcomes invented alongside the code.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.experience_asset.application.discovery import (
    ProposalRejected,
    validate_relation_proposal,
)
from app.experience_asset.domain.enums import (
    DiscoveryFailureClass,
    DiscoveryOutcome,
    ProjectionEdgeType,
    RelationType,
)
from app.experience_asset.domain.relation import RoleGraphProjectionV1
from app.experience_asset.inference.models import (
    ProposedRelationMapping,
    RelationDiscoveryProposal,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "examples" / "e5"
DIGEST = "a" * 64


def _load(relative: str) -> dict:
    return json.loads((EXAMPLES / relative).read_text(encoding="utf-8"))


def _scenario(name: str) -> dict:
    return _load(f"scenario/{name}.json")


def _projection(relative: str) -> RoleGraphProjectionV1:
    return RoleGraphProjectionV1.model_validate(_load(relative))


@pytest.fixture
def current() -> RoleGraphProjectionV1:
    return _projection("instance/role-graph-projection-current.json")


@pytest.fixture
def historical() -> RoleGraphProjectionV1:
    return _projection("instance/role-graph-projection-historical.json")


@pytest.fixture
def hard_negative() -> RoleGraphProjectionV1:
    return _projection("scenario/hard-negative-projection.json")


def _members(projection: RoleGraphProjectionV1, role: ProjectionEdgeType):
    return [node for node in projection.nodes if node.role is role]


def _admissible_pair(current, historical):
    """A METHOD_REUSE pair the frozen admissibility table accepts."""
    left = _members(current, ProjectionEdgeType.HAS_ACTION)
    right = _members(historical, ProjectionEdgeType.HAS_ACTION) or _members(
        historical, ProjectionEdgeType.HAS_APPLICABILITY
    )
    assert left and right, "the frozen projections must carry an admissible pair"
    return left[0], right[0]


def _boundary(projection: RoleGraphProjectionV1):
    for role in (
        ProjectionEdgeType.HAS_LIMITATION,
        ProjectionEdgeType.HAS_APPLICABILITY,
        ProjectionEdgeType.HAS_COUNTEREXAMPLE,
    ):
        found = _members(projection, role)
        if found:
            return found[0]
    raise AssertionError("the current projection must carry a boundary node")


def _valid_proposal(current, historical) -> RelationDiscoveryProposal:
    left, right = _admissible_pair(current, historical)
    return RelationDiscoveryProposal(
        outcome="CANDIDATE",
        related_asset_id=historical.asset_id,
        historical_projection_id=historical.projection_id,
        relation_type=RelationType.METHOD_REUSE.value,
        node_mappings=[
            {"current_node_id": left.node_id, "historical_node_id": right.node_id}
        ],
        current_boundary_node_ids=[_boundary(current).node_id],
        reason="model prose that must not reach the candidate",
    )


def _validate(proposal, current, eligible):
    return validate_relation_proposal(
        proposal,
        current_projection=current,
        eligible={item.projection_id: item for item in eligible},
        discovery_fingerprint=DIGEST,
    )


# -- GRAG-03 / GRAG-05 ---------------------------------------------------


def test_a_validated_candidate_carries_the_whole_package(current, historical, hard_negative):
    scenario = _scenario("cross-topic-positive")
    assert scenario["expected_outcome"] == "CANDIDATE"
    assert scenario["expected_candidate_count"] == 1

    candidate = _validate(
        _valid_proposal(current, historical), current, [historical, hard_negative]
    )

    assert candidate.relation_type is RelationType.METHOD_REUSE
    assert candidate.related_asset_id == historical.asset_id
    # The admission rule is a complete package, and every part of it is
    # checkable: fixed type, bilateral mapping, grounded boundary, both sides'
    # provenance. There is no score, because a number derived from nothing that
    # was validated makes an unverified association look measured.
    assert candidate.node_mappings
    assert candidate.current_boundary_node_ids
    assert {entry.side for entry in candidate.provenance} == {"CURRENT", "HISTORICAL"}
    assert candidate.detail_included is False


def test_model_prose_never_reaches_the_candidate(current, historical):
    proposal = _valid_proposal(current, historical)

    candidate = _validate(proposal, current, [historical])

    # Promoted prose becomes a claim the user attributes to their own evidence
    # with nothing behind it, so every rendered string is canonical node text.
    rendered = candidate.model_dump_json()
    assert proposal.reason not in rendered
    node_text = {node.summary_text for node in [*current.nodes, *historical.nodes]}
    assert any(candidate.title in text or text in candidate.title for text in node_text)


def test_the_unrelated_asset_never_becomes_the_candidate(current, historical, hard_negative):
    candidate = _validate(
        _valid_proposal(current, historical), current, [historical, hard_negative]
    )

    assert candidate.related_asset_id != hard_negative.asset_id


# -- GRAG-06 / GRAG-17: the six frozen defects ---------------------------


def test_forbidden_label_is_rejected(current, historical):
    proposal = _valid_proposal(current, historical).model_copy(
        update={"relation_type": "STRONGLY_RELATED"}
    )
    with pytest.raises(ProposalRejected) as caught:
        _validate(proposal, current, [historical])
    assert caught.value.defect == "forbidden-label"


def test_nonexistent_node_is_rejected(current, historical):
    proposal = _valid_proposal(current, historical).model_copy(
        update={
            "node_mappings": [
                ProposedRelationMapping(
                    current_node_id="CRITICAL_MOMENT:invented",
                    historical_node_id=historical.nodes[0].node_id,
                )
            ]
        }
    )
    with pytest.raises(ProposalRejected) as caught:
        _validate(proposal, current, [historical])
    assert caught.value.defect == "nonexistent-node"


def test_a_current_node_submitted_as_historical_is_rejected(current, historical):
    left, _ = _admissible_pair(current, historical)
    proposal = _valid_proposal(current, historical).model_copy(
        update={
            "node_mappings": [
                ProposedRelationMapping(
                    current_node_id=left.node_id, historical_node_id=left.node_id
                )
            ]
        }
    )
    with pytest.raises(ProposalRejected) as caught:
        _validate(proposal, current, [historical])
    # Accepting it would describe the user's own asset as the history it is
    # being compared against.
    assert caught.value.defect == "wrong-side-node"


def test_a_missing_boundary_abstains(current, historical):
    proposal = _valid_proposal(current, historical).model_copy(
        update={"current_boundary_node_ids": []}
    )
    with pytest.raises(ProposalRejected) as caught:
        _validate(proposal, current, [historical])
    assert caught.value.defect == "missing-boundary"


def test_an_ungrounded_boundary_node_abstains(current, historical):
    root = next(node for node in current.nodes if node.is_root)
    proposal = _valid_proposal(current, historical).model_copy(
        update={"current_boundary_node_ids": [root.node_id]}
    )
    with pytest.raises(ProposalRejected) as caught:
        _validate(proposal, current, [historical])
    # A root is a real node but carries no limitation, applicability or
    # counterexample role, so it grounds no transfer boundary.
    assert caught.value.defect == "missing-boundary"


def test_an_inadmissible_role_pair_is_rejected(current, historical):
    """The same mapping is admissible for one relation type and not another."""
    left, right = _admissible_pair(current, historical)
    admissible = _valid_proposal(current, historical)
    assert _validate(admissible, current, [historical]).relation_type is (
        RelationType.METHOD_REUSE
    )

    # PREREQUISITE admits only HAS_APPLICABILITY on the current side, so the very
    # pair METHOD_REUSE accepts is inadmissible here. Without the table this
    # would render as a relation whose claim nothing supports.
    assert left.role is ProjectionEdgeType.HAS_ACTION
    proposal = admissible.model_copy(
        update={
            "relation_type": RelationType.PREREQUISITE.value,
            "node_mappings": [
                ProposedRelationMapping(
                    current_node_id=left.node_id, historical_node_id=right.node_id
                )
            ],
        }
    )
    with pytest.raises(ProposalRejected) as caught:
        _validate(proposal, current, [historical])
    assert caught.value.defect == "inadmissible-role-pair"


def test_a_projection_the_runtime_never_supplied_is_rejected(current, historical, hard_negative):
    proposal = _valid_proposal(current, historical)
    with pytest.raises(ProposalRejected) as caught:
        # Only the hard-negative graph was supplied, so the named projection was
        # never one the Runtime can check identifiers against.
        _validate(proposal, current, [hard_negative])
    assert caught.value.defect == "nonexistent-node"


def test_every_frozen_defect_has_a_test():
    """The scenario names six; none may be quietly dropped."""
    declared = {
        item["id"] for item in _scenario("invalid-false-association")["invalid_proposals"]
    }
    assert declared == {
        "forbidden-label",
        "nonexistent-node",
        "wrong-side-node",
        "missing-boundary",
        "one-sided-provenance",
        "inadmissible-role-pair",
    }
    scenario = _scenario("invalid-false-association")
    # Reporting any of them as NO_MATCH would file a transport accident as a
    # semantic conclusion and cache it.
    assert scenario["expected_outcome"] == "TECHNICAL_FAILURE"
    assert scenario["must_not_be"] == "NO_MATCH"
    assert (
        scenario["expected_failure_class"]
        == DiscoveryFailureClass.RUNTIME_VALIDATION_REJECTED.value
    )


def test_the_hard_negative_corpus_is_a_finished_search():
    scenario = _scenario("hard-negative-corpus")
    assert scenario["expected_outcome"] == DiscoveryOutcome.NO_MATCH.value
    assert scenario["expected_candidate_count"] == 0
    # Presenting abstention as an error would train the user to retry until
    # something appears.
    assert scenario["must_not_be"] == DiscoveryFailureClass.MODEL_UNAVAILABLE.value.replace(
        "MODEL_UNAVAILABLE", "TECHNICAL_FAILURE"
    )


def test_an_unknown_uuid_projection_is_not_resolvable(current, historical):
    proposal = _valid_proposal(current, historical).model_copy(
        update={"historical_projection_id": UUID(int=0)}
    )
    with pytest.raises(ProposalRejected):
        _validate(proposal, current, [historical])


def test_a_candidate_naming_the_current_asset_is_rejected(current):
    proposal = RelationDiscoveryProposal(
        outcome="CANDIDATE",
        related_asset_id=current.asset_id,
        historical_projection_id=current.projection_id,
        relation_type=RelationType.SAME_THEME.value,
        node_mappings=[
            {
                "current_node_id": current.nodes[0].node_id,
                "historical_node_id": current.nodes[0].node_id,
            }
        ],
        current_boundary_node_ids=[_boundary(current).node_id],
    )
    with pytest.raises(ProposalRejected) as caught:
        _validate(proposal, current, [current])
    assert caught.value.defect == "wrong-side-node"


def test_a_no_match_proposal_yields_no_candidate(current, historical):
    proposal = RelationDiscoveryProposal(outcome="NO_MATCH")
    with pytest.raises(ProposalRejected) as caught:
        _validate(proposal, current, [historical])
    assert caught.value.defect == "not-a-candidate"


def test_validation_uses_a_fresh_candidate_identity(current, historical):
    first = _validate(_valid_proposal(current, historical), current, [historical])
    second = _validate(_valid_proposal(current, historical), current, [historical])
    assert first.candidate_id != second.candidate_id
    assert first.discovery_fingerprint == second.discovery_fingerprint == DIGEST
    assert uuid4() not in {first.candidate_id, second.candidate_id}
