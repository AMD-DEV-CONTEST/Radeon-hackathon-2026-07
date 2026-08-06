"""Ticket 03 — explicit acceptance to KnowledgeCardReady, at the HTTP seam."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.experience_asset.api.main import create_app
from app.experience_asset.application.readiness import READINESS_REFUSAL_REASONS
from app.experience_asset.inference.models import M4MapProposal
from tests.integration.test_m4_api import (
    ScriptedM4Client,
    create_m4,
    default_m4_proposal,
)


def _client(tmp_path: Path, name: str, model: ScriptedM4Client | None = None):
    return TestClient(
        create_app(database_path=tmp_path / name, model_client=model or ScriptedM4Client())
    )


def _accept(client: TestClient, asset_id: str, workspace: dict, **overrides):
    body = {
        "asset_id": asset_id,
        "expected_artifact_id": workspace["map"]["artifact_id"],
        "expected_canonical_version_id": workspace["canonical_version_id"],
        "user_action": "CONFIRM",
    }
    body.update(overrides)
    return client.post(f"/api/v1/m4/assets/{asset_id}/accept", json=body)


def _gap_model() -> ScriptedM4Client:
    return ScriptedM4Client(
        m4_script=[
            lambda request: M4MapProposal.model_validate(
                default_m4_proposal(request, gap_roles=("COUNTEREXAMPLE",))
            )
        ]
    )


def test_acceptance_binds_readiness_to_an_exact_version_and_hash(tmp_path: Path):
    with _client(tmp_path, "ready.sqlite3") as client:
        asset_id, workspace = create_m4(client)

        # Before acceptance the card is simply not ready, and says so.
        assert client.get(f"/api/v1/m4/assets/{asset_id}/readiness").status_code == 404

        accepted = _accept(client, asset_id, workspace)
        assert accepted.status_code == 201, accepted.text
        record = accepted.json()
        assert record["explicit_user_acceptance"] is True
        assert record["milestone_state"] == "CONFIRMED"
        assert record["lifecycle"] == "ACTIVE"

        # A relation discovered against one version is an argument about that
        # content, so the binding names a version and a hash rather than the
        # asset.
        after = client.get(f"/api/v1/m4/assets/{asset_id}").json()
        assert record["version_id"] == after["canonical_version_id"]
        assert record["knowledge_card_hash"] == after["canonical_content_hash"]
        assert record["m4_artifact_id"] == after["map"]["artifact_id"]
        assert after["map"]["state"] == "CONFIRMED"

        fetched = client.get(f"/api/v1/m4/assets/{asset_id}/readiness")
        assert fetched.status_code == 200
        assert fetched.json()["readiness_id"] == record["readiness_id"]


def test_accepting_visible_gaps_binds_under_the_same_rules(tmp_path: Path):
    with _client(tmp_path, "gaps.sqlite3", _gap_model()) as client:
        asset_id, workspace = create_m4(client)
        gaps = [
            item["statement_id"]
            for entry in workspace["map"]["entries"]
            for item in entry["statements"]
            if item["is_visible_gap"]
        ]
        assert gaps

        # CONFIRM would bury the gaps the user was shown.
        refused = _accept(client, asset_id, workspace)
        assert refused.status_code == 422
        assert refused.json()["detail"]["reason"] == "NOT_READY"

        accepted = _accept(
            client,
            asset_id,
            workspace,
            user_action="ACCEPT_WITH_GAPS",
            accepted_gap_statement_ids=gaps,
        )
        assert accepted.status_code == 201, accepted.text
        record = accepted.json()
        assert record["milestone_state"] == "COMPLETE_WITH_GAPS"
        assert sorted(record["accepted_gap_statement_ids"]) == sorted(gaps)
        # A user who knows their experience is incomplete proceeds without being
        # forced to fabricate the missing parts, under the same binding rules.
        after = client.get(f"/api/v1/m4/assets/{asset_id}").json()
        assert record["version_id"] == after["canonical_version_id"]
        assert record["knowledge_card_hash"] == after["canonical_content_hash"]


def test_accepting_gaps_must_name_the_gaps_that_exist(tmp_path: Path):
    with _client(tmp_path, "named.sqlite3", _gap_model()) as client:
        asset_id, workspace = create_m4(client)
        supported = next(
            item["statement_id"]
            for entry in workspace["map"]["entries"]
            for item in entry["statements"]
            if not item["is_visible_gap"]
        )

        mismatched = _accept(
            client,
            asset_id,
            workspace,
            user_action="ACCEPT_WITH_GAPS",
            accepted_gap_statement_ids=[supported],
        )

        # The record has to show what the user actually agreed to leave open.
        assert mismatched.status_code == 422
        assert mismatched.json()["detail"]["reason"] == "NOT_READY"
        assert client.get(f"/api/v1/m4/assets/{asset_id}/readiness").status_code == 404


def test_repeat_acceptance_is_idempotent_and_a_stale_one_is_refused(tmp_path: Path):
    with _client(tmp_path, "idempotent.sqlite3") as client:
        asset_id, workspace = create_m4(client)
        first = _accept(client, asset_id, workspace).json()

        # The same version again returns the same readiness identity: relations
        # already name it, so a second click must not mint a new one.
        again = _accept(
            client,
            asset_id,
            workspace,
            expected_canonical_version_id=first["version_id"],
            expected_artifact_id=first["m4_artifact_id"],
        )
        assert again.status_code == 201
        assert again.json()["readiness_id"] == first["readiness_id"]

        # The pre-acceptance version is stale now. Silently rebinding it to the
        # current one would grant readiness for content the user never read.
        stale = _accept(client, asset_id, workspace)
        assert stale.status_code == 409
        assert stale.json()["detail"]["reason"] == "ALREADY_ACCEPTED"


def test_an_invalidated_map_cannot_be_accepted(tmp_path: Path):
    from tests.integration.test_m4_api import correct_the_ledger

    with _client(tmp_path, "invalidated.sqlite3") as client:
        asset_id, workspace = create_m4(client)
        correct_the_ledger(client, asset_id)
        invalidated = client.get(f"/api/v1/m4/assets/{asset_id}").json()
        assert invalidated["map"]["state"] == "INVALIDATED"

        refused = _accept(client, asset_id, invalidated)

        assert refused.status_code == 422
        assert refused.json()["detail"]["reason"] == "NOT_READY"
        assert client.get(f"/api/v1/m4/assets/{asset_id}/readiness").status_code == 404


def test_refusal_reasons_are_distinguishable(tmp_path: Path):
    """AC-6: "finish your card" and "your card changed" have opposite next actions."""
    assert set(READINESS_REFUSAL_REASONS) == {
        "NOT_READY",
        "STALE_VERSION",
        "CARD_HASH_MISMATCH",
        "ALREADY_ACCEPTED",
        "STORAGE_CONFLICT",
    }
    with _client(tmp_path, "reasons.sqlite3") as client:
        asset_id, workspace = create_m4(client)

        stale = _accept(
            client,
            asset_id,
            workspace,
            expected_canonical_version_id="00000000-0000-4000-8000-000000000000",
        )

        assert stale.status_code == 422
        assert stale.json()["detail"]["reason"] == "STALE_VERSION"
        assert stale.json()["detail"]["message"]


def test_acceptance_starts_no_discovery_run(tmp_path: Path):
    """GRAG-02: accepting a ready card creates no discovery run."""
    with _client(tmp_path, "no-run.sqlite3") as client:
        asset_id, workspace = create_m4(client)
        before = _discovery_rows(client, asset_id)

        accepted = _accept(client, asset_id, workspace)
        assert accepted.status_code == 201

        # Running a search here would spend local model time and put historical
        # summaries in front of someone who has not asked to compare anything.
        assert _discovery_rows(client, asset_id) == before == (0, 0, 0)


def _discovery_rows(client: TestClient, asset_id: str) -> tuple[int, int, int]:
    import sqlite3

    repository = client.app.state.repository
    connection = sqlite3.connect(repository.database_path)
    try:
        return tuple(
            connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "relation_discovery_attempts",
                "discovery_fingerprint_records",
                "relation_candidates",
            )
        )
    finally:
        connection.close()


def test_readiness_survives_restart_with_its_bindings(tmp_path: Path):
    database = tmp_path / "restart.sqlite3"
    model = ScriptedM4Client()
    with TestClient(create_app(database_path=database, model_client=model)) as client:
        asset_id, workspace = create_m4(client)
        record = _accept(client, asset_id, workspace).json()

    with TestClient(create_app(database_path=database, model_client=model)) as client:
        restored = client.get(f"/api/v1/m4/assets/{asset_id}/readiness")
        assert restored.status_code == 200
        assert restored.json() == record


def _discovery_body(asset_id: str, workspace: dict, readiness: dict | None = None) -> dict:
    """The request the UI would send, naming the exact card it is holding."""
    return {
        "asset_id": asset_id,
        "current_version_id": (readiness or workspace)["version_id"]
        if readiness
        else workspace["canonical_version_id"],
        "knowledge_card_version_id": readiness["version_id"]
        if readiness
        else workspace["canonical_version_id"],
        "knowledge_card_hash": readiness["knowledge_card_hash"]
        if readiness
        else workspace["canonical_content_hash"],
        "scope": "CROSS_ASSET_SUMMARY",
    }


def test_discovery_before_readiness_is_denied_before_any_work(tmp_path: Path):
    """GRAG-01: the denial happens before the read, not after."""
    model = ScriptedM4Client()
    with _client(tmp_path, "denied.sqlite3", model) as client:
        asset_id, workspace = create_m4(client)
        calls_before = len(model.m4_requests)

        denied = client.post(
            f"/api/v1/relations/assets/{asset_id}/discovery",
            json=_discovery_body(asset_id, workspace),
        )

        assert denied.status_code == 409, denied.text
        assert denied.json()["detail"]["reason"] == "NOT_READY"
        assert denied.json()["detail"]["message"]
        # Doing the cross-asset read and discarding it would already have
        # exposed historical material and spent the budget.
        assert _discovery_rows(client, asset_id) == (0, 0, 0)
        assert len(model.m4_requests) == calls_before

        # And the lock the UI renders comes from the same backend state.
        locked = client.get(f"/api/v1/relations/assets/{asset_id}/discovery")
        assert locked.status_code == 200, locked.text
        assert locked.json()["discovery_outcome"] == "NOT_READY"
        assert locked.json()["readiness"] is None

        record = _accept(client, asset_id, workspace).json()

        # Past the gate the search actually runs. This asset is the only one in
        # the corpus, so there is nothing to compare against — which is a
        # finished search reporting NO_MATCH, not a fault.
        allowed = client.post(
            f"/api/v1/relations/assets/{asset_id}/discovery",
            json=_discovery_body(asset_id, workspace, record),
        )
        assert allowed.status_code == 202, allowed.text
        assert allowed.json()["discovery_outcome"] == "NO_MATCH"
        assert allowed.json()["candidates"] == []
        attempts, fingerprints, candidates = _discovery_rows(client, asset_id)
        assert (attempts, fingerprints, candidates) == (1, 1, 0)


def test_a_request_naming_a_superseded_card_is_refused_as_stale(tmp_path: Path):
    with _client(tmp_path, "stale-card.sqlite3") as client:
        asset_id, workspace = create_m4(client)
        record = _accept(client, asset_id, workspace).json()

        # Readiness exists, but not for the card this request is holding.
        stale = client.post(
            f"/api/v1/relations/assets/{asset_id}/discovery",
            json={
                **_discovery_body(asset_id, workspace, record),
                "knowledge_card_hash": "0" * 64,
            },
        )

        assert stale.status_code == 409
        assert stale.json()["detail"]["reason"] == "STALE"
        assert _discovery_rows(client, asset_id) == (0, 0, 0)


def test_the_lock_lifts_only_for_the_exact_accepted_version(tmp_path: Path):
    from tests.integration.test_m4_api import correct_the_ledger

    with _client(tmp_path, "exact.sqlite3") as client:
        asset_id, workspace = create_m4(client)
        record = _accept(client, asset_id, workspace).json()
        body = _discovery_body(asset_id, workspace, record)
        assert (
            client.post(
                f"/api/v1/relations/assets/{asset_id}/discovery", json=body
            ).status_code
            == 202
        )

        # An upstream correction moves the card past the accepted version, and
        # readiness is bound to that exact version rather than to the asset — so
        # the lock returns rather than silently covering new content.
        correct_the_ledger(client, asset_id)
        client.get(f"/api/v1/m4/assets/{asset_id}")

        relocked = client.post(
            f"/api/v1/relations/assets/{asset_id}/discovery", json=body
        )
        assert relocked.status_code == 409
        assert relocked.json()["detail"]["reason"] == "NOT_READY"
        assert client.get(f"/api/v1/m4/assets/{asset_id}/readiness").status_code == 404
