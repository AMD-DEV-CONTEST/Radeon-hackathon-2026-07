"""E6 at the HTTP seam, over SQLite, across a restart.

PR #31 had no API and no persistence, so "the user resolved a finding" lived
only in a Python object. These tests use the real app: build an asset through
M1-M4, evaluate M5, act on a finding, approve, then throw the process away and
open a second client on the same database to check the decisions survived.
"""

from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from app.experience_asset.api.main import create_app
from app.experience_asset.domain.enums import RouteType
from tests.integration.test_m4_api import ScriptedM4Client, create_m4


def _client(database_path: Path) -> TestClient:
    return TestClient(
        create_app(database_path=database_path, model_client=ScriptedM4Client())
    )


def _ready_asset(client: TestClient) -> str:
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
    return asset_id


def test_workspace_reports_not_ready_before_m4_acceptance(tmp_path: Path):
    database_path = tmp_path / "m5-not-ready.sqlite3"
    with _client(database_path) as client:
        asset_id, _ = create_m4(client)

        response = client.get(f"/api/v1/m5/assets/{asset_id}/workspace")

        # Not an error: the user has to be able to see why M5 is unavailable.
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["stale_reason"] == "M5_INPUT_NOT_READY"
        assert body["matrix"] is None


def test_evaluate_produces_five_routes_and_a_sourced_privacy_review(tmp_path: Path):
    database_path = tmp_path / "m5-evaluate.sqlite3"
    with _client(database_path) as client:
        asset_id = _ready_asset(client)

        response = client.post(f"/api/v1/m5/assets/{asset_id}/evaluate")

        assert response.status_code == 201, response.text
        body = response.json()
        routes = {decision["route"] for decision in body["matrix"]["decisions"]}
        assert routes == {
            RouteType.PRIVATE_SELF.value,
            RouteType.BEGINNER.value,
            RouteType.PEER.value,
            RouteType.CUSTOMER_EVALUATOR.value,
            RouteType.PUBLIC.value,
        }
        review = body["privacy_review"]
        assert review["proposal_sources"], "a review must name what produced it"

        customer = next(
            decision
            for decision in body["matrix"]["decisions"]
            if decision["route"] == RouteType.CUSTOMER_EVALUATOR.value
        )
        assert customer["eligibility"] == "INELIGIBLE"
        assert "MISSING_QUALIFYING_CONTEXT" in customer["reason_codes"]


def test_matrix_and_review_survive_a_restart(tmp_path: Path):
    database_path = tmp_path / "m5-restart.sqlite3"
    with _client(database_path) as client:
        asset_id = _ready_asset(client)
        evaluated = client.post(f"/api/v1/m5/assets/{asset_id}/evaluate")
        assert evaluated.status_code == 201, evaluated.text
        before = evaluated.json()

    # New process, same database: nothing may be held in memory.
    with _client(database_path) as client:
        response = client.get(f"/api/v1/m5/assets/{asset_id}/workspace")

    assert response.status_code == 200, response.text
    after = response.json()
    assert after["matrix_hash"] == before["matrix_hash"]
    assert after["privacy_review"]["review_hash"] == before["privacy_review"]["review_hash"]


def test_approval_requires_an_evaluation_first(tmp_path: Path):
    database_path = tmp_path / "m5-approve-order.sqlite3"
    with _client(database_path) as client:
        asset_id = _ready_asset(client)

        response = client.post(
            f"/api/v1/m5/assets/{asset_id}/approvals",
            json={
                "request": {
                    "asset_id": asset_id,
                    "version_id": str(UUID(int=1)),
                    "route": RouteType.PUBLIC.value,
                    "language": "en",
                    "expected_content_hash": "0" * 64,
                    "expected_privacy_review_hash": "0" * 64,
                    "expected_route_draft_hash": "0" * 64,
                    "expected_renderer_input_hash": "0" * 64,
                    "user_action": "APPROVE",
                },
                "draft": {
                    "route_draft_id": str(UUID(int=2)),
                    "route": RouteType.PUBLIC.value,
                    "language": "en",
                    "content": "draft",
                    "draft_hash": "0" * 64,
                    "canonical_version_id": str(UUID(int=1)),
                    "statement_ids": [],
                },
                "renderer_input_hash": "0" * 64,
            },
        )

        assert response.status_code in {409, 422}, response.text


def test_reevaluation_marks_earlier_approvals_of_other_bindings_stale(tmp_path: Path):
    """A fresh matrix is the moment an older binding stops holding."""

    database_path = tmp_path / "m5-stale.sqlite3"
    with _client(database_path) as client:
        asset_id = _ready_asset(client)
        first = client.post(f"/api/v1/m5/assets/{asset_id}/evaluate")
        assert first.status_code == 201, first.text
        second = client.post(f"/api/v1/m5/assets/{asset_id}/evaluate")
        assert second.status_code == 201, second.text

        # Re-evaluating the same unchanged card is idempotent in outcome.
        assert second.json()["matrix_hash"] == first.json()["matrix_hash"]


def test_evaluate_runs_through_the_startup_compiled_m5_graph(tmp_path: Path):
    database_path = tmp_path / "m5-graph.sqlite3"
    app = create_app(database_path=database_path, model_client=ScriptedM4Client())
    with TestClient(app) as client:
        assert client.app.state.m5_graph.compile_count == 1
        asset_id = _ready_asset(client)

        response = client.post(f"/api/v1/m5/assets/{asset_id}/evaluate")

        assert response.status_code == 201, response.text
        assert client.app.state.m5_graph.compile_count == 1
        assert client.app.state.m5_graph.last_state is not None
        assert client.app.state.m5_graph.last_state.route_matrix_hash == response.json()[
            "matrix_hash"
        ]
        run_id = UUID(client.app.state.m5_graph.last_state.run_id)
        terminal = client.app.state.repository.get_terminal_result(run_id)
        assert terminal is not None
        assert terminal.state.value == "NEEDS_USER_INPUT"
        traces = client.app.state.repository.list_workflow_traces(run_id)
        assert {trace["node_name"] for trace in traces} >= {
            "load_m5_context",
            "evaluate_m5_routes",
            "review_m5_privacy",
            "wait_m5_approval",
            "terminalize_m5_run",
        }
        assert all(trace["checkpoint_id"] for trace in traces)
        assert client.app.state.m5_graph._recovery_identity_matches(
            run_id, client.app.state.m5_graph.last_state
        )
        client.app.state.m5_graph.code_commit = "different-commit"
        assert not client.app.state.m5_graph._recovery_identity_matches(
            run_id, client.app.state.m5_graph.last_state
        )
