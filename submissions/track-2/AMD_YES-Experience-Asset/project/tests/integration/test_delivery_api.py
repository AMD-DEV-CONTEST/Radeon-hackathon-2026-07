"""E7 delivery at the HTTP seam.

PR #34 delivered E7 as a service with no HTTP surface, so preview, export and
deletion were reachable only from Python. These tests exercise the routes the
product actually calls.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.experience_asset.api.main import create_app
from app.experience_asset.delivery import LocalArtifactStore
from app.experience_asset.delivery.models import DeliveryOperation
from tests.e7_fixtures import ASSET_ID
from tests.integration.test_e7_deletion import save_private_export
from tests.integration.test_m4_api import create_m4


def _app(tmp_path: Path):
    from app.experience_asset.inference.models import M4MapProposal  # noqa: F401
    from tests.integration.test_m4_api import ScriptedM4Client

    return create_app(database_path=tmp_path / "app.sqlite3", model_client=ScriptedM4Client())


def _seed(client: TestClient):
    """Create one stored draft through the same service the API is bound to."""

    delivery = client.app.state.delivery_service
    return save_private_export(delivery)


def _ready_asset(client: TestClient) -> tuple[str, dict]:
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
    return asset_id, evaluated.json()


def _public_draft_body(client: TestClient, asset_id: str, evaluated: dict) -> dict:
    public = next(
        decision for decision in evaluated["matrix"]["decisions"] if decision["route"] == "PUBLIC"
    )
    statement_id = public["supporting_statement_ids"][0]
    statement = next(
        item
        for item in client.app.state.repository.get_current(UUID(asset_id)).statements
        if str(item.statement_id) == statement_id
    )
    claim = {"text": statement.text, "statement_ids": [statement_id]}
    return {
        "create_request_id": str(uuid4()),
        "route": "PUBLIC",
        "language": "zh-CN",
        "content": {
            "title": "我的可复用经验",
            "summary": claim,
            "sections": [{"heading": "核心经验", "claims": [claim]}],
            "notices": ["对外分享前请复核内容和隐私状态。"],
        },
    }


def test_preview_returns_three_formats_sharing_one_identity(tmp_path: Path):
    with TestClient(_app(tmp_path)) as client:
        draft, _ = _seed(client)

        response = client.get(f"/api/v1/delivery/drafts/{draft.draft.route_draft_id}/preview")

        assert response.status_code == 200, response.text
        body = response.json()
        identity = body["identity"]
        # One canonical identity behind all three renderings: if HTML and JSON
        # could disagree the user would have no way to know which one shipped.
        assert identity["route_draft_hash"] == draft.draft.content_hash
        assert identity["route_draft_hash"] in body["json"]
        assert body["html"] and body["markdown"] and body["json"]
        assert body["operation"] == DeliveryOperation.IN_APP_PREVIEW.value


def test_preview_of_an_unknown_draft_is_a_visible_404(tmp_path: Path):
    with TestClient(_app(tmp_path)) as client:
        response = client.get(
            "/api/v1/delivery/drafts/00000000-0000-4000-8000-0000000000ff/preview"
        )

        assert response.status_code == 404


def test_external_export_without_an_approval_is_refused(tmp_path: Path):
    """Preview is free; external sharing is not."""

    with TestClient(_app(tmp_path)) as client:
        draft, _ = _seed(client)

        response = client.post(
            f"/api/v1/delivery/drafts/{draft.draft.route_draft_id}/exports",
            json={"operation": DeliveryOperation.SHAREABLE_EXTERNAL_EXPORT.value},
        )

        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"]


def test_public_draft_approval_and_export_use_one_persisted_binding(tmp_path: Path):
    """The product path must not trust a client-supplied RouteDraft or approval."""

    with TestClient(_app(tmp_path)) as client:
        asset_id, evaluated = _ready_asset(client)
        created = client.post(
            f"/api/v1/delivery/assets/{asset_id}/drafts",
            json=_public_draft_body(client, asset_id, evaluated),
        )
        assert created.status_code == 201, created.text
        draft = created.json()
        draft_id = draft["draft"]["route_draft_id"]

        preview = client.get(f"/api/v1/delivery/drafts/{draft_id}/preview")
        assert preview.status_code == 200, preview.text
        assert (
            preview.json()["identity"]["renderer_input_identity"]
            == draft["renderer_input_identity"]
        )

        approved = client.post(
            f"/api/v1/m5/assets/{asset_id}/approvals",
            json={
                "route_draft_id": draft_id,
                "user_action": "APPROVE_SHAREABLE_EXPORT",
                "idempotency_key": f"demo:{draft_id}",
            },
        )
        assert approved.status_code == 201, approved.text
        approval_id = approved.json()["approval_id"]
        with sqlite3.connect(client.app.state.repository.database_path) as connection:
            row = connection.execute(
                "SELECT created_by_run_id FROM m5_approvals WHERE approval_id=?",
                (approval_id,),
            ).fetchone()
        assert row is not None
        approval_run_id = UUID(row[0])
        approval_traces = client.app.state.repository.list_workflow_traces(
            approval_run_id
        )
        assert {trace["node_name"] for trace in approval_traces} >= {
            "wait_m5_approval",
            "validate_m5_approval",
            "verify_m5_state",
            "terminalize_m5_run",
        }

    # A new application process must be able to recover both persisted sides
    # of the binding. In-memory fixture adapters cannot satisfy this assertion.
    with TestClient(_app(tmp_path)) as client:
        exported = client.post(
            f"/api/v1/delivery/drafts/{draft_id}/exports",
            json={
                "operation": "SHAREABLE_EXTERNAL_EXPORT",
                "approval_id": approval_id,
            },
        )
        assert exported.status_code == 201, exported.text
        assert exported.json()["state"] == "COMPLETE"


def test_live_draft_rejects_free_text_with_borrowed_statement_ids(tmp_path: Path):
    """A valid statement ID is evidence, not permission to invent its claim."""

    with TestClient(_app(tmp_path)) as client:
        asset_id, evaluated = _ready_asset(client)
        body = _public_draft_body(client, asset_id, evaluated)
        invented = "我凭这次经历证明任何疾病都能在一天内治愈。"
        body["content"]["summary"]["text"] = invented
        body["content"]["sections"][0]["claims"][0]["text"] = invented

        response = client.post(
            f"/api/v1/delivery/assets/{asset_id}/drafts",
            json=body,
        )

        assert response.status_code == 422, response.text
        assert "exact canonical evidence" in response.json()["detail"]

        borrowed_title = _public_draft_body(client, asset_id, evaluated)
        borrowed_title["content"]["title"] = invented
        title_response = client.post(
            f"/api/v1/delivery/assets/{asset_id}/drafts",
            json=borrowed_title,
        )
        assert title_response.status_code == 422, title_response.text
        assert "server-defined neutral text" in title_response.json()["detail"]


def test_identical_reevaluation_preserves_exact_approval(tmp_path: Path):
    with TestClient(_app(tmp_path)) as client:
        asset_id, evaluated = _ready_asset(client)
        draft = client.post(
            f"/api/v1/delivery/assets/{asset_id}/drafts",
            json=_public_draft_body(client, asset_id, evaluated),
        ).json()
        draft_id = draft["draft"]["route_draft_id"]
        approved = client.post(
            f"/api/v1/m5/assets/{asset_id}/approvals",
            json={
                "route_draft_id": draft_id,
                "user_action": "APPROVE_SHAREABLE_EXPORT",
                "idempotency_key": f"same:{draft_id}",
            },
        )
        assert approved.status_code == 201, approved.text

        repeated = client.post(f"/api/v1/m5/assets/{asset_id}/evaluate")
        assert repeated.status_code == 201, repeated.text
        exported = client.post(
            f"/api/v1/delivery/drafts/{draft_id}/exports",
            json={
                "operation": "SHAREABLE_EXTERNAL_EXPORT",
                "approval_id": approved.json()["approval_id"],
            },
        )
        assert exported.status_code == 201, exported.text


def test_legacy_hash_only_approval_fails_closed_instead_of_crashing(tmp_path: Path):
    with TestClient(_app(tmp_path)) as client:
        asset_id, evaluated = _ready_asset(client)
        draft = client.post(
            f"/api/v1/delivery/assets/{asset_id}/drafts",
            json=_public_draft_body(client, asset_id, evaluated),
        ).json()
        draft_id = draft["draft"]["route_draft_id"]
        approval = client.post(
            f"/api/v1/m5/assets/{asset_id}/approvals",
            json={
                "route_draft_id": draft_id,
                "user_action": "APPROVE_SHAREABLE_EXPORT",
                "idempotency_key": f"legacy:{draft_id}",
            },
        ).json()
        with sqlite3.connect(client.app.state.repository.database_path) as connection:
            connection.execute(
                "UPDATE m5_approvals SET draft_id=? WHERE approval_id=?",
                ("f" * 64, approval["approval_id"]),
            )
            connection.commit()

        rejected = client.post(
            f"/api/v1/delivery/drafts/{draft_id}/exports",
            json={
                "operation": "SHAREABLE_EXTERNAL_EXPORT",
                "approval_id": approval["approval_id"],
            },
        )

        assert rejected.status_code == 403, rejected.text
        assert rejected.json()["detail"]["code"] == "APPROVAL_BINDING_UNAVAILABLE"


def test_external_export_rejects_approval_for_another_persisted_draft(tmp_path: Path):
    with TestClient(_app(tmp_path)) as client:
        asset_id, evaluated = _ready_asset(client)
        first = client.post(
            f"/api/v1/delivery/assets/{asset_id}/drafts",
            json=_public_draft_body(client, asset_id, evaluated),
        ).json()
        approval = client.post(
            f"/api/v1/m5/assets/{asset_id}/approvals",
            json={
                "route_draft_id": first["draft"]["route_draft_id"],
                "user_action": "APPROVE_SHAREABLE_EXPORT",
                "idempotency_key": "first-draft",
            },
        )
        assert approval.status_code == 201, approval.text

        second_body = _public_draft_body(client, asset_id, evaluated)
        second = client.post(f"/api/v1/delivery/assets/{asset_id}/drafts", json=second_body)
        assert second.status_code == 201, second.text

        rejected = client.post(
            f"/api/v1/delivery/drafts/{second.json()['draft']['route_draft_id']}/exports",
            json={
                "operation": "SHAREABLE_EXTERNAL_EXPORT",
                "approval_id": approval.json()["approval_id"],
            },
        )
        assert rejected.status_code == 403, rejected.text
        assert rejected.json()["detail"]["code"] == "APPROVAL_BINDING_MISMATCH"


def test_deletion_needs_a_second_confirmation_and_then_completes(tmp_path: Path):
    with TestClient(_app(tmp_path)) as client:
        _, exported = _seed(client)

        requested = client.post(
            "/api/v1/delivery/deletion-requests", json={"asset_id": str(ASSET_ID)}
        )
        assert requested.status_code == 201, requested.text
        request = requested.json()

        # First attempt without the explicit second step must not delete.
        premature = client.post(
            f"/api/v1/delivery/deletion-requests/{request['request_id']}/confirm",
            json={
                "confirmation_token": request["confirmation_token"],
                "second_confirmation": False,
            },
        )
        assert premature.status_code == 428, premature.text
        assert all(Path(record.path).exists() for record in exported.records)

        confirmed = client.post(
            f"/api/v1/delivery/deletion-requests/{request['request_id']}/confirm",
            json={
                "confirmation_token": request["confirmation_token"],
                "second_confirmation": True,
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["terminal_state"] == "SUCCEEDED"
        assert not any(Path(record.path).exists() for record in exported.records)


def test_confirmed_deletion_is_idempotent_over_http(tmp_path: Path):
    with TestClient(_app(tmp_path)) as client:
        _seed(client)
        request = client.post(
            "/api/v1/delivery/deletion-requests", json={"asset_id": str(ASSET_ID)}
        ).json()
        body = {
            "confirmation_token": request["confirmation_token"],
            "second_confirmation": True,
        }
        path = f"/api/v1/delivery/deletion-requests/{request['request_id']}/confirm"

        first = client.post(path, json=body)
        second = client.post(path, json=body)

        assert first.status_code == second.status_code == 200
        assert first.json()["terminal_state"] == second.json()["terminal_state"]


def test_delivery_store_is_separate_from_the_canonical_asset_database(tmp_path: Path):
    """Irreversible file deletion must not live next to version history."""

    with TestClient(_app(tmp_path)) as client:
        delivery = client.app.state.delivery_service
        assert delivery.repository.database_path != tmp_path / "app.sqlite3"
        assert isinstance(delivery.artifact_store, LocalArtifactStore)
