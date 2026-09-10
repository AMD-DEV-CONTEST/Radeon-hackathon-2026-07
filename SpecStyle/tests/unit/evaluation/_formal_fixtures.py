"""Canonical formal-evaluation documents for unit tests."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid

from specstyle.calibration.evidence_io import canonical_json, evidence_sha256
from specstyle.evaluation.protocol import FORMAL_ARMS


def sha(character: str) -> str:
    return character * 64


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def blind_id() -> str:
    return f"blind-{uuid.uuid4().hex}"


def _strategy_contract(arm: str) -> str:
    characters = {
        "A_single_pass": "7",
        "B_random_retry": "8",
        "C_verifier_best_of_k": "9",
        "D_directed_no_guardrail": "a",
        "E_full_specstyle": "c",
    }
    return sha(characters[arm])


def protocol_document(*, evidence_class: str = "FORMAL") -> bytes:
    return canonical_json(
        {
            "schema_version": "specstyle.evaluation.five_arm_protocol.v1",
            "study_id": "repair-lift-heldout-v1",
            "evidence_class": evidence_class,
            "dataset_manifest_sha256": sha("1"),
            "input_ids": ["input-001", "input-002"],
            "generation_materials_sha256s": {
                "input-001": sha("1"),
                "input-002": sha("2"),
            },
            "initial_request_sha256s": {
                "input-001": sha("f"),
                "input-002": sha("f"),
            },
            "bindings": {
                "compiler_sha256": sha("2"),
                "final_qa_contract_sha256": sha("3"),
                "model_supply_sha256": sha("4"),
                "preprocessor_sha256": sha("5"),
                "production_context_sha256": sha("d"),
                "runtime_sha256": sha("6"),
                "threshold_profile_sha256": sha("e"),
            },
            "arms": list(FORMAL_ARMS),
            "budget": {
                "a_generations": 1,
                "max_generations_b_to_e": 3,
            },
            "seed_schedules": {
                "input-001": [101, 102, 103],
                "input-002": [201, 202, 203],
            },
            "strategies": {
                "a_strategy_contract_sha256": sha("7"),
                "b_strategy_contract_sha256": sha("8"),
                "c_strategy_contract_sha256": sha("9"),
                "c_tie_break": "lowest_seed_index",
                "c_utility_sha256": sha("b"),
                "d_guardrail_mode": "DISABLED_EVALUATION_ONLY",
                "d_strategy_contract_sha256": sha("a"),
                "e_guardrail_mode": "ENFORCED",
                "e_strategy_contract_sha256": sha("c"),
            },
            "blind": {
                "adjudication": "majority_boolean",
                "randomization_protocol_sha256": sha("a"),
                "minimum_raters_per_artifact": 1,
                "protocol_sha256": sha("b"),
            },
            "statistics": {
                "bootstrap_resamples": 1000,
                "bootstrap_seed": 44,
                "confidence_level": 0.95,
                "method": "paired_percentile_bootstrap_bonferroni",
                "minimum_effect": 0.05,
                "multiple_comparison": "bonferroni_six_one_sided",
                "noninferiority_margin": 0.02,
                "sample_size": 2,
            },
            "missingness_rule": "all_inputs_denominator_labels_required_for_artifacts",
        }
    )


def sealed_protocol(protocol: bytes) -> bytes:
    return canonical_json(
        {
            "schema_version": "specstyle.evaluation.sealed_protocol.v1",
            "production_approval_sha256": sha("d"),
            "production_context_sha256": sha("d"),
            "protocol_sha256": evidence_sha256(protocol).value,
            "repo_sha": sha("c"),
            "sealed_at": "2026-08-03T10:00:00Z",
            "threshold_profile_sha256": sha("e"),
            "trust_level": "LOCAL_PROCESS_ONLY",
        }
    )


def machine_ledger(protocol: bytes, sealed: bytes) -> bytes:
    records = []
    seeds = {"input-001": [101, 102, 103], "input-002": [201, 202, 203]}
    terminals = {
        ("input-001", "A_single_pass"): "REJECTED",
        ("input-002", "A_single_pass"): "REJECTED",
        ("input-002", "B_random_retry"): "MANUAL_REVIEW",
        ("input-002", "C_verifier_best_of_k"): "REJECTED",
    }
    for input_index, input_id in enumerate(("input-001", "input-002")):
        for arm_index, arm in enumerate(FORMAL_ARMS):
            terminal = terminals.get((input_id, arm), "APPROVED")
            count = (
                1
                if arm == "A_single_pass"
                else 3
                if arm == "C_verifier_best_of_k"
                or (arm == "B_random_retry" and terminal != "APPROVED")
                else 2
            )
            attempts = []
            for generation_index in range(count):
                if generation_index == 0:
                    seed = seeds[input_id][0]
                    seed_reason = "INITIAL"
                elif arm == "B_random_retry":
                    seed = seeds[input_id][generation_index]
                    seed_reason = "RANDOM_RETRY"
                elif arm == "C_verifier_best_of_k":
                    seed = seeds[input_id][generation_index]
                    seed_reason = "VERIFIER_CANDIDATE"
                else:
                    seed = seeds[input_id][0]
                    seed_reason = "FROZEN_REPAIR"
                artifact = digest(
                    f"artifact:{input_index}:{arm_index}:{generation_index}"
                )
                attempts.append(
                    {
                        "artifact_sha256": artifact,
                        "generation_index": generation_index,
                        "generation_materials_sha256": (
                            sha("1") if input_id == "input-001" else sha("2")
                        ),
                        "generation_status": "GENERATED",
                        "gpu_seconds": 10.0 + generation_index,
                        "guardrail_decision": (
                            "NOT_APPLICABLE"
                            if generation_index == 0
                            or arm
                            not in {
                                "D_directed_no_guardrail",
                                "E_full_specstyle",
                            }
                            else "DISABLED_EVALUATION_ONLY"
                            if arm == "D_directed_no_guardrail"
                            else "PASSED"
                        ),
                        "model_supply_sha256": sha("4"),
                        "qa_pass": terminal == "APPROVED"
                        and generation_index == count - 1,
                        "qa_result_sha256": digest(
                            f"qa:{input_index}:{arm_index}:{generation_index}"
                        ),
                        "repair_action_sha256": (
                            digest(
                                f"repair:{input_index}:{arm_index}:{generation_index}"
                            )
                            if generation_index > 0
                            and arm
                            in {
                                "D_directed_no_guardrail",
                                "E_full_specstyle",
                            }
                            else None
                        ),
                        "request_sha256": sha("f"),
                        "runtime_sha256": sha("6"),
                        "seed": seed,
                        "seed_reason": seed_reason,
                        "trigger_rule_ids": (
                            ["l2_style"]
                            if generation_index > 0
                            and arm
                            in {
                                "D_directed_no_guardrail",
                                "E_full_specstyle",
                            }
                            else []
                        ),
                        "utility_contract_sha256": (
                            sha("b") if arm == "C_verifier_best_of_k" else None
                        ),
                        "utility_result_sha256": (
                            digest(
                                f"utility:{input_index}:{arm_index}:{generation_index}"
                            )
                            if arm == "C_verifier_best_of_k"
                            else None
                        ),
                        "utility_score": (
                            float(generation_index + 1)
                            if arm == "C_verifier_best_of_k"
                            else None
                        ),
                    }
                )
            has_artifact = terminal != "FAILED"
            strategy_contract = _strategy_contract(arm)
            stop_reason = (
                "SINGLE_PASS_COMPLETE"
                if arm == "A_single_pass"
                else "BUDGET_EXHAUSTED"
                if arm == "C_verifier_best_of_k" or terminal != "APPROVED"
                else "QA_PASSED"
            )
            stop_evidence = digest(f"stop:{input_index}:{arm_index}:{stop_reason}")
            stop_event = {
                "generation_index": count - 1,
                "guardrail_decision": "NOT_APPLICABLE",
                "kind": stop_reason,
                "repair_action_sha256": None,
                "result_sha256": stop_evidence,
                "trigger_rule_ids": [],
            }
            strategy_material = {
                "arm": arm,
                "strategy_contract_sha256": strategy_contract,
                "attempts": attempts,
                "decision": {
                    "candidate_sha256": (
                        attempts[-1]["artifact_sha256"] if has_artifact else None
                    ),
                    "failure_reasons": (
                        [] if terminal == "APPROVED" else ["QA_NOT_PASSED"]
                    ),
                    "machine_terminal": terminal,
                    "stop_event": stop_event,
                },
            }
            records.append(
                {
                    "arm": arm,
                    "attempts": attempts,
                    "blind_artifact_id": (blind_id() if has_artifact else None),
                    "candidate_sha256": attempts[-1]["artifact_sha256"]
                    if has_artifact
                    else None,
                    "failure_reasons": []
                    if terminal == "APPROVED"
                    else ["QA_NOT_PASSED"],
                    "final_machine_pass": terminal == "APPROVED",
                    "final_qa_contract_sha256": sha("3"),
                    "generations_used": count,
                    "gpu_seconds": sum(item["gpu_seconds"] for item in attempts),
                    "initial_machine_pass": terminal == "APPROVED" and count == 1,
                    "input_id": input_id,
                    "machine_terminal": terminal,
                    "observed_at": "2026-08-03T10:01:00Z",
                    "stop_event": stop_event,
                    "strategy_contract_sha256": strategy_contract,
                    "strategy_trace_sha256": hashlib.sha256(
                        canonical_json(strategy_material)
                    ).hexdigest(),
                }
            )
    blind_records = [
        {
            "artifact_sha256": record["candidate_sha256"],
            "blind_artifact_id": record["blind_artifact_id"],
        }
        for record in records
        if record["blind_artifact_id"] is not None
    ]
    presentation_order = [item["blind_artifact_id"] for item in blind_records]
    if len(presentation_order) > 1:
        original = list(presentation_order)
        while presentation_order == original:
            secrets.SystemRandom().shuffle(presentation_order)
    mapping_sha256 = hashlib.sha256(canonical_json(blind_records)).hexdigest()
    presentation_sha256 = hashlib.sha256(canonical_json(presentation_order)).hexdigest()
    return canonical_json(
        {
            "blind_assignment_receipt": {
                "issued_at": "2026-08-03T10:02:00Z",
                "mapping_sha256": mapping_sha256,
                "presentation_order_sha256": presentation_sha256,
                "randomization_protocol_sha256": sha("a"),
                "randomizer_id": "external-blinding-service",
                "schema_version": "specstyle.evaluation.blind_assignment_receipt.v1",
                "trust_level": "UNVERIFIED_EXTERNAL_RANDOMIZER",
            },
            "blind_presentation_order": presentation_order,
            "schema_version": "specstyle.evaluation.machine_ledger.v1",
            "execution_trust": "UNVERIFIED_EXTERNAL_EXECUTOR",
            "sealed_protocol_sha256": evidence_sha256(sealed).value,
            "profile": "production",
            "records": records,
        }
    )


def blind_labels(
    protocol: bytes,
    sealed: bytes,
    ledger: bytes,
    *,
    label_source: str = "EXTERNAL_HUMAN",
    omit_last: bool = False,
) -> bytes:
    records = json.loads(ledger)["records"]
    labels = []
    for index, record in enumerate(records):
        blind_id = record["blind_artifact_id"]
        if blind_id is None:
            continue
        labels.append(
            {
                "blind_artifact_id": blind_id,
                "blind_protocol_sha256": sha("b"),
                "clarity_acceptable": True,
                "high_priority_degraded": index == 8,
                "overall_usable": index not in {0, 4},
                "rater_pseudonym": f"rater-{index}",
                "rework_minutes": 0.0 if index not in {0, 4} else 5.0,
                "style_faithful": index != 0,
                "subject_preserved": index != 4,
            }
        )
    labels.sort(key=lambda item: (item["blind_artifact_id"], item["rater_pseudonym"]))
    if omit_last:
        labels.pop()
    return canonical_json(
        {
            "schema_version": "specstyle.evaluation.blind_labels.v1",
            "blind_protocol_sha256": sha("b"),
            "label_source": label_source,
            "labels": labels,
            "machine_ledger_sha256": evidence_sha256(ledger).value,
            "sealed_protocol_sha256": evidence_sha256(sealed).value,
        }
    )


def label_approval_receipt(
    protocol: bytes,
    sealed: bytes,
    ledger: bytes,
    labels: bytes,
    *,
    label_source: str = "EXTERNAL_HUMAN",
) -> bytes:
    study_id = json.loads(protocol)["study_id"]
    return canonical_json(
        {
            "schema_version": "specstyle.evaluation.label_approval_receipt.v1",
            "approval_kind": "BLIND_HUMAN_LABELS",
            "approved": True,
            "approver_id": "independent-annotation-lead",
            "blind_labels_sha256": evidence_sha256(labels).value,
            "blind_protocol_sha256": sha("b"),
            "issued_at": "2026-08-03T11:00:00Z",
            "label_source": label_source,
            "machine_ledger_sha256": evidence_sha256(ledger).value,
            "receipt_id": "blind-labels-approved-v1",
            "sealed_protocol_sha256": evidence_sha256(sealed).value,
            "study_id": study_id,
            "trust_level": "LOCAL_ASSERTION_ONLY",
        }
    )
