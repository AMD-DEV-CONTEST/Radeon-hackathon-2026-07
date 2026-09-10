from __future__ import annotations

import json

import pytest

from specstyle.calibration.evidence import canonical_json, evidence_sha256
from specstyle.calibration.formal_approval import (
    ApprovedMetricBinding,
    MetricEvidenceChain,
    validate_metric_production_approval,
    validate_profile_approval,
)
from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.spec.compiled_models import ResourcePin
from tests.unit.calibration.test_formal_evidence import (
    _documents,
    _prepare,
    _reveal_receipt,
    _target_cell,
)
from specstyle.calibration.formal_evidence import reveal_metric_test


def _resource_pin(value: dict[str, str]) -> ResourcePin:
    return ResourcePin(value["id"], value["revision"], Sha256(value["sha256"]))


def _metric_material(metric_id: str):
    documents = _documents(metric_id)
    target = json.loads(documents["target"])
    plan = json.loads(documents["plan"])
    metric = next(item for item in target["metrics"] if item["metric_id"] == metric_id)
    prepared = _prepare(documents)
    reveal = reveal_metric_test(
        documents["target"],
        prepared,
        documents["test"],
        _reveal_receipt(prepared, documents),
    )
    report = json.loads(prepared)
    approval = canonical_json(
        {
            "schema_version": "specstyle.calibration.metric_production_approval.v1",
            "approval_id": f"{metric_id}-production-v1",
            "approved": True,
            "target_cell_sha256": evidence_sha256(documents["target"]).value,
            "study_id": plan["study_id"],
            "layer": metric["layer"],
            "observation_unit": metric["observation_unit"],
            "metric_id": metric_id,
            "operator": metric["operator"],
            "threshold": report["threshold"],
            "implementation_pin": metric["implementation_pin"],
            "binding_pin": metric["binding_pin"],
            "verifier_pin": metric["verifier_pin"],
            "preprocessor_pin": metric["preprocessor_pin"],
            "prepared_evidence_sha256": evidence_sha256(prepared).value,
            "test_reveal_sha256": evidence_sha256(reveal).value,
            "annotation_protocol_sha256": evidence_sha256(documents["protocol"]).value,
            "approver_id": "guan",
            "issued_at": "2026-08-04T02:00:00Z",
        }
    )
    binding = validate_metric_production_approval(
        documents["target"], _evidence_chain(documents, prepared, reveal), approval
    )
    return documents, approval, binding


def _evidence_chain(
    documents: dict[str, bytes],
    prepared: bytes | None = None,
    revealed: bytes | None = None,
) -> MetricEvidenceChain:
    prepared_evidence = prepared or _prepare(documents)
    receipt = _reveal_receipt(prepared_evidence, documents)
    test_reveal = revealed or reveal_metric_test(
        documents["target"],
        prepared_evidence,
        documents["test"],
        receipt,
    )
    return MetricEvidenceChain(
        study_plan=documents["plan"],
        annotation_protocol=documents["protocol"],
        sample_manifest=documents["manifest"],
        calibration_observations=documents["calibration"],
        validation_observations=documents["validation"],
        test_commitment=documents["commitment"],
        label_approval_receipt=documents["approval"],
        prepared_evidence=prepared_evidence,
        test_observations=documents["test"],
        reveal_authorization_receipt=receipt,
        test_reveal=test_reveal,
    )


def _profile_approval(
    target: bytes,
    source: str,
    metric_approval_sha256s: list[str],
    profile_pin: dict[str, str],
) -> bytes:
    return canonical_json(
        {
            "schema_version": "specstyle.calibration.profile_approval.v1",
            "approval_id": f"{source}-profile-production-v1",
            "approved": True,
            "target_cell_sha256": evidence_sha256(target).value,
            "source": source,
            "threshold_profile_pin": profile_pin,
            "metric_approval_sha256s": metric_approval_sha256s,
            "approver_id": "guan",
            "issued_at": "2026-08-04T03:00:00Z",
        }
    )


