from __future__ import annotations

import json
import os
from pathlib import Path
from dataclasses import replace

import pytest

from specstyle.errors import DomainError, InfrastructureError
from specstyle.observability.hashing import hash_bytes


def _artifact(tmp_path: Path, run_id: str = "preview-job"):
    from specstyle.domain.identifiers import AttemptId, JobId
    from specstyle.generation.preview_diffusers_loader import load_preview_pipeline
    from specstyle.generation.preview_execution import (
        bind_preview_execution,
        build_preview_artifact,
    )
    from tests.unit.generation.test_preview_diffusers_runtime import (
        _Peft,
        _PreviewDiffusers,
        _Torch,
        _png,
        _runtime,
    )
    from tests.unit.generation.test_diffusers_loader import _environment

    supply, adapter, graph, request = _runtime(tmp_path / "models")
    request = replace(
        request,
        job_id=JobId(run_id),
        attempt_id=AttemptId(f"{run_id}-a0"),
    )
    loaded = load_preview_pipeline(
        supply,
        adapter,
        graph,
        _environment(),
        torch_module=_Torch(),
        diffusers_module=_PreviewDiffusers(),
        peft_module=_Peft(),
    )
    try:
        binding = bind_preview_execution(loaded, request)
        return build_preview_artifact(_png((512, 512), "green"), binding)
    finally:
        loaded.close()
        adapter.close()
        supply.close()


def _roots(tmp_path: Path) -> tuple[int, int, Path, Path]:
    private = tmp_path / "private"
    display = tmp_path / "display"
    private.mkdir(mode=0o700)
    display.mkdir(mode=0o700)
    return (
        os.open(private, os.O_RDONLY | os.O_DIRECTORY),
        os.open(display, os.O_RDONLY | os.O_DIRECTORY),
        private,
        display,
    )


def test_preview_evidence_atomically_publishes_private_pair_then_display(
    tmp_path: Path,
) -> None:
    from specstyle.workflow.preview_evidence import publish_preview_evidence

    artifact = _artifact(tmp_path, "preview-run-1")
    private_fd, display_fd, private, display = _roots(tmp_path)
    try:
        published = publish_preview_evidence(
            private_fd, display_fd, "preview-run-1", artifact
        )
    finally:
        os.close(display_fd)
        os.close(private_fd)

    evidence = private / published.evidence_name
    assert sorted(item.name for item in evidence.iterdir()) == [
        "artifact.png",
        "record.json",
    ]
    record = json.loads((evidence / "record.json").read_text(encoding="utf-8"))
    display_bytes = (display / published.display_name).read_bytes()
    assert record["schema_version"] == "specstyle.preview.evidence.v3"
    assert record["run_id"] == "preview-run-1"
    assert record["evidence_class"] == "ENGINEERING_ONLY"
    assert record["generation"] == {
        "variation_index": 0,
        "seed": {
            "algorithm": "specstyle.seed.v1",
            "value": published.seed,
        },
        "resolution": [512, 512],
    }
    assert record["artifact"]["content_sha256"] == hash_bytes(display_bytes).value
    assert record["artifact"]["execution_fingerprint"] == (
        artifact.execution_fingerprint.value
    )
    assert record["runtime"] == {
        "dtype": "float16",
        "vae_at_rest_dtype": "float16",
        "vae_compute_dtype": "float32",
        "vae_precision_policy": "diffusers_force_upcast_roundtrip_v1",
    }
    assert record["planes"] == {
        "verification": "NOT_RUN",
        "repair": "NOT_RUN",
        "export": "NOT_RUN",
    }
    assert "APPROVED" not in (evidence / "record.json").read_text()
    assert published.content_sha256 == hash_bytes(display_bytes)
    assert published.schema_version == "specstyle.preview.evidence.v3"
    assert published.runtime_dtype == "float16"
    assert published.vae_at_rest_dtype == "float16"
    assert published.vae_compute_dtype == "float32"
    assert published.vae_precision_policy == "diffusers_force_upcast_roundtrip_v1"
    assert published.variation_index == 0
    assert published.seed_algorithm == "specstyle.seed.v1"
    assert published.resolution == (512, 512)


def test_display_failure_never_returns_completed_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import specstyle.workflow.preview_evidence as module

    artifact = _artifact(tmp_path, "preview-run-display-fail")
    private_fd, display_fd, private, display = _roots(tmp_path)
    monkeypatch.setattr(
        module,
        "_publish_display",
        lambda *_args: (_ for _ in ()).throw(
            InfrastructureError("preview display unavailable")
        ),
    )
    try:
        with pytest.raises(InfrastructureError, match="display"):
            module.publish_preview_evidence(
                private_fd, display_fd, "preview-run-display-fail", artifact
            )
    finally:
        os.close(display_fd)
        os.close(private_fd)
    assert (private / "preview-run-display-fail" / "record.json").is_file()
    assert list(display.iterdir()) == []


