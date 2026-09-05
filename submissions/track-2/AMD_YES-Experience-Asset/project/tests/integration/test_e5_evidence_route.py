"""The evidence card over HTTP — ticket 08 criterion 7's backend half.

Until ticket 01 gave `RelationWorkspaceV1` a field for it, the card could be
built, hashed and verified at the module seam but not returned over the declared
contract, and the route raised the typed not-implemented. These tests drive the
route itself, because that is the seam a consumer actually reaches.

State is built through the repository rather than through the HTTP chain: a
confirmed relation needs two ready assets with active projections, and a
discovery call to produce the candidate. Building it directly keeps these tests
about the evidence route rather than about discovery.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.experience_asset.api.main import create_app
from app.experience_asset.application.decision import DecisionService
from app.experience_asset.application.invalidation import (
    InvalidationService,
    MutationEvent,
)
from tests.integration.test_e5_decision import (
    _decision,
    _pair,
    _settled_candidate,
)


def _world(tmp_path: Path, name: str):
    """Two ready assets, one confirmed relation, and a client over that database."""
    database = tmp_path / name
    repository, current, historical = _pair(tmp_path, name)
    candidate = _settled_candidate(repository, current, historical)
    asset, readiness, _ = current
    DecisionService(repository).decide(
        asset.asset_id,
        candidate.candidate_id,
        _decision(candidate, readiness, "CONFIRM"),
    )
    relation = repository.list_confirmed_relations(asset.asset_id)[0]
    return repository, TestClient(create_app(database_path=database)), asset, relation


def _body(asset, relation, **overrides) -> dict:
    body = {
        "asset_id": str(asset.asset_id),
        "current_version_id": str(asset.version_id),
        "knowledge_card_version_id": str(relation.current_version_id),
        "knowledge_card_hash": relation.current_knowledge_card_hash,
        "scope": "CROSS_ASSET_DETAIL",
        "relation_bindings": [
            {
                "relation_id": str(relation.relation_id),
                "related_asset_id": str(relation.related_asset_id),
            }
        ],
    }
    body.update(overrides)
    return body


def _post(client, asset, relation, **overrides):
    return client.post(
        f"/api/v1/relations/assets/{asset.asset_id}/relations/{relation.relation_id}/evidence",
        json=_body(asset, relation, **overrides),
    )


def test_a_confirmed_relation_returns_its_rendered_card(tmp_path: Path):
    repository, client, asset, relation = _world(tmp_path, "render.sqlite3")

    with client:
        response = _post(client, asset, relation)

    assert response.status_code == 200, response.text
    card = response.json()["evidence_card"]
    assert card["outcome"] == "RENDERED"
    assert card["relation_id"] == str(relation.relation_id)
    assert card["card_hash"]
    # GRAG-13: the bilateral package, not a summary of it.
    assert card["mapped_roles"] and card["boundaries"]
    assert {side["side"] for side in card["provenance"]} == {"CURRENT", "HISTORICAL"}
    # The binding the card was authorized against travels with it, so a reader
    # can check the card against the card they accepted.
    assert card["current_knowledge_card_hash"] == relation.current_knowledge_card_hash


def test_the_workspace_still_carries_the_relation_state_around_the_card(tmp_path: Path):
    """The card rides inside the relation surface rather than replacing it.

    A separate response model would have split one relation surface into two
    shapes the front end fetches separately, and the binding shown beside the
    card is what makes it checkable.
    """
    repository, client, asset, relation = _world(tmp_path, "around.sqlite3")

    with client:
        workspace = _post(client, asset, relation).json()

    assert workspace["asset_id"] == str(asset.asset_id)
    assert workspace["readiness"] is not None
    assert [item["relation_id"] for item in workspace["confirmed_relations"]] == [
        str(relation.relation_id)
    ]


def test_a_revoked_relation_is_refused_rather_than_rendered(tmp_path: Path):
    """Revocation at the repository must reach the wire.

    If the route rendered from the request's own binding values, a replayed
    request would keep returning the card after the permission was revoked —
    the failure mode this whole ticket exists to prevent.
    """
    repository, client, asset, relation = _world(tmp_path, "revoked.sqlite3")
    InvalidationService(repository).apply(
        MutationEvent.CURRENT_ASSET_CORRECTION,
        asset_id=asset.asset_id,
        reason="the user corrected the asset",
    )

    with client:
        response = _post(client, asset, relation)

    assert response.status_code == 404
    assert response.json()["detail"]["reason"] == "RELATION_NOT_LIVE"


def test_an_unknown_relation_answers_the_same_way_as_a_revoked_one(tmp_path: Path):
    """Indistinguishable on purpose.

    Separating "never existed" from "you may not read it" would let a caller
    probe for which relations exist on assets they cannot read.
    """
    _, client, asset, relation = _world(tmp_path, "unknown.sqlite3")
    stranger = relation.model_copy(update={"relation_id": uuid4()})

    with client:
        response = _post(client, asset, stranger)

    assert response.status_code == 404
    assert response.json()["detail"]["reason"] == "RELATION_NOT_LIVE"


def test_a_request_naming_another_asset_is_refused_before_anything_is_read(
    tmp_path: Path,
):
    _, client, asset, relation = _world(tmp_path, "mismatch.sqlite3")

    with client:
        response = _post(client, asset, relation, asset_id=str(uuid4()))

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "BINDING_MISMATCH"


def test_the_read_leaves_the_current_card_hash_untouched(tmp_path: Path):
    """GRAG-14 at the HTTP seam, where a consumer could actually cause it."""
    repository, client, asset, relation = _world(tmp_path, "noncontam.sqlite3")
    before = repository.get_current(asset.asset_id)

    with client:
        assert _post(client, asset, relation).status_code == 200

    after = repository.get_current(asset.asset_id)
    assert after.version_id == before.version_id
    assert after.model_dump_json() == before.model_dump_json()
    readiness = repository.read_active_readiness(asset.asset_id)
    assert readiness.knowledge_card_hash == relation.current_knowledge_card_hash
