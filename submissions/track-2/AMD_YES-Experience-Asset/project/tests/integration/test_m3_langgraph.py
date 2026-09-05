from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.experience_asset.api.main import create_app
from app.experience_asset.application.m3 import M3LedgerService
from app.experience_asset.domain.m3 import M3EditRequestV1
from app.experience_asset.inference import FakeModelClient
from app.experience_asset.inference.models import (
    InvalidModelOutput,
    M3LedgerProposal,
    M3LedgerResult,
    ModelMetadata,
    ModelTimedOut,
    ModelUnavailable,
    ToolCallProposal,
)
from app.experience_asset.workflow.m3_graph import (
    M3_MAX_OUTPUT_TOKENS,
    M3_MODEL_TIMEOUT_SECONDS,
    ensure_m3_entry_moment_coverage,
    m3_local_model_output_schema,
)
from app.experience_asset.workflow.m3_state import M3_GRAPH_NODES, M3_TOPOLOGY_HASH


class ScriptedM3Client(FakeModelClient):
    def __init__(self, script=()):
        super().__init__()
        self.script = deque(script)
        self.requests = []

    async def generate_m3_ledger(self, request):
        self.requests.append(request)
        outcome = self.script.popleft() if self.script else None
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            outcome = outcome(request)
        moment = request.canonical_context["moment_ids"][0]
        statement = str(request.source_excerpts[0].span_id).split(":", 1)[1]
        proposal = outcome or M3LedgerProposal(
            entries=[
                {
                    "prior_decision_id": (
                        request.canonical_context.get("affected_entry_ids", [None])[0]
                    ),
                    "title": "选择与结果",
                    "source_moment_ids": [moment],
                    "statements": [
                        {
                            "role": role,
                            "text": f"{role} evidence",
                            "source_moment_ids": [moment],
                            "source_statement_ids": [statement],
                        }
                        for role in (
                            "ALTERNATIVE",
                            "REASON",
                            "DECISION",
                            "ACTION",
                            "OBSERVED_RESULT",
                        )
                    ],
                }
            ]
        )
        return M3LedgerResult(
            proposal=proposal,
            metadata=ModelMetadata(
                server_kind="fake",
                server_base_url="http://127.0.0.1/fake",
                model_id="deterministic-contract-fake",
                elapsed_ms=0,
                received_at=datetime.now(UTC),
            ),
        )


def accepted_m2(client: TestClient) -> tuple[str, dict, dict]:
    created = client.post(
        "/api/v1/m1/assets",
        json={
            "source_kind": "PASTED_TEXT",
            "display_label": "M3 fixture",
            "text": "我试坐后发现支撑不足, 随后更换了椅子。",
            "goal_hint": "复盘选择",
        },
    ).json()
    asset_id = created["asset"]["asset_id"]
    m1 = client.post(
        f"/api/v1/m1/assets/{asset_id}/confirm",
        json={"expected_version_id": created["asset"]["version_id"], "complete_with_gaps": True},
    ).json()
    proposed = client.post(
        f"/api/v1/m2/assets/{asset_id}",
        json={"expected_m1_version_id": m1["asset"]["version_id"]},
    ).json()
    edited = client.patch(
        f"/api/v1/m2/assets/{asset_id}",
        json={
            "expected_artifact_id": proposed["artifact"]["artifact_id"],
            "moments": [
                {
                    "moment_id": item["moment_id"],
                    "title": item["title"],
                    "criticality_status": "USER_CONFIRMED",
                }
                for item in proposed["artifact"]["moments"]
            ],
        },
    ).json()
    accepted = client.post(
        f"/api/v1/m2/assets/{asset_id}/confirm",
        json={
            "expected_artifact_id": edited["artifact"]["artifact_id"],
            "complete_with_gaps": True,
        },
    ).json()
    canonical = client.get(f"/api/v1/m1/assets/{asset_id}").json()["asset"]
    return asset_id, accepted["artifact"], canonical


