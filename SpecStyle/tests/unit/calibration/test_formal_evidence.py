from __future__ import annotations

import json

import pytest

from specstyle.calibration.evidence import canonical_json, evidence_sha256
from specstyle.calibration.formal_evidence import (
    prepare_metric_evidence,
    reveal_metric_test,
)
from specstyle.calibration.splits import assign_split
from specstyle.calibration.target_cell import load_target_cell
from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes


def _sha(value: str) -> str:
    return hash_bytes(value.encode()).value


def _pin(name: str) -> dict[str, str]:
    return {"id": name, "revision": "v1", "sha256": _sha(name)}


def _target_cell(*, suffix: str = "") -> bytes:
    metrics = [
        {
            "layer": "L2",
            "observation_unit": "batch",
            "metric_id": "batch_style_consistency",
            "operator": "lte",
            "implementation_pin": _pin(f"batch-metric{suffix}"),
            "binding_pin": _pin(f"style-encoder{suffix}"),
            "verifier_pin": _pin(f"style-verifier{suffix}"),
            "preprocessor_pin": _pin(f"style-preprocessor{suffix}"),
        },
        {
            "layer": "L2",
            "observation_unit": "item",
            "metric_id": "reference_style_statistics_similarity",
            "operator": "gte",
            "implementation_pin": _pin(f"style-metric{suffix}"),
            "binding_pin": _pin(f"style-encoder{suffix}"),
            "verifier_pin": _pin(f"style-verifier{suffix}"),
            "preprocessor_pin": _pin(f"style-preprocessor{suffix}"),
        },
        {
            "layer": "L3",
            "observation_unit": "item",
            "metric_id": "structure_edge_similarity",
            "operator": "gte",
            "implementation_pin": _pin(f"structure-metric{suffix}"),
            "binding_pin": _pin(f"structure-plugin{suffix}"),
            "verifier_pin": _pin(f"structure-verifier{suffix}"),
            "preprocessor_pin": _pin(f"edge-preprocessor{suffix}"),
        },
    ]
    return canonical_json(
        {
            "schema_version": "specstyle.production.target_cell.v1",
            "style_pack_id": "editorial-clean",
            "style_pack_pin": _pin(f"editorial-clean{suffix}"),
            "domain_profile": "structure_only",
            "domain_verifier_version": "structure-v1",
            "output_profile": "xhs_grid",
            "output_profile_pin": _pin(f"xhs-grid{suffix}"),
            "generation_profile": "production",
            "compiler_pin": _pin(f"compiler{suffix}"),
            "rule_catalog_pin": _pin(f"rules{suffix}"),
            "metrics": metrics,
        }
    )


def _group_for(split: str, salt: str, index: int) -> str:
    candidate = index
    while True:
        digest = Sha256(_sha(f"group:{split}:{candidate}"))
        if assign_split(digest, salt) == split:
            return digest.value
        candidate += 1


def _cohort(sample_id: str, index: int) -> tuple[str, list[dict[str, object]]]:
    members = [
        {
            "member_id": f"{sample_id}-member-{member}",
            "candidate_sha256": _sha(f"candidate:{index}:{member}"),
            "source_family_sha256": _sha(f"source-family:{index}:{member}"),
            "reference_family_sha256": _sha(f"reference-family:{index}:{member}"),
            "seed": index * 10 + member,
        }
        for member in range(2)
    ]
    material = canonical_json({"expected_count": 2, "members": members})
    return evidence_sha256(material).value, members


