"""Per-item tamper negatives for the role-graph contract.

A validator that only checks identifier uniqueness looks strict while accepting
graphs that describe impossible things. These tests mutate one field of a valid
checked-in fixture at a time and require a rejection for each, so "the contract
is frozen" means the frozen shape is actually enforced rather than merely
declared.

Each case names the failure it prevents. A rejection without a stated reason
teaches the next reader nothing about why the rule exists, and rules whose
purpose is unknown get relaxed the first time they are inconvenient.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.experience_asset.domain.relation import (
    KnowledgeCardReadinessRecordV1,
    NodeProvenanceV1,
    RelationCandidateV1,
    RoleGraphEdgeV1,
    RoleGraphNodeV1,
    RoleGraphProjectionV1,
    compute_projection_hash,
)

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "examples" / "e5"
PROJECTION = FIXTURES / "instance" / "role-graph-projection-current.json"
CANDIDATE = FIXTURES / "instance" / "relation-candidate.json"
READINESS = FIXTURES / "instance" / "knowledge-card-readiness.json"

OTHER_ID = "00000000-0000-4000-8000-0000000009ff"


def projection() -> dict:
    return json.loads(PROJECTION.read_text(encoding="utf-8"))


def rehash(payload: dict) -> dict:
    """Recompute the hash so a case tests its own defect, not a stale hash.

    Members are built with `model_construct`, which skips validation: several
    tampered inputs are deliberately invalid, and validating them here would
    reject the case before the projection validator ever sees it.
    """
    parsed = copy.deepcopy(payload)
    nodes = [RoleGraphNodeV1.model_construct(**node) for node in parsed["nodes"]]
    edges = [RoleGraphEdgeV1.model_construct(**edge) for edge in parsed["edges"]]
    provenance = [
        NodeProvenanceV1.model_construct(**entry) for entry in parsed["provenance"]
    ]
    parsed["projection_hash"] = compute_projection_hash(
        asset_id=parsed["asset_id"],
        version_id=parsed["version_id"],
        knowledge_card_hash=parsed["knowledge_card_hash"],
        projection_schema_version=parsed["projection_schema_version"],
        nodes=nodes,
        edges=edges,
        provenance=provenance,
    )
    return parsed


def test_the_untampered_fixture_still_validates() -> None:
    """Guard the guards: if the baseline failed, every case below would pass."""
    RoleGraphProjectionV1.model_validate(projection())


def _member_edge(payload: dict) -> dict:
    return payload["edges"][0]


PROJECTION_TAMPERS = {
    "edge type contradicts its member node's role": lambda d: _member_edge(d).__setitem__(
        "edge_type",
        "HAS_CUE" if _member_edge(d)["edge_type"] != "HAS_CUE" else "HAS_REASON",
    ),
    "edge belongs to another projection": lambda d: _member_edge(d).__setitem__(
        "projection_id", OTHER_ID
    ),
    "node belongs to another projection": lambda d: d["nodes"][0].__setitem__(
        "projection_id", OTHER_ID
    ),
    "provenance belongs to another projection": lambda d: d["provenance"][0].__setitem__(
        "projection_id", OTHER_ID
    ),
    "edge spans two canonical records": lambda d: _member_edge(d).__setitem__(
        "canonical_record_id", OTHER_ID
    ),
    "active projection carries invalidation evidence": lambda d: d.__setitem__(
        "invalidation_reason", "should not be here while ACTIVE"
    ),
}


@pytest.mark.parametrize("defect", sorted(PROJECTION_TAMPERS))
def test_projection_rejects_each_structural_defect(defect) -> None:
    payload = projection()
    PROJECTION_TAMPERS[defect](payload)
    # Rehash first, so the case proves the structural rule rather than merely
    # tripping the hash check that every mutation would also trip.
    with pytest.raises(ValueError):
        RoleGraphProjectionV1.model_validate(rehash(payload))


def test_projection_rejects_a_forged_hash() -> None:
    """A drifted projection would otherwise present itself as its own inputs."""
    payload = projection()
    payload["projection_hash"] = "f" * 64
    with pytest.raises(ValueError, match="projection_hash"):
        RoleGraphProjectionV1.model_validate(payload)


def test_changing_only_the_summary_text_is_rejected() -> None:
    """The real regression: change the text, keep every declared hash.

    An earlier test changed the *declared* hash instead and never called the
    validator, so it stayed green with the text/hash check deleted. This one
    fails without it — the summary is what reaches the FTS index and the model
    prompt, so a validator that ignores it lets the input change while every
    hash reports it unchanged.
    """
    payload = projection()
    payload["nodes"][0]["summary_text"] = "replacement summary reaching the index and the prompt"

    with pytest.raises(ValueError, match="summary_text_hash"):
        RoleGraphProjectionV1.model_validate(payload)


def test_a_matching_text_and_hash_pair_is_accepted() -> None:
    """Paired positive: recomputing the hash for new text must be allowed."""
    payload = projection()
    text = "rewritten summary text"
    payload["nodes"][0]["summary_text"] = text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    payload["nodes"][0]["summary_text_hash"] = digest

    RoleGraphProjectionV1.model_validate(rehash(payload))


def test_projection_hash_covers_content_not_just_identity() -> None:
    """Editing node content must change the projection hash."""
    payload = projection()
    before = payload["projection_hash"]
    payload["nodes"][0]["summary_text_hash"] = "a" * 64
    assert rehash(payload)["projection_hash"] != before


def test_active_projection_rejects_a_member_node_with_no_edge() -> None:
    """An unreachable member node is quotable by id but has no explanation."""
    payload = projection()
    payload["edges"] = [
        edge
        for edge in payload["edges"]
        if edge["member_node_id"] != payload["edges"][0]["member_node_id"]
    ]
    with pytest.raises(ValueError):
        RoleGraphProjectionV1.model_validate(rehash(payload))


CANDIDATE_TAMPERS = {
    "relation type outside the closed vocabulary": lambda d: d.__setitem__(
        "relation_type", "LOOSELY_RELATED"
    ),
    "no current-side transfer boundary": lambda d: d.__setitem__(
        "current_boundary_node_ids", []
    ),
    "provenance on one side only": lambda d: d.__setitem__(
        "provenance", [ref for ref in d["provenance"] if ref["side"] == "CURRENT"]
    ),
    "inadmissible role pair for the declared relation": lambda d: d["node_mappings"][
        0
    ].__setitem__("current_role", "HAS_CUE"),
    "relation between an asset and itself": lambda d: d.__setitem__(
        "related_asset_id", d["current_asset_id"]
    ),
    "candidate claims historical detail": lambda d: d.__setitem__(
        "detail_included", True
    ),
    "root mapping smuggled into a role-level relation": lambda d: d["node_mappings"][
        0
    ].update({"current_role": None, "historical_role": None}),
    "half a mapping: one root and one member": lambda d: d["node_mappings"][0].__setitem__(
        "current_role", None
    ),
}


@pytest.mark.parametrize("defect", sorted(CANDIDATE_TAMPERS))
def test_candidate_rejects_each_invalid_proposal(defect) -> None:
    payload = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    CANDIDATE_TAMPERS[defect](payload)
    with pytest.raises(ValueError):
        RelationCandidateV1.model_validate(payload)


def test_same_theme_cannot_be_the_fallback_label() -> None:
    """An empty admissibility table must not mean "anything goes".

    If `SAME_THEME` accepted any role pair, it would become the label a proposal
    falls back to when no other rule fits — the escape hatch a closed vocabulary
    exists to remove.
    """
    payload = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    payload["relation_type"] = "SAME_THEME"
    with pytest.raises(ValueError, match="root-to-root"):
        RelationCandidateV1.model_validate(payload)


READINESS_TAMPERS = {
    "accepted but still building": lambda d: d.__setitem__("lifecycle", "BUILDING"),
    "active yet carrying an invalidation time": lambda d: d.update(
        {"invalidated_at": "2026-08-02T00:00:00Z", "invalidation_reason": "x"}
    ),
    "stale without saying why": lambda d: d.__setitem__("lifecycle", "STALE"),
    "confirmed while naming accepted gaps": lambda d: d.__setitem__(
        "accepted_gap_statement_ids", ["00000000-0000-4000-8000-0000000009fe"]
    ),
}


@pytest.mark.parametrize("defect", sorted(READINESS_TAMPERS))
def test_readiness_rejects_each_contradictory_state(defect) -> None:
    """Two consumers must not be able to read one record as opposite answers."""
    payload = json.loads(READINESS.read_text(encoding="utf-8"))
    READINESS_TAMPERS[defect](payload)
    with pytest.raises(ValueError):
        KnowledgeCardReadinessRecordV1.model_validate(payload)


LEGACY_FALSEY_VALUES = [{}, "", False, 0, "[]"]


@pytest.mark.parametrize("value", LEGACY_FALSEY_VALUES)
def test_legacy_shim_rejects_malformed_falsey_values(value) -> None:
    """`{}`, `""`, `False`, `0` are not the pre-E5 shape.

    Testing truthiness would drop them as "empty", hiding a corrupt snapshot
    behind a compatibility path built for one known shape.
    """
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.experience_asset.domain.factory import new_empty_asset
    from app.experience_asset.domain.models import ExperienceAssetV1

    asset = new_empty_asset(asset_id=uuid4(), version_id=uuid4(), now=datetime.now(UTC))
    payload = asset.model_dump(mode="json")
    payload["relation_candidates"] = value

    with pytest.raises(ValueError):
        ExperienceAssetV1.model_validate(payload)


def test_legacy_shim_accepts_the_real_pre_e5_defaults() -> None:
    """Paired positive: the shape this path exists for must still load."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.experience_asset.domain.factory import new_empty_asset
    from app.experience_asset.domain.models import ExperienceAssetV1

    asset = new_empty_asset(asset_id=uuid4(), version_id=uuid4(), now=datetime.now(UTC))
    payload = asset.model_dump(mode="json")
    payload.update(
        {
            "related_assets": [],
            "knowledge_card_readiness": None,
            "relation_candidates": [],
            "relation_candidate_decisions": [],
        }
    )

    assert ExperienceAssetV1.model_validate(payload).version_id == asset.version_id
