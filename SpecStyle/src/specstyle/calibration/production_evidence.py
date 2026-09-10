"""Cross-bind held-out evidence to one approved Production threshold."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from specstyle.calibration.evidence_io import (
    _count,
    _exact,
    _float,
    _load_canonical,
    _pin,
    _sha,
    _text,
    evidence_sha256,
)
from specstyle.domain.identifiers import Identifier, Sha256
from specstyle.errors import DomainError
from specstyle.spec.compiled_models import ResourcePin

_PREPARED_KEYS = {
    "schema_version",
    "study_id",
    "layer",
    "style_pack_id",
    "domain_profile",
    "output_profiles",
    "metric",
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
    "test_bindings_sha256",
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
    "study_id",
    "validation_report_sha256",
    "test_observations_sha256",
    "reveal_receipt_sha256",
    "status",
    "reasons",
    "metric",
    "threshold",
    "calibration",
    "validation",
    "test",
    "eligible_context_status",
    "production_approval_required",
    "authorization_receipt_id",
}
_APPROVAL_KEYS = {
    "schema_version",
    "approval_id",
    "approved",
    "study_id",
    "calibration_evidence_sha256",
    "validation_evidence_sha256",
    "annotation_protocol_sha256",
    "style_pack_id",
    "domain_profile",
    "output_profile",
    "output_profile_pin",
    "threshold_profile_pin",
    "metric",
    "verifier_pin",
    "preprocessor_pin",
    "approver_id",
    "issued_at",
}
_METRIC_KEYS = {"metric_id", "operator", "value", "implementation_pin"}
_STATISTIC_KEYS = {
    "sample_count",
    "positive_count",
    "negative_count",
    "tpr",
    "fpr",
    "confusion",
}
_CONFUSION_KEYS = {"fn", "fp", "tn", "tp"}


@dataclass(frozen=True, slots=True)
class ProductionThresholdExpectation:
    style_pack_id: Identifier
    domain_profile: str
    output_profile: str
    output_profile_pin: ResourcePin
    threshold_profile_pin: ResourcePin
    metric_id: Identifier
    metric_implementation_pin: ResourcePin
    operator: str
    value: float

    def __post_init__(self) -> None:
        if (
            type(self.style_pack_id) is not Identifier
            or self.domain_profile != "product_instance"
            or type(self.output_profile) is not str
            or not self.output_profile
            or type(self.output_profile_pin) is not ResourcePin
            or type(self.threshold_profile_pin) is not ResourcePin
            or type(self.metric_id) is not Identifier
            or type(self.metric_implementation_pin) is not ResourcePin
            or self.operator != ">="
            or type(self.value) is not float
        ):
            raise DomainError("invalid production threshold expectation")


@dataclass(frozen=True, slots=True)
class ValidatedEvidenceBinding:
    production_approval_sha256: Sha256
    verifier_pin: ResourcePin
    preprocessor_pin: ResourcePin


def _resource_pin(value: object, name: str) -> ResourcePin:
    raw = _pin(value, name)
    return ResourcePin(raw["id"], raw["revision"], Sha256(raw["sha256"]))


def _utc_timestamp(value: object) -> None:
    try:
        text = _text(value, "production approval time")
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except (DomainError, TypeError, ValueError):
        raise DomainError("invalid production threshold evidence") from None
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != text:
        raise DomainError("invalid production threshold evidence")


def _statistics(value: object, name: str) -> dict[str, Any]:
    try:
        raw = _exact(value, _STATISTIC_KEYS, name)
        sample_count = _count(raw["sample_count"], f"{name} sample count", minimum=2)
        positive = _count(raw["positive_count"], f"{name} positives", minimum=1)
        negative = _count(raw["negative_count"], f"{name} negatives", minimum=1)
        tpr = _float(raw["tpr"], f"{name} tpr")
        fpr = _float(raw["fpr"], f"{name} fpr")
        confusion = _exact(raw["confusion"], _CONFUSION_KEYS, f"{name} confusion")
        counts = {
            key: _count(confusion[key], f"{name} {key}") for key in _CONFUSION_KEYS
        }
    except (DomainError, KeyError, TypeError):
        raise DomainError("invalid production threshold evidence") from None
    if (
        sample_count != positive + negative
        or sample_count != sum(counts.values())
        or positive != counts["tp"] + counts["fn"]
        or negative != counts["tn"] + counts["fp"]
        or tpr != counts["tp"] / positive
        or fpr != counts["fp"] / negative
    ):
        raise DomainError("invalid production threshold evidence")
    return raw


def _validate_prepared_semantics(raw: dict[str, Any]) -> None:
    try:
        _text(raw["study_id"], "study id")
        _text(raw["style_pack_id"], "style pack")
        _text(raw["output_profiles"][0], "output profile")
        metric = _exact(
            raw["metric"],
            {"metric_id", "operator", "implementation_pin"},
            "prepared metric",
        )
        _text(metric["metric_id"], "metric id")
        if metric["operator"] != "gte":
            raise DomainError("invalid metric operator")
        _pin(metric["implementation_pin"], "metric implementation pin")
        _pin(raw["verifier_pin"], "verifier pin")
        _pin(raw["preprocessor_pin"], "preprocessor pin")
        targets = _exact(raw["targets"], {"min_tpr", "max_fpr"}, "targets")
        min_tpr = _float(targets["min_tpr"], "minimum tpr")
        max_fpr = _float(targets["max_fpr"], "maximum fpr")
        for key in (
            "study_plan_sha256",
            "sample_manifest_sha256",
            "annotation_protocol_sha256",
            "label_approval_receipt_sha256",
            "test_commitment_sha256",
            "sealed_test_observations_sha256",
            "test_bindings_sha256",
        ):
            _sha(raw[key], key)
        sample_ids = raw["test_sample_ids"]
        if type(sample_ids) is not list or not sample_ids:
            raise DomainError("invalid test sample ids")
        parsed_ids = [_text(item, "test sample id") for item in sample_ids]
        positive = _count(raw["test_positive_count"], "test positives", minimum=1)
        negative = _count(raw["test_negative_count"], "test negatives", minimum=1)
    except (DomainError, KeyError, TypeError):
        raise DomainError("invalid production threshold evidence") from None
    calibration = _statistics(raw["calibration"], "calibration statistics")
    validation = _statistics(raw["validation"], "validation statistics")
    if (
        not 0.0 <= min_tpr <= 1.0
        or not 0.0 <= max_fpr <= 1.0
        or len(set(parsed_ids)) != len(parsed_ids)
        or positive + negative != len(parsed_ids)
        or calibration["tpr"] < min_tpr
        or calibration["fpr"] > max_fpr
        or validation["tpr"] < min_tpr
        or validation["fpr"] > max_fpr
    ):
        raise DomainError("invalid production threshold evidence")


def _prepared(data: bytes) -> dict[str, Any]:
    raw = _exact(_load_canonical(data), _PREPARED_KEYS, "prepared evidence")
    if (
        raw["schema_version"] != "specstyle.calibration.prepared_evidence.v1"
        or raw["layer"] != "L2"
        or raw["domain_profile"] != "product_instance"
        or type(raw["output_profiles"]) is not list
        or len(raw["output_profiles"]) != 1
        or raw["status"] != "VALIDATION_PASSED"
        or raw["reasons"] != []
        or type(raw["threshold"]) is not float
        or raw["test_held"] is not True
    ):
        raise DomainError("invalid production threshold evidence")
    _validate_prepared_semantics(raw)
    return raw


def _revealed(
    data: bytes, prepared_data: bytes, prepared: dict[str, Any]
) -> dict[str, Any]:
    raw = _exact(_load_canonical(data), _REVEAL_KEYS, "test reveal evidence")
    if (
        raw["schema_version"] != "specstyle.calibration.test_reveal.v1"
        or raw["study_id"] != prepared["study_id"]
        or raw["validation_report_sha256"] != evidence_sha256(prepared_data).value
        or raw["status"] != "TEST_PASSED_PENDING_PRODUCTION_APPROVAL"
        or raw["reasons"] != []
        or raw["metric"] != prepared["metric"]
        or raw["threshold"] != prepared["threshold"]
        or raw["calibration"] != prepared["calibration"]
        or raw["validation"] != prepared["validation"]
        or raw["test_observations_sha256"]
        != prepared["sealed_test_observations_sha256"]
        or raw["eligible_context_status"] != "CALIBRATED"
        or raw["production_approval_required"] is not True
    ):
        raise DomainError("invalid production threshold evidence")
    try:
        _sha(raw["reveal_receipt_sha256"], "reveal receipt")
        _text(raw["authorization_receipt_id"], "authorization receipt id")
    except DomainError:
        raise DomainError("invalid production threshold evidence") from None
    test = _statistics(raw["test"], "test statistics")
    targets = prepared["targets"]
    if (
        test["sample_count"] != len(prepared["test_sample_ids"])
        or test["positive_count"] != prepared["test_positive_count"]
        or test["negative_count"] != prepared["test_negative_count"]
        or test["tpr"] < targets["min_tpr"]
        or test["fpr"] > targets["max_fpr"]
    ):
        raise DomainError("invalid production threshold evidence")
    return raw


def _protocol(data: bytes, prepared: dict[str, Any]) -> None:
    raw = _exact(
        _load_canonical(data),
        {"schema_version", "protocol_id", "label_definition"},
        "annotation protocol",
    )
    if (
        raw["schema_version"] != "specstyle.annotation_protocol.v1"
        or evidence_sha256(data).value != prepared["annotation_protocol_sha256"]
    ):
        raise DomainError("invalid production threshold evidence")
    _text(raw["protocol_id"], "annotation protocol id")
    _text(raw["label_definition"], "annotation label definition")


def _expected_pin(pin: ResourcePin) -> dict[str, str]:
    return {"id": pin.id, "revision": pin.revision, "sha256": pin.sha256.value}


def _validate_approval(
    raw: dict[str, Any],
    prepared_data: bytes,
    reveal_data: bytes,
    protocol_data: bytes,
    prepared: dict[str, Any],
    expectation: ProductionThresholdExpectation,
) -> tuple[ResourcePin, ResourcePin]:
    metric = _exact(raw["metric"], _METRIC_KEYS, "approved metric")
    expected_metric = {
        "metric_id": expectation.metric_id.value,
        "operator": expectation.operator,
        "value": expectation.value,
        "implementation_pin": _expected_pin(expectation.metric_implementation_pin),
    }
    if (
        raw["schema_version"] != "specstyle.calibration.production_approval.v1"
        or raw["approved"] is not True
        or raw["study_id"] != prepared["study_id"]
        or raw["calibration_evidence_sha256"] != evidence_sha256(prepared_data).value
        or raw["validation_evidence_sha256"] != evidence_sha256(reveal_data).value
        or raw["annotation_protocol_sha256"] != evidence_sha256(protocol_data).value
        or raw["style_pack_id"] != expectation.style_pack_id.value
        or raw["domain_profile"] != expectation.domain_profile
        or raw["output_profile"] != expectation.output_profile
        or raw["output_profile_pin"] != _expected_pin(expectation.output_profile_pin)
        or raw["threshold_profile_pin"]
        != _expected_pin(expectation.threshold_profile_pin)
        or metric != expected_metric
        or prepared["metric"]["metric_id"] != metric["metric_id"]
        or prepared["metric"]["operator"] != "gte"
        or prepared["metric"]["implementation_pin"] != metric["implementation_pin"]
        or prepared["threshold"] != metric["value"]
        or prepared["verifier_pin"] != raw["verifier_pin"]
        or prepared["preprocessor_pin"] != raw["preprocessor_pin"]
        or prepared["style_pack_id"] != raw["style_pack_id"]
        or prepared["domain_profile"] != raw["domain_profile"]
        or prepared["output_profiles"] != [raw["output_profile"]]
    ):
        raise DomainError("invalid production threshold evidence")
    _text(raw["approval_id"], "production approval id")
    _text(raw["approver_id"], "production approver id")
    _utc_timestamp(raw["issued_at"])
    return (
        _resource_pin(raw["verifier_pin"], "approved verifier pin"),
        _resource_pin(raw["preprocessor_pin"], "approved preprocessor pin"),
    )


def validate_production_threshold_evidence(
    prepared_evidence: bytes,
    test_reveal_evidence: bytes,
    annotation_protocol: bytes,
    production_approval: bytes,
    expectation: ProductionThresholdExpectation,
) -> ValidatedEvidenceBinding:
    """Validate four immutable evidence objects against one context projection."""
    if type(expectation) is not ProductionThresholdExpectation:
        raise DomainError("invalid production threshold expectation")
    prepared = _prepared(prepared_evidence)
    _revealed(test_reveal_evidence, prepared_evidence, prepared)
    _protocol(annotation_protocol, prepared)
    approval = _exact(
        _load_canonical(production_approval), _APPROVAL_KEYS, "production approval"
    )
    verifier, preprocessor = _validate_approval(
        approval,
        prepared_evidence,
        test_reveal_evidence,
        annotation_protocol,
        prepared,
        expectation,
    )
    return ValidatedEvidenceBinding(
        evidence_sha256(production_approval), verifier, preprocessor
    )


def require_runtime_evidence_binding(
    binding: ValidatedEvidenceBinding,
    encoder_pin: ResourcePin,
    preprocessing_version: str,
) -> None:
    """Bind approved evidence to the loaded encoder and processor provenance."""
    if (
        type(binding) is not ValidatedEvidenceBinding
        or type(encoder_pin) is not ResourcePin
        or encoder_pin != binding.verifier_pin
        or type(preprocessing_version) is not str
        or preprocessing_version != binding.preprocessor_pin.revision
    ):
        raise DomainError("production runtime evidence binding mismatch")