def invoke(tmp_path: Path, model: ScriptedM3Client):
    app = create_app(database_path=tmp_path / "asset.sqlite3", model_client=model)
    with TestClient(app) as client:
        asset_id, m2, canonical = accepted_m2(client)
        response = client.post(
            f"/api/v1/m3/assets/{asset_id}",
            json={
                "expected_m2_artifact_id": m2["artifact_id"],
                "expected_canonical_version_id": canonical["version_id"],
            },
        )
    return app, response, asset_id


def test_first_valid_and_checkpoint_excludes_content(tmp_path: Path):
    model = ScriptedM3Client()
    app, response, _ = invoke(tmp_path, model)
    assert response.status_code == 201, response.text
    assert (
        len(app.state.repository.list_m3_artifact_ids(response.json()["artifact"]["asset_id"])) == 1
    )
    run_id = __import__("uuid").UUID(
        response.json()["artifact"]["generated_by_run_id"]
    )
    terminal = app.state.repository.get_terminal_result(run_id)
    assert terminal.elapsed_ms >= 0
    assert terminal.model_call_count == 1
    metadata = app.state.repository.get_m3_proposal_metadata(run_id, 1)
    assert metadata.model_id == "deterministic-contract-fake"
    assert metadata.server_base_url == "http://127.0.0.1/fake"
    traces = app.state.repository.list_workflow_traces(run_id)
    assert [trace["node_name"] for trace in traces] == [
        "load_m3_context",
        "plan_m3_ledger",
        "validate_m3_output",
        "evaluate_m3_tool_policy",
        "persist_m3_ledger",
        "verify_m3_ledger",
        "terminalize_m3_run",
    ]
    assert next(
        trace for trace in traces if trace["node_name"] == "verify_m3_ledger"
    )["verification_outcome"] == "VERIFIED"
    context = model.requests[0].canonical_context
    assert context["moments"]
    assert context["moments"][0]["description"]
    assert context["moments"][0]["source_statement_ids"]
    assert set(context["moment_ids"]) == {
        moment["moment_id"] for moment in context["moments"]
    }
    request = model.requests[0]
    assert request.max_output_tokens == M3_MAX_OUTPUT_TOKENS == 1536
    assert request.timeout_seconds == M3_MODEL_TIMEOUT_SECONDS == 120
    entry_schema = request.output_schema["$defs"]["M3ProposedEntry"]
    statement_schema = request.output_schema["$defs"]["M3ProposedStatement"]
    assert request.output_schema["properties"]["entries"]["maxItems"] == 1
    assert entry_schema["properties"]["source_moment_ids"]["maxItems"] == len(
        context["moment_ids"]
    )
    assert entry_schema["properties"]["statements"]["maxItems"] == 5
    assert statement_schema["properties"]["text"]["maxLength"] == 480
    common_required = {"role", "text", "source_moment_ids"}
    source_branch, derived_branch, unresolved_branch = statement_schema["anyOf"]
    for branch in statement_schema["anyOf"]:
        assert branch["type"] == "object"
        assert branch["additionalProperties"] is False
        assert common_required.issubset(branch["required"])
        assert common_required.issubset(branch["properties"])
    assert "source_statement_ids" in source_branch["required"]
    assert source_branch["properties"]["source_statement_ids"]["minItems"] == 1
    assert "derived_from_statement_ids" in derived_branch["required"]
    assert (
        derived_branch["properties"]["derived_from_statement_ids"]["minItems"]
        == 1
    )
    assert "unresolved_reason" in unresolved_branch["required"]
    assert unresolved_branch["properties"]["unresolved_reason"] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 240,
    }
    allowed_ids = statement_schema["properties"]["source_statement_ids"]["items"]["enum"]
    assert set(allowed_ids) == {
        statement_id
        for moment in context["moments"]
        for statement_id in moment["source_statement_ids"]
    }
    assert "de-duplicated union of every statement's source_moment_ids" in (
        request.system_policy
    )
    assert "must be a subset of the entry list" in request.system_policy
    workflow_bytes = app.state.workflow_database_path.read_bytes()
    assert "我试坐后发现".encode() not in workflow_bytes


