from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.experience_asset.application.m3 import (
    M3ContractError,
    M3LedgerService,
    M3RecoveryAction,
    decide_invalid_output_recovery,
    invalidate_after_m2_correction,
)
from app.experience_asset.domain.enums import MilestoneState
from app.experience_asset.domain.m3 import (
    DecisionEvidenceLedgerV1,
    M3FailureV1,
    M3ProgressV1,
    M3StatementEditV1,
    M3WorkspaceV1,
)
from app.experience_asset.inference.models import M3LedgerProposal, ToolCallProposal
from app.experience_asset.workflow.m3_state import (
    M3_GRAPH_EDGES,
    M3_GRAPH_NODES,
    M3_GRAPH_STATE_ALLOWED_KEYS,
    M3_MODEL_CALL_BUDGET,
    M3_NODE_RETRY_BUDGET,
    M3_REPLAN_BUDGET,
    M3_STRUCTURED_REPAIR_BUDGET,
    M3_TOPOLOGY_HASH,
    M3_WORKFLOW_VERSION,
    M3GraphStateV1,
    validate_m3_graph_state,
)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_DIR = ROOT / "contracts" / "examples"
SCHEMA_DIR = ROOT / "contracts" / "json-schema"
CHECKPOINT_PATH = ROOT / "contracts" / "checkpoints" / "e4-m3-preparation-v1.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_ledger(name: str = "m3-ledger-complete.json") -> DecisionEvidenceLedgerV1:
    return DecisionEvidenceLedgerV1.model_validate(load_json(EXAMPLE_DIR / name))


def valid_graph_state() -> dict:
    return {
        "run_id": str(uuid4()),
        "asset_id": str(uuid4()),
        "base_version_id": str(uuid4()),
        "base_m2_artifact_id": str(uuid4()),
        "command_id": str(uuid4()),
        "workflow_version": M3_WORKFLOW_VERSION,
        "topology_hash": M3_TOPOLOGY_HASH,
        "node_attempt": 0,
        "structured_repair_attempts": 0,
        "replan_attempts": 0,
        "model_call_count": 0,
        "last_node": "",
        "selected_edge": "",
        "structured_proposal_hash": None,
        "policy_decision_id": None,
        "tool_execution_id": None,
        "artifact_id": None,
        "canonical_version_id": None,
        "terminal_candidate": "",
        "finding_codes": [],
        "safe_message": "",
        "retryable": False,
    }


@pytest.mark.parametrize(
    "name",
    [
        "m3-ledger-complete.json",
        "m3-ledger-incomplete.json",
        "m3-ledger-conflicting.json",
        "m3-ledger-correction-invalidated.json",
    ],
)
def test_public_m3_examples_validate(name: str) -> None:
    artifact = load_ledger(name)
    assert artifact.entries


def test_incomplete_result_stays_explicit_instead_of_being_invented() -> None:
    artifact = load_ledger("m3-ledger-incomplete.json")
    result = next(
        statement
        for statement in artifact.entries[0].statements
        if statement.role == "OBSERVED_RESULT"
    )

    assert artifact.state is MilestoneState.NEEDS_INPUT
    assert result.status.value == "UNRESOLVED"
    assert result.evidence_disposition == "UNRESOLVED"
    assert result.source_statement_ids == []
    assert result.unresolved_reason


def test_conflicting_evidence_remains_visible_and_source_linked() -> None:
    artifact = load_ledger("m3-ledger-conflicting.json")
    reason = next(
        statement for statement in artifact.entries[0].statements if statement.role == "REASON"
    )

    assert reason.evidence_disposition == "CONFLICTING"
    assert len(reason.source_statement_ids) == 2
    assert reason.unresolved_reason
    assert reason.confirmation.value == "UNCONFIRMED"


def test_unsupported_source_fact_is_rejected_before_persistence() -> None:
    payload = load_json(EXAMPLE_DIR / "m3-ledger-complete.json")
    payload["state"] = "REVIEW_READY"
    statement = payload["entries"][0]["statements"][0]
    statement["source_statement_ids"] = []
    statement["evidence_strength"] = "NONE"

    with pytest.raises(ValidationError, match="requires evidence references"):
        DecisionEvidenceLedgerV1.model_validate(payload)


