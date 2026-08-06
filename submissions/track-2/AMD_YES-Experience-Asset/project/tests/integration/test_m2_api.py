import sqlite3
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.experience_asset.api.main import create_app
from app.experience_asset.inference import (
    FakeModelClient,
    M2SemanticRoleAssignment,
    M2SemanticRoleProposal,
)
from app.experience_asset.inference.models import ModelUnavailable


def create_m2_test_app(
    database_path: Path,
    *,
    model_client: FakeModelClient | None = None,
):
    return create_app(
        database_path=database_path,
        model_client=model_client or FakeModelClient(),
    )


class UnavailableM2ModelClient(FakeModelClient):
    async def generate_m2_roles(self, request):
        raise ModelUnavailable("configured local model outage")


def accepted_m1(client: TestClient) -> dict:
    created = client.post(
        "/api/v1/m1/assets",
        json={
            "source_kind": "PASTED_TEXT",
            "display_label": "M2 fixture",
            "text": "第一次试坐发现支撑不足。后来更换了椅子。",
            "goal_hint": "复盘选择",
        },
    ).json()
    asset_id = created["asset"]["asset_id"]
    response = client.post(
        f"/api/v1/m1/assets/{asset_id}/confirm",
        json={
            "expected_version_id": created["asset"]["version_id"],
            "complete_with_gaps": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_m2_create_edit_stale_confirm_and_restart(tmp_path: Path) -> None:
    database = tmp_path / "asset.sqlite3"
    with TestClient(create_m2_test_app(database)) as client:
        m1 = accepted_m1(client)
        asset_id = m1["asset"]["asset_id"]
        created_response = client.post(
            f"/api/v1/m2/assets/{asset_id}",
            json={
                "expected_m1_version_id": m1["asset"]["version_id"],
            },
        )
        assert created_response.status_code == 201, created_response.text
        created = created_response.json()
        artifact = created["artifact"]
        assert artifact["base_m1_version_id"] == m1["asset"]["version_id"]
        assert all(moment["source_statement_ids"] for moment in artifact["moments"])
        canonical = client.get(f"/api/v1/m1/assets/{asset_id}").json()["asset"]
        assert canonical["milestone_states"]["M2"] == artifact["state"]
        assert canonical["current_milestone"] == "M2"
        assert canonical["critical_moments"][0]["title"] == artifact["moments"][0]["title"]
        m2_projection = next(
            item for item in canonical["milestone_artifacts"] if item["milestone"] == "M2"
        )
        assert m2_projection["payload"] == {"m2_artifact_id": artifact["artifact_id"]}
        with sqlite3.connect(database) as connection:
            assert connection.execute(
                "SELECT command, model_call_count FROM runs WHERE run_id = ?",
                (artifact["generated_by_run_id"],),
            ).fetchone() == ("E3-M2-critical-moment-langgraph", 1)
        proposed_confirm = client.post(
            f"/api/v1/m2/assets/{asset_id}/confirm",
            json={
                "expected_artifact_id": artifact["artifact_id"],
                "complete_with_gaps": True,
            },
        )
        assert proposed_confirm.status_code == 422
        assert "confirm each proposed critical moment" in proposed_confirm.text
        artifact["moments"][0]["title"] = "用户修订标题"
        edited_response = client.patch(
            f"/api/v1/m2/assets/{asset_id}",
            json={
                "expected_artifact_id": artifact["artifact_id"],
                "moments": [
                    {
                        "moment_id": moment["moment_id"],
                        "title": moment["title"],
                        "criticality_status": "USER_CONFIRMED",
                    }
                    for moment in artifact["moments"]
                ],
            },
        )
        assert edited_response.status_code == 200, edited_response.text
        edited = edited_response.json()
        assert all(
            moment["criticality_status"] == "USER_CONFIRMED"
            and moment["criticality_confirmed_at"]
            for moment in edited["artifact"]["moments"]
        )
        stale = client.patch(
            f"/api/v1/m2/assets/{asset_id}",
            json={
                "expected_artifact_id": artifact["artifact_id"],
                "moments": [
                    {"moment_id": moment["moment_id"], "title": moment["title"]}
                    for moment in artifact["moments"]
                ],
            },
        )
        assert stale.status_code == 409
        confirmed = client.post(
            f"/api/v1/m2/assets/{asset_id}/confirm",
            json={
                "expected_artifact_id": edited["artifact"]["artifact_id"],
                "complete_with_gaps": True,
            },
        )
        assert confirmed.status_code == 200
        assert len(confirmed.json()["history_artifact_ids"]) == 3
        canonical = client.get(f"/api/v1/m1/assets/{asset_id}").json()["asset"]
        assert canonical["milestone_states"]["M2"] == "CONFIRMED"
        assert canonical["current_milestone"] == "M3"
    with TestClient(create_m2_test_app(database)) as client:
        restored = client.get(f"/api/v1/m2/assets/{asset_id}")
        assert restored.status_code == 200
        restored_workspace = restored.json()
        assert restored_workspace["artifact"]["state"] == "CONFIRMED"
        reopened = client.patch(
            f"/api/v1/m2/assets/{asset_id}",
            json={
                "expected_artifact_id": restored_workspace["artifact"]["artifact_id"],
                "moments": [
                    {
                        "moment_id": moment["moment_id"],
                        "title": (
                            "确认后重新修订的标题"
                            if index == 0
                            else moment["title"]
                        ),
                    }
                    for index, moment in enumerate(
                        restored_workspace["artifact"]["moments"]
                    )
                ],
            },
        )
        assert reopened.status_code == 200, reopened.text
        reopened_workspace = reopened.json()
        assert reopened_workspace["artifact"]["state"] not in {
            "CONFIRMED",
            "COMPLETE_WITH_GAPS",
        }
        assert (
            reopened_workspace["artifact"]["moments"][0]["criticality_status"]
            == "AGENT_PROPOSED"
        )
        assert (
            reopened_workspace["artifact"]["moments"][0][
                "criticality_confirmed_at"
            ]
            is None
        )
        canonical = client.get(f"/api/v1/m1/assets/{asset_id}").json()["asset"]
        assert canonical["current_milestone"] == "M2"


def test_m2_maps_strict_model_roles_without_keyword_fallback(tmp_path: Path) -> None:
    model = FakeModelClient()
    with TestClient(
        create_m2_test_app(
            tmp_path / "asset.sqlite3",
            model_client=model,
        )
    ) as client:
        created = client.post(
            "/api/v1/m1/assets",
            json={
                "source_kind": "PASTED_TEXT",
                "display_label": "Explicit role fixture",
                "text": (
                    "因为第一次试坐时腿麻, 我发现支撑不足。"
                    "没想到软垫更不舒服。"
                    "于是我决定更换椅子。"
                    "朋友也在场。"
                ),
                "goal_hint": "复盘选择",
            },
        ).json()
        accepted = client.post(
            f"/api/v1/m1/assets/{created['asset']['asset_id']}/confirm",
            json={
                "expected_version_id": created["asset"]["version_id"],
                "complete_with_gaps": True,
            },
        ).json()
        assignments = []
        for statement in accepted["asset"]["statements"]:
            text = statement["text"]
            roles = (
                ["CUE"]
                if "发现支撑不足" in text
                else ["SURPRISE"]
                if "没想到" in text
                else ["CHANGE"]
                if "决定更换" in text
                else []
            )
            assignments.append(
                M2SemanticRoleAssignment(
                    statement_id=statement["statement_id"],
                    roles=roles,
                    reasoning="Configured public semantic-role fixture.",
                )
            )
        model.m2_role_proposal = M2SemanticRoleProposal(assignments=assignments)
        response = client.post(
            f"/api/v1/m2/assets/{created['asset']['asset_id']}",
            json={"expected_m1_version_id": accepted["asset"]["version_id"]},
        )
        assert response.status_code == 201, response.text
        moments = response.json()["artifact"]["moments"]
        cue = next(moment for moment in moments if "发现支撑不足" in moment["description"])
        surprise = next(
            moment for moment in moments if "没想到" in moment["description"]
        )
        change = next(moment for moment in moments if "决定更换" in moment["description"])
        neutral = next(moment for moment in moments if "朋友也在场" in moment["description"])
        assert cue["cue_statement_ids"] == cue["source_statement_ids"]
        assert surprise["surprise_statement_ids"] == surprise["source_statement_ids"]
        assert change["change_statement_ids"] == change["source_statement_ids"]
        assert neutral["cue_statement_ids"] == []
        assert neutral["change_statement_ids"] == []
        assert neutral["surprise_statement_ids"] == []


def test_m2_preserves_implicit_semantics_and_rejects_ambiguous_return_keyword(
    tmp_path: Path,
) -> None:
    model = FakeModelClient()
    with TestClient(
        create_m2_test_app(
            tmp_path / "semantic.sqlite3",
            model_client=model,
        )
    ) as client:
        created = client.post(
            "/api/v1/m1/assets",
            json={
                "source_kind": "PASTED_TEXT",
                "display_label": "Implicit semantic fixture",
                "text": (
                    "两小时后腿部持续发麻, 这个身体反应成为我判断不合适的依据。"
                    "我预期会改善, 结果腰部压力更明显。"
                    "The pain returned after lunch."
                    "I packed the chair and contacted the store for an exchange."
                ),
                "goal_hint": "复盘选择",
            },
        ).json()
        accepted = client.post(
            f"/api/v1/m1/assets/{created['asset']['asset_id']}/confirm",
            json={
                "expected_version_id": created["asset"]["version_id"],
                "complete_with_gaps": True,
            },
        ).json()
        assignments = []
        for statement in accepted["asset"]["statements"]:
            text = statement["text"]
            roles = (
                ["CUE"]
                if "身体反应" in text
                else ["SURPRISE"]
                if "预期会改善" in text
                else ["CHANGE"]
                if "contacted the store" in text
                else []
            )
            assignments.append(
                M2SemanticRoleAssignment(
                    statement_id=statement["statement_id"],
                    roles=roles,
                    reasoning="Configured implicit semantic regression.",
                )
            )
        model.m2_role_proposal = M2SemanticRoleProposal(assignments=assignments)

        response = client.post(
            f"/api/v1/m2/assets/{created['asset']['asset_id']}",
            json={"expected_m1_version_id": accepted["asset"]["version_id"]},
        )
        assert response.status_code == 201, response.text
        moments = response.json()["artifact"]["moments"]
        cue = next(moment for moment in moments if "身体反应" in moment["description"])
        surprise = next(
            moment for moment in moments if "预期会改善" in moment["description"]
        )
        ambiguous = next(
            moment for moment in moments if "pain returned" in moment["description"]
        )
        exchange = next(
            moment
            for moment in moments
            if "contacted the store" in moment["description"]
        )

        assert cue["cue_statement_ids"] == cue["source_statement_ids"]
        assert surprise["surprise_statement_ids"] == surprise["source_statement_ids"]
        assert ambiguous["change_statement_ids"] == []
        assert exchange["change_statement_ids"] == exchange["source_statement_ids"]


def test_m2_invalid_model_statement_reference_safe_stops_without_artifact(
    tmp_path: Path,
) -> None:
    database = tmp_path / "invalid-semantic.sqlite3"
    model = FakeModelClient()
    app = create_m2_test_app(database, model_client=model)
    with TestClient(app) as client:
        accepted = accepted_m1(client)
        assignments = [
            M2SemanticRoleAssignment(
                statement_id=(
                    uuid4()
                    if index == 0
                    else statement["statement_id"]
                ),
                roles=[],
                reasoning="Configured invalid-reference regression.",
            )
            for index, statement in enumerate(accepted["asset"]["statements"])
        ]
        model.m2_role_proposal = M2SemanticRoleProposal(assignments=assignments)

        response = client.post(
            f"/api/v1/m2/assets/{accepted['asset']['asset_id']}",
            json={"expected_m1_version_id": accepted["asset"]["version_id"]},
        )

        assert response.status_code == 422
        assert "invalid semantic roles" in response.text
        assert client.get(
            f"/api/v1/m2/assets/{accepted['asset']['asset_id']}"
        ).status_code == 404

    with sqlite3.connect(database) as connection:
        terminal_state, model_call_count = connection.execute(
            """
            SELECT terminal_state, model_call_count
            FROM runs WHERE command = 'E3-M2-critical-moment-langgraph'
            """
        ).fetchone()
    assert terminal_state == "INVALID_MODEL_OUTPUT"
    assert model_call_count == 1


def test_m2_model_unavailable_is_explicit_and_does_not_fallback(
    tmp_path: Path,
) -> None:
    database = tmp_path / "unavailable-semantic.sqlite3"
    app = create_m2_test_app(
        database,
        model_client=UnavailableM2ModelClient(),
    )
    with TestClient(app) as client:
        accepted = accepted_m1(client)
        response = client.post(
            f"/api/v1/m2/assets/{accepted['asset']['asset_id']}",
            json={"expected_m1_version_id": accepted["asset"]["version_id"]},
        )

        assert response.status_code == 422
        assert "local model is unavailable" in response.text
        assert client.get(
            f"/api/v1/m2/assets/{accepted['asset']['asset_id']}"
        ).status_code == 404

    with sqlite3.connect(database) as connection:
        terminal_state, model_call_count = connection.execute(
            """
            SELECT terminal_state, model_call_count
            FROM runs WHERE command = 'E3-M2-critical-moment-langgraph'
            """
        ).fetchone()
    assert terminal_state == "MODEL_UNAVAILABLE"
    assert model_call_count == 1


def test_m2_regeneration_accepts_latest_canonical_m1_version(tmp_path: Path) -> None:
    with TestClient(create_m2_test_app(tmp_path / "asset.sqlite3")) as client:
        accepted = accepted_m1(client)
        asset_id = accepted["asset"]["asset_id"]
        first = client.post(
            f"/api/v1/m2/assets/{asset_id}",
            json={"expected_m1_version_id": accepted["asset"]["version_id"]},
        )
        assert first.status_code == 201, first.text

        stale = client.post(
            f"/api/v1/m2/assets/{asset_id}",
            json={"expected_m1_version_id": accepted["asset"]["version_id"]},
        )
        assert stale.status_code == 409

        latest = client.get(f"/api/v1/m1/assets/{asset_id}").json()
        regenerated = client.post(
            f"/api/v1/m2/assets/{asset_id}",
            json={"expected_m1_version_id": latest["asset"]["version_id"]},
        )
        assert regenerated.status_code == 201, regenerated.text
        assert (
            regenerated.json()["artifact"]["base_m1_version_id"]
            == latest["asset"]["version_id"]
        )


def test_dependent_m1_correction_invalidates_but_unrelated_edit_does_not(tmp_path: Path) -> None:
    with TestClient(create_m2_test_app(tmp_path / "asset.sqlite3")) as client:
        m1 = accepted_m1(client)
        asset_id = m1["asset"]["asset_id"]
        with_dependency = client.patch(
            f"/api/v1/m1/assets/{asset_id}/brief",
            json={
                "expected_version_id": m1["asset"]["version_id"],
                "context": "先用于个人复盘。",
            },
        ).json()
        m1 = client.post(
            f"/api/v1/m1/assets/{asset_id}/confirm",
            json={
                "expected_version_id": with_dependency["asset"]["version_id"],
                "complete_with_gaps": True,
            },
        ).json()
        m2 = client.post(
            f"/api/v1/m2/assets/{asset_id}",
            json={
                "expected_m1_version_id": m1["asset"]["version_id"],
            },
        ).json()
        current_m1 = client.get(f"/api/v1/m1/assets/{asset_id}").json()
        unrelated = client.patch(
            f"/api/v1/m1/assets/{asset_id}/brief",
            json={
                "expected_version_id": current_m1["asset"]["version_id"],
                "constraints": ["新增无关约束"],
            },
        ).json()
        still_current = client.get(f"/api/v1/m2/assets/{asset_id}").json()
        assert still_current["is_current"] is True
        corrected = client.patch(
            f"/api/v1/m1/assets/{asset_id}/brief",
            json={
                "expected_version_id": unrelated["asset"]["version_id"],
                "context": "改为形成可复用检查清单。",
            },
        )
        assert corrected.status_code == 200
        stale_patch = client.patch(
            f"/api/v1/m2/assets/{asset_id}",
            json={
                "expected_artifact_id": m2["artifact"]["artifact_id"],
                "moments": [
                    {"moment_id": moment["moment_id"], "title": moment["title"]}
                    for moment in m2["artifact"]["moments"]
                ],
            },
        )
        assert stale_patch.status_code == 409
        stale_confirm = client.post(
            f"/api/v1/m2/assets/{asset_id}/confirm",
            json={
                "expected_artifact_id": m2["artifact"]["artifact_id"],
                "complete_with_gaps": True,
            },
        )
        assert stale_confirm.status_code == 409
        invalidated = client.get(f"/api/v1/m2/assets/{asset_id}").json()
        assert invalidated["artifact"]["state"] == "INVALIDATED"
        assert invalidated["is_current"] is False
        assert m2["artifact"]["artifact_id"] in invalidated["history_artifact_ids"]
        canonical = corrected.json()["asset"]
        assert canonical["milestone_states"]["M2"] == "INVALIDATED"
        assert canonical["current_milestone"] == "M2"
        accepted_correction = client.post(
            f"/api/v1/m1/assets/{asset_id}/confirm",
            json={
                "expected_version_id": canonical["version_id"],
                "complete_with_gaps": True,
            },
        )
        assert accepted_correction.status_code == 200, accepted_correction.text
        latest_version = client.get(
            f"/api/v1/m1/assets/{asset_id}"
        ).json()["asset"]["version_id"]
        regenerated = client.post(
            f"/api/v1/m2/assets/{asset_id}",
            json={"expected_m1_version_id": latest_version},
        )
        assert regenerated.status_code == 201, regenerated.text
        assert regenerated.json()["is_current"] is True


def test_answering_related_conflict_question_atomically_invalidates_m2(tmp_path: Path) -> None:
    with TestClient(create_m2_test_app(tmp_path / "asset.sqlite3")) as client:
        created = client.post(
            "/api/v1/m1/assets",
            json={
                "source_kind": "PASTED_TEXT",
                "display_label": "Duration conflict",
                "text": "我当天就退掉了这把椅子。后来我又说其实连续用了两周才退。",
                "goal_hint": "澄清购买经历",
            },
        ).json()
        asset_id = created["asset"]["asset_id"]
        conflict = next(
            question
            for question in created["questions"]
            if question["priority_inputs"].get("missing_field") == "duration_conflict"
        )
        accepted = client.post(
            f"/api/v1/m1/assets/{asset_id}/confirm",
            json={
                "expected_version_id": created["asset"]["version_id"],
                "complete_with_gaps": True,
            },
        ).json()
        m2 = client.post(
            f"/api/v1/m2/assets/{asset_id}",
            json={"expected_m1_version_id": accepted["asset"]["version_id"]},
        ).json()
        conflict_moments = [
            moment for moment in m2["artifact"]["moments"]
            if moment["temporal_status"] == "CONFLICTING"
        ]
        assert conflict_moments
        assert set(conflict_moments[0]["conflict_statement_ids"]) == set(
            conflict["affected_statement_ids"]
        )

        answered = client.post(
            f"/api/v1/m1/assets/{asset_id}/questions/{conflict['question_id']}",
            json={
                "expected_version_id": client.get(
                    f"/api/v1/m1/assets/{asset_id}"
                ).json()["asset"]["version_id"],
                "action": "ANSWER",
                "answer": "实际是连续使用两周后才退。",
            },
        )
        assert answered.status_code == 200, answered.text
        assert answered.json()["asset"]["milestone_states"]["M2"] == "INVALIDATED"
        stale_confirm = client.post(
            f"/api/v1/m2/assets/{asset_id}/confirm",
            json={
                "expected_artifact_id": m2["artifact"]["artifact_id"],
                "complete_with_gaps": True,
            },
        )
        assert stale_confirm.status_code == 409
        current_m2 = client.get(f"/api/v1/m2/assets/{asset_id}").json()
        assert current_m2["artifact"]["state"] == "INVALIDATED"


def test_compatible_same_day_and_later_events_are_not_marked_conflicting(tmp_path: Path) -> None:
    with TestClient(create_m2_test_app(tmp_path / "asset.sqlite3")) as client:
        created = client.post(
            "/api/v1/m1/assets",
            json={
                "source_kind": "PASTED_TEXT",
                "display_label": "Compatible timeline",
                "text": "当天提交申请。三天后收到答复。",
                "goal_hint": "复盘流程",
            },
        ).json()
        accepted = client.post(
            f"/api/v1/m1/assets/{created['asset']['asset_id']}/confirm",
            json={
                "expected_version_id": created["asset"]["version_id"],
                "complete_with_gaps": True,
            },
        ).json()
        m2 = client.post(
            f"/api/v1/m2/assets/{created['asset']['asset_id']}",
            json={"expected_m1_version_id": accepted["asset"]["version_id"]},
        )
        assert m2.status_code == 201, m2.text
        assert all(
            moment["temporal_status"] != "CONFLICTING"
            for moment in m2.json()["artifact"]["moments"]
        )


def test_failed_generation_run_start_does_not_commit_m2(tmp_path: Path) -> None:
    app = create_m2_test_app(tmp_path / "asset.sqlite3")
    with TestClient(app, raise_server_exceptions=False) as client:
        m1 = accepted_m1(client)
        asset_id = m1["asset"]["asset_id"]
        canonical_version = m1["asset"]["version_id"]
        with patch.object(
            app.state.repository,
            "start_workflow_run",
            side_effect=RuntimeError("boom"),
        ):
            response = client.post(
                f"/api/v1/m2/assets/{asset_id}",
                json={"expected_m1_version_id": canonical_version},
            )
        assert response.status_code == 500
        canonical = client.get(f"/api/v1/m1/assets/{asset_id}").json()["asset"]
        assert canonical["version_id"] == canonical_version
        assert client.get(f"/api/v1/m2/assets/{asset_id}").status_code == 404