def _samples(
    unit: str, salt: str
) -> tuple[list[dict[str, object]], dict[str, list[dict[str, object]]]]:
    samples: list[dict[str, object]] = []
    observations = {name: [] for name in ("calibration", "validation", "test")}
    index = 0
    for split in observations:
        for positive in (True, False):
            sample_id = f"sample-{index}"
            annotation = _sha(f"annotation:{index}:{positive}")
            common = {
                "sample_id": sample_id,
                "isolation_group_sha256": _group_for(split, salt, index),
                "split": split,
                "annotation_record_sha256": annotation,
                "provenance_record_sha256": _sha(f"provenance:{index}"),
            }
            if unit == "item":
                binding = _sha(f"candidate:{index}")
                sample = {
                    **common,
                    "candidate_sha256": binding,
                    "source_family_sha256": _sha(f"source-family:{index}"),
                    "reference_family_sha256": _sha(f"reference-family:{index}"),
                }
            else:
                binding, members = _cohort(sample_id, index)
                sample = {
                    **common,
                    "cohort_sha256": binding,
                    "expected_count": len(members),
                    "members": members,
                }
            samples.append(sample)
            observations[split].append(
                {
                    "sample_id": sample_id,
                    "sample_binding_sha256": binding,
                    "score": (0.1 if positive else 0.9)
                    if unit == "batch"
                    else (0.9 if positive else 0.1),
                    "label_positive": positive,
                    "annotation_record_sha256": annotation,
                }
            )
            index += 1
    return samples, observations


def _documents(metric_id: str, *, label_source: str = "HUMAN_APPROVED"):
    target = _target_cell()
    target_sha = evidence_sha256(target).value
    unit = "batch" if metric_id == "batch_style_consistency" else "item"
    layer = "L3" if metric_id == "structure_edge_similarity" else "L2"
    operator = "lte" if unit == "batch" else "gte"
    salt = f"{metric_id}-salt"
    protocol = canonical_json(
        {
            "schema_version": "specstyle.annotation_protocol.v2",
            "protocol_id": f"{metric_id}-human-v1",
            "target_cell_sha256": target_sha,
            "observation_unit": unit,
            "metric_id": metric_id,
            "label_definition": "positive means the frozen metric claim is usable",
        }
    )
    plan = canonical_json(
        {
            "schema_version": "specstyle.calibration.study_plan.v2",
            "study_id": f"{metric_id}-study-v1",
            "target_cell_sha256": target_sha,
            "layer": layer,
            "observation_unit": unit,
            "metric_id": metric_id,
            "operator": operator,
            "targets": {"min_tpr": 1.0, "max_fpr": 0.0},
            "split": {
                "algorithm": "sha256_mod_60_20_20",
                "salt": salt,
                "minimum_positive_per_split": 1,
                "minimum_negative_per_split": 1,
            },
            "annotation_protocol_sha256": evidence_sha256(protocol).value,
        }
    )
    samples, observations = _samples(unit, salt)
    manifest = canonical_json(
        {
            "schema_version": "specstyle.calibration.sample_manifest.v2",
            "target_cell_sha256": target_sha,
            "study_plan_sha256": evidence_sha256(plan).value,
            "observation_unit": unit,
            "samples": samples,
        }
    )
    manifest_sha = evidence_sha256(manifest).value

    def observation(split: str) -> bytes:
        return canonical_json(
            {
                "schema_version": "specstyle.calibration.observations.v2",
                "target_cell_sha256": target_sha,
                "study_plan_sha256": evidence_sha256(plan).value,
                "sample_manifest_sha256": manifest_sha,
                "split": split,
                "observation_unit": unit,
                "metric_id": metric_id,
                "operator": operator,
                "observations": observations[split],
            }
        )

    calibration = observation("calibration")
    validation = observation("validation")
    test = observation("test")
    commitment = canonical_json(
        {
            "schema_version": "specstyle.calibration.test_commitment.v2",
            "target_cell_sha256": target_sha,
            "study_plan_sha256": evidence_sha256(plan).value,
            "sample_manifest_sha256": manifest_sha,
            "observation_unit": unit,
            "sealed_test_observations_sha256": evidence_sha256(test).value,
            "sample_ids": [row["sample_id"] for row in observations["test"]],
            "sample_bindings_sha256": hash_bytes(
                canonical_json(
                    [row["sample_binding_sha256"] for row in observations["test"]]
                )
            ).value,
            "positive_count": 1,
            "negative_count": 1,
        }
    )
    approval = canonical_json(
        {
            "schema_version": "specstyle.calibration.approval_receipt.v2",
            "receipt_id": f"{metric_id}-labels-approved-v1",
            "study_id": f"{metric_id}-study-v1",
            "target_cell_sha256": target_sha,
            "approval_kind": "HUMAN_LABELS",
            "approved": True,
            "label_source": label_source,
            "observation_unit": unit,
            "study_plan_sha256": evidence_sha256(plan).value,
            "sample_manifest_sha256": manifest_sha,
            "annotation_protocol_sha256": evidence_sha256(protocol).value,
            "observation_sha256s": [
                evidence_sha256(calibration).value,
                evidence_sha256(validation).value,
                evidence_sha256(test).value,
            ],
            "approver_id": "independent-label-reviewer",
            "issued_at": "2026-08-04T00:00:00Z",
        }
    )
    return {
        "target": target,
        "protocol": protocol,
        "plan": plan,
        "manifest": manifest,
        "calibration": calibration,
        "validation": validation,
        "test": test,
        "commitment": commitment,
        "approval": approval,
    }


