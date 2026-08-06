"""Public HTTP behaviour of the M4 Insight and Boundary Map."""

from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.experience_asset.api.main import create_app
from app.experience_asset.inference.models import (
    M4MapProposal,
    M4MapResult,
    ModelMetadata,
    ModelUnavailable,
)
from app.experience_asset.workflow.m4_graph import m4_local_model_output_schema
from tests.integration.test_m3_langgraph import ScriptedM3Client, accepted_m2

M4_ROLES = (
    "LESSON",
    "SUPPORT",
    "COUNTERFACTUAL",
    "LIMITATION",
    "COUNTEREXAMPLE",
    "APPLICABILITY",
)


class ScriptedM4Client(ScriptedM3Client):
    """Deterministic M4 substitute that answers from the bounded context it is given.

    The default proposal cites only identifiers the request actually supplied, so
    a test that fails is failing on behaviour rather than on a fixture that
    invented a reference the production path would have rejected anyway.
    """

    def __init__(self, m3_script=(), m4_script=()):
        super().__init__(m3_script)
        self.m4_script = deque(m4_script)
        self.m4_requests = []

    async def generate_m4_map(self, request):
        self.m4_requests.append(request)
        outcome = self.m4_script.popleft() if self.m4_script else None
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            outcome = outcome(request)
        proposal = outcome or M4MapProposal.model_validate(
            default_m4_proposal(request)
        )
        return M4MapResult(
            proposal=proposal,
            metadata=ModelMetadata(
                server_kind="fake",
                server_base_url="http://127.0.0.1/fake",
                model_id="deterministic-contract-fake",
                elapsed_ms=0,
                received_at=datetime.now(UTC),
            ),
        )


def default_m4_proposal(request, *, gap_roles: tuple[str, ...] = ()) -> dict:
    decision = request.canonical_context["decision_ids"][0]
    statement = request.canonical_context["allowed_statement_ids"][0]
    return {
        "entries": [
            {
                "prior_insight_id": (
                    request.canonical_context.get("affected_insight_ids", [None])[0]
                ),
                "title": "换椅子的教训",
                "source_decision_ids": [decision],
                "statements": [
                    {
                        "role": role,
                        "text": f"{role} statement",
                        **(
                            {"gap_reason": "来源里没有覆盖这一点。"}
                            if role in gap_roles
                            else {
                                "source_statement_ids": [statement],
                                "source_decision_ids": [decision],
                            }
                        ),
                    }
                    for role in M4_ROLES
                ],
            }
        ]
    }


