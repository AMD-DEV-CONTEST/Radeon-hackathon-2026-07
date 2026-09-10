"""Machine and blinded-human evidence remain strictly separated."""

from __future__ import annotations

import hashlib
import json

import pytest

from specstyle.calibration.evidence_io import canonical_json
from specstyle.errors import DomainError
from specstyle.evaluation.evidence import (
    import_blind_labels,
    validate_machine_ledger,
)

from tests.unit.evaluation._formal_fixtures import (
    blind_labels,
    label_approval_receipt,
    machine_ledger,
    protocol_document,
    sealed_protocol,
)


def _documents():
    protocol = protocol_document()
    sealed = sealed_protocol(protocol)
    ledger = machine_ledger(protocol, sealed)
    return protocol, sealed, ledger


def test_machine_ledger_validates_complete_input_by_arm_matrix() -> None:
    protocol, sealed, ledger = _documents()
    receipt = json.loads(validate_machine_ledger(protocol, sealed, ledger))

    assert receipt["status"] == "STRUCTURALLY_VALIDATED_AWAITING_BLIND_LABELS"
    assert receipt["formal_eligible"] is False
    assert receipt["input_count"] == 2
    assert receipt["record_count"] == 10
    assert receipt["missing_artifact_count"] == 0


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update({"profile": "preview"}),
        lambda value: value["records"].pop(),
        lambda value: value["records"].append(value["records"][0]),
        lambda value: value["records"][1]["attempts"][0].update({"seed": 999}),
        lambda value: value["records"][1]["attempts"][0].update(
            {"model_supply_sha256": "f" * 64}
        ),
        lambda value: value["records"][1]["attempts"][0].update(
            {"request_sha256": "e" * 64}
        ),
        lambda value: value["records"][1]["attempts"][0].update(
            {"generation_status": "GENERATION_FAILED"}
        ),
        lambda value: value["records"][1].update(
            {"final_qa_contract_sha256": "f" * 64}
        ),
        lambda value: value["records"][0].update(
            {"observed_at": "2026-08-03T09:59:59Z"}
        ),
    ),
)
def test_machine_ledger_rejects_unfair_incomplete_or_preview_evidence(mutate) -> None:
    protocol, sealed, ledger = _documents()
    value = json.loads(ledger)
    mutate(value)

    with pytest.raises(DomainError, match="machine evaluation ledger"):
        validate_machine_ledger(protocol, sealed, canonical_json(value))


def test_best_of_k_must_consume_full_preregistered_budget() -> None:
    protocol, sealed, ledger = _documents()
    value = json.loads(ledger)
    record = value["records"][2]
    record["attempts"].pop()
    record["generations_used"] = 2
    record["gpu_seconds"] = sum(item["gpu_seconds"] for item in record["attempts"])
    record["candidate_sha256"] = record["attempts"][-1]["artifact_sha256"]
    record["attempts"][-1]["qa_pass"] = True

    with pytest.raises(DomainError, match="machine evaluation ledger"):
        validate_machine_ledger(protocol, sealed, canonical_json(value))


def test_full_repair_cannot_change_seed_without_sampling_defect_reason() -> None:
    protocol, sealed, ledger = _documents()
    value = json.loads(ledger)
    value["records"][4]["attempts"][1]["seed"] = 102

    with pytest.raises(DomainError, match="machine evaluation ledger"):
        validate_machine_ledger(protocol, sealed, canonical_json(value))


def test_retry_materials_and_strategy_contract_are_bound() -> None:
    protocol, sealed, ledger = _documents()
    value = json.loads(ledger)
    value["records"][1]["attempts"][1]["generation_materials_sha256"] = "f" * 64
    with pytest.raises(DomainError, match="machine evaluation ledger"):
        validate_machine_ledger(protocol, sealed, canonical_json(value))

    value = json.loads(ledger)
    value["records"][4]["strategy_contract_sha256"] = "f" * 64
    value["records"][4]["strategy_trace_sha256"] = "e" * 64
    with pytest.raises(DomainError, match="machine evaluation ledger"):
        validate_machine_ledger(protocol, sealed, canonical_json(value))


