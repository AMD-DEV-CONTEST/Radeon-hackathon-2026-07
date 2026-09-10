"""Formal paired statistics plus the legacy TEST_ONLY callback summary."""

from __future__ import annotations

import random
from dataclasses import dataclass
import math
from typing import Any

from specstyle.calibration.evidence_io import canonical_json, evidence_sha256
from specstyle.errors import DomainError
from specstyle.evaluation.arms import ArmResult
from specstyle.evaluation.evidence import (
    BlindHumanLabel,
    EvaluationEvidence,
    MachineArmRecord,
    load_blind_evidence,
)
from specstyle.evaluation.protocol import FORMAL_ARMS


@dataclass(frozen=True, slots=True)
class _HumanOutcome:
    usable: bool
    high_priority_degraded: bool
    style_faithful: bool
    subject_preserved: bool
    clarity_acceptable: bool
    rework_minutes: float


def _majority(labels: list[BlindHumanLabel], name: str) -> bool:
    return sum(bool(getattr(item, name)) for item in labels) > len(labels) // 2


def _human_outcomes(evidence: EvaluationEvidence) -> dict[str, _HumanOutcome]:
    grouped: dict[str, list[BlindHumanLabel]] = {}
    for label in evidence.labels:
        grouped.setdefault(label.blind_artifact_id, []).append(label)
    return {
        blind_id: _HumanOutcome(
            _majority(labels, "overall_usable"),
            _majority(labels, "high_priority_degraded"),
            _majority(labels, "style_faithful"),
            _majority(labels, "subject_preserved"),
            _majority(labels, "clarity_acceptable"),
            sum(item.rework_minutes for item in labels) / len(labels),
        )
        for blind_id, labels in grouped.items()
    }


def _record_outcome(
    record: MachineArmRecord, humans: dict[str, _HumanOutcome]
) -> _HumanOutcome | None:
    if record.blind_artifact_id is None:
        return None
    return humans[record.blind_artifact_id]


def _rate(count: int, denominator: int) -> float:
    return count / float(denominator)


def _arm_statistics(
    arm: str,
    records: list[MachineArmRecord],
    humans: dict[str, _HumanOutcome],
) -> dict[str, Any]:
    n = len(records)
    outcomes = [_record_outcome(item, humans) for item in records]
    approved = [item.terminal == "APPROVED" for item in records]
    usable = [item is not None and item.usable for item in outcomes]
    usable_approved = sum(a and u for a, u in zip(approved, usable, strict=True))
    approved_count = sum(approved)
    initial_failures = sum(not item.initial_machine_pass for item in records)
    repair_successes = sum(
        not item.initial_machine_pass and item.final_machine_pass for item in records
    )
    terminal = {
        name: sum(item.terminal == name for item in records)
        for name in ("APPROVED", "REJECTED", "MANUAL_REVIEW", "FAILED")
    }
    return {
        "arm": arm,
        "n_inputs": n,
        "blind_human_usable_and_approved_count": usable_approved,
        "human_usable_yield": _rate(usable_approved, n),
        "automation_coverage": _rate(approved_count, n),
        "approved_precision": (
            _rate(usable_approved, approved_count) if approved_count else None
        ),
        "false_accept_count": sum(
            a and not u for a, u in zip(approved, usable, strict=True)
        ),
        "false_reject_count": sum(
            not a and u for a, u in zip(approved, usable, strict=True)
        ),
        "initial_pass_rate": _rate(
            sum(item.initial_machine_pass for item in records), n
        ),
        "final_pass_rate": _rate(sum(item.final_machine_pass for item in records), n),
        "repair_success_rate": (
            _rate(repair_successes, initial_failures) if initial_failures else None
        ),
        "high_priority_degradation_rate": _rate(
            sum(item is None or item.high_priority_degraded for item in outcomes), n
        ),
        "style_faithful_rate": _rate(
            sum(item is not None and item.style_faithful for item in outcomes), n
        ),
        "subject_preserved_rate": _rate(
            sum(item is not None and item.subject_preserved for item in outcomes), n
        ),
        "clarity_acceptable_rate": _rate(
            sum(item is not None and item.clarity_acceptable for item in outcomes), n
        ),
        "mean_human_rework_minutes": _rate(
            sum(item.rework_minutes for item in outcomes if item is not None), n
        ),
        "mean_generations": _rate(sum(item.generations_used for item in records), n),
        "mean_gpu_seconds": _rate(sum(item.gpu_seconds for item in records), n),
        "missing_artifact_count": sum(item is None for item in outcomes),
        "terminal_distribution": terminal,
    }


