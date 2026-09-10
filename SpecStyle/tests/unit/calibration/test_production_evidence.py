"""Production approval validation over prepared held-out evidence."""

from __future__ import annotations

import json

import pytest

from specstyle.calibration.evidence import canonical_json, evidence_sha256, reveal_test
from specstyle.calibration.production_evidence import (
    ProductionThresholdExpectation,
    require_runtime_evidence_binding,
    validate_production_threshold_evidence,
)
from specstyle.domain.identifiers import Identifier, Sha256
from specstyle.errors import DomainError
from specstyle.spec.compiled_models import ResourcePin
from tests.unit.calibration.test_evidence import (
    _documents,
    _prepare,
    _reveal_receipt,
)


def _pin(name: str) -> dict[str, str]:
    return {
        "id": name,
        "revision": "v1",
        "sha256": evidence_sha256(
            canonical_json({"name": name, "schema_version": "pin-source.v1"})
        ).value,
    }


def _materials():
    documents = _documents()
    prepared = _prepare(documents)
    reveal = reveal_test(
        prepared,
        documents["test"],
        _reveal_receipt(prepared, documents["test"]),
    )
    plan = json.loads(documents["plan"])
    output_pin = {
        "id": "specstyle-output-renderer-xhs-grid",
        "revision": "v1",
        "sha256": "ef8ec7971a7d8b8b61133c029efca0443ac679173fac39e69dcff34eaf044669",
    }
    threshold_pin = _pin("l2-profile")
    approval = canonical_json(
        {
            "schema_version": "specstyle.calibration.production_approval.v1",
            "approval_id": "production-threshold-approval-v1",
            "approved": True,
            "study_id": "l2-style-v1",
            "calibration_evidence_sha256": evidence_sha256(prepared).value,
            "validation_evidence_sha256": evidence_sha256(reveal).value,
            "annotation_protocol_sha256": evidence_sha256(documents["protocol"]).value,
            "style_pack_id": "editorial-clean",
            "domain_profile": "product_instance",
            "output_profile": "xhs_grid",
            "output_profile_pin": output_pin,
            "threshold_profile_pin": threshold_pin,
            "metric": {
                "metric_id": "reference_style_statistics_similarity",
                "operator": ">=",
                "value": 0.9,
                "implementation_pin": plan["metric"]["implementation_pin"],
            },
            "verifier_pin": plan["verifier_pin"],
            "preprocessor_pin": plan["preprocessor_pin"],
            "approver_id": "trusted-production-reviewer",
            "issued_at": "2026-08-03T02:00:00Z",
        }
    )
    expectation = ProductionThresholdExpectation(
        Identifier("editorial-clean"),
        "product_instance",
        "xhs_grid",
        ResourcePin(
            output_pin["id"],
            output_pin["revision"],
            Sha256(output_pin["sha256"]),
        ),
        ResourcePin(
            threshold_pin["id"],
            threshold_pin["revision"],
            Sha256(threshold_pin["sha256"]),
        ),
        Identifier("reference_style_statistics_similarity"),
        ResourcePin(
            plan["metric"]["implementation_pin"]["id"],
            plan["metric"]["implementation_pin"]["revision"],
            Sha256(plan["metric"]["implementation_pin"]["sha256"]),
        ),
        ">=",
        0.9,
    )
    return documents, prepared, reveal, approval, expectation