def test_strategy_trace_binds_c_utility_qa_and_selected_candidate() -> None:
    protocol, sealed, ledger = _documents()
    value = json.loads(ledger)
    record = value["records"][2]
    record["attempts"][0]["utility_score"] = 99.0
    record["attempts"][0]["qa_pass"] = True
    record["attempts"][-1]["qa_pass"] = False
    record["candidate_sha256"] = record["attempts"][0]["artifact_sha256"]
    record["initial_machine_pass"] = True

    with pytest.raises(DomainError, match="machine evaluation ledger"):
        validate_machine_ledger(protocol, sealed, canonical_json(value))


def test_generated_artifact_cannot_be_hidden_behind_failed_terminal() -> None:
    protocol, sealed, ledger = _documents()
    value = json.loads(ledger)
    record = value["records"][5]
    record["machine_terminal"] = "FAILED"
    record["candidate_sha256"] = None
    record["blind_artifact_id"] = None

    with pytest.raises(DomainError, match="machine evaluation ledger"):
        validate_machine_ledger(protocol, sealed, canonical_json(value))


def test_full_repair_early_failure_requires_allowed_stop_reason() -> None:
    protocol, sealed, ledger = _documents()
    value = json.loads(ledger)
    record = value["records"][4]
    record["machine_terminal"] = "REJECTED"
    record["final_machine_pass"] = False
    record["failure_reasons"] = ["QA_NOT_PASSED"]
    record["attempts"][-1]["qa_pass"] = False

    with pytest.raises(DomainError, match="machine evaluation ledger"):
        validate_machine_ledger(protocol, sealed, canonical_json(value))


def test_full_repair_can_stop_with_bound_no_improvement_evidence() -> None:
    protocol, sealed, ledger = _documents()
    value = json.loads(ledger)
    record = value["records"][4]
    record["machine_terminal"] = "REJECTED"
    record["final_machine_pass"] = False
    record["failure_reasons"] = ["QA_NOT_PASSED"]
    record["attempts"][-1]["qa_pass"] = False
    record["stop_event"] = {
        "generation_index": len(record["attempts"]) - 1,
        "guardrail_decision": "PASSED",
        "kind": "NO_IMPROVEMENT",
        "repair_action_sha256": record["attempts"][-1]["repair_action_sha256"],
        "result_sha256": "f" * 64,
        "trigger_rule_ids": record["attempts"][-1]["trigger_rule_ids"],
    }
    material = {
        "arm": record["arm"],
        "strategy_contract_sha256": record["strategy_contract_sha256"],
        "attempts": record["attempts"],
        "decision": {
            "candidate_sha256": record["candidate_sha256"],
            "failure_reasons": record["failure_reasons"],
            "machine_terminal": record["machine_terminal"],
            "stop_event": record["stop_event"],
        },
    }
    record["strategy_trace_sha256"] = hashlib.sha256(
        canonical_json(material)
    ).hexdigest()

    receipt = json.loads(
        validate_machine_ledger(protocol, sealed, canonical_json(value))
    )
    assert receipt["status"] == "STRUCTURALLY_VALIDATED_AWAITING_BLIND_LABELS"


def test_guardrail_rejection_must_be_independent_of_generation_attempts() -> None:
    protocol, sealed, ledger = _documents()
    value = json.loads(ledger)
    record = value["records"][4]
    record["machine_terminal"] = "REJECTED"
    record["final_machine_pass"] = False
    record["failure_reasons"] = ["QA_NOT_PASSED"]
    record["attempts"][-1]["qa_pass"] = False
    record["stop_event"] = {
        "generation_index": len(record["attempts"]) - 1,
        "guardrail_decision": "PASSED",
        "kind": "GUARDRAIL_REJECTED",
        "repair_action_sha256": record["attempts"][-1]["repair_action_sha256"],
        "result_sha256": "f" * 64,
        "trigger_rule_ids": record["attempts"][-1]["trigger_rule_ids"],
    }
    material = {
        "arm": record["arm"],
        "strategy_contract_sha256": record["strategy_contract_sha256"],
        "attempts": record["attempts"],
        "decision": {
            "candidate_sha256": record["candidate_sha256"],
            "failure_reasons": record["failure_reasons"],
            "machine_terminal": record["machine_terminal"],
            "stop_event": record["stop_event"],
        },
    }
    record["strategy_trace_sha256"] = hashlib.sha256(
        canonical_json(material)
    ).hexdigest()

    with pytest.raises(DomainError, match="machine evaluation ledger"):
        validate_machine_ledger(protocol, sealed, canonical_json(value))