def test_preview_evidence_rejects_cross_run_artifact_republication(
    tmp_path: Path,
) -> None:
    from specstyle.workflow.preview_evidence import publish_preview_evidence

    artifact = _artifact(tmp_path, "preview-original-run")
    private_fd, display_fd, _private, _display = _roots(tmp_path)
    try:
        with pytest.raises(DomainError, match="run binding"):
            publish_preview_evidence(
                private_fd, display_fd, "preview-different-run", artifact
            )
    finally:
        os.close(display_fd)
        os.close(private_fd)


def test_stored_v3_publication_is_reverified_before_wall_use(
    tmp_path: Path,
) -> None:
    from specstyle.workflow.preview_evidence import (
        publish_preview_evidence,
        verify_preview_evidence_publication,
    )

    run_id = "preview-verified-record"
    artifact = _artifact(tmp_path, run_id)
    private_fd, display_fd, private, _display = _roots(tmp_path)
    try:
        publication = publish_preview_evidence(private_fd, display_fd, run_id, artifact)
        verify_preview_evidence_publication(private_fd, publication)
        record_path = private / run_id / "record.json"
        record = json.loads(record_path.read_text())
        record["generation"]["seed"]["value"] += 1
        from specstyle.exporting.qa_report import canonical_json_bytes

        record_path.write_bytes(canonical_json_bytes(record))
        with pytest.raises(DomainError, match="publication mismatch"):
            verify_preview_evidence_publication(private_fd, publication)
    finally:
        os.close(display_fd)
        os.close(private_fd)


@pytest.mark.parametrize("corruption", ("extra_file", "noncanonical_record"))
def test_stored_v3_publication_rejects_record_structure_corruption(
    tmp_path: Path, corruption: str
) -> None:
    from specstyle.workflow.preview_evidence import (
        publish_preview_evidence,
        verify_preview_evidence_publication,
    )

    run_id = "preview-record-corruption"
    artifact = _artifact(tmp_path, run_id)
    private_fd, display_fd, private, _display = _roots(tmp_path)
    try:
        publication = publish_preview_evidence(private_fd, display_fd, run_id, artifact)
        evidence = private / run_id
        if corruption == "extra_file":
            (evidence / "extra").write_bytes(b"unexpected")
        else:
            record_path = evidence / "record.json"
            record = json.loads(record_path.read_text())
            record_path.write_text(json.dumps(record, indent=2))
        with pytest.raises(DomainError, match="record"):
            verify_preview_evidence_publication(private_fd, publication)
    finally:
        os.close(display_fd)
        os.close(private_fd)


def test_stored_v3_publication_rejects_compiled_fingerprint_tamper(
    tmp_path: Path,
) -> None:
    from specstyle.exporting.qa_report import canonical_json_bytes
    from specstyle.workflow.preview_evidence import (
        publish_preview_evidence,
        verify_preview_evidence_publication,
    )

    run_id = "preview-compiled-fingerprint"
    artifact = _artifact(tmp_path, run_id)
    private_fd, display_fd, private, _display = _roots(tmp_path)
    try:
        publication = publish_preview_evidence(private_fd, display_fd, run_id, artifact)
        record_path = private / run_id / "record.json"
        record = json.loads(record_path.read_text())
        record["artifact"]["compiled_request_fingerprint"] = "c" * 64
        record_path.write_bytes(canonical_json_bytes(record))
        with pytest.raises(DomainError, match="publication mismatch"):
            verify_preview_evidence_publication(private_fd, publication)
    finally:
        os.close(display_fd)
        os.close(private_fd)


def test_stored_v3_publication_rejects_vae_precision_policy_tamper(
    tmp_path: Path,
) -> None:
    from specstyle.exporting.qa_report import canonical_json_bytes
    from specstyle.workflow.preview_evidence import (
        publish_preview_evidence,
        verify_preview_evidence_publication,
    )

    run_id = "preview-vae-dtype"
    artifact = _artifact(tmp_path, run_id)
    private_fd, display_fd, private, _display = _roots(tmp_path)
    try:
        publication = publish_preview_evidence(private_fd, display_fd, run_id, artifact)
        record_path = private / run_id / "record.json"
        record = json.loads(record_path.read_text())
        record["runtime"]["vae_precision_policy"] = "untrusted"
        record_path.write_bytes(canonical_json_bytes(record))
        with pytest.raises(DomainError, match="record"):
            verify_preview_evidence_publication(private_fd, publication)
    finally:
        os.close(display_fd)
        os.close(private_fd)


