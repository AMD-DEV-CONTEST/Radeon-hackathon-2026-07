"""Held-out metric evidence with target-cell and cohort binding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from specstyle.calibration.evidence_io import (
    _count,
    _exact,
    _float,
    _load_canonical,
    _sha,
    _text,
    canonical_json,
    evidence_sha256,
)
from specstyle.calibration.formal_evidence_schema import (
    _BATCH_KEYS,
    _ITEM_KEYS,
    _MEMBER_KEYS,
    _OBSERVATION_KEYS,
    _PLAN_KEYS,
    _PREPARED_KEYS,
    _SPLITS,
    _pin_value,
)
from specstyle.calibration.splits import assign_split
from specstyle.calibration.target_cell import TargetCell, TargetMetric, load_target_cell
from specstyle.calibration.threshold_search import (
    ScoredPair,
    binary_rates,
    freeze_threshold,
    select_threshold_on_calibration,
)
from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes


@dataclass(frozen=True, slots=True)
class _Study:
    raw: dict[str, Any]
    digest: Sha256
    metric: TargetMetric


@dataclass(frozen=True, slots=True)
class _Manifest:
    digest: Sha256
    by_split: dict[str, tuple[dict[str, Any], ...]]


@dataclass(frozen=True, slots=True)
class _Observations:
    digest: Sha256
    pairs: tuple[ScoredPair, ...]


def _study(data: bytes, target: TargetCell) -> _Study:
    raw = _exact(_load_canonical(data), _PLAN_KEYS, "formal study plan")
    metric_id = _text(raw["metric_id"], "formal metric id")
    metric = target.require_metric(metric_id)
    targets = _exact(raw["targets"], {"min_tpr", "max_fpr"}, "formal targets")
    split = _exact(
        raw["split"],
        {
            "algorithm",
            "salt",
            "minimum_positive_per_split",
            "minimum_negative_per_split",
        },
        "formal split",
    )
    if (
        raw["schema_version"] != "specstyle.calibration.study_plan.v2"
        or raw["target_cell_sha256"] != target.sha256.value
        or raw["layer"] != metric.layer
        or raw["observation_unit"] != metric.observation_unit
        or raw["operator"] != metric.operator
        or split["algorithm"] != "sha256_mod_60_20_20"
    ):
        raise DomainError("formal study plan mismatch")
    _text(raw["study_id"], "formal study id")
    _text(split["salt"], "formal split salt")
    _count(split["minimum_positive_per_split"], "minimum positives", minimum=1)
    _count(split["minimum_negative_per_split"], "minimum negatives", minimum=1)
    min_tpr = _float(targets["min_tpr"], "minimum tpr")
    max_fpr = _float(targets["max_fpr"], "maximum fpr")
    if not 0.0 <= min_tpr <= 1.0 or not 0.0 <= max_fpr <= 1.0:
        raise DomainError("invalid formal targets")
    _sha(raw["annotation_protocol_sha256"], "annotation protocol sha256")
    return _Study(raw, evidence_sha256(data), metric)


def _protocol(data: bytes, target: TargetCell, study: _Study) -> None:
    raw = _exact(
        _load_canonical(data),
        {
            "schema_version",
            "protocol_id",
            "target_cell_sha256",
            "observation_unit",
            "metric_id",
            "label_definition",
        },
        "formal annotation protocol",
    )
    if (
        raw["schema_version"] != "specstyle.annotation_protocol.v2"
        or raw["target_cell_sha256"] != target.sha256.value
        or raw["observation_unit"] != study.metric.observation_unit
        or raw["metric_id"] != study.metric.metric_id.value
        or evidence_sha256(data).value != study.raw["annotation_protocol_sha256"]
    ):
        raise DomainError("formal annotation protocol mismatch")
    _text(raw["protocol_id"], "formal protocol id")
    _text(raw["label_definition"], "formal label definition")


def _member(value: object) -> dict[str, Any]:
    raw = _exact(value, _MEMBER_KEYS, "formal cohort member")
    _text(raw["member_id"], "formal cohort member id")
    for key in ("candidate_sha256", "source_family_sha256", "reference_family_sha256"):
        _sha(raw[key], key)
    _count(raw["seed"], "formal cohort seed")
    return raw


def _cohort(
    sample: dict[str, Any],
) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    expected = _count(sample["expected_count"], "formal cohort count", minimum=2)
    if type(sample["members"]) is not list:
        raise DomainError("invalid formal cohort")
    members = tuple(_member(item) for item in sample["members"])
    member_ids = tuple(item["member_id"] for item in members)
    candidates = tuple(item["candidate_sha256"] for item in members)
    if (
        len(members) != expected
        or len(set(member_ids)) != expected
        or len(set(candidates)) != expected
        or evidence_sha256(
            canonical_json({"expected_count": expected, "members": list(members)})
        ).value
        != sample["cohort_sha256"]
    ):
        raise DomainError("formal cohort binding mismatch")
    families = tuple(
        value
        for item in members
        for value in (item["source_family_sha256"], item["reference_family_sha256"])
    )
    return (
        _sha(sample["cohort_sha256"], "formal cohort sha256"),
        families,
        candidates,
        member_ids,
    )


def _sample(
    value: object, unit: str
) -> tuple[dict[str, Any], str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    raw = _exact(value, _BATCH_KEYS if unit == "batch" else _ITEM_KEYS, "formal sample")
    _text(raw["sample_id"], "formal sample id")
    for key in (
        "isolation_group_sha256",
        "annotation_record_sha256",
        "provenance_record_sha256",
    ):
        _sha(raw[key], key)
    if unit == "batch":
        binding, families, candidates, member_ids = _cohort(raw)
    else:
        binding = _sha(raw["candidate_sha256"], "formal candidate sha256")
        candidates = (binding,)
        member_ids = ()
        families = (
            _sha(raw["source_family_sha256"], "formal source family"),
            _sha(raw["reference_family_sha256"], "formal reference family"),
        )
    return raw, binding, families, candidates, member_ids


def _manifest(data: bytes, target: TargetCell, study: _Study) -> _Manifest:
    raw = _exact(
        _load_canonical(data),
        {
            "schema_version",
            "target_cell_sha256",
            "study_plan_sha256",
            "observation_unit",
            "samples",
        },
        "formal sample manifest",
    )
    if (
        raw["schema_version"] != "specstyle.calibration.sample_manifest.v2"
        or raw["target_cell_sha256"] != target.sha256.value
        or raw["study_plan_sha256"] != study.digest.value
        or raw["observation_unit"] != study.metric.observation_unit
        or type(raw["samples"]) is not list
        or not raw["samples"]
    ):
        raise DomainError("formal sample manifest mismatch")
    return _partition_samples(raw["samples"], study)


def _partition_samples(values: list[object], study: _Study) -> _Manifest:
    by_split: dict[str, list[dict[str, Any]]] = {name: [] for name in _SPLITS}
    seen_ids: set[str] = set()
    seen_bindings: set[str] = set()
    group_splits: dict[str, str] = {}
    family_splits: dict[str, str] = {}
    candidate_splits: dict[str, str] = {}
    member_splits: dict[str, str] = {}
    for value in values:
        sample, binding, families, candidates, member_ids = _sample(
            value, study.metric.observation_unit
        )
        split = sample["split"]
        group = sample["isolation_group_sha256"]
        expected = assign_split(Sha256(group), study.raw["split"]["salt"])
        if split != expected or split not in by_split:
            raise DomainError("formal sample split assignment mismatch")
        _unique_split(group_splits, group, split, "isolation group split leakage")
        for family in families:
            _unique_split(family_splits, family, split, "family split leakage")
        for candidate in candidates:
            _unique_split(candidate_splits, candidate, split, "candidate split leakage")
        for member_id in member_ids:
            _unique_split(member_splits, member_id, split, "member split leakage")
        if sample["sample_id"] in seen_ids or binding in seen_bindings:
            raise DomainError("duplicate formal sample")
        seen_ids.add(sample["sample_id"])
        seen_bindings.add(binding)
        sample["_binding"] = binding
        by_split[split].append(sample)
    return _Manifest(
        Sha256("0" * 64),
        {name: tuple(by_split[name]) for name in _SPLITS},
    )


def _unique_split(
    assigned: dict[str, str], identity: str, split: str, message: str
) -> None:
    if identity in assigned and assigned[identity] != split:
        raise DomainError(message)
    assigned[identity] = split


def _with_manifest_digest(manifest: _Manifest, data: bytes) -> _Manifest:
    return _Manifest(evidence_sha256(data), manifest.by_split)


def _observations(
    data: bytes, split: str, target: TargetCell, study: _Study, manifest: _Manifest
) -> _Observations:
    raw = _exact(
        _load_canonical(data),
        {
            "schema_version",
            "target_cell_sha256",
            "study_plan_sha256",
            "sample_manifest_sha256",
            "split",
            "observation_unit",
            "metric_id",
            "operator",
            "observations",
        },
        "formal observations",
    )
    expected = manifest.by_split[split]
    if (
        raw["schema_version"] != "specstyle.calibration.observations.v2"
        or raw["target_cell_sha256"] != target.sha256.value
        or raw["study_plan_sha256"] != study.digest.value
        or raw["sample_manifest_sha256"] != manifest.digest.value
        or raw["split"] != split
        or raw["observation_unit"] != study.metric.observation_unit
        or raw["metric_id"] != study.metric.metric_id.value
        or raw["operator"] != study.metric.operator
        or type(raw["observations"]) is not list
        or len(raw["observations"]) != len(expected)
    ):
        raise DomainError("formal observation binding mismatch")
    pairs = tuple(
        _observation(value, sample)
        for value, sample in zip(raw["observations"], expected, strict=True)
    )
    return _Observations(evidence_sha256(data), pairs)


def _observation(value: object, sample: dict[str, Any]) -> ScoredPair:
    raw = _exact(value, _OBSERVATION_KEYS, "formal observation")
    score = _float(raw["score"], "formal observation score")
    if (
        raw["sample_id"] != sample["sample_id"]
        or raw["sample_binding_sha256"] != sample["_binding"]
        or raw["annotation_record_sha256"] != sample["annotation_record_sha256"]
        or type(raw["label_positive"]) is not bool
    ):
        raise DomainError("formal observation sample mismatch")
    return ScoredPair(raw["sample_id"], score, raw["label_positive"])


def _commitment(
    data: bytes, target: TargetCell, study: _Study, manifest: _Manifest
) -> dict[str, Any]:
    raw = _exact(
        _load_canonical(data),
        {
            "schema_version",
            "target_cell_sha256",
            "study_plan_sha256",
            "sample_manifest_sha256",
            "observation_unit",
            "sealed_test_observations_sha256",
            "sample_ids",
            "sample_bindings_sha256",
            "positive_count",
            "negative_count",
        },
        "formal test commitment",
    )
    samples = manifest.by_split["test"]
    ids = [item["sample_id"] for item in samples]
    bindings = [item["_binding"] for item in samples]
    if (
        raw["schema_version"] != "specstyle.calibration.test_commitment.v2"
        or raw["target_cell_sha256"] != target.sha256.value
        or raw["study_plan_sha256"] != study.digest.value
        or raw["sample_manifest_sha256"] != manifest.digest.value
        or raw["observation_unit"] != study.metric.observation_unit
        or raw["sample_ids"] != ids
        or raw["sample_bindings_sha256"] != hash_bytes(canonical_json(bindings)).value
    ):
        raise DomainError("formal test commitment mismatch")
    _sha(raw["sealed_test_observations_sha256"], "sealed test observations")
    positive = _count(raw["positive_count"], "test positives", minimum=1)
    negative = _count(raw["negative_count"], "test negatives", minimum=1)
    if positive + negative != len(samples):
        raise DomainError("formal test commitment counts mismatch")
    return raw


def _label_approval(
    data: bytes,
    target: TargetCell,
    study: _Study,
    manifest: _Manifest,
    observed: tuple[_Observations, _Observations],
    sealed_test: str,
) -> dict[str, Any]:
    raw = _exact(
        _load_canonical(data),
        {
            "schema_version",
            "receipt_id",
            "study_id",
            "target_cell_sha256",
            "approval_kind",
            "approved",
            "label_source",
            "observation_unit",
            "study_plan_sha256",
            "sample_manifest_sha256",
            "annotation_protocol_sha256",
            "observation_sha256s",
            "approver_id",
            "issued_at",
        },
        "formal label approval receipt",
    )
    if (
        raw["schema_version"] != "specstyle.calibration.approval_receipt.v2"
        or raw["study_id"] != study.raw["study_id"]
        or raw["target_cell_sha256"] != target.sha256.value
        or raw["approval_kind"] != "HUMAN_LABELS"
        or type(raw["approved"]) is not bool
        or raw["label_source"] not in {"HUMAN_APPROVED", "SYNTHETIC"}
        or raw["observation_unit"] != study.metric.observation_unit
        or raw["study_plan_sha256"] != study.digest.value
        or raw["sample_manifest_sha256"] != manifest.digest.value
        or raw["annotation_protocol_sha256"] != study.raw["annotation_protocol_sha256"]
        or raw["observation_sha256s"]
        != [observed[0].digest.value, observed[1].digest.value, sealed_test]
    ):
        raise DomainError("formal label approval receipt mismatch")
    for key in ("receipt_id", "approver_id", "issued_at"):
        _text(raw[key], key)
    return raw


def _counts(pairs: tuple[ScoredPair, ...]) -> tuple[int, int]:
    positive = sum(item.label_positive for item in pairs)
    return positive, len(pairs) - positive


def _statistics(
    pairs: tuple[ScoredPair, ...], threshold: float, operator: str
) -> dict[str, Any]:
    tpr, fpr = binary_rates(pairs, threshold, operator)
    positive, negative = _counts(pairs)
    tp = sum(
        item.label_positive and _passes(item.score, threshold, operator)
        for item in pairs
    )
    fp = sum(
        not item.label_positive and _passes(item.score, threshold, operator)
        for item in pairs
    )
    return {
        "sample_count": len(pairs),
        "positive_count": positive,
        "negative_count": negative,
        "tpr": tpr,
        "fpr": fpr,
        "confusion": {"fn": positive - tp, "fp": fp, "tn": negative - fp, "tp": tp},
    }


def _passes(score: float, threshold: float, operator: str) -> bool:
    return score >= threshold if operator == "gte" else score <= threshold


def _report(
    target: TargetCell,
    study: _Study,
    manifest: _Manifest,
    commitment_data: bytes,
    commitment: dict[str, Any],
    approval_data: bytes,
    status: str,
    reasons: list[str],
    threshold: float | None,
    calibration: dict[str, Any] | None,
    validation: dict[str, Any] | None,
) -> bytes:
    metric = study.metric
    return canonical_json(
        {
            "schema_version": "specstyle.calibration.prepared_metric_evidence.v2",
            "target_cell_sha256": target.sha256.value,
            "study_id": study.raw["study_id"],
            "layer": metric.layer,
            "observation_unit": metric.observation_unit,
            "metric_id": metric.metric_id.value,
            "operator": metric.operator,
            "implementation_pin": _pin_value(metric.implementation_pin),
            "binding_pin": _pin_value(metric.binding_pin),
            "verifier_pin": _pin_value(metric.verifier_pin),
            "preprocessor_pin": _pin_value(metric.preprocessor_pin),
            "targets": study.raw["targets"],
            "study_plan_sha256": study.digest.value,
            "sample_manifest_sha256": manifest.digest.value,
            "annotation_protocol_sha256": study.raw["annotation_protocol_sha256"],
            "label_approval_receipt_sha256": evidence_sha256(approval_data).value,
            "test_commitment_sha256": evidence_sha256(commitment_data).value,
            "sealed_test_observations_sha256": commitment[
                "sealed_test_observations_sha256"
            ],
            "test_sample_ids": commitment["sample_ids"],
            "test_sample_bindings_sha256": commitment["sample_bindings_sha256"],
            "test_positive_count": commitment["positive_count"],
            "test_negative_count": commitment["negative_count"],
            "status": status,
            "reasons": reasons,
            "threshold": threshold,
            "calibration": calibration,
            "validation": validation,
            "test_held": True,
        }
    )


def prepare_metric_evidence(
    target_cell: bytes,
    study_plan: bytes,
    annotation_protocol: bytes,
    sample_manifest: bytes,
    calibration_observations: bytes,
    validation_observations: bytes,
    test_commitment: bytes,
    label_approval_receipt: bytes,
) -> bytes:
    """Freeze one item or cohort threshold while keeping test observations sealed."""
    target = load_target_cell(target_cell)
    study = _study(study_plan, target)
    _protocol(annotation_protocol, target, study)
    manifest = _with_manifest_digest(
        _manifest(sample_manifest, target, study), sample_manifest
    )
    calibration = _observations(
        calibration_observations, "calibration", target, study, manifest
    )
    validation = _observations(
        validation_observations, "validation", target, study, manifest
    )
    commitment = _commitment(test_commitment, target, study, manifest)
    approval = _label_approval(
        label_approval_receipt,
        target,
        study,
        manifest,
        (calibration, validation),
        commitment["sealed_test_observations_sha256"],
    )
    blocked = _blocked_reason(approval)
    if blocked is not None:
        return _report(
            target,
            study,
            manifest,
            test_commitment,
            commitment,
            label_approval_receipt,
            "BLOCKED",
            [blocked],
            None,
            None,
            None,
        )
    return _freeze(
        target,
        study,
        manifest,
        test_commitment,
        commitment,
        label_approval_receipt,
        calibration,
        validation,
    )


def _blocked_reason(approval: dict[str, Any]) -> str | None:
    if approval["label_source"] == "SYNTHETIC":
        return "BLOCKED_SYNTHETIC_LABELS"
    if not approval["approved"]:
        return "BLOCKED_MISSING_APPROVED_LABELS"
    return None


def _freeze(
    target: TargetCell,
    study: _Study,
    manifest: _Manifest,
    commitment_data: bytes,
    commitment: dict[str, Any],
    approval_data: bytes,
    calibration: _Observations,
    validation: _Observations,
) -> bytes:
    minimum = study.raw["split"]
    groups = (
        _counts(calibration.pairs),
        _counts(validation.pairs),
        (commitment["positive_count"], commitment["negative_count"]),
    )
    if any(
        positive < minimum["minimum_positive_per_split"]
        or negative < minimum["minimum_negative_per_split"]
        for positive, negative in groups
    ):
        return _report(
            target,
            study,
            manifest,
            commitment_data,
            commitment,
            approval_data,
            "BLOCKED",
            ["BLOCKED_INSUFFICIENT_SPLIT_LABELS"],
            None,
            None,
            None,
        )
    targets = study.raw["targets"]
    try:
        threshold = select_threshold_on_calibration(
            calibration.pairs,
            metric_id=study.metric.metric_id.value,
            operator=study.metric.operator,
            max_fpr=targets["max_fpr"],
            min_tpr=targets["min_tpr"],
        )
    except DomainError as exc:
        if str(exc) != "no threshold meets calibration targets":
            raise
        return _report(
            target,
            study,
            manifest,
            commitment_data,
            commitment,
            approval_data,
            "REJECTED",
            ["CALIBRATION_TARGETS_NOT_MET"],
            None,
            None,
            None,
        )
    decision = freeze_threshold(
        metric_id=study.metric.metric_id.value,
        operator=study.metric.operator,
        threshold=threshold,
        calibration=calibration.pairs,
        validation=validation.pairs,
        max_fpr=targets["max_fpr"],
        min_tpr=targets["min_tpr"],
    )
    reasons = (
        [] if decision.status == "VALIDATION_PASSED" else ["VALIDATION_TARGETS_NOT_MET"]
    )
    return _report(
        target,
        study,
        manifest,
        commitment_data,
        commitment,
        approval_data,
        decision.status,
        reasons,
        threshold,
        _statistics(calibration.pairs, threshold, study.metric.operator),
        _statistics(validation.pairs, threshold, study.metric.operator),
    )


def _prepared(data: bytes, target: TargetCell) -> dict[str, Any]:
    raw = _exact(
        _load_canonical(data), _PREPARED_KEYS, "prepared formal metric evidence"
    )
    metric = target.require_metric(raw["metric_id"])
    if (
        raw["schema_version"] != "specstyle.calibration.prepared_metric_evidence.v2"
        or raw["target_cell_sha256"] != target.sha256.value
        or raw["layer"] != metric.layer
        or raw["observation_unit"] != metric.observation_unit
        or raw["operator"] != metric.operator
        or raw["status"] != "VALIDATION_PASSED"
        or raw["reasons"] != []
        or type(raw["threshold"]) is not float
        or raw["test_held"] is not True
    ):
        raise DomainError("prepared formal metric evidence mismatch")
    return raw


def _reveal_receipt(
    data: bytes,
    target: TargetCell,
    prepared_data: bytes,
    prepared: dict[str, Any],
    test: bytes,
) -> dict[str, Any]:
    raw = _exact(
        _load_canonical(data),
        {
            "schema_version",
            "receipt_id",
            "study_id",
            "target_cell_sha256",
            "approval_kind",
            "approved",
            "validation_report_sha256",
            "sealed_test_observations_sha256",
            "approver_id",
            "issued_at",
        },
        "formal reveal receipt",
    )
    if (
        raw["schema_version"] != "specstyle.calibration.reveal_receipt.v2"
        or raw["study_id"] != prepared["study_id"]
        or raw["target_cell_sha256"] != target.sha256.value
        or raw["approval_kind"] != "REVEAL_TEST"
        or raw["approved"] is not True
        or raw["validation_report_sha256"] != evidence_sha256(prepared_data).value
        or raw["sealed_test_observations_sha256"] != evidence_sha256(test).value
        or raw["sealed_test_observations_sha256"]
        != prepared["sealed_test_observations_sha256"]
    ):
        raise DomainError("formal reveal receipt mismatch")
    for key in ("receipt_id", "approver_id", "issued_at"):
        _text(raw[key], key)
    return raw


def reveal_metric_test(
    target_cell: bytes,
    prepared_evidence: bytes,
    test_observations: bytes,
    reveal_authorization_receipt: bytes,
) -> bytes:
    """Reveal one sealed item or cohort test set after validation passed."""
    target = load_target_cell(target_cell)
    prepared = _prepared(prepared_evidence, target)
    study = _Study(
        {
            "study_id": prepared["study_id"],
            "split": {"salt": "unused"},
        },
        Sha256(prepared["study_plan_sha256"]),
        target.require_metric(prepared["metric_id"]),
    )
    manifest = _Manifest(
        Sha256(prepared["sample_manifest_sha256"]), {name: () for name in _SPLITS}
    )
    test = _revealed_observations(test_observations, target, study, manifest, prepared)
    receipt = _reveal_receipt(
        reveal_authorization_receipt,
        target,
        prepared_evidence,
        prepared,
        test_observations,
    )
    stats = _statistics(test.pairs, prepared["threshold"], prepared["operator"])
    targets = prepared["targets"]
    passed = stats["tpr"] >= targets["min_tpr"] and stats["fpr"] <= targets["max_fpr"]
    return canonical_json(
        {
            "schema_version": "specstyle.calibration.metric_test_reveal.v2",
            "target_cell_sha256": target.sha256.value,
            "study_id": prepared["study_id"],
            "validation_report_sha256": evidence_sha256(prepared_evidence).value,
            "test_observations_sha256": evidence_sha256(test_observations).value,
            "reveal_receipt_sha256": evidence_sha256(
                reveal_authorization_receipt
            ).value,
            "status": "TEST_PASSED_PENDING_PRODUCTION_APPROVAL"
            if passed
            else "REJECTED",
            "reasons": [] if passed else ["TEST_TARGETS_NOT_MET"],
            "layer": prepared["layer"],
            "observation_unit": prepared["observation_unit"],
            "metric_id": prepared["metric_id"],
            "operator": prepared["operator"],
            "threshold": prepared["threshold"],
            "calibration": prepared["calibration"],
            "validation": prepared["validation"],
            "test": stats,
            "eligible_context_status": "CALIBRATED" if passed else "DRAFT",
            "production_approval_required": True,
            "authorization_receipt_id": receipt["receipt_id"],
        }
    )


def _revealed_observations(
    data: bytes,
    target: TargetCell,
    study: _Study,
    manifest: _Manifest,
    prepared: dict[str, Any],
) -> _Observations:
    raw = _exact(
        _load_canonical(data),
        {
            "schema_version",
            "target_cell_sha256",
            "study_plan_sha256",
            "sample_manifest_sha256",
            "split",
            "observation_unit",
            "metric_id",
            "operator",
            "observations",
        },
        "formal observations",
    )
    values = raw["observations"]
    if (
        raw["schema_version"] != "specstyle.calibration.observations.v2"
        or raw["target_cell_sha256"] != target.sha256.value
        or raw["study_plan_sha256"] != study.digest.value
        or raw["sample_manifest_sha256"] != manifest.digest.value
        or raw["split"] != "test"
        or raw["observation_unit"] != prepared["observation_unit"]
        or raw["metric_id"] != prepared["metric_id"]
        or raw["operator"] != prepared["operator"]
        or type(values) is not list
        or [item.get("sample_id") for item in values] != prepared["test_sample_ids"]
        or hash_bytes(
            canonical_json([item.get("sample_binding_sha256") for item in values])
        ).value
        != prepared["test_sample_bindings_sha256"]
    ):
        raise DomainError("formal test observation binding mismatch")
    pairs = tuple(_revealed_pair(item) for item in values)
    if _counts(pairs) != (
        prepared["test_positive_count"],
        prepared["test_negative_count"],
    ):
        raise DomainError("formal test observation count mismatch")
    return _Observations(evidence_sha256(data), pairs)


def _revealed_pair(value: object) -> ScoredPair:
    raw = _exact(value, _OBSERVATION_KEYS, "formal observation")
    _sha(raw["sample_binding_sha256"], "formal sample binding")
    _sha(raw["annotation_record_sha256"], "formal annotation record")
    if type(raw["label_positive"]) is not bool:
        raise DomainError("formal observation sample mismatch")
    return ScoredPair(
        _text(raw["sample_id"], "formal sample id"),
        _float(raw["score"], "formal observation score"),
        raw["label_positive"],
    )


__all__ = ("prepare_metric_evidence", "reveal_metric_test")
