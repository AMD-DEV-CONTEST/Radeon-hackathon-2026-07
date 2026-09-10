"""Auditable held-out calibration evidence contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from specstyle.calibration.evidence import (
    canonical_json,
    evidence_sha256,
    prepare_evidence,
    reveal_test,
)
from specstyle.calibration.evidence_cli import main
from specstyle.calibration.splits import assign_split
from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes


def _sha(value: str) -> str:
    return hash_bytes(value.encode()).value


def _pin(name: str) -> dict[str, str]:
    return {"id": name, "revision": "v1", "sha256": _sha(name)}


def _group_for(split: str, index: int) -> str:
    candidate = index
    while True:
        digest = Sha256(_sha(f"group:{split}:{candidate}"))
        if assign_split(digest, "study-salt") == split:
            return digest.value
        candidate += 1


def _documents(*, label_source: str = "HUMAN_APPROVED", approved: bool = True):
    protocol = canonical_json(
        {
            "schema_version": "specstyle.annotation_protocol.v1",
            "protocol_id": "style-match-human-v1",
            "label_definition": "positive means usable style match",
        }
    )
    plan = {
        "schema_version": "specstyle.calibration.study_plan.v1",
        "study_id": "l2-style-v1",
        "layer": "L2",
        "style_pack_id": "editorial-clean",
        "domain_profile": "product_instance",
        "output_profiles": ["xhs_grid"],
        "metric": {
            "metric_id": "reference_style_statistics_similarity",
            "operator": "gte",
            "implementation_pin": _pin("style-statistics-metric"),
        },
        "verifier_pin": _pin("dinov2-style-encoder"),
        "preprocessor_pin": _pin("dinov2-preprocessor"),
        "targets": {"min_tpr": 1.0, "max_fpr": 0.0},
        "split": {
            "algorithm": "sha256_mod_60_20_20",
            "salt": "study-salt",
            "minimum_positive_per_split": 1,
            "minimum_negative_per_split": 1,
        },
        "annotation_protocol_sha256": evidence_sha256(protocol).value,
    }
    plan_bytes = canonical_json(plan)
    plan_hash = evidence_sha256(plan_bytes).value
    samples = []
    observations: dict[str, list[dict[str, object]]] = {
        "calibration": [],
        "validation": [],
        "test": [],
    }
    sample_index = 0
    for split_index, split in enumerate(observations):
        for positive in (True, False):
            sample_id = f"sample-{sample_index}"
            candidate_sha = _sha(f"candidate:{sample_index}")
            annotation_sha = _sha(f"annotation:{sample_index}:{positive}")
            samples.append(
                {
                    "sample_id": sample_id,
                    "candidate_sha256": candidate_sha,
                    "source_sha256": _sha(f"source:{sample_index}"),
                    "reference_sha256": _sha(f"reference:{sample_index}"),
                    "isolation_group_sha256": _group_for(
                        split, split_index * 10 + int(positive)
                    ),
                    "split": split,
                    "style_pack_id": "editorial-clean",
                    "domain_profile": "product_instance",
                    "output_profile": "xhs_grid",
                    "annotation_record_sha256": annotation_sha,
                    "provenance_record_sha256": _sha(f"provenance:{sample_index}"),
                }
            )
            observations[split].append(
                {
                    "sample_id": sample_id,
                    "candidate_sha256": candidate_sha,
                    "score": 0.9 if positive else 0.1,
                    "label_positive": positive,
                    "annotation_record_sha256": annotation_sha,
                }
            )
            sample_index += 1
    manifest = {
        "schema_version": "specstyle.calibration.sample_manifest.v1",
        "study_plan_sha256": plan_hash,
        "samples": samples,
    }
    manifest_bytes = canonical_json(manifest)
    manifest_hash = evidence_sha256(manifest_bytes).value

    def observation(split: str) -> bytes:
        return canonical_json(
            {
                "schema_version": "specstyle.calibration.observations.v1",
                "study_plan_sha256": plan_hash,
                "sample_manifest_sha256": manifest_hash,
                "split": split,
                "metric_id": "reference_style_statistics_similarity",
                "metric_implementation_pin": _pin("style-statistics-metric"),
                "verifier_pin": _pin("dinov2-style-encoder"),
                "preprocessor_pin": _pin("dinov2-preprocessor"),
                "observations": observations[split],
            }
        )

    calibration = observation("calibration")
    validation = observation("validation")
    test = observation("test")
    commitment = canonical_json(
        {
            "schema_version": "specstyle.calibration.test_commitment.v1",
            "study_plan_sha256": plan_hash,
            "sample_manifest_sha256": manifest_hash,
            "sealed_test_observations_sha256": evidence_sha256(test).value,
            "sample_ids": [row["sample_id"] for row in observations["test"]],
            "positive_count": 1,
            "negative_count": 1,
        }
    )
    approval = canonical_json(
        {
            "schema_version": "specstyle.calibration.approval_receipt.v1",
            "receipt_id": "labels-approved-v1",
            "study_id": "l2-style-v1",
            "approval_kind": "HUMAN_LABELS",
            "approved": approved,
            "label_source": label_source,
            "study_plan_sha256": plan_hash,
            "sample_manifest_sha256": manifest_hash,
            "annotation_protocol_sha256": evidence_sha256(protocol).value,
            "observation_sha256s": [
                evidence_sha256(calibration).value,
                evidence_sha256(validation).value,
                evidence_sha256(test).value,
            ],
            "approver_id": "independent-reviewer-1",
            "issued_at": "2026-08-03T00:00:00Z",
        }
    )
    return {
        "protocol": protocol,
        "plan": plan_bytes,
        "manifest": manifest_bytes,
        "calibration": calibration,
        "validation": validation,
        "test": test,
        "commitment": commitment,
        "approval": approval,
    }


def _prepare(documents: dict[str, bytes]) -> bytes:
    return prepare_evidence(
        documents["plan"],
        documents["protocol"],
        documents["manifest"],
        documents["calibration"],
        documents["validation"],
        documents["commitment"],
        documents["approval"],
    )


def _reveal_receipt(prepared: bytes, test: bytes) -> bytes:
    return canonical_json(
        {
            "schema_version": "specstyle.calibration.reveal_receipt.v1",
            "receipt_id": "reveal-approved-v1",
            "study_id": "l2-style-v1",
            "approval_kind": "REVEAL_TEST",
            "approved": True,
            "validation_report_sha256": evidence_sha256(prepared).value,
            "sealed_test_observations_sha256": evidence_sha256(test).value,
            "approver_id": "independent-reviewer-2",
            "issued_at": "2026-08-03T01:00:00Z",
        }
    )


def test_prepare_freezes_threshold_without_production_validation() -> None:
    documents = _documents()
    report = json.loads(_prepare(documents))

    assert report["status"] == "VALIDATION_PASSED"
    assert report["status"] != "VALIDATED"
    assert report["threshold"] == 0.9
    assert report["calibration"]["confusion"] == {
        "fn": 0,
        "fp": 0,
        "tn": 1,
        "tp": 1,
    }
    assert report["validation"]["tpr"] == 1.0
    assert report["test_held"] is True


@pytest.mark.parametrize(
    ("label_source", "approved", "reason"),
    [
        ("SYNTHETIC", True, "BLOCKED_SYNTHETIC_LABELS"),
        ("HUMAN_APPROVED", False, "BLOCKED_MISSING_APPROVED_LABELS"),
    ],
)
def test_prepare_blocks_unapproved_labels(
    label_source: str, approved: bool, reason: str
) -> None:
    report = json.loads(
        _prepare(_documents(label_source=label_source, approved=approved))
    )

    assert report["status"] == "BLOCKED"
    assert report["reasons"] == [reason]
    assert report["threshold"] is None


def test_prepare_rejects_split_assignment_drift() -> None:
    documents = _documents()
    manifest = json.loads(documents["manifest"])
    manifest["samples"][0]["split"] = "test"
    documents["manifest"] = canonical_json(manifest)

    with pytest.raises(DomainError, match="split assignment"):
        _prepare(documents)


def test_prepare_requires_bound_annotation_protocol() -> None:
    documents = _documents()
    documents["protocol"] = canonical_json(
        {
            "schema_version": "specstyle.annotation_protocol.v1",
            "protocol_id": "different-protocol",
            "label_definition": "different labels",
        }
    )

    with pytest.raises(DomainError, match="annotation protocol"):
        _prepare(documents)


def test_prepare_requires_one_output_profile_per_study() -> None:
    documents = _documents()
    plan = json.loads(documents["plan"])
    plan["output_profiles"] = ["xhs_grid", "talking_head_cover"]
    documents["plan"] = canonical_json(plan)

    with pytest.raises(DomainError, match="one output profile"):
        _prepare(documents)


def test_canonical_loader_rejects_duplicate_keys_and_noncanonical_bytes() -> None:
    documents = _documents()
    pretty = json.dumps(json.loads(documents["plan"]), indent=2).encode()
    duplicate = b'{"schema_version":"a","schema_version":"b"}'

    with pytest.raises(DomainError, match="canonical"):
        prepare_evidence(
            pretty,
            documents["protocol"],
            documents["manifest"],
            documents["calibration"],
            documents["validation"],
            documents["commitment"],
            documents["approval"],
        )
    with pytest.raises(DomainError, match="duplicate"):
        evidence_sha256(duplicate)


def test_reveal_test_requires_authorization_and_keeps_frozen_threshold() -> None:
    documents = _documents()
    prepared = _prepare(documents)
    reveal_receipt = _reveal_receipt(prepared, documents["test"])

    report = json.loads(reveal_test(prepared, documents["test"], reveal_receipt))

    assert report["status"] == "TEST_PASSED_PENDING_PRODUCTION_APPROVAL"
    assert report["threshold"] == json.loads(prepared)["threshold"]
    assert report["test"]["confusion"]["tp"] == 1
    assert report["eligible_context_status"] == "CALIBRATED"


@pytest.mark.parametrize(
    "drift",
    ("sample_id", "candidate_sha256", "annotation_record_sha256", "label_count"),
)
def test_reveal_test_rejects_committed_test_content_drift(drift: str) -> None:
    documents = _documents()
    test = json.loads(documents["test"])
    if drift == "sample_id":
        test["observations"][0]["sample_id"] = "replacement-sample"
    elif drift in {"candidate_sha256", "annotation_record_sha256"}:
        test["observations"][0][drift] = _sha(f"replacement:{drift}")
    else:
        test["observations"][0]["label_positive"] = False
    documents["test"] = canonical_json(test)
    commitment = json.loads(documents["commitment"])
    commitment["sealed_test_observations_sha256"] = evidence_sha256(
        documents["test"]
    ).value
    documents["commitment"] = canonical_json(commitment)
    approval = json.loads(documents["approval"])
    approval["observation_sha256s"][2] = evidence_sha256(documents["test"]).value
    documents["approval"] = canonical_json(approval)
    prepared = _prepare(documents)

    with pytest.raises(DomainError, match="test commitment"):
        reveal_test(
            prepared,
            documents["test"],
            _reveal_receipt(prepared, documents["test"]),
        )


def test_reveal_test_rejects_commitment_or_receipt_drift() -> None:
    documents = _documents()
    prepared = _prepare(documents)
    receipt = {
        "schema_version": "specstyle.calibration.reveal_receipt.v1",
        "receipt_id": "reveal-approved-v1",
        "study_id": "l2-style-v1",
        "approval_kind": "REVEAL_TEST",
        "approved": True,
        "validation_report_sha256": evidence_sha256(prepared).value,
        "sealed_test_observations_sha256": "0" * 64,
        "approver_id": "independent-reviewer-2",
        "issued_at": "2026-08-03T01:00:00Z",
    }

    with pytest.raises(DomainError, match="reveal receipt"):
        reveal_test(prepared, documents["test"], canonical_json(receipt))


def _write_documents(root: Path, documents: dict[str, bytes]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for name, content in documents.items():
        path = root / f"{name}.json"
        path.write_bytes(content)
        paths[name] = path
    return paths


def test_prepare_cli_writes_new_private_report(tmp_path: Path) -> None:
    paths = _write_documents(tmp_path, _documents())
    output = tmp_path / "prepared.json"

    exit_code = main(
        [
            "prepare",
            "--study-plan",
            str(paths["plan"]),
            "--annotation-protocol",
            str(paths["protocol"]),
            "--sample-manifest",
            str(paths["manifest"]),
            "--calibration-observations",
            str(paths["calibration"]),
            "--validation-observations",
            str(paths["validation"]),
            "--test-commitment",
            str(paths["commitment"]),
            "--label-approval-receipt",
            str(paths["approval"]),
            "--out",
            str(output),
        ]
    )

    assert exit_code == 0
    assert json.loads(output.read_bytes())["status"] == "VALIDATION_PASSED"
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(DomainError, match="already exists"):
        main(
            [
                "prepare",
                "--study-plan",
                str(paths["plan"]),
                "--annotation-protocol",
                str(paths["protocol"]),
                "--sample-manifest",
                str(paths["manifest"]),
                "--calibration-observations",
                str(paths["calibration"]),
                "--validation-observations",
                str(paths["validation"]),
                "--test-commitment",
                str(paths["commitment"]),
                "--label-approval-receipt",
                str(paths["approval"]),
                "--out",
                str(output),
            ]
        )


def test_blocked_cli_writes_evidence_and_returns_two(tmp_path: Path) -> None:
    paths = _write_documents(tmp_path, _documents(label_source="SYNTHETIC"))
    output = tmp_path / "blocked.json"

    exit_code = main(
        [
            "prepare",
            "--study-plan",
            str(paths["plan"]),
            "--annotation-protocol",
            str(paths["protocol"]),
            "--sample-manifest",
            str(paths["manifest"]),
            "--calibration-observations",
            str(paths["calibration"]),
            "--validation-observations",
            str(paths["validation"]),
            "--test-commitment",
            str(paths["commitment"]),
            "--label-approval-receipt",
            str(paths["approval"]),
            "--out",
            str(output),
        ]
    )

    assert exit_code == 2
    assert json.loads(output.read_bytes())["status"] == "BLOCKED"
