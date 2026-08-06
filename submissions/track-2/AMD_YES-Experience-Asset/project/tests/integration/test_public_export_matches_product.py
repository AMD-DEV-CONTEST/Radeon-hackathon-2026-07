"""The public export must say what the product surface says.

E6 stores its route decisions in a binding-scoped sidecar, while the canonical
snapshot still carries the placeholder decisions written before M5 ran. Exporting
the snapshot's copy publishes "every route blocked for missing evidence" while
the UI shows three routes eligible — a deliverable that materially misstates
what the product did, which the execution package lists as a blocking failure.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from app.experience_asset.api.main import create_app
from app.experience_asset.domain.public_serialization import to_public_asset
from app.experience_asset.persistence.m5_store import M5Store
from app.experience_asset.persistence.repository import SQLiteAssetRepository
from tests.integration.test_m4_api import ScriptedM4Client, create_m4


def _evaluated_asset(tmp_path: Path):
    database_path = tmp_path / "export.sqlite3"
    with TestClient(
        create_app(database_path=database_path, model_client=ScriptedM4Client())
    ) as client:
        asset_id, workspace = create_m4(client)
        accepted = client.post(
            f"/api/v1/m4/assets/{asset_id}/accept",
            json={
                "asset_id": asset_id,
                "expected_artifact_id": workspace["map"]["artifact_id"],
                "expected_canonical_version_id": workspace["canonical_version_id"],
                "user_action": "CONFIRM",
            },
        )
        assert accepted.status_code == 201, accepted.text
        evaluated = client.post(f"/api/v1/m5/assets/{asset_id}/evaluate")
        assert evaluated.status_code == 201, evaluated.text
        surface = evaluated.json()

    repository = SQLiteAssetRepository(database_path)
    repository.initialize()
    asset = repository.get_current(UUID(asset_id))
    content_hash = repository.get_version_content_hash(asset.version_id)
    matrix = M5Store(database_path).read_route_matrix(
        asset_id=UUID(asset_id), version_id=asset.version_id, content_hash=content_hash
    )
    return asset, repository, matrix, surface


def test_export_route_states_match_what_the_user_was_shown(tmp_path: Path):
    asset, repository, matrix, surface = _evaluated_asset(tmp_path)
    assert matrix is not None

    public = to_public_asset(
        asset,
        relations=repository.list_confirmed_relations(asset.asset_id),
        route_decisions=matrix.decisions,
    )

    shown = {
        decision["route"]: decision["eligibility"]
        for decision in surface["matrix"]["decisions"]
    }
    exported = {route: value["eligibility"] for route, value in public["routes"].items()}
    assert exported == {
        "private_self": shown["PRIVATE_SELF"].lower(),
        "beginner": shown["BEGINNER"].lower(),
        "peer": shown["PEER"].lower(),
        "customer_evaluator": shown["CUSTOMER_EVALUATOR"].lower(),
        "public": shown["PUBLIC"].lower(),
    }


def test_omitting_the_m5_decisions_publishes_the_stale_placeholders(tmp_path: Path):
    """Pins the failure mode, so a future caller cannot reintroduce it quietly."""

    asset, repository, matrix, surface = _evaluated_asset(tmp_path)

    stale = to_public_asset(
        asset, relations=repository.list_confirmed_relations(asset.asset_id)
    )
    live = to_public_asset(
        asset,
        relations=repository.list_confirmed_relations(asset.asset_id),
        route_decisions=matrix.decisions,
    )

    assert stale["routes"] != live["routes"]
    assert all(value["eligibility"] == "blocked" for value in stale["routes"].values())


def test_customer_route_stays_ineligible_in_the_export(tmp_path: Path):
    """The truthful ineligible route has to survive serialization too."""

    asset, repository, matrix, _ = _evaluated_asset(tmp_path)

    public = to_public_asset(
        asset,
        relations=repository.list_confirmed_relations(asset.asset_id),
        route_decisions=matrix.decisions,
    )

    customer = public["routes"]["customer_evaluator"]
    assert customer["eligibility"] == "ineligible"
    assert "MISSING_QUALIFYING_CONTEXT" in customer["reason"]