def _paired_vectors(
    arm_records: dict[str, list[MachineArmRecord]],
    humans: dict[str, _HumanOutcome],
    arm: str,
) -> tuple[list[float], list[float]]:
    usable: list[float] = []
    degraded: list[float] = []
    for record in arm_records[arm]:
        human = _record_outcome(record, humans)
        usable.append(
            float(record.terminal == "APPROVED" and human is not None and human.usable)
        )
        degraded.append(float(human is None or human.high_priority_degraded))
    return usable, degraded


def _percentile(
    samples: list[float], probability: float, *, upper: bool = False
) -> float:
    ordered = sorted(samples)
    position = probability * (len(ordered) - 1)
    index = math.ceil(position) if upper else math.floor(position)
    return ordered[index]


def _bootstrap_indices(n: int, count: int, seed: int) -> list[tuple[int, ...]]:
    generator = random.Random(seed)
    return [tuple(generator.randrange(n) for _ in range(n)) for _ in range(count)]


def _paired_comparison(
    comparator: str,
    full: tuple[list[float], list[float]],
    baseline: tuple[list[float], list[float]],
    samples: list[tuple[int, ...]],
    confidence: float,
) -> dict[str, Any]:
    primary = [left - right for left, right in zip(full[0], baseline[0], strict=True)]
    degraded = [left - right for left, right in zip(full[1], baseline[1], strict=True)]
    primary_samples = [sum(primary[i] for i in draw) / len(draw) for draw in samples]
    degraded_samples = [sum(degraded[i] for i in draw) / len(draw) for draw in samples]
    two_sided_alpha = (1.0 - confidence) / 2.0
    simultaneous_alpha = (1.0 - confidence) / 6.0
    return {
        "comparator": comparator,
        "primary_effect": sum(primary) / len(primary),
        "primary_confidence_interval": [
            _percentile(primary_samples, two_sided_alpha),
            _percentile(primary_samples, 1.0 - two_sided_alpha, upper=True),
        ],
        "primary_simultaneous_lower_bound": _percentile(
            primary_samples, simultaneous_alpha
        ),
        "degradation_effect": sum(degraded) / len(degraded),
        "degradation_confidence_interval": [
            _percentile(degraded_samples, two_sided_alpha),
            _percentile(degraded_samples, 1.0 - two_sided_alpha, upper=True),
        ],
        "degradation_simultaneous_upper_bound": _percentile(
            degraded_samples, 1.0 - simultaneous_alpha, upper=True
        ),
    }


def _preregistered_criteria_met(
    comparisons: list[dict[str, Any]], minimum_effect: float, margin: float
) -> bool:
    return all(
        item["primary_simultaneous_lower_bound"] > minimum_effect
        and item["degradation_simultaneous_upper_bound"] < margin
        for item in comparisons
    )


def _comparisons(
    evidence: EvaluationEvidence,
    arm_records: dict[str, list[MachineArmRecord]],
    humans: dict[str, _HumanOutcome],
) -> tuple[list[dict[str, Any]], bool]:
    config = evidence.protocol["statistics"]
    samples = _bootstrap_indices(
        len(evidence.protocol["input_ids"]),
        config["bootstrap_resamples"],
        config["bootstrap_seed"],
    )
    full = _paired_vectors(arm_records, humans, FORMAL_ARMS[-1])
    results = [
        _paired_comparison(
            comparator,
            full,
            _paired_vectors(arm_records, humans, comparator),
            samples,
            config["confidence_level"],
        )
        for comparator in FORMAL_ARMS[1:4]
    ]
    criteria_met = _preregistered_criteria_met(
        results, config["minimum_effect"], config["noninferiority_margin"]
    )
    return results, criteria_met


