from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from specstyle.calibration.evidence import canonical_json, evidence_sha256
from specstyle.calibration.formal_evidence import reveal_metric_test
from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.generation.model_registry import ModelDescriptor
from specstyle.spec.compiled_models import ResourcePin
from tests.unit.calibration.test_formal_approval import _profile_approval
from tests.unit.calibration.test_formal_evidence import (
    _documents,
    _prepare,
    _reveal_receipt,
)
from tests.unit.production.test_context_config import (
    _load,
    _factory_environment,
    _factory_graph,
    _pin,
    _v2_xhs_context_document,
    _write_document,
)

_OUTPUT_PIN = {
    "id": "specstyle-output-renderer-xhs-grid",
    "revision": "v1",
    "sha256": "ef8ec7971a7d8b8b61133c029efca0443ac679173fac39e69dcff34eaf044669",
}
_FORMAL_KEYS = (
    "study_plan",
    "annotation_protocol",
    "sample_manifest",
    "calibration_observations",
    "validation_observations",
    "test_commitment",
    "label_approval_receipt",
    "prepared_evidence",
    "test_observations",
    "reveal_authorization_receipt",
    "test_reveal",
    "metric_production_approval",
)


def _retargeted_documents(metric_id: str) -> dict[str, bytes]:
    documents = _documents(metric_id)
    target = json.loads(documents["target"])
    target["output_profile_pin"] = _OUTPUT_PIN
    documents["target"] = canonical_json(target)
    target_sha = evidence_sha256(documents["target"]).value

    protocol = json.loads(documents["protocol"])
    protocol["target_cell_sha256"] = target_sha
    documents["protocol"] = canonical_json(protocol)
    plan = json.loads(documents["plan"])
    plan["target_cell_sha256"] = target_sha
    plan["annotation_protocol_sha256"] = evidence_sha256(documents["protocol"]).value
    documents["plan"] = canonical_json(plan)

    manifest = json.loads(documents["manifest"])
    manifest["target_cell_sha256"] = target_sha
    manifest["study_plan_sha256"] = evidence_sha256(documents["plan"]).value
    documents["manifest"] = canonical_json(manifest)
    manifest_sha = evidence_sha256(documents["manifest"]).value
    for split in ("calibration", "validation", "test"):
        observations = json.loads(documents[split])
        observations["target_cell_sha256"] = target_sha
        observations["study_plan_sha256"] = evidence_sha256(documents["plan"]).value
        observations["sample_manifest_sha256"] = manifest_sha
        documents[split] = canonical_json(observations)

    commitment = json.loads(documents["commitment"])
    commitment["target_cell_sha256"] = target_sha
    commitment["study_plan_sha256"] = evidence_sha256(documents["plan"]).value
    commitment["sample_manifest_sha256"] = manifest_sha
    commitment["sealed_test_observations_sha256"] = evidence_sha256(
        documents["test"]
    ).value
    documents["commitment"] = canonical_json(commitment)

    receipt = json.loads(documents["approval"])
    receipt["target_cell_sha256"] = target_sha
    receipt["study_plan_sha256"] = evidence_sha256(documents["plan"]).value
    receipt["sample_manifest_sha256"] = manifest_sha
    receipt["annotation_protocol_sha256"] = evidence_sha256(documents["protocol"]).value
    receipt["observation_sha256s"] = [
        evidence_sha256(documents[name]).value
        for name in ("calibration", "validation", "test")
    ]
    documents["approval"] = canonical_json(receipt)
    return documents


def _metric_approval_material(metric_id: str) -> tuple[dict[str, bytes], bytes]:
    documents = _retargeted_documents(metric_id)
    prepared = _prepare(documents)
    reveal_receipt = _reveal_receipt(prepared, documents)
    revealed = reveal_metric_test(
        documents["target"], prepared, documents["test"], reveal_receipt
    )
    target = json.loads(documents["target"])
    metric = next(item for item in target["metrics"] if item["metric_id"] == metric_id)
    report = json.loads(prepared)
    approval = canonical_json(
        {
            "schema_version": "specstyle.calibration.metric_production_approval.v1",
            "approval_id": f"{metric_id}-production-v1",
            "approved": True,
            "target_cell_sha256": evidence_sha256(documents["target"]).value,
            "study_id": json.loads(documents["plan"])["study_id"],
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
            "test_reveal_sha256": evidence_sha256(revealed).value,
            "annotation_protocol_sha256": evidence_sha256(documents["protocol"]).value,
            "approver_id": "guan",
            "issued_at": "2026-08-04T02:00:00Z",
        }
    )
    documents.update(
        {
            "prepared": prepared,
            "reveal_receipt": reveal_receipt,
            "revealed": revealed,
            "metric_approval": approval,
        }
    )
    return documents, approval