def test_stored_v3_publication_rejects_invalid_call(tmp_path: Path) -> None:
    from specstyle.workflow.preview_evidence import verify_preview_evidence_publication

    private_fd, display_fd, _private, _display = _roots(tmp_path)
    try:
        with pytest.raises(DomainError):
            verify_preview_evidence_publication(private_fd, object())  # type: ignore[arg-type]
    finally:
        os.close(display_fd)
        os.close(private_fd)


def test_preview_evidence_rejects_tampered_generation_binding(
    tmp_path: Path,
) -> None:
    from specstyle.exporting.qa_report import canonical_json_bytes
    from specstyle.workflow.preview_evidence import publish_preview_evidence

    artifact = _artifact(tmp_path, "preview-tampered-generation")
    material = json.loads(artifact.binding.material_json)
    material["compiled_request"]["variation_index"] = 1
    object.__setattr__(
        artifact.binding,
        "material_json",
        canonical_json_bytes(material).decode("utf-8"),
    )
    private_fd, display_fd, _private, _display = _roots(tmp_path)
    try:
        with pytest.raises(DomainError, match="execution binding"):
            publish_preview_evidence(
                private_fd, display_fd, "preview-tampered-generation", artifact
            )
    finally:
        os.close(display_fd)
        os.close(private_fd)


def test_preview_evidence_is_no_replace_and_display_orphans_are_removed(
    tmp_path: Path,
) -> None:
    from specstyle.workflow.preview_evidence import (
        publish_preview_evidence,
        reconcile_preview_display,
    )

    artifact = _artifact(tmp_path, "preview-run-stable")
    private_fd, display_fd, _private, display = _roots(tmp_path)
    try:
        published = publish_preview_evidence(
            private_fd, display_fd, "preview-run-stable", artifact
        )
        with pytest.raises(DomainError, match="already exists"):
            publish_preview_evidence(
                private_fd, display_fd, "preview-run-stable", artifact
            )
        orphan = display / "orphan.png"
        orphan.write_bytes(artifact.content)
        orphan.chmod(0o600)
        removed = reconcile_preview_display(private_fd, display_fd)
    finally:
        os.close(display_fd)
        os.close(private_fd)
    assert removed == ("orphan.png",)
    assert not orphan.exists()
    assert (display / published.display_name).is_file()


def test_reconcile_keeps_legacy_v1_preview_evidence(tmp_path: Path) -> None:
    from specstyle.exporting.qa_report import canonical_json_bytes
    from specstyle.workflow.preview_evidence import (
        publish_preview_evidence,
        reconcile_preview_display,
    )

    artifact = _artifact(tmp_path, "preview-legacy-v1")
    private_fd, display_fd, private, display = _roots(tmp_path)
    try:
        published = publish_preview_evidence(
            private_fd, display_fd, "preview-legacy-v1", artifact
        )
        record_path = private / published.evidence_name / "record.json"
        record = json.loads(record_path.read_text())
        record["schema_version"] = "specstyle.preview.evidence.v1"
        record.pop("evidence_class")
        record.pop("generation")
        record.pop("runtime")
        record_path.write_bytes(canonical_json_bytes(record))

        removed = reconcile_preview_display(private_fd, display_fd)
    finally:
        os.close(display_fd)
        os.close(private_fd)
    assert removed == ()
    assert (display / published.display_name).is_file()


def test_reconcile_keeps_legacy_v2_preview_evidence(tmp_path: Path) -> None:
    from specstyle.exporting.qa_report import canonical_json_bytes
    from specstyle.workflow.preview_evidence import (
        publish_preview_evidence,
        reconcile_preview_display,
    )

    artifact = _artifact(tmp_path, "preview-legacy-v2")
    private_fd, display_fd, private, display = _roots(tmp_path)
    try:
        published = publish_preview_evidence(
            private_fd, display_fd, "preview-legacy-v2", artifact
        )
        record_path = private / published.evidence_name / "record.json"
        record = json.loads(record_path.read_text())
        record["schema_version"] = "specstyle.preview.evidence.v2"
        record.pop("runtime")
        record_path.write_bytes(canonical_json_bytes(record))

        removed = reconcile_preview_display(private_fd, display_fd)
    finally:
        os.close(display_fd)
        os.close(private_fd)
    assert removed == ()
    assert (display / published.display_name).is_file()


def test_reconcile_unlinks_display_symlink_without_following_target(
    tmp_path: Path,
) -> None:
    from specstyle.workflow.preview_evidence import reconcile_preview_display

    private_fd, display_fd, _private, display = _roots(tmp_path)
    target = tmp_path / "outside.png"
    target.write_bytes(b"must remain")
    link = display / "orphan-link.png"
    link.symlink_to(target)
    try:
        removed = reconcile_preview_display(private_fd, display_fd)
    finally:
        os.close(display_fd)
        os.close(private_fd)
    assert removed == ("orphan-link.png",)
    assert not link.exists()
    assert target.read_bytes() == b"must remain"