def test_guardrail_rejection_can_end_e_with_a_bound_decision_event() -> None:
    protocol, sealed, ledger = _documents()
    value = json.loads(ledger)
    record = value["records"][4]
    record["machine_terminal"] = "REJECTED"
    record["final_machine_pass"] = False
    record["failure_reasons"] = ["QA_NOT_PASSED"]
    record["attempts"][-1]["qa_pass"] = False
    record["stop_event"] = {
        "generation_index": None,
        "guardrail_decision": "REJECTED",
        "kind": "GUARDRAIL_REJECTED",
        "repair_action_sha256": "e" * 64,
        "result_sha256": "f" * 64,
        "trigger_rule_ids": ["l2_style"],
    }
    material = {
        "arm": record["arm"],
        "strategy_contract_sha256": record["strategy_contract_sha256"],
        "attempts": record["attempts"],
        "decision": {
            "candidate_sha256": record["candidate_sha256"],
            "failure_reasons": record["failure_reasons"],
            "machine_terminal": record["machine_terminal"],
            "stop_event": record["stop_event"],
        },
    }
    record["strategy_trace_sha256"] = hashlib.sha256(
        canonical_json(material)
    ).hexdigest()

    receipt = json.loads(
        validate_machine_ledger(protocol, sealed, canonical_json(value))
    )
    assert receipt["status"] == "STRUCTURALLY_VALIDATED_AWAITING_BLIND_LABELS"


def test_d_without_guardrails_cannot_stop_early_for_no_improvement() -> None:
    protocol, sealed, ledger = _documents()
    value = json.loads(ledger)
    record = value["records"][3]
    record["machine_terminal"] = "REJECTED"
    record["final_machine_pass"] = False
    record["failure_reasons"] = ["QA_NOT_PASSED"]
    record["attempts"][-1]["qa_pass"] = False
    record["stop_event"] = {
        "generation_index": len(record["attempts"]) - 1,
        "guardrail_decision": "DISABLED_EVALUATION_ONLY",
        "kind": "NO_IMPROVEMENT",
        "repair_action_sha256": record["attempts"][-1]["repair_action_sha256"],
        "result_sha256": "f" * 64,
        "trigger_rule_ids": record["attempts"][-1]["trigger_rule_ids"],
    }
    material = {
        "arm": record["arm"],
        "strategy_contract_sha256": record["strategy_contract_sha256"],
        "attempts": record["attempts"],
        "decision": {
            "candidate_sha256": record["candidate_sha256"],
            "failure_reasons": record["failure_reasons"],
            "machine_terminal": record["machine_terminal"],
            "stop_event": record["stop_event"],
        },
    }
    record["strategy_trace_sha256"] = hashlib.sha256(
        canonical_json(material)
    ).hexdigest()

    with pytest.raises(DomainError, match="machine evaluation ledger"):
        validate_machine_ledger(protocol, sealed, canonical_json(value))


def test_random_retry_must_exhaust_budget_when_no_attempt_passes() -> None:
    protocol, sealed, ledger = _documents()
    value = json.loads(ledger)
    record = value["records"][1]
    record["machine_terminal"] = "REJECTED"
    record["final_machine_pass"] = False
    record["failure_reasons"] = ["QA_NOT_PASSED"]
    record["attempts"][-1]["qa_pass"] = False

    with pytest.raises(DomainError, match="machine evaluation ledger"):
        validate_machine_ledger(protocol, sealed, canonical_json(value))


def test_best_of_k_must_select_highest_utility_with_lowest_index_tie_break() -> None:
    protocol, sealed, ledger = _documents()
    value = json.loads(ledger)
    record = value["records"][2]
    record["candidate_sha256"] = record["attempts"][0]["artifact_sha256"]
    record["attempts"][0]["qa_pass"] = True
    record["attempts"][-1]["qa_pass"] = False
    record["initial_machine_pass"] = True

    with pytest.raises(DomainError, match="machine evaluation ledger"):
        validate_machine_ledger(protocol, sealed, canonical_json(value))