def test_regeneration_schema_requires_the_exact_affected_decision_id() -> None:
    affected_id = str(__import__("uuid").uuid4())

    schema = m3_local_model_output_schema(
        max_entry_moments=2,
        required_prior_decision_id=affected_id,
    )

    entry_schema = schema["$defs"]["M3ProposedEntry"]
    assert "prior_decision_id" in entry_schema["required"]
    assert entry_schema["properties"]["prior_decision_id"] == {
        "type": "string",
        "format": "uuid",
        "enum": [affected_id],
    }


def test_structural_normalization_appends_statement_moments_without_rewriting_content():
    first_moment, second_moment, source_statement = (
        __import__("uuid").uuid4(),
        __import__("uuid").uuid4(),
        __import__("uuid").uuid4(),
    )
    proposal = M3LedgerProposal(
        entries=[
            {
                "title": "选择与结果",
                "source_moment_ids": [first_moment],
                "statements": [
                    {
                        "role": role,
                        "text": f"{role} evidence",
                        "source_moment_ids": [
                            second_moment if role == "OBSERVED_RESULT" else first_moment
                        ],
                        "source_statement_ids": [source_statement],
                    }
                    for role in (
                        "ALTERNATIVE",
                        "REASON",
                        "DECISION",
                        "ACTION",
                        "OBSERVED_RESULT",
                    )
                ],
            }
        ]
    )

    normalized = ensure_m3_entry_moment_coverage(proposal)

    assert normalized.entries[0].source_moment_ids == [first_moment, second_moment]
    assert normalized.entries[0].statements == proposal.entries[0].statements
    assert proposal.entries[0].source_moment_ids == [first_moment]


def test_parse_invalid_enters_repair_then_succeeds(tmp_path: Path):
    model = ScriptedM3Client([InvalidModelOutput("bad"), None])
    app, response, _ = invoke(tmp_path, model)
    assert response.status_code == 201, response.text
    assert len(model.requests) == 2


def test_empty_evidence_shape_is_repaired_with_validation_feedback(tmp_path: Path):
    def empty_evidence_proposal(request):
        moment = request.canonical_context["moment_ids"][0]
        return M3LedgerProposal(
            entries=[
                {
                    "title": "选择与结果",
                    "source_moment_ids": [moment],
                    "statements": [
                        {
                            "role": role,
                            "text": f"{role} evidence",
                            "source_moment_ids": [moment],
                            "source_statement_ids": [],
                            "derived_from_statement_ids": [],
                            "unresolved_reason": None,
                        }
                        for role in (
                            "ALTERNATIVE",
                            "REASON",
                            "DECISION",
                            "ACTION",
                            "OBSERVED_RESULT",
                        )
                    ],
                }
            ]
        )

    model = ScriptedM3Client([empty_evidence_proposal, None])
    _, response, _ = invoke(tmp_path, model)

    assert response.status_code == 201, response.text
    assert len(model.requests) == 2
    repair_request = model.requests[1]
    assert repair_request.stage == "E4-M3-ledger-repair"
    feedback = repair_request.canonical_context["repair_feedback"]
    assert feedback["validation_error"] == "supported M3 statement requires evidence"
    assert feedback["rejected_proposal"]["entries"][0]["statements"][0] == {
        "role": "ALTERNATIVE",
        "text": "ALTERNATIVE evidence",
        "source_moment_ids": [repair_request.canonical_context["moment_ids"][0]],
        "source_statement_ids": [],
        "derived_from_statement_ids": [],
        "unresolved_reason": None,
    }
    assert "This is a correction request" in repair_request.system_policy
    assert "Do not repeat the rejected evidence shape" in repair_request.system_policy