def _prepare(documents: dict[str, bytes]) -> bytes:
    return prepare_metric_evidence(
        documents["target"],
        documents["plan"],
        documents["protocol"],
        documents["manifest"],
        documents["calibration"],
        documents["validation"],
        documents["commitment"],
        documents["approval"],
    )


def _replace_manifest(documents: dict[str, bytes], manifest: dict[str, object]) -> None:
    documents["manifest"] = canonical_json(manifest)
    manifest_sha = evidence_sha256(documents["manifest"]).value
    samples_by_split = {
        split: [sample for sample in manifest["samples"] if sample["split"] == split]
        for split in ("calibration", "validation", "test")
    }
    observation_sha256s = []
    for split in ("calibration", "validation", "test"):
        observation = json.loads(documents[split])
        observation["sample_manifest_sha256"] = manifest_sha
        for row, sample in zip(
            observation["observations"], samples_by_split[split], strict=True
        ):
            row["sample_binding_sha256"] = sample.get(
                "cohort_sha256", sample.get("candidate_sha256")
            )
        documents[split] = canonical_json(observation)
        observation_sha256s.append(evidence_sha256(documents[split]).value)

    test = json.loads(documents["test"])
    commitment = json.loads(documents["commitment"])
    commitment["sample_manifest_sha256"] = manifest_sha
    commitment["sealed_test_observations_sha256"] = observation_sha256s[-1]
    commitment["sample_bindings_sha256"] = hash_bytes(
        canonical_json([row["sample_binding_sha256"] for row in test["observations"]])
    ).value
    documents["commitment"] = canonical_json(commitment)

    approval = json.loads(documents["approval"])
    approval["sample_manifest_sha256"] = manifest_sha
    approval["observation_sha256s"] = observation_sha256s
    documents["approval"] = canonical_json(approval)


def _reveal_receipt(prepared: bytes, documents: dict[str, bytes]) -> bytes:
    plan = json.loads(documents["plan"])
    return canonical_json(
        {
            "schema_version": "specstyle.calibration.reveal_receipt.v2",
            "receipt_id": f"{plan['study_id']}-reveal-v1",
            "study_id": plan["study_id"],
            "target_cell_sha256": evidence_sha256(documents["target"]).value,
            "approval_kind": "REVEAL_TEST",
            "approved": True,
            "validation_report_sha256": evidence_sha256(prepared).value,
            "sealed_test_observations_sha256": evidence_sha256(documents["test"]).value,
            "approver_id": "independent-reveal-reviewer",
            "issued_at": "2026-08-04T01:00:00Z",
        }
    )