def accepted_m3(client: TestClient) -> tuple[str, dict, dict]:
    """Drive M1→M3 through the product path and confirm the ledger."""
    asset_id, m2, canonical = accepted_m2(client)
    created = client.post(
        f"/api/v1/m3/assets/{asset_id}",
        json={
            "expected_m2_artifact_id": m2["artifact_id"],
            "expected_canonical_version_id": canonical["version_id"],
        },
    )
    assert created.status_code == 201, created.text
    artifact = created.json()["artifact"]
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
    confirmed = client.post(
        f"/api/v1/m3/assets/{asset_id}/confirm",
        json={
            "expected_artifact_id": edited.json()["artifact"]["artifact_id"],
            "complete_with_gaps": False,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    current = client.get(f"/api/v1/m1/assets/{asset_id}").json()["asset"]
    return asset_id, confirmed.json()["artifact"], current


def create_m4(client: TestClient) -> tuple[str, dict]:
    asset_id, m3, canonical = accepted_m3(client)
    response = client.post(
        f"/api/v1/m4/assets/{asset_id}",
        json={
            "asset_id": asset_id,
            "expected_m3_artifact_id": m3["artifact_id"],
            "expected_canonical_version_id": canonical["version_id"],
        },
    )
    assert response.status_code == 201, response.text
    return asset_id, response.json()


def test_map_carries_every_role_with_openable_evidence(tmp_path: Path):
    with TestClient(
        create_app(database_path=tmp_path / "m4.sqlite3", model_client=ScriptedM4Client())
    ) as client:
        asset_id, workspace = create_m4(client)
        artifact = workspace["map"]
        assert artifact is not None
        entry = artifact["entries"][0]
        assert {item["role"] for item in entry["statements"]} == set(M4_ROLES)
        assert sum(item["role"] == "LESSON" for item in entry["statements"]) == 1

        # Without the drill-down the user can only judge a lesson on its
        # plausibility, which is the judgement the evidence exists to replace.
        evidence_ids = {item["statement_id"] for item in workspace["evidence_statements"]}
        assert artifact["dependency_statement_ids"]
        assert set(artifact["dependency_statement_ids"]).issubset(evidence_ids)
        assert all(item["text"] for item in workspace["evidence_statements"])

        fetched = client.get(f"/api/v1/m4/assets/{asset_id}")
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["map"]["artifact_id"] == artifact["artifact_id"]
        assert fetched.json()["canonical_content_hash"]


def test_editing_versions_the_map_instead_of_mutating_it(tmp_path: Path):
    with TestClient(
        create_app(database_path=tmp_path / "edit.sqlite3", model_client=ScriptedM4Client())
    ) as client:
        asset_id, workspace = create_m4(client)
        artifact = workspace["map"]
        before_version = workspace["canonical_version_id"]
        target = next(
            item
            for item in artifact["entries"][0]["statements"]
            if item["role"] == "APPLICABILITY"
        )
        edited = client.patch(
            f"/api/v1/m4/assets/{asset_id}",
            json={
                "asset_id": asset_id,
                "expected_artifact_id": artifact["artifact_id"],
                "edits": [
                    {
                        "statement_id": target["statement_id"],
                        "text": "只有在同款支撑不足的座椅上才可迁移。",
                    }
                ],
            },
        )
        assert edited.status_code == 200, edited.text
        after = edited.json()
        assert after["map"]["artifact_id"] != artifact["artifact_id"]
        assert after["canonical_version_id"] != before_version

        # A stale expectation must not silently overwrite: an accepted version
        # has to stay a fixed thing that readiness and relations can refer to.
        stale = client.patch(
            f"/api/v1/m4/assets/{asset_id}",
            json={
                "asset_id": asset_id,
                "expected_artifact_id": artifact["artifact_id"],
                "edits": [
                    {"statement_id": target["statement_id"], "text": "stale draft"}
                ],
            },
        )
        assert stale.status_code == 409


def test_visible_gap_is_explicit_and_keeps_the_map_out_of_review_ready(tmp_path: Path):
    model = ScriptedM4Client(
        m4_script=[
            lambda request: M4MapProposal.model_validate(
                default_m4_proposal(request, gap_roles=("COUNTEREXAMPLE",))
            )
        ]
    )
    with TestClient(
        create_app(database_path=tmp_path / "gap.sqlite3", model_client=model)
    ) as client:
        _, workspace = create_m4(client)
        artifact = workspace["map"]
        gap = next(
            item
            for item in artifact["entries"][0]["statements"]
            if item["role"] == "COUNTEREXAMPLE"
        )
        # A gap that renders like a finished lesson leaves the user no signal to
        # go looking for what is absent.
        assert gap["is_visible_gap"] is True
        assert gap["gap_reason"]
        assert gap["status"] == "UNRESOLVED"
        assert gap["source_statement_ids"] == []
        assert gap["source_decision_ids"] == []
        assert artifact["state"] == "NEEDS_INPUT"


def test_core_role_without_source_statement_is_rejected_without_persisting(tmp_path: Path):
    def unsupported_lesson(request):
        payload = default_m4_proposal(request)
        payload["entries"][0]["statements"][0]["source_statement_ids"] = []
        # A decision reference alone cannot drive the evidence drill-down that
        # lets the user inspect what the lesson rests on.
        return M4MapProposal.model_validate(payload)

    model = ScriptedM4Client(m4_script=[unsupported_lesson] * 8)
    with TestClient(
        create_app(database_path=tmp_path / "core-gap.sqlite3", model_client=model)
    ) as client:
        asset_id, m3, canonical = accepted_m3(client)
        response = client.post(
            f"/api/v1/m4/assets/{asset_id}",
            json={
                "asset_id": asset_id,
                "expected_m3_artifact_id": m3["artifact_id"],
                "expected_canonical_version_id": canonical["version_id"],
            },
        )
        assert response.status_code == 422, response.text
        assert client.get(f"/api/v1/m4/assets/{asset_id}").json()["map"] is None


def test_local_schema_requires_grounding_for_core_roles_only():
    statement_schema = m4_local_model_output_schema(
        max_entry_decisions=1,
        allowed_decision_ids=["11111111-1111-4111-8111-111111111111"],
        allowed_statement_ids=["22222222-2222-4222-8222-222222222222"],
    )["$defs"]["M4ProposedStatement"]
    branches_by_role: dict[str, list[dict]] = {}
    for branch in statement_schema["anyOf"]:
        role = branch["properties"]["role"]["enum"][0]
        branches_by_role.setdefault(role, []).append(branch)

    for role in ("LESSON", "SUPPORT"):
        assert len(branches_by_role[role]) == 1
        assert all(
            branch["properties"]["source_statement_ids"].get("minItems") == 1
            for branch in branches_by_role[role]
        )
    assert len(branches_by_role["COUNTEREXAMPLE"]) == 3
    assert any(
        branch["properties"]["source_statement_ids"].get("maxItems") == 0
        and branch["properties"]["source_decision_ids"].get("maxItems") == 0
        for branch in branches_by_role["COUNTEREXAMPLE"]
    )


def test_marking_a_gap_by_hand_retires_its_citations(tmp_path: Path):
    with TestClient(
        create_app(database_path=tmp_path / "mark.sqlite3", model_client=ScriptedM4Client())
    ) as client:
        asset_id, workspace = create_m4(client)
        artifact = workspace["map"]
        target = next(
            item
            for item in artifact["entries"][0]["statements"]
            if item["role"] == "LIMITATION"
        )
        assert target["source_statement_ids"]
        edited = client.patch(
            f"/api/v1/m4/assets/{asset_id}",
            json={
                "asset_id": asset_id,
                "expected_artifact_id": artifact["artifact_id"],
                "edits": [
                    {
                        "statement_id": target["statement_id"],
                        "is_visible_gap": True,
                        "gap_reason": "来源没有说明失效条件。",
                    }
                ],
            },
        )
        assert edited.status_code == 200, edited.text
        marked = next(
            item
            for item in edited.json()["map"]["entries"][0]["statements"]
            if item["statement_id"] == target["statement_id"]
        )
        assert marked["is_visible_gap"] is True
        assert marked["source_statement_ids"] == []
        assert edited.json()["map"]["state"] == "NEEDS_INPUT"

        without_reason = client.patch(
            f"/api/v1/m4/assets/{asset_id}",
            json={
                "asset_id": asset_id,
                "expected_artifact_id": edited.json()["map"]["artifact_id"],
                "edits": [
                    {
                        "statement_id": next(
                            item["statement_id"]
                            for item in artifact["entries"][0]["statements"]
                            if item["role"] == "SUPPORT"
                        ),
                        "is_visible_gap": True,
                    }
                ],
            },
        )
        assert without_reason.status_code == 422


def test_proposal_citing_an_unknown_statement_persists_nothing(tmp_path: Path):
    unknown = "11111111-1111-4111-8111-111111111111"

    def forged(request):
        payload = default_m4_proposal(request)
        payload["entries"][0]["statements"][1]["source_statement_ids"] = [unknown]
        return M4MapProposal.model_validate(payload)

    model = ScriptedM4Client(m4_script=[forged, forged, forged, forged])
    with TestClient(
        create_app(database_path=tmp_path / "forged.sqlite3", model_client=model)
    ) as client:
        asset_id, m3, canonical = accepted_m3(client)
        response = client.post(
            f"/api/v1/m4/assets/{asset_id}",
            json={
                "asset_id": asset_id,
                "expected_m3_artifact_id": m3["artifact_id"],
                "expected_canonical_version_id": canonical["version_id"],
            },
        )
        assert response.status_code == 422, response.text
        # A half-applied proposal would leave the artifact in a state no
        # contract describes, so nothing may be readable afterwards.
        workspace = client.get(f"/api/v1/m4/assets/{asset_id}")
        assert workspace.status_code == 200
        assert workspace.json()["map"] is None
        assert workspace.json()["canonical_version_id"] == canonical["version_id"]

        run_id = response.json()["detail"]["run_id"]
        status = client.get(f"/api/v1/m4/assets/{asset_id}/runs/{run_id}")
        assert status.status_code == 200, status.text
        assert status.json()["failure"]["failure_code"] == "INVALID_MODEL_OUTPUT"
        assert status.json()["failure"]["safe_user_message"]


def test_model_unavailable_reports_a_terminal_state_without_a_partial_map(tmp_path: Path):
    model = ScriptedM4Client(
        m4_script=[ModelUnavailable("local server down"), ModelUnavailable("still down")]
    )
    with TestClient(
        create_app(database_path=tmp_path / "down.sqlite3", model_client=model)
    ) as client:
        asset_id, m3, canonical = accepted_m3(client)
        response = client.post(
            f"/api/v1/m4/assets/{asset_id}",
            json={
                "asset_id": asset_id,
                "expected_m3_artifact_id": m3["artifact_id"],
                "expected_canonical_version_id": canonical["version_id"],
            },
        )
        assert response.status_code == 422, response.text
        assert client.get(f"/api/v1/m4/assets/{asset_id}").json()["map"] is None
        run_id = response.json()["detail"]["run_id"]
        failure = client.get(f"/api/v1/m4/assets/{asset_id}/runs/{run_id}").json()["failure"]
        assert failure["failure_code"] == "MODEL_UNAVAILABLE"
        assert failure["retryable"] is True


def test_context_sent_to_the_model_is_bounded_and_the_bound_is_recorded(tmp_path: Path):
    model = ScriptedM4Client()
    with TestClient(
        create_app(database_path=tmp_path / "bound.sqlite3", model_client=model)
    ) as client:
        create_m4(client)

    request = model.m4_requests[0]
    bound = request.canonical_context["context_bound"]
    # Injecting the full record set and hoping it fits fails by erroring or by
    # silently truncating; a truncated context yields a proposal citing records
    # the model never saw, which then reads as model quality rather than size.
    assert bound["decisions_supplied"] <= bound["max_decisions"]
    assert bound["statements_supplied"] <= bound["max_statements"]
    assert bound["decisions_supplied"] <= bound["decisions_available"]
    assert bound["model_call_budget"] and bound["timeout_seconds"]
    assert bound["structured_repair_budget"] and bound["max_output_tokens"]
    assert all(
        len(excerpt.text) <= bound["max_excerpt_chars"] for excerpt in request.source_excerpts
    )
    assert request.timeout_seconds == bound["timeout_seconds"]
    assert request.max_output_tokens == bound["max_output_tokens"]
    # PR #44 raised the window to 20480. Item counts alone cannot show a payload
    # fit — "6 decisions" is not a size — so the bound also carries the counted
    # prompt, the budget it was checked against, and the method that counted it.
    assert bound["prompt_tokens_counted"] > 0
    assert bound["prompt_budget_tokens"] == bound["context_budget_tokens"] - (
        bound["reserved_output_tokens"]
    )
    assert bound["within_budget"] is (
        bound["prompt_tokens_counted"] <= bound["prompt_budget_tokens"]
    )
    assert bound["counting_method"] in {"tokenizer", "character-ratio-estimate"}
    # The approved budget and the only window measured on the W7900 stay
    # distinguishable on the record; a single number would read as both.
    assert bound["verified_context_tokens"] == 8192
    assert bound["budget_authority"]


def test_a_narrowed_budget_actually_shrinks_the_payload(tmp_path: Path, monkeypatch):
    """The bound is load-bearing, not decoration.

    Recording a budget that no filling loop consults is the failure this test
    exists to catch: every assertion above would still pass if the number were
    written to the record and then ignored.
    """
    from app.experience_asset.inference.budget import VERIFIED_CONTEXT_TOKENS

    wide = ScriptedM4Client()
    with TestClient(
        create_app(database_path=tmp_path / "wide.sqlite3", model_client=wide)
    ) as client:
        create_m4(client)

    # Well under the verified window, but still above M4's own output
    # reservation — a budget smaller than the reservation is refused outright,
    # which is a different behaviour and is covered in the unit tests.
    monkeypatch.setenv("E5_CONTEXT_BUDGET_TOKENS", str(VERIFIED_CONTEXT_TOKENS // 2))
    narrow = ScriptedM4Client()
    with TestClient(
        create_app(database_path=tmp_path / "narrow.sqlite3", model_client=narrow)
    ) as client:
        create_m4(client)

    wide_bound = wide.m4_requests[0].canonical_context["context_bound"]
    narrow_bound = narrow.m4_requests[0].canonical_context["context_bound"]
    assert narrow_bound["context_budget_tokens"] < wide_bound["context_budget_tokens"]
    assert narrow_bound["prompt_tokens_counted"] <= wide_bound["prompt_tokens_counted"]
    assert narrow_bound["decisions_supplied"] <= wide_bound["decisions_supplied"]
    # One decision is sent even when it does not fit, because M4 cannot build a
    # map from nothing — and that case is recorded as over budget rather than
    # being presented as a payload that fit.
    assert narrow_bound["decisions_supplied"] >= 1


def test_retrieval_stays_inside_the_current_asset(tmp_path: Path):
    model = ScriptedM4Client()
    with TestClient(
        create_app(database_path=tmp_path / "scope.sqlite3", model_client=model)
    ) as client:
        asset_id, workspace = create_m4(client)

    request = model.m4_requests[0]
    # M4 runs before readiness exists. A historical asset admitted here would
    # anchor an experience the user is still clarifying, and the anchoring is
    # invisible afterwards because the lesson reads as self-derived.
    assert request.canonical_context["asset_id"] == asset_id
    assert "related" not in str(request.canonical_context).lower()
    served = {str(item["statement_id"]) for item in workspace["evidence_statements"]}
    assert set(request.canonical_context["allowed_statement_ids"]) >= served


def test_a_second_map_requires_explicit_regeneration(tmp_path: Path):
    with TestClient(
        create_app(database_path=tmp_path / "second.sqlite3", model_client=ScriptedM4Client())
    ) as client:
        asset_id, workspace = create_m4(client)
        again = client.post(
            f"/api/v1/m4/assets/{asset_id}",
            json={
                "asset_id": asset_id,
                "expected_m3_artifact_id": workspace["map"]["base_m3_artifact_id"],
                "expected_canonical_version_id": workspace["canonical_version_id"],
            },
        )
        assert again.status_code == 422
        assert "regeneration" in again.text


def test_map_survives_restart_and_stays_readable(tmp_path: Path):
    database = tmp_path / "restart.sqlite3"
    model = ScriptedM4Client()
    with TestClient(create_app(database_path=database, model_client=model)) as client:
        asset_id, workspace = create_m4(client)
        artifact_id = workspace["map"]["artifact_id"]

    with TestClient(create_app(database_path=database, model_client=model)) as client:
        restored = client.get(f"/api/v1/m4/assets/{asset_id}")
        assert restored.status_code == 200
        assert restored.json()["map"]["artifact_id"] == artifact_id


def correct_the_ledger(client: TestClient, asset_id: str) -> dict:
    """Edit an M3 statement the map depends on, the way a user correcting it would."""
    ledger = client.get(f"/api/v1/m3/assets/{asset_id}").json()["artifact"]
    target = ledger["entries"][0]["statements"][0]
    edited = client.patch(
        f"/api/v1/m3/assets/{asset_id}",
        json={
            "expected_artifact_id": ledger["artifact_id"],
            "statements": [
                {
                    "statement_id": target["statement_id"],
                    "text": "其实支撑没问题, 是坐姿的问题。",
                    "user_action": "CONFIRM",
                }
            ],
        },
    )
    assert edited.status_code == 200, edited.text
    return edited.json()["artifact"]


def test_correcting_the_ledger_invalidates_the_map_and_shows_it(tmp_path: Path):
    with TestClient(
        create_app(database_path=tmp_path / "invalidate.sqlite3", model_client=ScriptedM4Client())
    ) as client:
        asset_id, workspace = create_m4(client)
        before = workspace["map"]
        assert before["state"] == "REVIEW_READY"

        correct_the_ledger(client, asset_id)

        # Continuing to display the old map would present conclusions drawn
        # from evidence the user has since corrected.
        after = client.get(f"/api/v1/m4/assets/{asset_id}")
        assert after.status_code == 200, after.text
        invalidated = after.json()["map"]
        assert invalidated["state"] == "INVALIDATED"
        assert invalidated["invalidation_reason"]
        assert invalidated["invalidated_by_m3_artifact_id"]
        assert invalidated["affected_insight_ids"]
        assert invalidated["artifact_id"] != before["artifact_id"]

        # The pre-correction artifact stays readable as history rather than
        # being rewritten in place.
        assert after.json()["canonical_version_id"] != workspace["canonical_version_id"]


def test_an_invalidated_map_refuses_edits_and_reconciles_only_once(tmp_path: Path):
    with TestClient(
        create_app(database_path=tmp_path / "refuse.sqlite3", model_client=ScriptedM4Client())
    ) as client:
        asset_id, workspace = create_m4(client)
        correct_the_ledger(client, asset_id)
        invalidated = client.get(f"/api/v1/m4/assets/{asset_id}").json()

        rejected = client.patch(
            f"/api/v1/m4/assets/{asset_id}",
            json={
                "asset_id": asset_id,
                "expected_artifact_id": invalidated["map"]["artifact_id"],
                "edits": [
                    {
                        "statement_id": invalidated["map"]["entries"][0]["statements"][0][
                            "statement_id"
                        ],
                        "text": "试图在失效的 map 上继续编辑",
                    }
                ],
            },
        )
        assert rejected.status_code == 422
        assert "regenerate" in rejected.text

        # Reconciliation writes once. Re-deriving on every read would append a
        # canonical version per GET while the user's only move stays the same.
        settled = client.get(f"/api/v1/m4/assets/{asset_id}").json()
        assert settled["map"]["artifact_id"] == invalidated["map"]["artifact_id"]
        assert settled["canonical_version_id"] == invalidated["canonical_version_id"]


def test_correcting_m2_reaches_the_map_through_the_ledger(tmp_path: Path):
    """AC-8 names M1, M2 and M3. Only M3 is compared directly, so prove the cascade."""
    with TestClient(
        create_app(database_path=tmp_path / "cascade.sqlite3", model_client=ScriptedM4Client())
    ) as client:
        asset_id, workspace = create_m4(client)
        assert workspace["map"]["state"] == "REVIEW_READY"

        moments = client.get(f"/api/v1/m2/assets/{asset_id}").json()["artifact"]
        corrected = client.patch(
            f"/api/v1/m2/assets/{asset_id}",
            json={
                "expected_artifact_id": moments["artifact_id"],
                "moments": [
                    {
                        "moment_id": item["moment_id"],
                        "title": f"{item['title']} 已修正",
                        "criticality_status": "USER_CONFIRMED",
                    }
                    for item in moments["moments"]
                ],
            },
        )
        assert corrected.status_code == 200, corrected.text

        # E4 rebases or invalidates M3 in the transaction that records the M2
        # correction, so the map's one comparison against the current ledger is
        # what carries an upstream edit the map never looked at directly.
        after = client.get(f"/api/v1/m4/assets/{asset_id}").json()
        assert after["map"]["state"] == "INVALIDATED"
        assert after["map"]["invalidation_reason"]


def reconfirm_ledger(client: TestClient, asset_id: str) -> dict:
    ledger = client.get(f"/api/v1/m3/assets/{asset_id}").json()["artifact"]
    confirmed = client.post(
        f"/api/v1/m3/assets/{asset_id}/confirm",
        json={"expected_artifact_id": ledger["artifact_id"], "complete_with_gaps": False},
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()["artifact"]


def test_regeneration_waits_for_the_ledger_to_be_accepted_again(tmp_path: Path):
    with TestClient(
        create_app(database_path=tmp_path / "regen.sqlite3", model_client=ScriptedM4Client())
    ) as client:
        asset_id, _ = create_m4(client)
        correct_the_ledger(client, asset_id)
        invalidated = client.get(f"/api/v1/m4/assets/{asset_id}").json()
        assert invalidated["map"]["state"] == "INVALIDATED"

        # Correcting the ledger drops it out of its accepted state. Rebuilding
        # insights before the user re-accepts it would draw conclusions from a
        # ledger they are still in the middle of correcting.
        premature = client.post(
            f"/api/v1/m4/assets/{asset_id}/regenerate",
            json={
                "asset_id": asset_id,
                "expected_m3_artifact_id": client.get(f"/api/v1/m3/assets/{asset_id}").json()[
                    "artifact"
                ]["artifact_id"],
                "expected_canonical_version_id": invalidated["canonical_version_id"],
                "expected_invalidated_artifact_id": invalidated["map"]["artifact_id"],
            },
        )
        assert premature.status_code == 422
        assert "accepted M3" in premature.text

        accepted = reconfirm_ledger(client, asset_id)
        current = client.get(f"/api/v1/m1/assets/{asset_id}").json()["asset"]
        rebuilt = client.post(
            f"/api/v1/m4/assets/{asset_id}/regenerate",
            json={
                "asset_id": asset_id,
                "expected_m3_artifact_id": accepted["artifact_id"],
                "expected_canonical_version_id": current["version_id"],
                "expected_invalidated_artifact_id": invalidated["map"]["artifact_id"],
            },
        )
        assert rebuilt.status_code == 201, rebuilt.text
        assert rebuilt.json()["map"]["state"] in {"REVIEW_READY", "NEEDS_INPUT"}
        assert rebuilt.json()["map"]["artifact_id"] != invalidated["map"]["artifact_id"]
        assert rebuilt.json()["map"]["base_m3_artifact_id"] == accepted["artifact_id"]


def test_map_operations_never_mint_readiness_as_a_side_effect(tmp_path: Path):
    """Ticket 02 declares no readiness transition; ticket 03 owns the only one.

    This replaces the assertion that the acceptance handlers return 501. That
    pinned a boundary which existed only while ticket 03 was unbuilt; the
    invariant worth keeping is that generating or editing a map grants nothing.
    """
    with TestClient(
        create_app(database_path=tmp_path / "t03.sqlite3", model_client=ScriptedM4Client())
    ) as client:
        asset_id, workspace = create_m4(client)
        assert client.get(f"/api/v1/m4/assets/{asset_id}/readiness").status_code == 404

        target = workspace["map"]["entries"][0]["statements"][0]
        edited = client.patch(
            f"/api/v1/m4/assets/{asset_id}",
            json={
                "asset_id": asset_id,
                "expected_artifact_id": workspace["map"]["artifact_id"],
                "edits": [{"statement_id": target["statement_id"], "text": "改写一版"}],
            },
        )
        assert edited.status_code == 200, edited.text
        assert client.get(f"/api/v1/m4/assets/{asset_id}/readiness").status_code == 404