def test_explicit_all_unresolved_ledger_persists_as_needs_input(tmp_path: Path):
    def all_unresolved_proposal(request):
        moment = request.canonical_context["moment_ids"][0]
        return M3LedgerProposal(
            entries=[
                {
                    "title": "选择与结果",
                    "source_moment_ids": [moment],
                    "statements": [
                        {
                            "role": role,
                            "text": f"{role} evidence is not stated in the source",
                            "source_moment_ids": [moment],
                            "source_statement_ids": [],
                            "derived_from_statement_ids": [],
                            "unresolved_reason": (
                                "The source does not provide claim-level evidence."
                            ),
                        }
                        for role in (
                            "ALTERNATIVE",
                            "REASON",
                            "DECISION",
                            "ACTION",
                            "OBSERVED_RESULT",
                        )
                    ],
                }
            ]
        )

    app, response, asset_id = invoke(
        tmp_path,
        ScriptedM3Client([all_unresolved_proposal]),
    )

    assert response.status_code == 201, response.text
    artifact = response.json()["artifact"]
    assert artifact["state"] == "NEEDS_INPUT"
    assert artifact["dependency_moment_ids"]
    assert artifact["dependency_statement_ids"] == []
    assert all(
        statement["status"] == "UNRESOLVED"
        and statement["unresolved_reason"]
        and not statement["source_statement_ids"]
        and not statement["derived_from_statement_ids"]
        for entry in artifact["entries"]
        for statement in entry["statements"]
    )

    with TestClient(app) as client:
        confirmed_as_self_report = client.patch(
            f"/api/v1/m3/assets/{asset_id}",
            json={
                "expected_artifact_id": artifact["artifact_id"],
                "statements": [
                    {
                        "statement_id": statement["statement_id"],
                        "text": statement["text"],
                        "user_action": "CONFIRM",
                    }
                    for entry in artifact["entries"]
                    for statement in entry["statements"]
                ],
            },
        )
        assert confirmed_as_self_report.status_code == 200, (
            confirmed_as_self_report.text
        )
        persisted = client.get(f"/api/v1/m3/assets/{asset_id}")
        assert persisted.status_code == 200, persisted.text

    persisted_statements = [
        statement
        for entry in persisted.json()["artifact"]["entries"]
        for statement in entry["statements"]
    ]
    assert all(
        statement["status"] == "USER_JUDGMENT"
        and statement["confirmation"] == "CONFIRMED"
        and statement["evidence_strength"] == "SELF_REPORTED"
        and statement["confirmed_at"]
        and not statement["source_statement_ids"]
        and not statement["derived_from_statement_ids"]
        for statement in persisted_statements
    )


def test_two_invalid_repairs_then_final_replan_never_exceeds_four_calls(tmp_path: Path):
    model = ScriptedM3Client(
        [InvalidModelOutput("1"), InvalidModelOutput("2"), InvalidModelOutput("3"), None]
    )
    _, response, _ = invoke(tmp_path, model)
    assert response.status_code == 201, response.text
    assert len(model.requests) == 4


@pytest.mark.parametrize("first", [ModelTimedOut("timeout"), ModelUnavailable("offline")])
def test_transient_first_call_then_success(tmp_path: Path, first):
    model = ScriptedM3Client([first, None])
    _, response, _ = invoke(tmp_path, model)
    assert response.status_code == 201, response.text
    assert len(model.requests) == 2


def test_two_transient_failures_have_queryable_terminal(tmp_path: Path):
    model = ScriptedM3Client([ModelUnavailable("1"), ModelUnavailable("2")])
    app, response, _ = invoke(tmp_path, model)
    assert response.status_code == 422
    assert response.json()["detail"]["run_id"]
    assert len(model.requests) == 2
    status = app.state.repository.get_terminal_result(
        __import__("uuid").UUID(response.json()["detail"]["run_id"])
    )
    assert status.state.value == "MODEL_UNAVAILABLE"
    assert status.model_call_count == 2


def test_invalid_then_two_transients_preserves_transient_terminal(tmp_path: Path):
    model = ScriptedM3Client([
        InvalidModelOutput("invalid"), ModelUnavailable("first"), ModelUnavailable("second")
    ])
    app, response, _ = invoke(tmp_path, model)
    run_id = __import__("uuid").UUID(response.json()["detail"]["run_id"])
    terminal = app.state.repository.get_terminal_result(run_id)
    assert response.status_code == 422
    assert terminal.state.value == "MODEL_UNAVAILABLE"
    assert terminal.model_call_count == 3
    assert terminal.internal_error_class == "M3WorkflowFailure"