def test_l2_and_l3_profile_approvals_are_independent_exact_sets() -> None:
    l2_item = _metric_material("reference_style_statistics_similarity")
    l2_batch = _metric_material("batch_style_consistency")
    l3 = _metric_material("structure_edge_similarity")
    target = l2_item[0]["target"]
    l2_pin = {
        "id": "l2-profile",
        "revision": "v1",
        "sha256": "a" * 64,
    }
    l3_pin = {
        "id": "l3-profile",
        "revision": "v1",
        "sha256": "b" * 64,
    }

    l2_binding = validate_profile_approval(
        target,
        (l2_item[2], l2_batch[2]),
        _profile_approval(
            target,
            "l2",
            [
                evidence_sha256(l2_item[1]).value,
                evidence_sha256(l2_batch[1]).value,
            ],
            l2_pin,
        ),
        _resource_pin(l2_pin),
    )
    l3_binding = validate_profile_approval(
        target,
        (l3[2],),
        _profile_approval(
            target,
            "l3",
            [evidence_sha256(l3[1]).value],
            l3_pin,
        ),
        _resource_pin(l3_pin),
    )

    assert l2_binding.source == "l2"
    assert {item.metric_id.value for item in l2_binding.metrics} == {
        "reference_style_statistics_similarity",
        "batch_style_consistency",
    }
    assert l3_binding.source == "l3"
    assert tuple(item.metric_id.value for item in l3_binding.metrics) == (
        "structure_edge_similarity",
    )


def test_l2_profile_approval_rejects_missing_batch_metric() -> None:
    item = _metric_material("reference_style_statistics_similarity")
    target = item[0]["target"]
    pin = {"id": "l2-profile", "revision": "v1", "sha256": "a" * 64}
    approval = _profile_approval(
        target,
        "l2",
        [evidence_sha256(item[1]).value],
        pin,
    )

    with pytest.raises(DomainError, match="profile approval"):
        validate_profile_approval(target, (item[2],), approval, _resource_pin(pin))


def test_metric_approval_rejects_cross_target_cell() -> None:
    documents, approval, _binding = _metric_material("structure_edge_similarity")

    with pytest.raises(DomainError, match="metric production approval"):
        validate_metric_production_approval(
            _target_cell(suffix="-other"),
            _evidence_chain(documents),
            approval,
        )


def test_metric_approval_recomputes_test_statistics() -> None:
    documents, approval, _binding = _metric_material("structure_edge_similarity")
    prepared = _prepare(documents)
    reveal = reveal_metric_test(
        documents["target"],
        prepared,
        documents["test"],
        _reveal_receipt(prepared, documents),
    )
    reveal_raw = json.loads(reveal)
    reveal_raw["test"].update(
        {"tpr": 0.0, "confusion": {"fn": 1, "fp": 0, "tn": 1, "tp": 0}}
    )
    changed_reveal = canonical_json(reveal_raw)
    approval_raw = json.loads(approval)
    approval_raw["test_reveal_sha256"] = evidence_sha256(changed_reveal).value

    with pytest.raises(DomainError, match="metric production approval"):
        validate_metric_production_approval(
            documents["target"],
            _evidence_chain(documents, prepared, changed_reveal),
            canonical_json(approval_raw),
        )