@pytest.mark.parametrize(
    ("metric_id", "expected_threshold"),
    (
        ("batch_style_consistency", 0.1),
        ("structure_edge_similarity", 0.9),
    ),
)
def test_v2_prepares_and_reveals_operator_aware_metric_evidence(
    metric_id: str, expected_threshold: float
) -> None:
    documents = _documents(metric_id)
    prepared = _prepare(documents)
    report = json.loads(prepared)

    assert report["status"] == "VALIDATION_PASSED"
    assert report["threshold"] == expected_threshold
    assert report["observation_unit"] == (
        "batch" if metric_id == "batch_style_consistency" else "item"
    )
    revealed = json.loads(
        reveal_metric_test(
            documents["target"],
            prepared,
            documents["test"],
            _reveal_receipt(prepared, documents),
        )
    )
    assert revealed["status"] == "TEST_PASSED_PENDING_PRODUCTION_APPROVAL"
    assert revealed["test"]["tpr"] == 1.0
    assert revealed["test"]["fpr"] == 0.0


def test_batch_manifest_rejects_cohort_hash_drift() -> None:
    documents = _documents("batch_style_consistency")
    manifest = json.loads(documents["manifest"])
    manifest["samples"][0]["members"][0]["seed"] += 1
    documents["manifest"] = canonical_json(manifest)

    with pytest.raises(DomainError, match="cohort"):
        _prepare(documents)


def test_batch_manifest_rejects_family_leakage_across_splits() -> None:
    documents = _documents("batch_style_consistency")
    manifest = json.loads(documents["manifest"])
    shared = manifest["samples"][0]["members"][0]["source_family_sha256"]
    manifest["samples"][-1]["members"][0]["source_family_sha256"] = shared
    cohort = manifest["samples"][-1]
    cohort["cohort_sha256"] = evidence_sha256(
        canonical_json(
            {"expected_count": cohort["expected_count"], "members": cohort["members"]}
        )
    ).value
    _replace_manifest(documents, manifest)

    with pytest.raises(DomainError, match="family split leakage"):
        _prepare(documents)


@pytest.mark.parametrize(
    ("field", "message"),
    (
        ("candidate_sha256", "candidate split leakage"),
        ("member_id", "member split leakage"),
    ),
)
def test_batch_manifest_rejects_member_leakage_across_splits(
    field: str, message: str
) -> None:
    documents = _documents("batch_style_consistency")
    manifest = json.loads(documents["manifest"])
    shared = manifest["samples"][0]["members"][0][field]
    cohort = manifest["samples"][-1]
    cohort["members"][0][field] = shared
    cohort["cohort_sha256"] = evidence_sha256(
        canonical_json(
            {"expected_count": cohort["expected_count"], "members": cohort["members"]}
        )
    ).value
    _replace_manifest(documents, manifest)

    with pytest.raises(DomainError, match=message):
        _prepare(documents)


def test_v2_synthetic_labels_never_freeze_threshold() -> None:
    report = json.loads(
        _prepare(_documents("structure_edge_similarity", label_source="SYNTHETIC"))
    )

    assert report["status"] == "BLOCKED"
    assert report["reasons"] == ["BLOCKED_SYNTHETIC_LABELS"]
    assert report["threshold"] is None


@pytest.mark.parametrize(
    ("field", "value"), (("operator", "gte"), ("observation_unit", "item"))
)
def test_v2_study_cannot_drift_from_target_metric(field: str, value: str) -> None:
    documents = _documents("batch_style_consistency")
    plan = json.loads(documents["plan"])
    plan[field] = value
    documents["plan"] = canonical_json(plan)

    with pytest.raises(DomainError, match="formal study plan"):
        _prepare(documents)


def test_target_cell_requires_the_complete_three_metric_contract() -> None:
    target = json.loads(_target_cell())
    target["metrics"] = target["metrics"][:-1]

    with pytest.raises(DomainError, match="target cell"):
        load_target_cell(canonical_json(target))