def test_guardrail_trace_cannot_be_swapped_between_d_and_e() -> None:
    protocol, sealed, ledger = _documents()
    value = json.loads(ledger)
    value["records"][4]["attempts"][1]["guardrail_decision"] = (
        "DISABLED_EVALUATION_ONLY"
    )

    with pytest.raises(DomainError, match="machine evaluation ledger"):
        validate_machine_ledger(protocol, sealed, canonical_json(value))


def test_blind_label_import_has_no_arm_input_or_machine_fields() -> None:
    protocol, sealed, ledger = _documents()
    labels = blind_labels(protocol, sealed, ledger)
    approval = label_approval_receipt(protocol, sealed, ledger, labels)
    receipt = json.loads(
        import_blind_labels(protocol, sealed, ledger, labels, approval)
    )

    assert receipt["status"] == "BLIND_LABELS_COMPLETE"
    assert receipt["labeled_artifact_count"] == 10
    assert receipt["evidence_class"] == "FORMAL_PENDING_EXTERNAL_AUTHORIZATION"
    assert receipt["formal_eligible"] is False

    value = json.loads(labels)
    value["labels"][0]["arm"] = "E_full_specstyle"
    with pytest.raises(DomainError, match="blind evaluation labels"):
        import_blind_labels(protocol, sealed, ledger, canonical_json(value), approval)


def test_missing_blind_label_is_reported_without_mapping_it_to_false() -> None:
    protocol, sealed, ledger = _documents()
    labels = blind_labels(protocol, sealed, ledger, omit_last=True)
    approval = label_approval_receipt(protocol, sealed, ledger, labels)
    receipt = json.loads(
        import_blind_labels(protocol, sealed, ledger, labels, approval)
    )

    assert receipt["status"] == "BLIND_LABELS_INCOMPLETE"
    expected = {
        item["blind_artifact_id"]
        for item in json.loads(ledger)["records"]
        if item["blind_artifact_id"] is not None
    }
    observed = {item["blind_artifact_id"] for item in json.loads(labels)["labels"]}
    assert receipt["missing_blind_artifact_ids"] == sorted(expected - observed)


@pytest.mark.parametrize(
    "leaking_id",
    ("blind-0-4", "input-001__A_single_pass", "E_full_specstyle-seed-2"),
)
def test_blind_artifact_ids_must_be_opaque_uuid4_tokens(leaking_id: str) -> None:
    protocol, sealed, ledger = _documents()
    value = json.loads(ledger)
    value["records"][0]["blind_artifact_id"] = leaking_id

    with pytest.raises(DomainError, match="machine evaluation ledger"):
        validate_machine_ledger(protocol, sealed, canonical_json(value))


def test_blind_randomization_receipt_binds_mapping_and_presentation_order() -> None:
    protocol, sealed, ledger = _documents()
    value = json.loads(ledger)
    value["blind_presentation_order"] = [
        item["blind_artifact_id"]
        for item in value["records"]
        if item["blind_artifact_id"] is not None
    ]
    value["blind_assignment_receipt"]["presentation_order_sha256"] = hashlib.sha256(
        canonical_json(value["blind_presentation_order"])
    ).hexdigest()

    with pytest.raises(DomainError, match="machine evaluation ledger"):
        validate_machine_ledger(protocol, sealed, canonical_json(value))


def test_synthetic_labels_are_permanently_test_only() -> None:
    protocol = protocol_document(evidence_class="TEST_ONLY")
    sealed = sealed_protocol(protocol)
    ledger = machine_ledger(protocol, sealed)
    labels = blind_labels(
        protocol,
        sealed,
        ledger,
        label_source="SYNTHETIC_TEST",
    )
    approval = label_approval_receipt(
        protocol,
        sealed,
        ledger,
        labels,
        label_source="SYNTHETIC_TEST",
    )
    receipt = json.loads(
        import_blind_labels(protocol, sealed, ledger, labels, approval)
    )

    assert receipt["evidence_class"] == "TEST_ONLY"
    assert receipt["formal_eligible"] is False


def test_label_approval_receipt_must_cross_bind_external_ledger() -> None:
    protocol, sealed, ledger = _documents()
    labels = blind_labels(protocol, sealed, ledger)
    approval = json.loads(label_approval_receipt(protocol, sealed, ledger, labels))
    approval["blind_labels_sha256"] = "f" * 64

    with pytest.raises(DomainError, match="label approval receipt"):
        import_blind_labels(protocol, sealed, ledger, labels, canonical_json(approval))