def test_metric_approval_rejects_self_consistent_forged_statistics() -> None:
    documents, approval, _binding = _metric_material("structure_edge_similarity")
    prepared_raw = json.loads(_prepare(documents))
    forged = {
        "sample_count": 4,
        "positive_count": 2,
        "negative_count": 2,
        "tpr": 1.0,
        "fpr": 0.0,
        "confusion": {"fn": 0, "fp": 0, "tn": 2, "tp": 2},
    }
    prepared_raw["calibration"] = forged
    prepared_raw["validation"] = forged
    changed_prepared = canonical_json(prepared_raw)
    reveal_raw = json.loads(
        reveal_metric_test(
            documents["target"],
            _prepare(documents),
            documents["test"],
            _reveal_receipt(_prepare(documents), documents),
        )
    )
    reveal_raw["validation_report_sha256"] = evidence_sha256(changed_prepared).value
    reveal_raw["calibration"] = forged
    reveal_raw["validation"] = forged
    changed_reveal = canonical_json(reveal_raw)
    approval_raw = json.loads(approval)
    approval_raw["prepared_evidence_sha256"] = evidence_sha256(changed_prepared).value
    approval_raw["test_reveal_sha256"] = evidence_sha256(changed_reveal).value

    with pytest.raises(DomainError, match="metric production approval"):
        validate_metric_production_approval(
            documents["target"],
            _evidence_chain(documents, changed_prepared, changed_reveal),
            canonical_json(approval_raw),
        )


def test_metric_approval_rejects_extra_prepared_evidence_keys() -> None:
    documents, approval, _binding = _metric_material("structure_edge_similarity")
    prepared_raw = json.loads(_prepare(documents))
    prepared_raw["unexpected"] = "field"
    changed_prepared = canonical_json(prepared_raw)
    reveal_raw = json.loads(
        reveal_metric_test(
            documents["target"],
            _prepare(documents),
            documents["test"],
            _reveal_receipt(_prepare(documents), documents),
        )
    )
    reveal_raw["validation_report_sha256"] = evidence_sha256(changed_prepared).value
    changed_reveal = canonical_json(reveal_raw)
    approval_raw = json.loads(approval)
    approval_raw["prepared_evidence_sha256"] = evidence_sha256(changed_prepared).value
    approval_raw["test_reveal_sha256"] = evidence_sha256(changed_reveal).value

    with pytest.raises(DomainError, match="metric production approval"):
        validate_metric_production_approval(
            documents["target"],
            _evidence_chain(documents, changed_prepared, changed_reveal),
            canonical_json(approval_raw),
        )


def test_metric_bindings_can_only_be_issued_by_validation() -> None:
    with pytest.raises(TypeError, match="issued only"):
        ApprovedMetricBinding()


def test_profile_approval_rejects_unsealed_metric_binding() -> None:
    item = _metric_material("reference_style_statistics_similarity")
    batch = _metric_material("batch_style_consistency")
    forged = object.__new__(ApprovedMetricBinding)
    for name in ApprovedMetricBinding.__dataclass_fields__:
        if name != "_seal":
            object.__setattr__(forged, name, getattr(item[2], name))
    target = item[0]["target"]
    pin = {"id": "l2-profile", "revision": "v1", "sha256": "a" * 64}
    approval = _profile_approval(
        target,
        "l2",
        [
            evidence_sha256(item[1]).value,
            evidence_sha256(batch[1]).value,
        ],
        pin,
    )

    with pytest.raises(DomainError, match="profile approval"):
        validate_profile_approval(
            target,
            (forged, batch[2]),
            approval,
            _resource_pin(pin),
        )


def test_profile_approval_rejects_sealed_binding_field_drift() -> None:
    item = _metric_material("reference_style_statistics_similarity")
    batch = _metric_material("batch_style_consistency")
    forged = object.__new__(ApprovedMetricBinding)
    for name in ApprovedMetricBinding.__dataclass_fields__:
        object.__setattr__(forged, name, getattr(item[2], name))
    object.__setattr__(forged, "operator", "lte")
    target = item[0]["target"]
    pin = {"id": "l2-profile", "revision": "v1", "sha256": "a" * 64}
    approval = _profile_approval(
        target,
        "l2",
        [
            evidence_sha256(item[1]).value,
            evidence_sha256(batch[1]).value,
        ],
        pin,
    )

    with pytest.raises(DomainError, match="profile approval"):
        validate_profile_approval(
            target,
            (forged, batch[2]),
            approval,
            _resource_pin(pin),
        )