def test_proposal_evidence_must_belong_to_its_declared_moment() -> None:
    first_moment_id, second_moment_id = uuid4(), uuid4()
    first_statement_id, second_statement_id = uuid4(), uuid4()
    repository = SimpleNamespace(
        get_current_m2=lambda _asset_id: SimpleNamespace(
            moments=[
                SimpleNamespace(
                    moment_id=first_moment_id,
                    source_statement_ids=[first_statement_id],
                ),
                SimpleNamespace(
                    moment_id=second_moment_id,
                    source_statement_ids=[second_statement_id],
                ),
            ]
        ),
        get_current=lambda _asset_id: SimpleNamespace(
            statements=[
                SimpleNamespace(statement_id=first_statement_id),
                SimpleNamespace(statement_id=second_statement_id),
            ]
        ),
    )
    proposal = M3LedgerProposal(
        entries=[
            {
                "title": "错误关联",
                "source_moment_ids": [first_moment_id],
                "statements": [
                    {
                        "role": role,
                        "text": f"{role} statement",
                        "source_moment_ids": [first_moment_id],
                        "source_statement_ids": [second_statement_id],
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

    with pytest.raises(M3ContractError, match="declared source moments"):
        M3LedgerService(repository).validate_proposal(uuid4(), proposal)

    duplicate_payload = proposal.model_dump(mode="python")
    for statement in duplicate_payload["entries"][0]["statements"]:
        statement["source_statement_ids"] = [first_statement_id, first_statement_id]
    duplicate_proposal = M3LedgerProposal.model_validate(duplicate_payload)
    with pytest.raises(M3ContractError, match="source statement IDs must be unique"):
        M3LedgerService(repository).validate_proposal(uuid4(), duplicate_proposal)


def test_missing_role_requires_an_explicit_unresolved_statement() -> None:
    payload = load_json(EXAMPLE_DIR / "m3-ledger-complete.json")
    payload["state"] = "REVIEW_READY"
    payload["entries"][0]["statements"] = [
        statement
        for statement in payload["entries"][0]["statements"]
        if statement["role"] != "OBSERVED_RESULT"
    ]

    with pytest.raises(ValidationError):
        DecisionEvidenceLedgerV1.model_validate(payload)


def test_confirmed_ledger_rejects_conflicts_and_unconfirmed_claims() -> None:
    payload = load_json(EXAMPLE_DIR / "m3-ledger-conflicting.json")
    payload["state"] = "CONFIRMED"

    with pytest.raises(ValidationError, match="cannot contain gaps"):
        DecisionEvidenceLedgerV1.model_validate(payload)


def test_user_edit_cannot_smuggle_an_unresolved_reason() -> None:
    with pytest.raises(ValidationError, match="only MARK_UNRESOLVED"):
        M3StatementEditV1(
            statement_id=uuid4(),
            text="A corrected public statement.",
            user_action="CONFIRM",
            unresolved_reason="This must not be retained as a hidden gap.",
        )


def test_affected_m2_correction_invalidates_only_the_dependent_ledger() -> None:
    artifact = load_ledger()
    changed_at = artifact.updated_at + timedelta(minutes=1)
    new_m2_artifact_id = uuid4()
    new_canonical_version_id = uuid4()

    invalidated = invalidate_after_m2_correction(
        artifact,
        changed_moment_ids={artifact.dependency_moment_ids[0]},
        changed_statement_ids=set(),
        new_m2_artifact_id=new_m2_artifact_id,
        new_canonical_version_id=new_canonical_version_id,
        changed_at=changed_at,
    )

    assert invalidated.state is MilestoneState.INVALIDATED
    assert invalidated.invalidated_by_m2_artifact_id == new_m2_artifact_id
    assert invalidated.invalidated_by_canonical_version_id == new_canonical_version_id
    assert invalidated.updated_at == changed_at
    assert artifact.state is MilestoneState.CONFIRMED


def test_unrelated_m2_correction_preserves_the_ledger() -> None:
    artifact = load_ledger()

    unchanged = invalidate_after_m2_correction(
        artifact,
        changed_moment_ids={uuid4()},
        changed_statement_ids={uuid4()},
        new_m2_artifact_id=uuid4(),
        new_canonical_version_id=uuid4(),
        changed_at=artifact.updated_at + timedelta(minutes=1),
    )

    assert unchanged is artifact


@pytest.mark.parametrize(
    "changed_at",
    [
        datetime(2026, 7, 29, 8, 31),
        datetime(2026, 7, 29, 8, 29, tzinfo=UTC),
    ],
)
def test_invalidation_rejects_naive_or_regressing_time(changed_at: datetime) -> None:
    artifact = load_ledger()

    with pytest.raises(ValueError, match="changed_at"):
        invalidate_after_m2_correction(
            artifact,
            changed_moment_ids={artifact.dependency_moment_ids[0]},
            changed_statement_ids=set(),
            new_m2_artifact_id=uuid4(),
            new_canonical_version_id=uuid4(),
            changed_at=changed_at,
        )


def test_m3_graph_state_rejects_private_or_canonical_payloads() -> None:
    state = valid_graph_state()
    state["raw_source_text"] = "private fixture content"

    with pytest.raises(ValueError, match="forbidden fields"):
        validate_m3_graph_state(state)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("node_attempt", M3_NODE_RETRY_BUDGET + 1),
        ("structured_repair_attempts", M3_STRUCTURED_REPAIR_BUDGET + 1),
        ("replan_attempts", M3_REPLAN_BUDGET + 1),
        ("model_call_count", M3_MODEL_CALL_BUDGET + 1),
    ],
)
def test_m3_workflow_budgets_are_fail_closed(field: str, value: int) -> None:
    state = valid_graph_state()
    state[field] = value

    with pytest.raises(ValidationError):
        M3GraphStateV1.model_validate(state)


def test_repair_and_replan_attempts_require_model_call_evidence() -> None:
    state = valid_graph_state()
    state.update(structured_repair_attempts=1, replan_attempts=1, model_call_count=1)

    with pytest.raises(ValidationError, match="cannot exceed model-call evidence"):
        M3GraphStateV1.model_validate(state)


def test_invalid_output_recovery_prefers_bounded_structured_repair() -> None:
    state = M3GraphStateV1.model_validate({**valid_graph_state(), "model_call_count": 1})

    decision = decide_invalid_output_recovery(state)

    assert decision.action is M3RecoveryAction.REPAIR
    assert decision.failure_code is None
    assert decision.state.structured_repair_attempts == 1
    assert decision.state.replan_attempts == 0
    assert decision.state.model_call_count == 2
    assert decision.state.selected_edge == "validate_m3_output:repairable"
    assert state.structured_repair_attempts == 0


def test_invalid_output_recovery_replans_only_after_repairs_are_exhausted() -> None:
    state = M3GraphStateV1.model_validate(
        {
            **valid_graph_state(),
            "structured_repair_attempts": M3_STRUCTURED_REPAIR_BUDGET,
            "model_call_count": 3,
        }
    )

    decision = decide_invalid_output_recovery(state)

    assert decision.action is M3RecoveryAction.REPLAN
    assert decision.failure_code is None
    assert decision.state.structured_repair_attempts == 2
    assert decision.state.replan_attempts == 1
    assert decision.state.model_call_count == 4
    assert decision.state.selected_edge == "validate_m3_output:exhausted"


def test_invalid_output_recovery_safe_stops_when_global_budget_is_exhausted() -> None:
    state = M3GraphStateV1.model_validate(
        {
            **valid_graph_state(),
            "structured_repair_attempts": M3_STRUCTURED_REPAIR_BUDGET,
            "replan_attempts": M3_REPLAN_BUDGET,
            "model_call_count": M3_MODEL_CALL_BUDGET,
        }
    )

    decision = decide_invalid_output_recovery(state)

    assert decision.action is M3RecoveryAction.SAFE_STOP
    assert decision.failure_code == "REPLAN_EXHAUSTED"
    assert decision.state.terminal_candidate == "INVALID_MODEL_OUTPUT"
    assert decision.state.selected_edge == "replan_m3_run:exhausted"
    assert decision.state.model_call_count == M3_MODEL_CALL_BUDGET
    assert "No ledger was saved" in decision.state.safe_message


def test_model_cannot_forge_tool_permission() -> None:
    with pytest.raises(ValidationError):
        ToolCallProposal.model_validate(
            {
                "name": "inspect_evidence_gaps",
                "arguments": {
                    "asset_id": str(uuid4()),
                    "current_version_id": str(uuid4()),
                    "milestone": "M3",
                    "statement_ids": [],
                },
                "requested_reason": "Inspect unresolved evidence.",
                "permission_granted": True,
            }
        )


def test_progress_uses_real_stage_and_bounded_counters() -> None:
    payload = load_json(EXAMPLE_DIR / "m3-workspace-complete.json")["progress"]
    progress = M3ProgressV1.model_validate(payload)

    assert progress.stage == "TERMINAL"
    assert progress.terminal_state.value == "SUCCEEDED"
    assert not hasattr(progress, "percent")
    assert not hasattr(progress, "eta_seconds")

    payload["structured_repairs_used"] = 2
    payload["replans_used"] = 1
    payload["model_calls_used"] = 2
    with pytest.raises(ValidationError, match="cannot exceed model-call evidence"):
        M3ProgressV1.model_validate(payload)


def test_permission_failure_maps_to_policy_blocked() -> None:
    payload = load_json(EXAMPLE_DIR / "m3-workspace-policy-blocked.json")
    workspace = M3WorkspaceV1.model_validate(payload)

    assert workspace.latest_failure is not None
    assert workspace.latest_failure.code == "PERMISSION_DENIED"
    assert workspace.latest_failure.terminal_state.value == "POLICY_BLOCKED"

    failure_payload = payload["latest_failure"]
    failure_payload["terminal_state"] = "INVALID_MODEL_OUTPUT"
    with pytest.raises(ValidationError, match="must map to terminal state"):
        M3FailureV1.model_validate(failure_payload)


def test_invalidated_workspace_cannot_offer_stale_edit_actions() -> None:
    payload = load_json(EXAMPLE_DIR / "m3-workspace-complete.json")
    payload["artifact"] = load_json(EXAMPLE_DIR / "m3-ledger-correction-invalidated.json")
    payload["is_current"] = False
    payload["allowed_actions"] = ["EDIT", "REGENERATE"]

    with pytest.raises(ValidationError, match="allows only REGENERATE"):
        M3WorkspaceV1.model_validate(payload)


def test_checked_in_m3_schemas_match_the_isolated_models() -> None:
    assert (
        load_json(SCHEMA_DIR / "decision-evidence-ledger-v0.1.schema.json")
        == DecisionEvidenceLedgerV1.model_json_schema()
    )
    assert load_json(SCHEMA_DIR / "m3-workspace-v1.schema.json") == (
        M3WorkspaceV1.model_json_schema()
    )
    assert load_json(SCHEMA_DIR / "m3-progress-v1.schema.json") == (
        M3ProgressV1.model_json_schema()
    )
    assert load_json(SCHEMA_DIR / "m3-failure-v1.schema.json") == (M3FailureV1.model_json_schema())


def test_checkpoint_records_integrated_checkpoint_two_boundary() -> None:
    checkpoint = load_json(CHECKPOINT_PATH)

    assert (
        checkpoint["status"]
        == "CHECKPOINT_2_IMPLEMENTED_W7900_EXECUTION_PREPARED"
    )
    assert checkpoint["scope_state"] == "MATERIAL_VERTICAL_SLICE_INTEGRATED"
    assert checkpoint["issue"] == 21
    assert checkpoint["upstream_gate"] == {
        "pull_request": 20,
        "merge_commit": "5c5c84f5209b2f91745924e69d55ea5290880153",
        "observed_status": "MERGED",
        "integration_audit_status": "COMPLETED_LOCAL",
    }
    assert checkpoint["workflow"]["version"] == M3_WORKFLOW_VERSION
    assert checkpoint["workflow"]["topology_hash"] == M3_TOPOLOGY_HASH
    assert checkpoint["workflow"]["nodes"] == list(M3_GRAPH_NODES)
    assert checkpoint["workflow"]["edges"] == [list(edge) for edge in M3_GRAPH_EDGES]
    assert set(checkpoint["workflow"]["state_allowlist"]) == set(M3_GRAPH_STATE_ALLOWED_KEYS)
    assert (
        checkpoint["workflow"]["model_request_profile"]["entry_source_moment_capacity"]
        == "all supplied M2 moments"
    )
    assert "union" in checkpoint["workflow"]["model_request_profile"]["entry_source_moment_rule"]
    assert "FastAPI routes and queryable run outcomes" in checkpoint["integration_implemented"]
    assert checkpoint["evidence_impact"]["status"] == (
        "W7900_EXECUTION_PREPARED_PROMOTION_NOT_VERIFIED"
    )
    assert checkpoint["affected_shared_files_after_e3_merge"]
    assert all(checkpoint["checkpoint_completion"].values())
    assert checkpoint["external_verification_deferred"] == [
        "quality-owner promotion",
        "kinnyuww execution of the prepared real W7900/ROCm/vLLM gate",
    ]
    assert checkpoint["w7900_handoff"]["implementation_owner_remaining_work"].startswith(
        "none after local gates pass"
    )
    for relative_path in (
        checkpoint["w7900_handoff"]["runner"],
        checkpoint["w7900_handoff"]["real_model_capture"],
        checkpoint["w7900_handoff"]["negative_path_capture"],
        checkpoint["w7900_handoff"]["packet_finalizer"],
        checkpoint["w7900_handoff"]["instructions"],
    ):
        assert (ROOT / relative_path).is_file(), relative_path
    assert checkpoint["interface_contracts"]["progress"]["forbidden"] == [
        "fabricated percentage",
        "fabricated ETA",
    ]
    failure_schema = load_json(SCHEMA_DIR / "m3-failure-v1.schema.json")
    assert set(checkpoint["interface_contracts"]["error"]["stable_codes"]) == set(
        failure_schema["properties"]["code"]["enum"]
    )

    for relative_path in (
        checkpoint["contracts"] + checkpoint["public_examples"] + checkpoint["evidence_templates"]
    ):
        assert (ROOT / relative_path).is_file(), relative_path


def test_negative_scenarios_cover_required_failure_and_recovery_paths() -> None:
    payload = load_json(EXAMPLE_DIR / "m3-negative-scenarios-v1.json")
    scenarios = {item["id"]: item for item in payload["scenarios"]}

    assert set(scenarios) == {
        "unsupported_claim",
        "invalid_output_repairable",
        "invalid_output_exhausted",
        "forged_tool_call",
        "permission_denied",
        "correction_invalidation",
    }
    assert scenarios["forged_tool_call"]["expected_terminal_if_exhausted"] == ("POLICY_BLOCKED")
    assert (
        scenarios["invalid_output_exhausted"]["expected_terminal_if_exhausted"]
        == "INVALID_MODEL_OUTPUT"
    )


def test_evidence_template_is_append_only_ready_and_topology_bound() -> None:
    manifest = load_json(ROOT / "evidence" / "templates" / "e4-m3" / "manifest.template.json")

    assert manifest["source"]["branch"] == "codex/e4-m3-ledger"
    assert (
        manifest["environment"]["workflow_schema_versions"]["m3_topology_hash"] == M3_TOPOLOGY_HASH
    )
    assert manifest["decision"]["result_class"] == "<CONDITIONAL|FAIL>"
    assert manifest["results"]["terminal_state"] == (
        "<W7900_COMPATIBILITY_READY_FOR_REVIEW|FAIL>"
    )
    assert manifest["history"]["supersedes_packet_id"] is None
    assert "append-only" in manifest["history"]["notes"]
