"""Machine and blinded-human evidence contracts for formal evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import re
from typing import Any

from specstyle.calibration.evidence_io import (
    _exact,
    _float,
    _load_canonical,
    _sha,
    _text,
    canonical_json,
    evidence_sha256,
)
from specstyle.errors import DomainError
from specstyle.evaluation.blind_assignment import validate_blind_assignment
from specstyle.evaluation.protocol import (
    FORMAL_ARMS,
    load_protocol,
    load_sealed_protocol,
)
from specstyle.evaluation.stop_contract import parse_stop_event, validate_stopping

_ATTEMPT_KEYS = {
    "artifact_sha256",
    "generation_index",
    "generation_materials_sha256",
    "generation_status",
    "gpu_seconds",
    "guardrail_decision",
    "model_supply_sha256",
    "qa_pass",
    "qa_result_sha256",
    "repair_action_sha256",
    "request_sha256",
    "runtime_sha256",
    "seed",
    "seed_reason",
    "trigger_rule_ids",
    "utility_contract_sha256",
    "utility_result_sha256",
    "utility_score",
}
_RECORD_KEYS = {
    "arm",
    "attempts",
    "blind_artifact_id",
    "candidate_sha256",
    "failure_reasons",
    "final_machine_pass",
    "final_qa_contract_sha256",
    "generations_used",
    "gpu_seconds",
    "initial_machine_pass",
    "input_id",
    "machine_terminal",
    "observed_at",
    "stop_event",
    "strategy_contract_sha256",
    "strategy_trace_sha256",
}
_LABEL_KEYS = {
    "blind_artifact_id",
    "blind_protocol_sha256",
    "clarity_acceptable",
    "high_priority_degraded",
    "overall_usable",
    "rater_pseudonym",
    "rework_minutes",
    "style_faithful",
    "subject_preserved",
}
_TERMINALS = {"APPROVED", "REJECTED", "MANUAL_REVIEW", "FAILED"}
_BLIND_ID = re.compile(r"blind-[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}", re.ASCII)


@dataclass(frozen=True, slots=True)
class MachineArmRecord:
    input_id: str
    arm: str
    terminal: str
    candidate_sha256: str | None
    blind_artifact_id: str | None
    generations_used: int
    gpu_seconds: float
    initial_machine_pass: bool
    final_machine_pass: bool


@dataclass(frozen=True, slots=True)
class BlindHumanLabel:
    blind_artifact_id: str
    rater_pseudonym: str
    style_faithful: bool
    subject_preserved: bool
    clarity_acceptable: bool
    overall_usable: bool
    high_priority_degraded: bool
    rework_minutes: float


@dataclass(frozen=True, slots=True)
class EvaluationEvidence:
    protocol: dict[str, Any]
    sealed: dict[str, Any]
    records: tuple[MachineArmRecord, ...]
    latest_observed_at: datetime
    labels: tuple[BlindHumanLabel, ...] = ()
    label_source: str | None = None
    missing_blind_artifact_ids: tuple[str, ...] = ()
    label_approval_receipt_sha256: str | None = None


def _timestamp(value: object, name: str) -> datetime:
    text = _text(value, name)
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise DomainError(f"invalid {name}") from None
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != text:
        raise DomainError(f"invalid {name}")
    return parsed


def _nonnegative_float(value: object, name: str) -> float:
    result = _float(value, name)
    if result < 0.0:
        raise DomainError(f"invalid {name}")
    return result


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or isinstance(value, bool) or value < minimum:
        raise DomainError(f"invalid {name}")
    return value


def _optional_sha(value: object, name: str) -> str | None:
    return None if value is None else _sha(value, name)


def _failure_reasons(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise DomainError("invalid machine evaluation ledger")
    reasons = tuple(_text(item, "machine failure reason") for item in value)
    if len(set(reasons)) != len(reasons):
        raise DomainError("invalid machine evaluation ledger")
    return reasons


def _rule_ids(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise DomainError("invalid machine evaluation ledger")
    rules = tuple(_text(item, "trigger rule id") for item in value)
    if len(set(rules)) != len(rules):
        raise DomainError("invalid machine evaluation ledger")
    return rules


def _validate_attempt_strategy(
    attempt: dict[str, Any], arm: str, index: int, utility_contract: str
) -> None:
    rules = _rule_ids(attempt["trigger_rule_ids"])
    action = _optional_sha(attempt["repair_action_sha256"], "repair action sha256")
    utility_result = _optional_sha(
        attempt["utility_result_sha256"], "utility result sha256"
    )
    utility_binding = _optional_sha(
        attempt["utility_contract_sha256"], "utility contract sha256"
    )
    utility = attempt["utility_score"]
    generated = attempt["generation_status"] == "GENERATED"
    if arm == FORMAL_ARMS[2] and generated:
        if (
            utility_binding != utility_contract
            or utility_result is None
            or type(utility) is not float
            or not math.isfinite(utility)
        ):
            raise DomainError("invalid machine evaluation ledger")
    elif (
        utility is not None or utility_result is not None or utility_binding is not None
    ):
        raise DomainError("invalid machine evaluation ledger")
    if index == 0 or arm in FORMAL_ARMS[:3]:
        expected = ((), None, "NOT_APPLICABLE")
    elif arm == FORMAL_ARMS[3]:
        expected = (rules, action, "DISABLED_EVALUATION_ONLY")
    else:
        expected = (rules, action, "PASSED")
    if (rules, action, attempt["guardrail_decision"]) != expected or (
        index > 0 and arm in FORMAL_ARMS[3:] and (not rules or action is None)
    ):
        raise DomainError("invalid machine evaluation ledger")


def _attempts(
    values: object,
    *,
    arm: str,
    seeds: list[int],
    initial_request_sha256: str,
    generation_materials_sha256: str,
    model_sha256: str,
    runtime_sha256: str,
    utility_contract_sha256: str,
) -> tuple[dict[str, Any], ...]:
    if type(values) is not list or not values or len(values) > len(seeds):
        raise DomainError("invalid machine evaluation ledger")
    parsed: list[dict[str, Any]] = []
    current_seed = seeds[0]
    next_seed = 1
    for index, value in enumerate(values):
        attempt = _exact(value, _ATTEMPT_KEYS, "machine generation attempt")
        gpu_seconds = _nonnegative_float(attempt["gpu_seconds"], "attempt GPU seconds")
        expected_seed, next_seed = _expected_seed(
            arm, index, attempt["seed_reason"], seeds, current_seed, next_seed
        )
        current_seed = expected_seed
        if (
            _integer(attempt["generation_index"], "generation index") != index
            or _integer(attempt["seed"], "generation seed") != expected_seed
            or _sha(attempt["model_supply_sha256"], "model supply sha256")
            != model_sha256
            or _sha(attempt["runtime_sha256"], "runtime sha256") != runtime_sha256
            or _sha(
                attempt["generation_materials_sha256"],
                "generation materials sha256",
            )
            != generation_materials_sha256
            or type(attempt["qa_pass"]) is not bool
        ):
            raise DomainError("invalid machine evaluation ledger")
        _sha(attempt["request_sha256"], "generation request sha256")
        if index == 0 and attempt["request_sha256"] != initial_request_sha256:
            raise DomainError("invalid machine evaluation ledger")
        artifact = _optional_sha(attempt["artifact_sha256"], "attempt artifact sha256")
        qa_result = _optional_sha(attempt["qa_result_sha256"], "QA result sha256")
        generated = attempt["generation_status"] == "GENERATED"
        if attempt["generation_status"] not in {"GENERATED", "GENERATION_FAILED"} or (
            generated != (artifact is not None and qa_result is not None)
        ):
            raise DomainError("invalid machine evaluation ledger")
        if not generated and attempt["qa_pass"]:
            raise DomainError("invalid machine evaluation ledger")
        _validate_attempt_strategy(attempt, arm, index, utility_contract_sha256)
        parsed.append({**attempt, "gpu_seconds": gpu_seconds})
    return tuple(parsed)


def _expected_seed(
    arm: str,
    index: int,
    reason: object,
    seeds: list[int],
    current_seed: int,
    next_seed: int,
) -> tuple[int, int]:
    if index == 0:
        if reason != "INITIAL":
            raise DomainError("invalid machine evaluation ledger")
        return seeds[0], next_seed
    if arm == "B_random_retry":
        if reason != "RANDOM_RETRY":
            raise DomainError("invalid machine evaluation ledger")
        return seeds[index], next_seed
    if arm == "C_verifier_best_of_k":
        if reason != "VERIFIER_CANDIDATE":
            raise DomainError("invalid machine evaluation ledger")
        return seeds[index], next_seed
    if arm in {"D_directed_no_guardrail", "E_full_specstyle"}:
        if reason == "FROZEN_REPAIR":
            return current_seed, next_seed
        if reason == "SAMPLING_DEFECT_RETRY" and next_seed < len(seeds):
            return seeds[next_seed], next_seed + 1
    raise DomainError("invalid machine evaluation ledger")


def _validate_terminal(
    raw: dict[str, Any],
    attempts: tuple[dict[str, Any], ...],
    reasons: tuple[str, ...],
) -> tuple[str | None, str | None]:
    terminal = raw["machine_terminal"]
    candidate = _optional_sha(raw["candidate_sha256"], "candidate sha256")
    blind_id = (
        None
        if raw["blind_artifact_id"] is None
        else _text(raw["blind_artifact_id"], "blind artifact id")
    )
    if blind_id is not None and _BLIND_ID.fullmatch(blind_id) is None:
        raise DomainError("invalid machine evaluation ledger")
    final_pass = raw["final_machine_pass"]
    if type(final_pass) is not bool or type(raw["initial_machine_pass"]) is not bool:
        raise DomainError("invalid machine evaluation ledger")
    artifact_hashes = {
        item["artifact_sha256"]
        for item in attempts
        if item["artifact_sha256"] is not None
    }
    approved = terminal == "APPROVED"
    selected = next(
        (item for item in attempts if item["artifact_sha256"] == candidate), None
    )
    if (
        terminal not in _TERMINALS
        or final_pass is not approved
        or (candidate is None) != (blind_id is None)
        or (candidate is not None and candidate not in artifact_hashes)
        or ((not artifact_hashes) != (terminal == "FAILED"))
        or ((candidate is None) != (not artifact_hashes))
        or (candidate is not None and selected is None)
        or (selected is not None and selected["qa_pass"] is not approved)
        or (approved and reasons)
        or (not approved and not reasons)
        or raw["initial_machine_pass"] is not attempts[0]["qa_pass"]
    ):
        raise DomainError("invalid machine evaluation ledger")
    return candidate, blind_id


def _strategy_contract(protocol: dict[str, Any], arm: str) -> str:
    names = {
        FORMAL_ARMS[0]: "a_strategy_contract_sha256",
        FORMAL_ARMS[1]: "b_strategy_contract_sha256",
        FORMAL_ARMS[2]: "c_strategy_contract_sha256",
        FORMAL_ARMS[3]: "d_strategy_contract_sha256",
        FORMAL_ARMS[4]: "e_strategy_contract_sha256",
    }
    return protocol["strategies"][names[arm]]


def _strategy_trace_sha256(
    arm: str,
    strategy_contract: str,
    attempts: tuple[dict[str, Any], ...],
    decision: dict[str, object],
) -> str:
    return evidence_sha256(
        canonical_json(
            {
                "arm": arm,
                "strategy_contract_sha256": strategy_contract,
                "attempts": list(attempts),
                "decision": decision,
            }
        )
    ).value


def _machine_record(
    value: object,
    *,
    input_id: str,
    arm: str,
    protocol: dict[str, Any],
    sealed_at: datetime,
) -> MachineArmRecord:
    raw = _exact(value, _RECORD_KEYS, "machine arm record")
    bindings = protocol["bindings"]
    strategy_contract = _strategy_contract(protocol, arm)
    attempts = _attempts(
        raw["attempts"],
        arm=arm,
        seeds=protocol["seed_schedules"][input_id],
        initial_request_sha256=protocol["initial_request_sha256s"][input_id],
        generation_materials_sha256=protocol["generation_materials_sha256s"][input_id],
        model_sha256=bindings["model_supply_sha256"],
        runtime_sha256=bindings["runtime_sha256"],
        utility_contract_sha256=protocol["strategies"]["c_utility_sha256"],
    )
    reasons = _failure_reasons(raw["failure_reasons"])
    candidate, blind_id = _validate_terminal(raw, attempts, reasons)
    stop_event = parse_stop_event(raw["stop_event"], attempts)
    decision = {
        "candidate_sha256": candidate,
        "failure_reasons": list(reasons),
        "machine_terminal": raw["machine_terminal"],
        "stop_event": stop_event,
    }
    generations = _integer(raw["generations_used"], "generations used", minimum=1)
    gpu_seconds = _nonnegative_float(raw["gpu_seconds"], "record GPU seconds")
    if (
        raw["input_id"] != input_id
        or raw["arm"] != arm
        or generations != len(attempts)
        or generations > protocol["budget"]["max_generations_b_to_e"]
        or not math.isclose(
            gpu_seconds,
            sum(item["gpu_seconds"] for item in attempts),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        or raw["final_qa_contract_sha256"] != bindings["final_qa_contract_sha256"]
        or _timestamp(raw["observed_at"], "machine observation time") < sealed_at
        or raw["strategy_contract_sha256"] != strategy_contract
        or raw["strategy_trace_sha256"]
        != _strategy_trace_sha256(arm, strategy_contract, attempts, decision)
    ):
        raise DomainError("invalid machine evaluation ledger")
    validate_stopping(
        arm,
        attempts,
        candidate,
        protocol["budget"]["max_generations_b_to_e"],
        stop_event,
    )
    return MachineArmRecord(
        input_id,
        arm,
        raw["machine_terminal"],
        candidate,
        blind_id,
        generations,
        gpu_seconds,
        raw["initial_machine_pass"],
        raw["final_machine_pass"],
    )


def load_machine_evidence(
    protocol_data: bytes, sealed_data: bytes, ledger_data: bytes, /
) -> EvaluationEvidence:
    """Parse a complete Production-only input-by-arm machine matrix."""
    try:
        protocol = load_protocol(protocol_data)
        sealed = load_sealed_protocol(sealed_data)
        if sealed["protocol_sha256"] != evidence_sha256(protocol_data).value:
            raise DomainError("invalid machine evaluation ledger")
        ledger = _exact(
            _load_canonical(ledger_data),
            {
                "blind_assignment_receipt",
                "blind_presentation_order",
                "schema_version",
                "sealed_protocol_sha256",
                "profile",
                "records",
                "execution_trust",
            },
            "machine evaluation ledger",
        )
        expected = [
            (item, arm) for item in protocol["input_ids"] for arm in FORMAL_ARMS
        ]
        if (
            ledger["schema_version"] != "specstyle.evaluation.machine_ledger.v1"
            or ledger["sealed_protocol_sha256"] != evidence_sha256(sealed_data).value
            or ledger["profile"] != "production"
            or ledger["execution_trust"] != "UNVERIFIED_EXTERNAL_EXECUTOR"
            or type(ledger["records"]) is not list
            or len(ledger["records"]) != len(expected)
            or sealed["production_context_sha256"]
            != protocol["bindings"]["production_context_sha256"]
            or sealed["threshold_profile_sha256"]
            != protocol["bindings"]["threshold_profile_sha256"]
        ):
            raise DomainError("invalid machine evaluation ledger")
        sealed_at = _timestamp(sealed["sealed_at"], "protocol seal time")
        latest_observed_at = max(
            _timestamp(value["observed_at"], "machine observation time")
            for value in ledger["records"]
        )
        records = tuple(
            _machine_record(
                value,
                input_id=input_id,
                arm=arm,
                protocol=protocol,
                sealed_at=sealed_at,
            )
            for value, (input_id, arm) in zip(ledger["records"], expected, strict=True)
        )
        blind_ids = [
            item.blind_artifact_id for item in records if item.blind_artifact_id
        ]
        if len(set(blind_ids)) != len(blind_ids):
            raise DomainError("invalid machine evaluation ledger")
        assignments = tuple(
            (item.candidate_sha256, item.blind_artifact_id)
            for item in records
            if item.candidate_sha256 is not None and item.blind_artifact_id is not None
        )
        validate_blind_assignment(ledger, protocol, assignments, latest_observed_at)
    except (DomainError, KeyError, TypeError):
        raise DomainError("invalid machine evaluation ledger") from None
    return EvaluationEvidence(protocol, sealed, records, latest_observed_at)


def validate_machine_ledger(
    protocol_data: bytes, sealed_data: bytes, ledger_data: bytes, /
) -> bytes:
    """Return a canonical validation receipt without importing human labels."""
    evidence = load_machine_evidence(protocol_data, sealed_data, ledger_data)
    return canonical_json(
        {
            "schema_version": "specstyle.evaluation.machine_validation.v1",
            "status": "STRUCTURALLY_VALIDATED_AWAITING_BLIND_LABELS",
            "evidence_class": "UNVERIFIED",
            "formal_eligible": False,
            "input_count": len(evidence.protocol["input_ids"]),
            "record_count": len(evidence.records),
            "missing_artifact_count": sum(
                item.candidate_sha256 is None for item in evidence.records
            ),
            "machine_ledger_sha256": evidence_sha256(ledger_data).value,
            "sealed_protocol_sha256": evidence_sha256(sealed_data).value,
            "blind_assignment_trust": "UNVERIFIED_EXTERNAL_RANDOMIZER",
            "blind_assignment_receipt_sha256": evidence_sha256(
                canonical_json(_load_canonical(ledger_data)["blind_assignment_receipt"])
            ).value,
        }
    )


def _blind_label(value: object) -> BlindHumanLabel:
    raw = _exact(value, _LABEL_KEYS, "blind evaluation label")
    boolean_keys = _LABEL_KEYS - {
        "blind_artifact_id",
        "blind_protocol_sha256",
        "rater_pseudonym",
        "rework_minutes",
    }
    if any(type(raw[name]) is not bool for name in boolean_keys):
        raise DomainError("invalid blind evaluation labels")
    blind_id = _text(raw["blind_artifact_id"], "blind artifact id")
    if _BLIND_ID.fullmatch(blind_id) is None:
        raise DomainError("invalid blind evaluation labels")
    return BlindHumanLabel(
        blind_id,
        _text(raw["rater_pseudonym"], "rater pseudonym"),
        raw["style_faithful"],
        raw["subject_preserved"],
        raw["clarity_acceptable"],
        raw["overall_usable"],
        raw["high_priority_degraded"],
        _nonnegative_float(raw["rework_minutes"], "human rework minutes"),
    )


def _approval_receipt(
    data: bytes,
    *,
    machine: EvaluationEvidence,
    sealed_data: bytes,
    ledger_data: bytes,
    label_data: bytes,
    raters: set[str],
) -> dict[str, Any]:
    keys = {
        "schema_version",
        "approval_kind",
        "approved",
        "approver_id",
        "blind_labels_sha256",
        "blind_protocol_sha256",
        "issued_at",
        "label_source",
        "machine_ledger_sha256",
        "receipt_id",
        "sealed_protocol_sha256",
        "study_id",
        "trust_level",
    }
    try:
        raw = _exact(_load_canonical(data), keys, "label approval receipt")
        approver = _text(raw["approver_id"], "label approver id")
        if (
            raw["schema_version"] != "specstyle.evaluation.label_approval_receipt.v1"
            or raw["approval_kind"] != "BLIND_HUMAN_LABELS"
            or raw["approved"] is not True
            or raw["label_source"] not in {"EXTERNAL_HUMAN", "SYNTHETIC_TEST"}
            or raw["study_id"] != machine.protocol["study_id"]
            or raw["blind_protocol_sha256"]
            != machine.protocol["blind"]["protocol_sha256"]
            or raw["blind_labels_sha256"] != evidence_sha256(label_data).value
            or raw["machine_ledger_sha256"] != evidence_sha256(ledger_data).value
            or raw["sealed_protocol_sha256"] != evidence_sha256(sealed_data).value
            or raw["trust_level"] != "LOCAL_ASSERTION_ONLY"
            or _timestamp(raw["issued_at"], "label approval time")
            < machine.latest_observed_at
            or approver in raters
        ):
            raise DomainError("invalid label approval receipt")
        _text(raw["receipt_id"], "label approval receipt id")
    except (DomainError, KeyError, TypeError):
        raise DomainError("invalid label approval receipt") from None
    return raw


def load_blind_evidence(
    protocol_data: bytes,
    sealed_data: bytes,
    ledger_data: bytes,
    label_data: bytes,
    approval_data: bytes,
    /,
) -> EvaluationEvidence:
    """Validate external blind labels without exposing arm or input fields."""
    machine = load_machine_evidence(protocol_data, sealed_data, ledger_data)
    try:
        raw = _exact(
            _load_canonical(label_data),
            {
                "schema_version",
                "blind_protocol_sha256",
                "label_source",
                "labels",
                "machine_ledger_sha256",
                "sealed_protocol_sha256",
            },
            "blind evaluation labels",
        )
        if (
            raw["schema_version"] != "specstyle.evaluation.blind_labels.v1"
            or raw["label_source"] not in {"EXTERNAL_HUMAN", "SYNTHETIC_TEST"}
            or raw["blind_protocol_sha256"]
            != machine.protocol["blind"]["protocol_sha256"]
            or raw["machine_ledger_sha256"] != evidence_sha256(ledger_data).value
            or raw["sealed_protocol_sha256"] != evidence_sha256(sealed_data).value
            or type(raw["labels"]) is not list
        ):
            raise DomainError("invalid blind evaluation labels")
        labels = tuple(_blind_label(item) for item in raw["labels"])
        if any(
            item["blind_protocol_sha256"]
            != machine.protocol["blind"]["protocol_sha256"]
            for item in raw["labels"]
        ):
            raise DomainError("invalid blind evaluation labels")
        pairs = [(item.blind_artifact_id, item.rater_pseudonym) for item in labels]
        if pairs != sorted(pairs) or len(set(pairs)) != len(pairs):
            raise DomainError("invalid blind evaluation labels")
        expected = {
            item.blind_artifact_id
            for item in machine.records
            if item.blind_artifact_id is not None
        }
        observed = {item.blind_artifact_id for item in labels}
        if not observed <= expected:
            raise DomainError("invalid blind evaluation labels")
        minimum = machine.protocol["blind"]["minimum_raters_per_artifact"]
        counts = {
            item: sum(label.blind_artifact_id == item for label in labels)
            for item in observed
        }
        if any(count < minimum or count % 2 == 0 for count in counts.values()):
            raise DomainError("invalid blind evaluation labels")
    except (DomainError, KeyError, TypeError):
        raise DomainError("invalid blind evaluation labels") from None
    approval = _approval_receipt(
        approval_data,
        machine=machine,
        sealed_data=sealed_data,
        ledger_data=ledger_data,
        label_data=label_data,
        raters={item.rater_pseudonym for item in labels},
    )
    if approval["label_source"] != raw["label_source"]:
        raise DomainError("invalid label approval receipt")
    missing = tuple(sorted(expected - observed))
    return EvaluationEvidence(
        machine.protocol,
        machine.sealed,
        machine.records,
        machine.latest_observed_at,
        labels,
        raw["label_source"],
        missing,
        evidence_sha256(approval_data).value,
    )


def import_blind_labels(
    protocol_data: bytes,
    sealed_data: bytes,
    ledger_data: bytes,
    label_data: bytes,
    approval_data: bytes,
    /,
) -> bytes:
    """Return a receipt that never promotes synthetic labels to formal evidence."""
    evidence = load_blind_evidence(
        protocol_data,
        sealed_data,
        ledger_data,
        label_data,
        approval_data,
    )
    complete = not evidence.missing_blind_artifact_ids
    pending = (
        complete
        and evidence.protocol["evidence_class"] == "FORMAL"
        and evidence.label_source == "EXTERNAL_HUMAN"
    )
    evidence_class = "FORMAL_PENDING_EXTERNAL_AUTHORIZATION" if pending else "TEST_ONLY"
    return canonical_json(
        {
            "schema_version": "specstyle.evaluation.label_import.v1",
            "status": (
                "BLIND_LABELS_COMPLETE" if complete else "BLIND_LABELS_INCOMPLETE"
            ),
            "evidence_class": evidence_class,
            "formal_eligible": False,
            "labeled_artifact_count": len(
                {item.blind_artifact_id for item in evidence.labels}
            ),
            "missing_blind_artifact_ids": list(evidence.missing_blind_artifact_ids),
            "blind_labels_sha256": evidence_sha256(label_data).value,
            "label_approval_receipt_sha256": evidence_sha256(approval_data).value,
            "machine_ledger_sha256": evidence_sha256(ledger_data).value,
            "sealed_protocol_sha256": evidence_sha256(sealed_data).value,
        }
    )