def _incomplete_report(
    evidence: EvaluationEvidence,
    sealed_data: bytes,
    ledger_data: bytes,
    label_data: bytes,
    approval_data: bytes,
) -> bytes:
    return canonical_json(
        {
            "schema_version": "specstyle.evaluation.final_report.v1",
            "status": "INCOMPLETE",
            "evidence_class": (
                "TEST_ONLY"
                if evidence.protocol["evidence_class"] == "TEST_ONLY"
                else "UNVERIFIED"
            ),
            "formal_eligible": False,
            "main_metric_definition": "blind_human_usable_and_machine_approved/all_inputs",
            "repair_lift_conclusion": "NOT_EVALUATED",
            "input_count": len(evidence.protocol["input_ids"]),
            "missing_blind_artifact_ids": list(evidence.missing_blind_artifact_ids),
            "arms": [],
            "comparisons": [],
            "sealed_protocol_sha256": evidence_sha256(sealed_data).value,
            "machine_ledger_sha256": evidence_sha256(ledger_data).value,
            "blind_labels_sha256": evidence_sha256(label_data).value,
            "label_approval_receipt_sha256": evidence_sha256(approval_data).value,
        }
    )


def finalize_evaluation(
    protocol_data: bytes,
    sealed_data: bytes,
    ledger_data: bytes,
    label_data: bytes,
    approval_data: bytes,
    /,
) -> bytes:
    """Join machine and blinded labels, then apply preregistered paired tests."""
    evidence = load_blind_evidence(
        protocol_data,
        sealed_data,
        ledger_data,
        label_data,
        approval_data,
    )
    if evidence.missing_blind_artifact_ids:
        return _incomplete_report(
            evidence, sealed_data, ledger_data, label_data, approval_data
        )
    humans = _human_outcomes(evidence)
    arm_records = {
        arm: [item for item in evidence.records if item.arm == arm]
        for arm in FORMAL_ARMS
    }
    arms = [_arm_statistics(arm, arm_records[arm], humans) for arm in FORMAL_ARMS]
    comparisons, criteria_met = _comparisons(evidence, arm_records, humans)
    pending = (
        evidence.protocol["evidence_class"] == "FORMAL"
        and evidence.label_source == "EXTERNAL_HUMAN"
    )
    return canonical_json(
        {
            "schema_version": "specstyle.evaluation.final_report.v1",
            "status": (
                "FORMAL_PENDING_EXTERNAL_AUTHORIZATION" if pending else "TEST_ONLY"
            ),
            "evidence_class": (
                "FORMAL_PENDING_EXTERNAL_AUTHORIZATION" if pending else "TEST_ONLY"
            ),
            "formal_eligible": False,
            "main_metric_definition": "blind_human_usable_and_machine_approved/all_inputs",
            "repair_lift_conclusion": ("NOT_AUTHORIZED" if pending else "NOT_FORMAL"),
            "preregistered_criteria_met": criteria_met,
            "input_count": len(evidence.protocol["input_ids"]),
            "missing_blind_artifact_ids": [],
            "arms": arms,
            "comparisons": comparisons,
            "sealed_protocol_sha256": evidence_sha256(sealed_data).value,
            "machine_ledger_sha256": evidence_sha256(ledger_data).value,
            "blind_labels_sha256": evidence_sha256(label_data).value,
            "label_approval_receipt_sha256": evidence_sha256(approval_data).value,
        }
    )


@dataclass(frozen=True, slots=True)
class ArmStats:
    arm: str
    n_inputs: int
    usable_count: int
    human_usable_yield: float
    mean_generations: float
    yield_ci95: tuple[float, float]


def summarize_arm(
    result: ArmResult, *, bootstrap: int = 200, seed: int = 0
) -> ArmStats:
    if type(result) is not ArmResult:
        raise DomainError("invalid arm result")
    n = len(result.records)
    if n == 0:
        raise DomainError("empty arm result")
    usable = sum(1 for r in result.records if r.usable)
    hy = usable / float(n)
    gens = [r.generations_used for r in result.records]
    mean_g = sum(gens) / float(n)
    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(max(1, bootstrap)):
        picks = [result.records[rng.randrange(n)] for _ in range(n)]
        samples.append(sum(1 for p in picks if p.usable) / float(n))
    samples.sort()
    lo = samples[int(0.025 * (len(samples) - 1))]
    hi = samples[int(0.975 * (len(samples) - 1))]
    return ArmStats(result.arm, n, usable, hy, mean_g, (lo, hi))


def compare_arms(results: tuple[ArmResult, ...]) -> tuple[ArmStats, ...]:
    if type(results) is not tuple or not results:
        raise DomainError("empty results")
    return tuple(summarize_arm(r, seed=i) for i, r in enumerate(results))
