"""Operator workspace commands for formal metric approval evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from specstyle.errors import DomainError
from tests.unit.calibration.test_formal_approval import (
    _metric_material,
    _profile_approval,
)
from tests.unit.calibration.test_formal_evidence import (
    _documents,
    _reveal_receipt,
)


def _write(path: Path, content: bytes) -> None:
    path.write_bytes(content)
    path.chmod(0o600)


def _workspace(tmp_path: Path, metric_id: str) -> tuple[Path, dict[str, bytes]]:
    root = tmp_path / metric_id
    root.mkdir(mode=0o700)
    documents = _documents(metric_id)
    names = {
        "target_cell.json": "target",
        "study_plan.json": "plan",
        "annotation_protocol.json": "protocol",
        "sample_manifest.json": "manifest",
        "calibration_observations.json": "calibration",
        "validation_observations.json": "validation",
        "test_commitment.json": "commitment",
        "label_approval_receipt.json": "approval",
        "sealed_test_observations.json": "test",
    }
    for filename, key in names.items():
        _write(root / filename, documents[key])
    return root, documents


def test_workspace_prepare_reveal_and_metric_approval_validation(
    tmp_path: Path,
) -> None:
    from specstyle.calibration.formal_study_workspace import (
        prepare_workspace,
        reveal_workspace,
        validate_metric_workspace,
    )

    root, documents = _workspace(tmp_path, "structure_edge_similarity")
    prepared_path = prepare_workspace(root)
    prepared = prepared_path.read_bytes()
    _write(root / "reveal_receipt.json", _reveal_receipt(prepared, documents))

    reveal_path = reveal_workspace(root)
    material = _metric_material("structure_edge_similarity")
    _write(root / "metric_production_approval.json", material[1])
    binding = validate_metric_workspace(root)

    assert json.loads(prepared)["status"] == "VALIDATION_PASSED"
    assert json.loads(reveal_path.read_bytes())["status"] == (
        "TEST_PASSED_PENDING_PRODUCTION_APPROVAL"
    )
    assert binding.metric_id.value == "structure_edge_similarity"
    assert binding.layer == "L3"


def test_workspace_outputs_are_idempotent_but_refuse_drift(tmp_path: Path) -> None:
    from specstyle.calibration.formal_study_workspace import prepare_workspace

    root, _documents_by_name = _workspace(
        tmp_path, "reference_style_statistics_similarity"
    )
    first = prepare_workspace(root).read_bytes()
    assert prepare_workspace(root).read_bytes() == first
    _write(root / "prepared_evidence.json", b"{}")

    with pytest.raises(DomainError, match="^formal study output drift$"):
        prepare_workspace(root)


def test_workspace_rejects_untrusted_permissions_and_unresolved_template(
    tmp_path: Path,
) -> None:
    from specstyle.calibration.formal_study_workspace import prepare_workspace

    root, _documents_by_name = _workspace(tmp_path, "batch_style_consistency")
    plan = root / "study_plan.json"
    plan.chmod(0o666)
    with pytest.raises(DomainError, match="^invalid formal study workspace$"):
        prepare_workspace(root)
    plan.chmod(0o600)
    _write(plan, b'{"value":"${UNRESOLVED}"}')
    with pytest.raises(DomainError):
        prepare_workspace(root)


def test_submission_templates_are_json_and_cannot_be_mistaken_for_evidence() -> None:
    root = (
        Path(__file__).parents[3]
        / "submission"
        / "track1-specstyle"
        / "formal-study-kit"
    )
    templates = sorted((root / "templates").glob("*.json"))

    assert len(templates) == 13
    for template in templates:
        parsed = json.loads(template.read_text(encoding="utf-8"))
        if template.name == "threshold_profile_pin.json":
            assert set(parsed) == {"id", "revision", "sha256"}
        else:
            assert parsed["schema_version"].startswith("specstyle.")
        assert "${" in template.read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "Production approver: `guan`" in readme
    assert "does not declare a repository code license" in readme


def test_workspace_validates_independent_l2_and_l3_profile_approvals(
    tmp_path: Path,
) -> None:
    from specstyle.calibration.evidence import canonical_json, evidence_sha256
    from specstyle.calibration.formal_study_workspace import (
        prepare_workspace,
        reveal_workspace,
        validate_profile_workspace,
    )

    metric_roots: dict[str, Path] = {}
    target: bytes | None = None
    approvals: dict[str, bytes] = {}
    for metric_id in (
        "batch_style_consistency",
        "reference_style_statistics_similarity",
        "structure_edge_similarity",
    ):
        root, documents = _workspace(tmp_path, metric_id)
        prepared = prepare_workspace(root).read_bytes()
        _write(root / "reveal_receipt.json", _reveal_receipt(prepared, documents))
        reveal_workspace(root)
        material = _metric_material(metric_id)
        _write(root / "metric_production_approval.json", material[1])
        metric_roots[metric_id] = root
        target = documents["target"]
        approvals[metric_id] = material[1]
    assert target is not None

    def profile(source: str, metric_ids: tuple[str, ...], marker: str) -> Path:
        root = tmp_path / f"profile-{source}"
        root.mkdir(mode=0o700)
        pin = {"id": f"{source}-profile", "revision": "v1", "sha256": marker * 64}
        _write(root / "target_cell.json", target)
        _write(root / "threshold_profile_pin.json", canonical_json(pin))
        _write(
            root / "profile_approval.json",
            _profile_approval(
                target,
                source,
                [evidence_sha256(approvals[item]).value for item in metric_ids],
                pin,
            ),
        )
        return root

    l2_metrics = (
        "batch_style_consistency",
        "reference_style_statistics_similarity",
    )
    l2 = validate_profile_workspace(
        profile("l2", l2_metrics, "a"),
        tuple(metric_roots[item] for item in l2_metrics),
    )
    l3 = validate_profile_workspace(
        profile("l3", ("structure_edge_similarity",), "b"),
        (metric_roots["structure_edge_similarity"],),
    )

    assert l2.source == "l2"
    assert {item.metric_id.value for item in l2.metrics} == set(l2_metrics)
    assert l3.source == "l3"


def test_materialized_batch_template_passes_complete_cohort_parser() -> None:
    from specstyle.calibration.evidence import canonical_json, evidence_sha256
    from specstyle.calibration.formal_evidence import _cohort
    from specstyle.observability.hashing import hash_bytes

    template = (
        Path(__file__).parents[3]
        / "submission"
        / "track1-specstyle"
        / "formal-study-kit"
        / "templates"
        / "batch_sample_manifest.json"
    )
    sample = json.loads(template.read_text(encoding="utf-8"))["samples"][0]
    members = []
    for index, member in enumerate(sample["members"]):
        members.append(
            {
                "member_id": f"member-{index}",
                "candidate_sha256": hash_bytes(f"candidate-{index}".encode()).value,
                "source_family_sha256": hash_bytes(f"source-{index}".encode()).value,
                "reference_family_sha256": hash_bytes(
                    f"reference-{index}".encode()
                ).value,
                "seed": member["seed"],
            }
        )
    sample["members"] = members
    sample["cohort_sha256"] = evidence_sha256(
        canonical_json({"expected_count": 4, "members": members})
    ).value

    binding, families, candidates, member_ids = _cohort(sample)

    assert binding == sample["cohort_sha256"]
    assert len(families) == 8
    assert len(candidates) == 4
    assert member_ids == tuple(f"member-{index}" for index in range(4))
