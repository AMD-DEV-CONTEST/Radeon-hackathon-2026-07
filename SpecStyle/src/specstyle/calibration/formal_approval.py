"""Independent metric and profile approvals for formal Production gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from typing import Any

from specstyle.calibration.evidence_io import (
    _exact,
    _float,
    _load_canonical,
    _pin,
    _sha,
    _text,
    evidence_sha256,
)
from specstyle.calibration.formal_evidence import (
    prepare_metric_evidence,
    reveal_metric_test,
)
from specstyle.calibration.target_cell import TargetCell, TargetMetric, load_target_cell
from specstyle.domain.identifiers import Identifier, Sha256
from specstyle.errors import DomainError
from specstyle.spec.compiled_models import ResourcePin

_METRIC_APPROVAL_KEYS = {
    "schema_version",
    "approval_id",
    "approved",
    "target_cell_sha256",
    "study_id",
    "layer",
    "observation_unit",
    "metric_id",
    "operator",
    "threshold",
    "implementation_pin",
    "binding_pin",
    "verifier_pin",
    "preprocessor_pin",
    "prepared_evidence_sha256",
    "test_reveal_sha256",
    "annotation_protocol_sha256",
    "approver_id",
    "issued_at",
}
_PROFILE_APPROVAL_KEYS = {
    "schema_version",
    "approval_id",
    "approved",
    "target_cell_sha256",
    "source",
    "threshold_profile_pin",
    "metric_approval_sha256s",
    "approver_id",
    "issued_at",
}
_PREPARED_KEYS = {
    "schema_version",
    "target_cell_sha256",
    "study_id",
    "layer",
    "observation_unit",
    "metric_id",
    "operator",
    "implementation_pin",
    "binding_pin",
    "verifier_pin",
    "preprocessor_pin",
    "targets",
    "study_plan_sha256",
    "sample_manifest_sha256",
    "annotation_protocol_sha256",
    "label_approval_receipt_sha256",
    "test_commitment_sha256",
    "sealed_test_observations_sha256",
    "test_sample_ids",
    "test_sample_bindings_sha256",
    "test_positive_count",
    "test_negative_count",
    "status",
    "reasons",
    "threshold",
    "calibration",
    "validation",
    "test_held",
}
_REVEAL_KEYS = {
    "schema_version",
    "target_cell_sha256",
    "study_id",
    "validation_report_sha256",
    "test_observations_sha256",
    "reveal_receipt_sha256",
    "status",
    "reasons",
    "layer",
    "observation_unit",
    "metric_id",
    "operator",
    "threshold",
    "calibration",
    "validation",
    "test",
    "eligible_context_status",
    "production_approval_required",
    "authorization_receipt_id",
}
_STATISTIC_KEYS = {
    "sample_count",
    "positive_count",
    "negative_count",
    "tpr",
    "fpr",
    "confusion",
}
_CONFUSION_KEYS = {"fn", "fp", "tn", "tp"}
_METRIC_BINDING_SEAL = object()
_PROFILE_APPROVAL_SEAL = object()


def _resource_pin(value: object, name: str) -> ResourcePin:
    raw = _pin(value, name)
    return ResourcePin(raw["id"], raw["revision"], Sha256(raw["sha256"]))


def _pin_value(pin: ResourcePin) -> dict[str, str]:
    return {"id": pin.id, "revision": pin.revision, "sha256": pin.sha256.value}


def _timestamp(value: object) -> str:
    text = _text(value, "formal approval time")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise DomainError("invalid formal approval timestamp") from None
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != text:
        raise DomainError("invalid formal approval timestamp")
    return text


@dataclass(frozen=True, slots=True, init=False)
class ApprovedMetricBinding:
    target_cell_sha256: Sha256
    study_id: str
    layer: str
    observation_unit: str
    metric_id: Identifier
    operator: str
    threshold: float
    implementation_pin: ResourcePin
    binding_pin: ResourcePin
    verifier_pin: ResourcePin
    preprocessor_pin: ResourcePin
    prepared_evidence_sha256: Sha256
    test_reveal_sha256: Sha256
    annotation_protocol_sha256: Sha256
    metric_approval_sha256: Sha256
    _seal: object = field(repr=False, compare=False)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("approved metric bindings are issued only by validation")

    def __post_init__(self) -> None:
        if (
            type(self.target_cell_sha256) is not Sha256
            or not self.study_id
            or self.layer not in {"L2", "L3"}
            or self.observation_unit not in {"item", "batch"}
            or type(self.metric_id) is not Identifier
            or self.operator not in {"gte", "lte"}
            or type(self.threshold) is not float
            or not isfinite(self.threshold)
            or any(
                type(pin) is not ResourcePin
                for pin in (
                    self.implementation_pin,
                    self.binding_pin,
                    self.verifier_pin,
                    self.preprocessor_pin,
                )
            )
            or any(
                type(digest) is not Sha256
                for digest in (
                    self.prepared_evidence_sha256,
                    self.test_reveal_sha256,
                    self.annotation_protocol_sha256,
                    self.metric_approval_sha256,
                )
            )
            or self._seal is not _METRIC_BINDING_SEAL
        ):
            raise DomainError("invalid approved metric binding")


@dataclass(frozen=True, slots=True)
class MetricEvidenceChain:
    study_plan: bytes
    annotation_protocol: bytes
    sample_manifest: bytes
    calibration_observations: bytes
    validation_observations: bytes
    test_commitment: bytes
    label_approval_receipt: bytes
    prepared_evidence: bytes
    test_observations: bytes
    reveal_authorization_receipt: bytes
    test_reveal: bytes

    def __post_init__(self) -> None:
        if any(
            type(value) is not bytes or not value
            for value in (
                self.study_plan,
                self.annotation_protocol,
                self.sample_manifest,
                self.calibration_observations,
                self.validation_observations,
                self.test_commitment,
                self.label_approval_receipt,
                self.prepared_evidence,
                self.test_observations,
                self.reveal_authorization_receipt,
                self.test_reveal,
            )
        ):
            raise DomainError("invalid metric evidence chain")


@dataclass(frozen=True, slots=True, init=False)
class ValidatedProfileApproval:
    production_approval_sha256: Sha256
    target_cell_sha256: Sha256
    source: str
    threshold_profile_pin: ResourcePin
    metrics: tuple[ApprovedMetricBinding, ...]
    _seal: object = field(repr=False, compare=False)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("profile approvals are issued only by validation")

    def __post_init__(self) -> None:
        if (
            type(self.production_approval_sha256) is not Sha256
            or type(self.target_cell_sha256) is not Sha256
            or self.source not in {"l2", "l3"}
            or type(self.threshold_profile_pin) is not ResourcePin
            or not self.metrics
            or any(type(item) is not ApprovedMetricBinding for item in self.metrics)
            or self._seal is not _PROFILE_APPROVAL_SEAL
        ):
            raise DomainError("invalid validated profile approval")


def _issue_metric_binding(
    *,
    target: TargetCell,
    metric: TargetMetric,
    study_id: str,
    threshold: float,
    prepared_evidence_sha256: Sha256,
    test_reveal_sha256: Sha256,
    annotation_protocol_sha256: Sha256,
    metric_approval_sha256: Sha256,
) -> ApprovedMetricBinding:
    issued = object.__new__(ApprovedMetricBinding)
    values = {
        "target_cell_sha256": target.sha256,
        "study_id": study_id,
        "layer": metric.layer,
        "observation_unit": metric.observation_unit,
        "metric_id": Identifier(metric.metric_id.value),
        "operator": metric.operator,
        "threshold": threshold,
        "implementation_pin": metric.implementation_pin,
        "binding_pin": metric.binding_pin,
        "verifier_pin": metric.verifier_pin,
        "preprocessor_pin": metric.preprocessor_pin,
        "prepared_evidence_sha256": prepared_evidence_sha256,
        "test_reveal_sha256": test_reveal_sha256,
        "annotation_protocol_sha256": annotation_protocol_sha256,
        "metric_approval_sha256": metric_approval_sha256,
        "_seal": _METRIC_BINDING_SEAL,
    }
    for name, value in values.items():
        object.__setattr__(issued, name, value)
    issued.__post_init__()
    return issued


def _issue_profile_approval(
    *,
    approval_sha256: Sha256,
    target: TargetCell,
    source: str,
    threshold_profile_pin: ResourcePin,
    metrics: tuple[ApprovedMetricBinding, ...],
) -> ValidatedProfileApproval:
    issued = object.__new__(ValidatedProfileApproval)
    values = {
        "production_approval_sha256": approval_sha256,
        "target_cell_sha256": target.sha256,
        "source": source,
        "threshold_profile_pin": threshold_profile_pin,
        "metrics": metrics,
        "_seal": _PROFILE_APPROVAL_SEAL,
    }
    for name, value in values.items():
        object.__setattr__(issued, name, value)
    issued.__post_init__()
    return issued


def _prepared(data: bytes, target: TargetCell, metric: TargetMetric) -> dict[str, Any]:
    raw = _exact(_load_canonical(data), _PREPARED_KEYS, "prepared metric evidence")
    if (
        raw.get("schema_version") != "specstyle.calibration.prepared_metric_evidence.v2"
        or raw.get("target_cell_sha256") != target.sha256.value
        or raw.get("layer") != metric.layer
        or raw.get("observation_unit") != metric.observation_unit
        or raw.get("metric_id") != metric.metric_id.value
        or raw.get("operator") != metric.operator
        or raw.get("implementation_pin") != _pin_value(metric.implementation_pin)
        or raw.get("binding_pin") != _pin_value(metric.binding_pin)
        or raw.get("verifier_pin") != _pin_value(metric.verifier_pin)
        or raw.get("preprocessor_pin") != _pin_value(metric.preprocessor_pin)
        or raw.get("status") != "VALIDATION_PASSED"
        or raw.get("reasons") != []
        or type(raw.get("threshold")) is not float
        or raw.get("test_held") is not True
    ):
        raise DomainError("invalid metric production approval evidence")
    for key in (
        "study_plan_sha256",
        "sample_manifest_sha256",
        "annotation_protocol_sha256",
        "label_approval_receipt_sha256",
        "test_commitment_sha256",
        "sealed_test_observations_sha256",
        "test_sample_bindings_sha256",
    ):
        _sha(raw[key], key)
    sample_ids = raw["test_sample_ids"]
    positive = _nonnegative_count(raw["test_positive_count"], "test positives", 1)
    negative = _nonnegative_count(raw["test_negative_count"], "test negatives", 1)
    if (
        type(sample_ids) is not list
        or not sample_ids
        or len({_text(value, "test sample id") for value in sample_ids})
        != len(sample_ids)
        or positive + negative != len(sample_ids)
    ):
        raise DomainError("invalid metric production approval evidence")
    targets = _exact(raw["targets"], {"min_tpr", "max_fpr"}, "metric targets")
    min_tpr = _float(targets["min_tpr"], "minimum tpr")
    max_fpr = _float(targets["max_fpr"], "maximum fpr")
    calibration = _statistics(raw["calibration"], "calibration statistics")
    validation = _statistics(raw["validation"], "validation statistics")
    if (
        not 0.0 <= min_tpr <= 1.0
        or not 0.0 <= max_fpr <= 1.0
        or calibration["tpr"] < min_tpr
        or calibration["fpr"] > max_fpr
        or validation["tpr"] < min_tpr
        or validation["fpr"] > max_fpr
    ):
        raise DomainError("invalid metric production approval evidence")
    return raw


def _reveal(
    data: bytes, prepared_data: bytes, prepared: dict[str, Any]
) -> dict[str, Any]:
    raw = _exact(_load_canonical(data), _REVEAL_KEYS, "metric test reveal")
    if (
        raw.get("schema_version") != "specstyle.calibration.metric_test_reveal.v2"
        or raw.get("target_cell_sha256") != prepared["target_cell_sha256"]
        or raw.get("study_id") != prepared["study_id"]
        or raw.get("validation_report_sha256") != evidence_sha256(prepared_data).value
        or raw.get("status") != "TEST_PASSED_PENDING_PRODUCTION_APPROVAL"
        or raw.get("reasons") != []
        or raw.get("layer") != prepared["layer"]
        or raw.get("observation_unit") != prepared["observation_unit"]
        or raw.get("metric_id") != prepared["metric_id"]
        or raw.get("operator") != prepared["operator"]
        or raw.get("threshold") != prepared["threshold"]
        or raw.get("calibration") != prepared["calibration"]
        or raw.get("validation") != prepared["validation"]
        or raw.get("test_observations_sha256")
        != prepared["sealed_test_observations_sha256"]
        or raw.get("eligible_context_status") != "CALIBRATED"
        or raw.get("production_approval_required") is not True
    ):
        raise DomainError("invalid metric production approval evidence")
    _sha(raw["test_observations_sha256"], "test observations sha256")
    _sha(raw["reveal_receipt_sha256"], "reveal receipt sha256")
    _text(raw["authorization_receipt_id"], "authorization receipt id")
    test = _statistics(raw["test"], "test statistics")
    targets = prepared["targets"]
    if (
        test["positive_count"] != prepared["test_positive_count"]
        or test["negative_count"] != prepared["test_negative_count"]
        or test["tpr"] < targets["min_tpr"]
        or test["fpr"] > targets["max_fpr"]
    ):
        raise DomainError("invalid metric production approval evidence")
    return raw


def _annotation_protocol(
    data: bytes, target: TargetCell, metric: TargetMetric, prepared: dict[str, Any]
) -> None:
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
        raw.get("schema_version") != "specstyle.annotation_protocol.v2"
        or raw.get("target_cell_sha256") != target.sha256.value
        or raw.get("observation_unit") != metric.observation_unit
        or raw.get("metric_id") != metric.metric_id.value
        or evidence_sha256(data).value != prepared["annotation_protocol_sha256"]
    ):
        raise DomainError("invalid metric production approval evidence")


def _statistics(value: object, name: str) -> dict[str, Any]:
    raw = _exact(value, _STATISTIC_KEYS, name)
    sample_count = _nonnegative_count(raw["sample_count"], f"{name} sample count", 2)
    positive = _nonnegative_count(raw["positive_count"], f"{name} positives", 1)
    negative = _nonnegative_count(raw["negative_count"], f"{name} negatives", 1)
    tpr = _float(raw["tpr"], f"{name} tpr")
    fpr = _float(raw["fpr"], f"{name} fpr")
    confusion = _exact(raw["confusion"], _CONFUSION_KEYS, f"{name} confusion")
    counts = {
        key: _nonnegative_count(confusion[key], f"{name} {key}", 0)
        for key in _CONFUSION_KEYS
    }
    if (
        sample_count != positive + negative
        or sample_count != sum(counts.values())
        or positive != counts["tp"] + counts["fn"]
        or negative != counts["tn"] + counts["fp"]
        or tpr != counts["tp"] / positive
        or fpr != counts["fp"] / negative
    ):
        raise DomainError("invalid metric production approval evidence")
    return raw


def _nonnegative_count(value: object, name: str, minimum: int) -> int:
    if type(value) is not int or isinstance(value, bool) or value < minimum:
        raise DomainError(f"invalid {name}")
    return value


def _validate_metric_approval(
    raw: dict[str, Any],
    data: bytes,
    target: TargetCell,
    metric: TargetMetric,
    prepared_data: bytes,
    prepared: dict[str, Any],
    reveal_data: bytes,
    protocol_data: bytes,
) -> ApprovedMetricBinding:
    threshold = _float(raw["threshold"], "approved formal threshold")
    expected = {
        "implementation_pin": metric.implementation_pin,
        "binding_pin": metric.binding_pin,
        "verifier_pin": metric.verifier_pin,
        "preprocessor_pin": metric.preprocessor_pin,
    }
    if (
        raw["schema_version"] != "specstyle.calibration.metric_production_approval.v1"
        or raw["approved"] is not True
        or raw["target_cell_sha256"] != target.sha256.value
        or raw["study_id"] != prepared["study_id"]
        or raw["layer"] != metric.layer
        or raw["observation_unit"] != metric.observation_unit
        or raw["metric_id"] != metric.metric_id.value
        or raw["operator"] != metric.operator
        or threshold != prepared["threshold"]
        or any(raw[name] != _pin_value(pin) for name, pin in expected.items())
        or raw["prepared_evidence_sha256"] != evidence_sha256(prepared_data).value
        or raw["test_reveal_sha256"] != evidence_sha256(reveal_data).value
        or raw["annotation_protocol_sha256"] != evidence_sha256(protocol_data).value
    ):
        raise DomainError("invalid metric production approval")
    _text(raw["approval_id"], "formal metric approval id")
    _text(raw["approver_id"], "formal metric approver id")
    _timestamp(raw["issued_at"])
    return _issue_metric_binding(
        target=target,
        metric=metric,
        study_id=prepared["study_id"],
        threshold=threshold,
        prepared_evidence_sha256=evidence_sha256(prepared_data),
        test_reveal_sha256=evidence_sha256(reveal_data),
        annotation_protocol_sha256=evidence_sha256(protocol_data),
        metric_approval_sha256=evidence_sha256(data),
    )


def _rebuild_metric_evidence(target_cell: bytes, chain: MetricEvidenceChain) -> None:
    prepared = prepare_metric_evidence(
        target_cell,
        chain.study_plan,
        chain.annotation_protocol,
        chain.sample_manifest,
        chain.calibration_observations,
        chain.validation_observations,
        chain.test_commitment,
        chain.label_approval_receipt,
    )
    if prepared != chain.prepared_evidence:
        raise DomainError("invalid metric production approval evidence")
    revealed = reveal_metric_test(
        target_cell,
        prepared,
        chain.test_observations,
        chain.reveal_authorization_receipt,
    )
    if revealed != chain.test_reveal:
        raise DomainError("invalid metric production approval evidence")


def validate_metric_production_approval(
    target_cell: bytes,
    evidence_chain: MetricEvidenceChain,
    metric_production_approval: bytes,
) -> ApprovedMetricBinding:
    """Validate one complete held-out chain and issue one metric binding."""
    try:
        if type(evidence_chain) is not MetricEvidenceChain:
            raise DomainError("invalid metric production approval")
        evidence_chain.__post_init__()
        _rebuild_metric_evidence(target_cell, evidence_chain)
        target = load_target_cell(target_cell)
        raw = _exact(
            _load_canonical(metric_production_approval),
            _METRIC_APPROVAL_KEYS,
            "metric production approval",
        )
        metric = target.require_metric(raw["metric_id"])
        prepared = _prepared(evidence_chain.prepared_evidence, target, metric)
        _reveal(
            evidence_chain.test_reveal,
            evidence_chain.prepared_evidence,
            prepared,
        )
        _annotation_protocol(
            evidence_chain.annotation_protocol,
            target,
            metric,
            prepared,
        )
        return _validate_metric_approval(
            raw,
            metric_production_approval,
            target,
            metric,
            evidence_chain.prepared_evidence,
            prepared,
            evidence_chain.test_reveal,
            evidence_chain.annotation_protocol,
        )
    except (AttributeError, DomainError, KeyError, TypeError):
        raise DomainError("invalid metric production approval") from None


def _profile_metrics(
    target: TargetCell, source: str, bindings: tuple[ApprovedMetricBinding, ...]
) -> tuple[ApprovedMetricBinding, ...]:
    layer = source.upper()
    expected = {item.metric_id.value for item in target.metrics if item.layer == layer}
    if not expected or any(
        type(item) is not ApprovedMetricBinding for item in bindings
    ):
        raise DomainError("invalid profile approval")
    for item in bindings:
        try:
            item.__post_init__()
            target_metric = target.require_metric(item.metric_id.value)
        except (AttributeError, DomainError):
            raise DomainError("invalid profile approval") from None
        if (
            item.target_cell_sha256 != target.sha256
            or item.layer != layer
            or item.layer != target_metric.layer
            or item.observation_unit != target_metric.observation_unit
            or item.operator != target_metric.operator
            or item.implementation_pin != target_metric.implementation_pin
            or item.binding_pin != target_metric.binding_pin
            or item.verifier_pin != target_metric.verifier_pin
            or item.preprocessor_pin != target_metric.preprocessor_pin
        ):
            raise DomainError("invalid profile approval")
    actual = {item.metric_id.value for item in bindings}
    if actual != expected or len(bindings) != len(actual):
        raise DomainError("invalid profile approval")
    ordered = tuple(sorted(bindings, key=lambda item: item.metric_id.value))
    if source == "l2":
        binding_pins = {item.binding_pin for item in ordered}
        verifier_pins = {item.verifier_pin for item in ordered}
        preprocessors = {item.preprocessor_pin for item in ordered}
        if any(
            len(values) != 1 for values in (binding_pins, verifier_pins, preprocessors)
        ):
            raise DomainError("invalid profile approval")
    return ordered


def validate_profile_approval(
    target_cell: bytes,
    metric_bindings: tuple[ApprovedMetricBinding, ...],
    profile_approval: bytes,
    expected_profile_pin: ResourcePin,
) -> ValidatedProfileApproval:
    """Cross-bind the exact approved metric set for one L2 or L3 profile."""
    try:
        target = load_target_cell(target_cell)
        raw = _exact(
            _load_canonical(profile_approval),
            _PROFILE_APPROVAL_KEYS,
            "profile approval",
        )
        source = raw["source"]
        if source not in {"l2", "l3"} or type(metric_bindings) is not tuple:
            raise DomainError("invalid profile approval")
        metrics = _profile_metrics(target, source, metric_bindings)
        digests = raw["metric_approval_sha256s"]
        supplied = tuple(_sha(value, "metric approval sha256") for value in digests)
        expected = tuple(item.metric_approval_sha256.value for item in metrics)
        if (
            raw["schema_version"] != "specstyle.calibration.profile_approval.v1"
            or raw["approved"] is not True
            or raw["target_cell_sha256"] != target.sha256.value
            or type(expected_profile_pin) is not ResourcePin
            or raw["threshold_profile_pin"] != _pin_value(expected_profile_pin)
            or type(digests) is not list
            or len(set(supplied)) != len(supplied)
            or set(supplied) != set(expected)
        ):
            raise DomainError("invalid profile approval")
        _text(raw["approval_id"], "formal profile approval id")
        _text(raw["approver_id"], "formal profile approver id")
        _timestamp(raw["issued_at"])
        return _issue_profile_approval(
            approval_sha256=evidence_sha256(profile_approval),
            target=target,
            source=source,
            threshold_profile_pin=expected_profile_pin,
            metrics=metrics,
        )
    except (AttributeError, DomainError, KeyError, TypeError):
        raise DomainError("invalid profile approval") from None


__all__ = (
    "ApprovedMetricBinding",
    "MetricEvidenceChain",
    "ValidatedProfileApproval",
    "validate_metric_production_approval",
    "validate_profile_approval",
)
