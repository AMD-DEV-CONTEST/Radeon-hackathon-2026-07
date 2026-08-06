from pathlib import Path

from fastapi.testclient import TestClient

from app.experience_asset.api.main import create_app
from app.experience_asset.inference.models import ModelUnavailable, ToolCallProposal
from tests.integration.test_m3_langgraph import ScriptedM3Client, accepted_m2


def create_m3(client: TestClient):
    asset_id, m2, canonical = accepted_m2(client)
    response = client.post(
        f"/api/v1/m3/assets/{asset_id}",
        json={
            "expected_m2_artifact_id": m2["artifact_id"],
            "expected_canonical_version_id": canonical["version_id"],
        },
    )
    assert response.status_code == 201, response.text
    return asset_id, response.json()


def test_create_get_edit_explicit_confirm_stale_and_restart(tmp_path: Path):
    database = tmp_path / "asset.sqlite3"
    model = ScriptedM3Client()
    with TestClient(create_app(database_path=database, model_client=model)) as client:
        asset_id, created = create_m3(client)
        artifact = created["artifact"]
        assert created["evidence_moments"]
        assert created["evidence_statements"]
        moment_ids = {item["moment_id"] for item in created["evidence_moments"]}
        statement_ids = {
            item["statement_id"] for item in created["evidence_statements"]
        }
        assert set(artifact["dependency_moment_ids"]).issubset(moment_ids)
        assert set(artifact["dependency_statement_ids"]).issubset(statement_ids)
        assert all(item["title"] and item["description"] for item in created["evidence_moments"])
        assert all(item["text"] for item in created["evidence_statements"])
        fetched = client.get(f"/api/v1/m3/assets/{asset_id}")
        assert fetched.json()["artifact"]["artifact_id"] == artifact["artifact_id"]
        statements = [item for entry in artifact["entries"] for item in entry["statements"]]
        edited = client.patch(
            f"/api/v1/m3/assets/{asset_id}",
            json={
                "expected_artifact_id": artifact["artifact_id"],
                "statements": [
                    {
                        "statement_id": item["statement_id"],
                        "text": item["text"],
                        "user_action": "CONFIRM",
                    }
                    for item in statements
                ],
            },
        )
        assert edited.status_code == 200, edited.text
        stale = client.patch(
            f"/api/v1/m3/assets/{asset_id}",
            json={
                "expected_artifact_id": artifact["artifact_id"],
                "statements": [
                    {
                        "statement_id": statements[0]["statement_id"],
                        "text": "stale draft",
                        "user_action": "CONFIRM",
                    }
                ],
            },
        )
        assert stale.status_code == 409
        confirmed = client.post(
            f"/api/v1/m3/assets/{asset_id}/confirm",
            json={
                "expected_artifact_id": edited.json()["artifact"]["artifact_id"],
                "complete_with_gaps": False,
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["artifact"]["state"] == "CONFIRMED"

    with TestClient(create_app(database_path=database, model_client=model)) as client:
        restored = client.get(f"/api/v1/m3/assets/{asset_id}")
        assert restored.status_code == 200
        assert restored.json()["artifact"]["state"] == "CONFIRMED"


def test_confirm_with_gaps_requires_explicit_choice(tmp_path: Path):
    with TestClient(
        create_app(database_path=tmp_path / "gaps.sqlite3", model_client=ScriptedM3Client())
    ) as client:
        asset_id, created = create_m3(client)
        statements = [
            item for entry in created["artifact"]["entries"] for item in entry["statements"]
        ]
        edits = [
            {
                "statement_id": item["statement_id"],
                "text": item["text"],
                "user_action": "MARK_UNRESOLVED" if index == 0 else "CONFIRM",
                **({"unresolved_reason": "结果仍待观察"} if index == 0 else {}),
            }
            for index, item in enumerate(statements)
        ]
        edited = client.patch(
            f"/api/v1/m3/assets/{asset_id}",
            json={"expected_artifact_id": created["artifact"]["artifact_id"], "statements": edits},
        ).json()
        rejected = client.post(
            f"/api/v1/m3/assets/{asset_id}/confirm",
            json={
                "expected_artifact_id": edited["artifact"]["artifact_id"],
                "complete_with_gaps": False,
            },
        )
        assert rejected.status_code == 422
        accepted = client.post(
            f"/api/v1/m3/assets/{asset_id}/confirm",
            json={
                "expected_artifact_id": edited["artifact"]["artifact_id"],
                "complete_with_gaps": True,
            },
        )
        assert accepted.status_code == 200
        assert accepted.json()["artifact"]["state"] == "COMPLETE_WITH_GAPS"


def test_policy_failure_is_queryable_by_run_id(tmp_path: Path):
    model = ScriptedM3Client([ModelUnavailable("first"), ModelUnavailable("second")])
    app = create_app(database_path=tmp_path / "failure.sqlite3", model_client=model)
    with TestClient(app) as client:
        asset_id, m2, canonical = accepted_m2(client)
        failed = client.post(
            f"/api/v1/m3/assets/{asset_id}",
            json={
                "expected_m2_artifact_id": m2["artifact_id"],
                "expected_canonical_version_id": canonical["version_id"],
            },
        )
        assert failed.status_code == 422
        status = client.get(failed.json()["detail"]["status_url"])
        assert status.status_code == 200
        assert status.json()["terminal_state"] == "MODEL_UNAVAILABLE"


def test_failed_create_then_success_uses_one_coherent_run_outcome(tmp_path: Path):
    model = ScriptedM3Client([ModelUnavailable("first"), ModelUnavailable("second"), None])
    app = create_app(database_path=tmp_path / "outcomes.sqlite3", model_client=model)
    with TestClient(app) as client:
        asset_id, m2, canonical = accepted_m2(client)
        payload = {
            "expected_m2_artifact_id": m2["artifact_id"],
            "expected_canonical_version_id": canonical["version_id"],
        }
        failed = client.post(f"/api/v1/m3/assets/{asset_id}", json=payload)
        failed_run = failed.json()["detail"]["run_id"]
        created = client.post(f"/api/v1/m3/assets/{asset_id}", json=payload)
        assert created.status_code == 201, created.text
        assert created.json()["progress"]["terminal_state"] == "SUCCEEDED"
        assert created.json()["latest_failure"] is None
        status = client.get(f"/api/v1/m3/runs/{failed_run}").json()
        assert status["terminal_state"] == "MODEL_UNAVAILABLE"
        assert status["code"] == "MODEL_UNAVAILABLE"
        assert status["model_calls_used"] == 2


def test_failed_regeneration_keeps_invalidated_artifact_get_contract_valid(tmp_path: Path):
    model = ScriptedM3Client()
    app = create_app(database_path=tmp_path / "failed-regenerate.sqlite3", model_client=model)
    with TestClient(app) as client:
        asset_id, created = create_m3(client)
        m2 = client.get(f"/api/v1/m2/assets/{asset_id}").json()["artifact"]
        corrected_edit = client.patch(
            f"/api/v1/m2/assets/{asset_id}",
            json={
                "expected_artifact_id": m2["artifact_id"],
                "moments": [
                    {
                        "moment_id": item["moment_id"],
                        "title": f"{item['title']} corrected",
                        "criticality_status": item["criticality_status"],
                    }
                    for item in m2["moments"]
                ],
            },
        ).json()
        corrected = client.post(
            f"/api/v1/m2/assets/{asset_id}/confirm",
            json={
                "expected_artifact_id": corrected_edit["artifact"]["artifact_id"],
                "complete_with_gaps": True,
            },
        ).json()
        invalidated = client.get(f"/api/v1/m3/assets/{asset_id}").json()
        assert invalidated["progress"]["terminal_state"] == "NEEDS_USER_INPUT"
        canonical = client.get(f"/api/v1/m1/assets/{asset_id}").json()["asset"]
        model.script.extend([ModelUnavailable("first"), ModelUnavailable("second")])
        failed = client.post(
            f"/api/v1/m3/assets/{asset_id}/regenerate",
            json={
                "expected_m2_artifact_id": corrected["artifact"]["artifact_id"],
                "expected_canonical_version_id": canonical["version_id"],
                "expected_invalidated_artifact_id": invalidated["artifact"]["artifact_id"],
            },
        )
        assert failed.status_code == 422
        fetched = client.get(f"/api/v1/m3/assets/{asset_id}")
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["artifact"]["artifact_id"] == invalidated["artifact"]["artifact_id"]
        assert fetched.json()["progress"]["terminal_state"] == "MODEL_UNAVAILABLE"
        assert fetched.json()["latest_failure"]["code"] == "MODEL_UNAVAILABLE"
        assert fetched.json()["latest_failure"]["retryable"] is True


def test_successful_regeneration_replaces_the_exact_affected_decision(tmp_path: Path):
    model = ScriptedM3Client()
    app = create_app(database_path=tmp_path / "regenerate.sqlite3", model_client=model)
    with TestClient(app) as client:
        asset_id, created = create_m3(client)
        original_decision_id = created["artifact"]["entries"][0]["decision_id"]
        m2 = client.get(f"/api/v1/m2/assets/{asset_id}").json()["artifact"]
        corrected_edit = client.patch(
            f"/api/v1/m2/assets/{asset_id}",
            json={
                "expected_artifact_id": m2["artifact_id"],
                "moments": [
                    {
                        "moment_id": item["moment_id"],
                        "title": f"{item['title']} corrected",
                        "criticality_status": item["criticality_status"],
                    }
                    for item in m2["moments"]
                ],
            },
        ).json()
        corrected = client.post(
            f"/api/v1/m2/assets/{asset_id}/confirm",
            json={
                "expected_artifact_id": corrected_edit["artifact"]["artifact_id"],
                "complete_with_gaps": True,
            },
        ).json()
        invalidated = client.get(f"/api/v1/m3/assets/{asset_id}").json()
        canonical = client.get(f"/api/v1/m1/assets/{asset_id}").json()["asset"]

        regenerated = client.post(
            f"/api/v1/m3/assets/{asset_id}/regenerate",
            json={
                "expected_m2_artifact_id": corrected["artifact"]["artifact_id"],
                "expected_canonical_version_id": canonical["version_id"],
                "expected_invalidated_artifact_id": invalidated["artifact"]["artifact_id"],
            },
        )

        assert regenerated.status_code == 200, regenerated.text
        regenerated_artifact = regenerated.json()["artifact"]
        assert regenerated_artifact["state"] in {"NEEDS_INPUT", "REVIEW_READY"}
        assert regenerated_artifact["base_m2_artifact_id"] == corrected["artifact"]["artifact_id"]
        assert regenerated_artifact["entries"][0]["decision_id"] == original_decision_id
        assert len(regenerated.json()["history_artifact_ids"]) >= 3


def test_m2_correction_atomically_invalidates_matching_m3_projection(tmp_path: Path):
    app = create_app(database_path=tmp_path / "transition.sqlite3", model_client=ScriptedM3Client())
    with TestClient(app) as client:
        asset_id, created = create_m3(client)
        before_history = created["history_artifact_ids"]
        m2 = client.get(f"/api/v1/m2/assets/{asset_id}").json()["artifact"]
        corrected = client.patch(
            f"/api/v1/m2/assets/{asset_id}",
            json={
                "expected_artifact_id": m2["artifact_id"],
                "moments": [
                    {
                        "moment_id": item["moment_id"],
                        "title": f"{item['title']} (corrected)" if index == 0 else item["title"],
                        "criticality_status": item["criticality_status"],
                    }
                    for index, item in enumerate(m2["moments"])
                ],
            },
        )
        assert corrected.status_code == 200, corrected.text
        m3 = client.get(f"/api/v1/m3/assets/{asset_id}").json()
        canonical = client.get(f"/api/v1/m1/assets/{asset_id}").json()["asset"]
        projection = next(
            item for item in canonical["milestone_artifacts"] if item["milestone"] == "M3"
        )
        assert m3["artifact"]["state"] == "INVALIDATED"
        assert m3["progress"]["terminal_state"] == "NEEDS_USER_INPUT"
        assert (
            m3["artifact"]["invalidated_by_m2_artifact_id"]
            == corrected.json()["artifact"]["artifact_id"]
        )
        assert projection["payload"]["m3_artifact_id"] == m3["artifact"]["artifact_id"]
        assert projection["state"] == "INVALIDATED"
        assert m3["history_artifact_ids"][: len(before_history)] == before_history

        before_current = canonical["version_id"]
        before_history = m3["history_artifact_ids"]
        statement = m3["artifact"]["entries"][0]["statements"][0]
        rejected_edit = client.patch(
            f"/api/v1/m3/assets/{asset_id}",
            json={
                "expected_artifact_id": m3["artifact"]["artifact_id"],
                "statements": [
                    {
                        "statement_id": statement["statement_id"],
                        "text": statement["text"],
                        "user_action": "CONFIRM",
                    }
                ],
            },
        )
        rejected_confirm = client.post(
            f"/api/v1/m3/assets/{asset_id}/confirm",
            json={
                "expected_artifact_id": m3["artifact"]["artifact_id"],
                "complete_with_gaps": True,
            },
        )
        assert rejected_edit.status_code == rejected_confirm.status_code == 422
        assert (
            client.get(f"/api/v1/m1/assets/{asset_id}").json()["asset"]["version_id"]
            == before_current
        )
        assert (
            client.get(f"/api/v1/m3/assets/{asset_id}").json()["history_artifact_ids"]
            == before_history
        )


def test_policy_blocked_regeneration_remains_queryable_and_uses_public_code(
    tmp_path: Path,
):
    model = ScriptedM3Client()
    app = create_app(database_path=tmp_path / "policy-regenerate.sqlite3", model_client=model)
    with TestClient(app) as client:
        asset_id, _ = create_m3(client)
        m2 = client.get(f"/api/v1/m2/assets/{asset_id}").json()["artifact"]
        corrected_edit = client.patch(
            f"/api/v1/m2/assets/{asset_id}",
            json={
                "expected_artifact_id": m2["artifact_id"],
                "moments": [
                    {
                        "moment_id": item["moment_id"],
                        "title": f"{item['title']} corrected",
                        "criticality_status": item["criticality_status"],
                    }
                    for item in m2["moments"]
                ],
            },
        ).json()
        corrected = client.post(
            f"/api/v1/m2/assets/{asset_id}/confirm",
            json={
                "expected_artifact_id": corrected_edit["artifact"]["artifact_id"],
                "complete_with_gaps": True,
            },
        ).json()
        invalidated = client.get(f"/api/v1/m3/assets/{asset_id}").json()
        canonical = client.get(f"/api/v1/m1/assets/{asset_id}").json()["asset"]

        original = model.generate_m3_ledger

        async def with_allowlisted_tool(request):
            result = await original(request)
            return result.model_copy(
                update={
                    "proposal": result.proposal.model_copy(
                        update={
                            "tool_call_proposals": [
                                ToolCallProposal(
                                    name="search_current_experience",
                                    arguments={
                                        "asset_id": request.canonical_context["asset_id"],
                                        "current_version_id": request.canonical_context[
                                            "version_id"
                                        ],
                                        "scope": "CURRENT_SOURCE",
                                        "query": "支撑",
                                        "top_k": 3,
                                    },
                                    permission_granted=False,
                                )
                            ]
                        }
                    )
                }
            )

        model.generate_m3_ledger = with_allowlisted_tool
        failed = client.post(
            f"/api/v1/m3/assets/{asset_id}/regenerate",
            json={
                "expected_m2_artifact_id": corrected["artifact"]["artifact_id"],
                "expected_canonical_version_id": canonical["version_id"],
                "expected_invalidated_artifact_id": invalidated["artifact"]["artifact_id"],
            },
        )
        assert failed.status_code == 422
        status = client.get(failed.json()["detail"]["status_url"])
        assert status.status_code == 200, status.text
        assert status.json()["terminal_state"] == "POLICY_BLOCKED"
        assert status.json()["code"] == "PERMISSION_DENIED"
        assert "PERMISSION_NOT_GRANTED" in status.json()["finding_codes"]

        fetched = client.get(f"/api/v1/m3/assets/{asset_id}")
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["artifact"]["state"] == "INVALIDATED"
        assert fetched.json()["latest_failure"]["code"] == "PERMISSION_DENIED"
        assert fetched.json()["latest_failure"]["terminal_state"] == "POLICY_BLOCKED"

        current_m2 = client.get(f"/api/v1/m2/assets/{asset_id}").json()["artifact"]
        revised_again = client.patch(
            f"/api/v1/m2/assets/{asset_id}",
            json={
                "expected_artifact_id": current_m2["artifact_id"],
                "moments": [
                    {
                        "moment_id": item["moment_id"],
                        "title": f"{item['title']} again",
                        "criticality_status": item["criticality_status"],
                    }
                    for item in current_m2["moments"]
                ],
            },
        )
        assert revised_again.status_code == 200, revised_again.text
        newest = client.get(f"/api/v1/m3/assets/{asset_id}")
        assert newest.status_code == 200, newest.text
        assert newest.json()["artifact"]["state"] == "INVALIDATED"
        assert newest.json()["progress"]["terminal_state"] == "NEEDS_USER_INPUT"
        assert newest.json()["latest_failure"] is None