def _store(evidence_root: Path, content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()
    directory = evidence_root / "sha256" / digest[:2]
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    (evidence_root / "sha256").chmod(0o700)
    path = directory / digest
    if not path.exists():
        path.write_bytes(content)
        path.chmod(0o400)
    else:
        assert path.read_bytes() == content
    return digest


def _pin_value(value: dict[str, str]) -> dict[str, str]:
    return {"id": value["id"], "revision": value["revision"], "sha256": value["sha256"]}


def _metric_entry(documents: dict[str, bytes], evidence_root: Path) -> dict[str, Any]:
    target = json.loads(documents["target"])
    metric_id = json.loads(documents["plan"])["metric_id"]
    metric = next(item for item in target["metrics"] if item["metric_id"] == metric_id)
    source = {
        "study_plan": documents["plan"],
        "annotation_protocol": documents["protocol"],
        "sample_manifest": documents["manifest"],
        "calibration_observations": documents["calibration"],
        "validation_observations": documents["validation"],
        "test_commitment": documents["commitment"],
        "label_approval_receipt": documents["approval"],
        "prepared_evidence": documents["prepared"],
        "test_observations": documents["test"],
        "reveal_authorization_receipt": documents["reveal_receipt"],
        "test_reveal": documents["revealed"],
        "metric_production_approval": documents["metric_approval"],
    }
    return {
        "metric_id": metric_id,
        "observation_unit": metric["observation_unit"],
        "operator": ">=" if metric["operator"] == "gte" else "<=",
        "value": json.loads(documents["prepared"])["threshold"],
        "implementation_pin": metric["implementation_pin"],
        "binding_pin": metric["binding_pin"],
        "verifier_pin": metric["verifier_pin"],
        "preprocessor_pin": metric["preprocessor_pin"],
        "calibration_dataset_sha256": _store(evidence_root, documents["calibration"]),
        "validation_dataset_sha256": _store(evidence_root, documents["validation"]),
        "annotation_protocol_sha256": _store(evidence_root, documents["protocol"]),
        "formal_evidence": {
            f"{name}_sha256": _store(evidence_root, source[name])
            for name in _FORMAL_KEYS
        },
    }


def _profile(
    source: str,
    metrics: list[dict[str, Any]],
    approvals: list[bytes],
    target: bytes,
    evidence_root: Path,
) -> dict[str, Any]:
    pin = _pin(f"{source}-formal-profile", "a" if source == "l2" else "b")
    profile_approval = _profile_approval(
        target,
        source,
        [evidence_sha256(value).value for value in approvals],
        pin,
    )
    return {
        "pin": pin,
        "logical_name": f"{source}-structure-xhs-production-v1",
        "source": source,
        "status": "VALIDATED",
        "style_pack_id": "editorial-clean",
        "domain_profile": "structure_only",
        "metrics": metrics,
        "production_approval_sha256": _store(evidence_root, profile_approval),
    }


def _write_v4_roots(tmp_path: Path) -> tuple[Path, Path]:
    config_root, evidence_root = tmp_path / "config", tmp_path / "evidence"
    config_root.mkdir(mode=0o700)
    evidence_root.mkdir(mode=0o700)
    materials = {
        metric_id: _metric_approval_material(metric_id)
        for metric_id in (
            "batch_style_consistency",
            "reference_style_statistics_similarity",
            "structure_edge_similarity",
        )
    }
    target = materials["structure_edge_similarity"][0]["target"]
    target_raw = json.loads(target)
    _store(evidence_root, target)
    entries = {
        name: _metric_entry(value[0], evidence_root)
        for name, value in materials.items()
    }
    document = _v2_xhs_context_document(
        {
            "calibration_dataset_sha256": entries[
                "reference_style_statistics_similarity"
            ]["calibration_dataset_sha256"],
            "validation_dataset_sha256": entries[
                "reference_style_statistics_similarity"
            ]["validation_dataset_sha256"],
            "annotation_protocol_sha256": entries[
                "reference_style_statistics_similarity"
            ]["annotation_protocol_sha256"],
        }
    )
    document["schema_version"] = "specstyle.production.context.v4"
    document["compiler_pin"] = target_raw["compiler_pin"]
    document["strength_mapping"]["preset_id"] = target_raw["style_pack_id"]
    document["strength_mapping"]["pin"] = target_raw["style_pack_pin"]
    document["rule_catalog"]["pin"] = target_raw["rule_catalog_pin"]
    document["rule_catalog"]["l2_item_rule"]["verifier_pin"] = entries[
        "reference_style_statistics_similarity"
    ]["verifier_pin"]
    document["rule_catalog"]["l2_batch_rule"]["verifier_pin"] = entries[
        "batch_style_consistency"
    ]["verifier_pin"]
    document["rule_catalog"]["l2_batch_rule"]["supported_output_profiles"] = [
        "xhs_grid"
    ]
    document["source_preprocess"]["processor_pin"] = entries[
        "reference_style_statistics_similarity"
    ]["preprocessor_pin"]
    document.pop("l2_threshold_profile")
    document["target_cell_sha256"] = evidence_sha256(target).value
    document["threshold_profiles"] = [
        _profile(
            "l2",
            [
                entries["batch_style_consistency"],
                entries["reference_style_statistics_similarity"],
            ],
            [
                materials[name][1]
                for name in (
                    "batch_style_consistency",
                    "reference_style_statistics_similarity",
                )
            ],
            target,
            evidence_root,
        ),
        _profile(
            "l3",
            [entries["structure_edge_similarity"]],
            [materials["structure_edge_similarity"][1]],
            target,
            evidence_root,
        ),
    ]
    l3_metric = entries["structure_edge_similarity"]
    document["l3_plugins"] = [
        {
            "pin": _pin_value(l3_metric["binding_pin"]),
            "domain_profile": "structure_only",
            "domain_verifier_version": target_raw["domain_verifier_version"],
            "supported_output_profiles": ["xhs_grid"],
            "rules": [
                {
                    "rule_id": "l3_structure_fidelity",
                    "kind": "L3_DOMAIN_FIDELITY",
                    "scope": "ITEM",
                    "requirement": "fidelity_required",
                    "supported_domains": ["structure_only"],
                    "supported_output_profiles": ["xhs_grid"],
                    "verifier_pin": _pin_value(l3_metric["verifier_pin"]),
                    "threshold_source": "l3",
                    "metric_id": "structure_edge_similarity",
                    "priority": 20,
                    "affected_by_actions": [],
                }
            ],
        }
    ]
    _write_document(config_root, document)
    return config_root, evidence_root


def test_v4_loads_two_approved_profiles_and_one_structure_plugin(
    tmp_path: Path,
) -> None:
    from specstyle.production.context_config import (
        require_validated_production_threshold,
    )

    config_root, evidence_root = _write_v4_roots(tmp_path)

    loaded = _load(config_root, evidence_root)

    assert loaded.schema_version == "specstyle.production.context.v4"
    assert loaded.target_cell_sha256 == evidence_sha256(
        _retargeted_documents("structure_edge_similarity")["target"]
    )
    assert tuple(profile.source for profile in loaded.threshold_profiles) == (
        "l2",
        "l3",
    )
    assert tuple(
        tuple(metric.metric_id.value for metric in profile.metrics)
        for profile in loaded.threshold_profiles
    ) == (
        ("batch_style_consistency", "reference_style_statistics_similarity"),
        ("structure_edge_similarity",),
    )
    assert loaded.l2_threshold_profile is loaded.threshold_profiles[0]
    assert len(loaded.l3_plugins) == 1
    assert loaded.l3_plugins[0].domain_profile == "structure_only"
    batch_rule = next(
        rule
        for rule in loaded.rule_catalog.rules
        if rule.metric_id is not None
        and rule.metric_id.value == "batch_style_consistency"
    )
    assert batch_rule.requirement == "always_required"
    assert require_validated_production_threshold(loaded) is None


def test_v4_rejects_runtime_style_pack_pin_drift(tmp_path: Path) -> None:
    config_root, evidence_root = _write_v4_roots(tmp_path)
    document = json.loads((config_root / "context.json").read_text(encoding="utf-8"))
    document["strength_mapping"]["pin"] = _pin("other-style-pack", "d")
    _write_document(config_root, document)

    with pytest.raises(DomainError, match="v4 context target drift"):
        _load(config_root, evidence_root)


def test_v4_factory_emits_both_profiles_and_rechecks_runtime_pins(
    tmp_path: Path,
) -> None:
    from specstyle.production.context_config import (
        make_production_compiler_context_factory,
    )

    config_root, evidence_root = _write_v4_roots(tmp_path)
    loaded = _load(config_root, evidence_root)
    graph = _factory_graph()
    encoder = loaded.l2_threshold_profile.binding_pin
    graph = replace(
        graph,
        ip_adapter=ModelDescriptor(
            encoder.id,
            "ip_adapter",
            encoder.revision,
            encoder.sha256,
            "MIT",
            "APPROVED",
            "sdxl",
        ),
    )

    factory = make_production_compiler_context_factory(
        loaded, _factory_environment(), graph
    )
    context = factory("v1")

    assert tuple(profile.source for profile in context.threshold_profiles) == (
        "l2",
        "l3",
    )
    assert len(context.l3_plugins) == 1
    assert context.output_profile_capabilities[0].supported_domains == (
        "structure_only",
    )
    with pytest.raises(DomainError, match="runtime evidence binding"):
        factory("other-preprocessor")
    object.__setattr__(loaded, "threshold_profiles", ())
    with pytest.raises(DomainError):
        factory("v1")


def test_v4_draft_profiles_load_but_cannot_pass_production_gate(tmp_path: Path) -> None:
    from specstyle.production.context_config import (
        require_validated_production_threshold,
    )

    config_root, evidence_root = _write_v4_roots(tmp_path)
    document = json.loads((config_root / "context.json").read_text(encoding="utf-8"))
    for profile in document["threshold_profiles"]:
        profile["status"] = "DRAFT"
        profile["production_approval_sha256"] = None
        for metric in profile["metrics"]:
            metric["formal_evidence"] = None
    _write_document(config_root, document)

    loaded = _load(config_root, evidence_root)

    assert all(profile.status == "DRAFT" for profile in loaded.threshold_profiles)
    with pytest.raises(DomainError, match="PRODUCTION_THRESHOLD_NOT_VALIDATED"):
        require_validated_production_threshold(loaded)


@pytest.mark.parametrize("mutation", ("empty", "forged_validated"))
def test_v4_gate_revalidates_loader_issued_nested_profiles(
    tmp_path: Path, mutation: str
) -> None:
    from specstyle.production.context_config import (
        require_validated_production_threshold,
    )

    config_root, evidence_root = _write_v4_roots(tmp_path)
    document = json.loads((config_root / "context.json").read_text(encoding="utf-8"))
    for profile in document["threshold_profiles"]:
        profile["status"] = "DRAFT"
        profile["production_approval_sha256"] = None
        for metric in profile["metrics"]:
            metric["formal_evidence"] = None
    _write_document(config_root, document)
    loaded = _load(config_root, evidence_root)
    if mutation == "empty":
        object.__setattr__(loaded, "threshold_profiles", ())
    else:
        for profile in loaded.threshold_profiles:
            object.__setattr__(profile, "status", "VALIDATED")
            object.__setattr__(profile, "profile_approval", object())

    with pytest.raises(DomainError, match="PRODUCTION_THRESHOLD_NOT_VALIDATED"):
        require_validated_production_threshold(loaded)


def test_v4_factory_revalidates_nested_profile_collection(tmp_path: Path) -> None:
    from specstyle.production.context_config import (
        make_production_compiler_context_factory,
    )

    config_root, evidence_root = _write_v4_roots(tmp_path)
    loaded = _load(config_root, evidence_root)
    graph = _factory_graph()
    encoder = loaded.l2_threshold_profile.binding_pin
    graph = replace(
        graph,
        ip_adapter=ModelDescriptor(
            encoder.id,
            "ip_adapter",
            encoder.revision,
            encoder.sha256,
            "MIT",
            "APPROVED",
            "sdxl",
        ),
    )
    object.__setattr__(loaded, "threshold_profiles", ())

    with pytest.raises(DomainError):
        make_production_compiler_context_factory(loaded, _factory_environment(), graph)


@pytest.mark.parametrize("mutation", ("preprocessor_pin", "correlated_threshold"))
def test_v4_gate_rejects_correlated_metric_binding_drift(
    tmp_path: Path, mutation: str
) -> None:
    from specstyle.production.context_config import (
        make_production_compiler_context_factory,
        require_validated_production_threshold,
    )

    config_root, evidence_root = _write_v4_roots(tmp_path)
    loaded = _load(config_root, evidence_root)
    profile = loaded.threshold_profiles[0]
    binding = profile.metric_bindings[0]
    if mutation == "preprocessor_pin":
        object.__setattr__(
            binding,
            "preprocessor_pin",
            ResourcePin("other-preprocessor", "v1", Sha256("d" * 64)),
        )
    else:
        object.__setattr__(binding, "threshold", 999.0)
        object.__setattr__(profile.metrics[0], "value", 999.0)

    with pytest.raises(DomainError, match="PRODUCTION_THRESHOLD_NOT_VALIDATED"):
        require_validated_production_threshold(loaded)
    graph = _factory_graph()
    encoder = profile.binding_pin
    graph = replace(
        graph,
        ip_adapter=ModelDescriptor(
            encoder.id,
            "ip_adapter",
            encoder.revision,
            encoder.sha256,
            "MIT",
            "APPROVED",
            "sdxl",
        ),
    )
    with pytest.raises(DomainError):
        make_production_compiler_context_factory(loaded, _factory_environment(), graph)


def test_v4_factory_rejects_full_preprocessor_pin_drift(tmp_path: Path) -> None:
    from specstyle.production.context_config import (
        make_production_compiler_context_factory,
    )

    config_root, evidence_root = _write_v4_roots(tmp_path)
    loaded = _load(config_root, evidence_root)
    encoder = loaded.l2_threshold_profile.binding_pin
    graph = replace(
        _factory_graph(),
        ip_adapter=ModelDescriptor(
            encoder.id,
            "ip_adapter",
            encoder.revision,
            encoder.sha256,
            "MIT",
            "APPROVED",
            "sdxl",
        ),
    )
    object.__setattr__(
        loaded.source_preprocess,
        "processor_pin",
        ResourcePin("other-preprocessor", "v1", Sha256("d" * 64)),
    )

    with pytest.raises(DomainError, match="runtime evidence binding"):
        make_production_compiler_context_factory(loaded, _factory_environment(), graph)


@pytest.mark.parametrize(
    "mutation",
    (
        "legacy_key",
        "missing_l3",
        "duplicate_profile",
        "duplicate_metric",
        "cross_profile_metric",
        "operator",
        "implementation_pin",
        "formal_hash",
        "approval",
    ),
)
def test_v4_rejects_incomplete_or_cross_bound_formal_context(
    tmp_path: Path, mutation: str
) -> None:
    config_root, evidence_root = _write_v4_roots(tmp_path)
    document = json.loads((config_root / "context.json").read_text(encoding="utf-8"))
    if mutation == "legacy_key":
        document["l2_threshold_profile"] = document["threshold_profiles"][0]
    elif mutation == "missing_l3":
        document["threshold_profiles"].pop()
    elif mutation == "duplicate_profile":
        document["threshold_profiles"][1] = document["threshold_profiles"][0]
    elif mutation == "duplicate_metric":
        document["threshold_profiles"][0]["metrics"].append(
            document["threshold_profiles"][0]["metrics"][0]
        )
    elif mutation == "cross_profile_metric":
        document["threshold_profiles"][1]["metrics"][0]["metric_id"] = (
            "reference_style_statistics_similarity"
        )
    elif mutation == "operator":
        document["threshold_profiles"][0]["metrics"][0]["operator"] = ">="
    elif mutation == "implementation_pin":
        document["threshold_profiles"][0]["metrics"][0]["implementation_pin"] = _pin(
            "other-implementation", "c"
        )
    elif mutation == "formal_hash":
        formal = document["threshold_profiles"][0]["metrics"][0]["formal_evidence"]
        formal["prepared_evidence_sha256"] = formal["test_reveal_sha256"]
    else:
        document["threshold_profiles"][1]["production_approval_sha256"] = document[
            "threshold_profiles"
        ][0]["production_approval_sha256"]
    _write_document(config_root, document)

    with pytest.raises(DomainError):
        _load(config_root, evidence_root)