def test_validated_evidence_binds_context_and_runtime_pins() -> None:
    documents, prepared, reveal, approval, expectation = _materials()

    binding = validate_production_threshold_evidence(
        prepared, reveal, documents["protocol"], approval, expectation
    )

    assert binding.production_approval_sha256 == evidence_sha256(approval)
    assert binding.verifier_pin.id == "dinov2-style-encoder"
    require_runtime_evidence_binding(
        binding,
        ResourcePin(
            binding.verifier_pin.id,
            binding.verifier_pin.revision,
            Sha256(binding.verifier_pin.sha256.value),
        ),
        "v1",
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("approved",), False),
        (("calibration_evidence_sha256",), "0" * 64),
        (("validation_evidence_sha256",), "1" * 64),
        (("annotation_protocol_sha256",), "2" * 64),
        (("output_profile_pin", "revision"), "other"),
        (("threshold_profile_pin", "revision"), "other"),
        (("metric", "value"), 0.8),
        (("verifier_pin", "revision"), "other"),
        (("preprocessor_pin", "revision"), "other"),
        (("issued_at",), "tomorrow"),
    ],
)
def test_production_approval_rejects_false_or_cross_binding_drift(
    path: tuple[str, ...], value: object
) -> None:
    documents, prepared, reveal, approval, expectation = _materials()
    raw = json.loads(approval)
    target = raw
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = value

    with pytest.raises(DomainError, match="production threshold evidence"):
        validate_production_threshold_evidence(
            prepared,
            reveal,
            documents["protocol"],
            canonical_json(raw),
            expectation,
        )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("test_observations_sha256",), "0" * 64),
        (("reveal_receipt_sha256",), "not-a-sha"),
        (("authorization_receipt_id",), ""),
        (("calibration", "fpr"), 0.5),
    ],
)
def test_production_approval_rejects_semantically_invalid_reveal(
    path: tuple[str, ...], value: object
) -> None:
    documents, prepared, reveal, approval, expectation = _materials()
    reveal_raw = json.loads(reveal)
    target = reveal_raw
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = value
    changed_reveal = canonical_json(reveal_raw)
    approval_raw = json.loads(approval)
    approval_raw["validation_evidence_sha256"] = evidence_sha256(changed_reveal).value

    with pytest.raises(DomainError, match="production threshold evidence"):
        validate_production_threshold_evidence(
            prepared,
            changed_reveal,
            documents["protocol"],
            canonical_json(approval_raw),
            expectation,
        )


def test_production_approval_rejects_consistent_test_statistics_below_target() -> None:
    documents, prepared, reveal, approval, expectation = _materials()
    reveal_raw = json.loads(reveal)
    reveal_raw["test"].update(
        {"tpr": 0.0, "confusion": {"fn": 1, "fp": 0, "tn": 1, "tp": 0}}
    )
    changed_reveal = canonical_json(reveal_raw)
    approval_raw = json.loads(approval)
    approval_raw["validation_evidence_sha256"] = evidence_sha256(changed_reveal).value

    with pytest.raises(DomainError, match="production threshold evidence"):
        validate_production_threshold_evidence(
            prepared,
            changed_reveal,
            documents["protocol"],
            canonical_json(approval_raw),
            expectation,
        )


def test_production_approval_rejects_test_counts_outside_sealed_commitment() -> None:
    documents, prepared, reveal, approval, expectation = _materials()
    reveal_raw = json.loads(reveal)
    reveal_raw["test"].update(
        {
            "sample_count": 4,
            "positive_count": 2,
            "negative_count": 2,
            "confusion": {"fn": 0, "fp": 0, "tn": 2, "tp": 2},
        }
    )
    changed_reveal = canonical_json(reveal_raw)
    approval_raw = json.loads(approval)
    approval_raw["validation_evidence_sha256"] = evidence_sha256(changed_reveal).value

    with pytest.raises(DomainError, match="production threshold evidence"):
        validate_production_threshold_evidence(
            prepared,
            changed_reveal,
            documents["protocol"],
            canonical_json(approval_raw),
            expectation,
        )


@pytest.mark.parametrize("runtime", ("encoder", "preprocessor"))
def test_runtime_evidence_binding_rejects_pin_drift(runtime: str) -> None:
    documents, prepared, reveal, approval, expectation = _materials()
    binding = validate_production_threshold_evidence(
        prepared, reveal, documents["protocol"], approval, expectation
    )
    encoder = binding.verifier_pin
    preprocessing_version = "v1"
    if runtime == "encoder":
        encoder = ResourcePin("other", "v1", Sha256("f" * 64))
    else:
        preprocessing_version = "other"

    with pytest.raises(DomainError, match="runtime evidence binding"):
        require_runtime_evidence_binding(binding, encoder, preprocessing_version)