def test_three_invalid_then_transient_fourth_call_has_no_internal_error(tmp_path: Path):
    model = ScriptedM3Client([
        InvalidModelOutput("1"), InvalidModelOutput("2"), InvalidModelOutput("3"),
        ModelUnavailable("fourth"),
    ])
    app, response, _ = invoke(tmp_path, model)
    terminal = app.state.repository.get_terminal_result(
        __import__("uuid").UUID(response.json()["detail"]["run_id"])
    )
    assert response.status_code == 422
    assert len(model.requests) == 4
    assert terminal.state.value == "MODEL_UNAVAILABLE"
    assert terminal.model_call_count == 4
    assert terminal.internal_error_class != "UnboundLocalError"


def test_tool_proposal_policy_blocked_without_artifact(tmp_path: Path):
    model = ScriptedM3Client()
    # Build a valid proposal dynamically, then add a forbidden inert tool.
    original = model.generate_m3_ledger

    async def with_tool(request):
        result = await original(request)
        return result.model_copy(
            update={
                "proposal": result.proposal.model_copy(
                    update={
                        "tool_call_proposals": [
                            ToolCallProposal(
                                name="delete_asset",
                                arguments={},
                                permission_granted=False,
                            )
                        ]
                    }
                )
            }
        )

    model.generate_m3_ledger = with_tool
    app, response, asset_id = invoke(tmp_path, model)
    assert response.status_code == 422
    assert app.state.repository.list_m3_artifact_ids(asset_id) == []
    run_id = __import__("uuid").UUID(response.json()["detail"]["run_id"])
    decisions = app.state.repository.list_m3_policy_decisions(run_id)
    assert len(decisions) == 1
    assert decisions[0].outcome.value == "DENY"
    assert "TOOL_NOT_ALLOWLISTED" in decisions[0].reason_codes
    request = model.requests[0]
    replayed = asyncio.run(
        app.state.m3_graph.policy(
            {
                "run_id": str(run_id),
                "asset_id": request.canonical_context["asset_id"],
                "base_version_id": request.canonical_context["version_id"],
                "proposal_attempt": 1,
            }
        )
    )
    assert replayed["policy_decision_id"] == str(decisions[0].decision_id)
    assert len(app.state.repository.list_m3_policy_decisions(run_id)) == 1


def test_topology_checkpoint_matches_declared_graph(tmp_path: Path):
    app, response, _ = invoke(tmp_path, ScriptedM3Client())
    assert response.status_code == 201
    checkpoint = json.loads(
        (Path(__file__).parents[2] / "contracts/checkpoints/e4-m3-preparation-v1.json").read_text()
    )
    assert checkpoint["workflow"]["topology_hash"] == M3_TOPOLOGY_HASH
    assert checkpoint["workflow"]["nodes"] == list(M3_GRAPH_NODES)


def test_replay_uses_run_commit_after_graph_artifact_is_superseded_by_user_edit(tmp_path: Path):
    app, response, asset_id = invoke(tmp_path, ScriptedM3Client())
    artifact = response.json()["artifact"]
    run_id = __import__("uuid").UUID(artifact["generated_by_run_id"])
    before = app.state.repository.get_m3_run_commit(run_id)
    statements = [item for entry in artifact["entries"] for item in entry["statements"]]
    M3LedgerService(app.state.repository).edit(
        __import__("uuid").UUID(asset_id),
        M3EditRequestV1(
            expected_artifact_id=artifact["artifact_id"],
            statements=[
                {
                    "statement_id": item["statement_id"],
                    "text": item["text"],
                    "user_action": "CONFIRM",
                }
                for item in statements
            ],
        ),
    )
    count = len(app.state.repository.list_m3_artifact_ids(__import__("uuid").UUID(asset_id)))
    persisted = asyncio.run(app.state.m3_graph.persist({"run_id": str(run_id)}))
    verified = asyncio.run(app.state.m3_graph.verify({**persisted, "run_id": str(run_id)}))
    assert verified["selected_edge"] == "verified"
    assert app.state.repository.get_m3_run_commit(run_id) == before
    history = app.state.repository.list_m3_artifact_ids(__import__("uuid").UUID(asset_id))
    assert len(history) == count
