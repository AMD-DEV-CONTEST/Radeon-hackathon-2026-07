"""SEC-001A candidates, local weights, fail-closed Diffusers loader."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.generation.candidates import (
    CandidateModel,
    LicenseEvidence,
    approved_production_registry,
    catalog_summary,
    default_candidates,
    with_license_status,
)
from specstyle.generation.diffusers_loader import load_pipeline, plan_local_load
from specstyle.generation.local_weights import resolve_weight
from specstyle.generation.model_approval import LicenseApproval
from specstyle.generation.model_registry import ModelDescriptor, ModelRegistry
from specstyle.generation.pipeline_factory import PipelineFactory
from specstyle.generation.weight_manifest import (
    ModelLoadEntrypoint,
    WeightFile,
    WeightManifest,
    manifest_sha256,
)
from specstyle.observability.hashing import hash_bytes, hash_file


def _sha(c: str = "a") -> Sha256:
    return Sha256(c * 64)


_REVISION = "a" * 40


def test_default_candidates_all_unknown_and_no_production_registry() -> None:
    cats = default_candidates()
    assert cats
    assert all(c.license_status == "UNKNOWN" for c in cats)
    summary = catalog_summary(cats)
    assert len(summary) == len(cats)
    assert all(row["license_status"] == "UNKNOWN" for row in summary)
    with pytest.raises(DomainError):
        approved_production_registry(cats, (), ())


def test_status_only_candidate_flip_cannot_build_production_registry() -> None:
    cats = default_candidates()
    with pytest.raises(DomainError, match="placeholder"):
        with_license_status(cats, "sdxl-base-1.0", "APPROVED")


def test_known_placeholder_digest_is_rejected_even_with_full_revision() -> None:
    candidate = replace(default_candidates()[0], revision=_REVISION)
    with pytest.raises(DomainError, match="placeholder digest"):
        with_license_status((candidate,), candidate.model_id, "APPROVED")

    descriptor = ModelDescriptor(
        candidate.model_id,
        candidate.role,
        candidate.revision,
        candidate.expected_sha256,
        "Apache-2.0",
        "APPROVED",
        candidate.family,
    )
    with pytest.raises(DomainError, match="placeholder digest"):
        ModelRegistry((descriptor,)).require_production(candidate.model_id)


@pytest.mark.parametrize(
    "license_spdx", [" UNKNOWN ", "tBd", "Placeholder", "Totally-Made-Up"]
)
def test_production_registry_rejects_reserved_license_values(
    license_spdx: str,
) -> None:
    descriptor = ModelDescriptor(
        "base",
        "base",
        _REVISION,
        _sha("1"),
        license_spdx,
        "APPROVED",
        "sdxl",
    )
    with pytest.raises(DomainError, match="license"):
        ModelRegistry((descriptor,)).require_production("base")


def _official_registry_inputs() -> tuple[
    tuple[CandidateModel, ...],
    tuple[WeightManifest, ...],
    tuple[LicenseApproval, ...],
]:
    candidates: list[CandidateModel] = []
    manifests: list[WeightManifest] = []
    approvals: list[LicenseApproval] = []
    for model_id, role, relative_root in (
        ("base", "base", "models/base"),
        ("ip", "ip_adapter", "models/ip"),
        ("cn", "controlnet", "models/cn"),
    ):
        payload = f"{model_id}-weights".encode()
        entrypoint = ModelLoadEntrypoint("diffusers_pretrained", "pipeline")
        if role == "ip_adapter":
            entrypoint = ModelLoadEntrypoint(
                "diffusers_ip_adapter", "pipeline", "model.safetensors"
            )
        files = [
            WeightFile(
                "pipeline/model.safetensors",
                len(payload),
                hash_bytes(payload),
            )
        ]
        if role == "ip_adapter":
            files.extend(
                (
                    WeightFile(
                        "pipeline/image_encoder/config.json",
                        2,
                        hash_bytes(b"{}"),
                    ),
                    WeightFile(
                        "pipeline/image_encoder/model.safetensors",
                        7,
                        hash_bytes(b"encoder"),
                    ),
                )
            )
        manifest = WeightManifest(
            model_id,
            role,
            _REVISION,
            relative_root,
            entrypoint,
            tuple(files),
            Sha256("0" * 64),
        ).with_computed_root()
        evidence_url = f"https://licenses.example/{model_id}"
        candidate = CandidateModel(
            model_id,
            role,
            "sdxl",
            _REVISION,
            manifest.root_sha256,
            "APPROVED",
            LicenseEvidence(
                "Apache-2.0",
                evidence_url,
                "allowed",
                "allowed",
                "allowed",
                "approved evidence",
            ),
            relative_root,
            "production component",
        )
        approval = LicenseApproval(
            model_id,
            _REVISION,
            manifest_sha256(manifest),
            "Apache-2.0",
            evidence_url,
        )
        candidates.append(candidate)
        manifests.append(manifest)
        approvals.append(approval)
    return tuple(candidates), tuple(manifests), tuple(approvals)


def test_official_approved_registry_binds_candidates_manifests_and_approvals() -> None:
    candidates, manifests, approvals = _official_registry_inputs()

    registry = approved_production_registry(candidates, manifests, approvals)

    assert (
        registry.require_production("base").expected_sha256 == manifests[0].root_sha256
    )
    assert registry.require_production("ip").role == "ip_adapter"


@pytest.mark.parametrize(
    "mismatch",
    [
        "relative_root",
        "root_digest",
        "license",
        "evidence",
        "approval_model",
        "approval_revision",
        "approval_digest",
        "duplicate_approval",
        "extra_approval",
        "manifest_canonical",
    ],
)
def test_official_registry_rejects_any_supply_binding_mismatch(mismatch: str) -> None:
    candidates, manifests, approvals = _official_registry_inputs()
    first_candidate = candidates[0]
    first_approval = approvals[0]
    if mismatch == "relative_root":
        candidates = (
            replace(first_candidate, weights_relpath="models/other"),
            *candidates[1:],
        )
    elif mismatch == "root_digest":
        candidates = (
            replace(first_candidate, expected_sha256=_sha("9")),
            *candidates[1:],
        )
    elif mismatch == "license":
        candidates = (
            replace(
                first_candidate, evidence=replace(first_candidate.evidence, spdx="MIT")
            ),
            *candidates[1:],
        )
    elif mismatch == "evidence":
        candidates = (
            replace(
                first_candidate,
                evidence=replace(
                    first_candidate.evidence,
                    license_url="https://licenses.example/different",
                ),
            ),
            *candidates[1:],
        )
    elif mismatch == "approval_model":
        approvals = (replace(first_approval, model_id="other"), *approvals[1:])
    elif mismatch == "approval_revision":
        approvals = (replace(first_approval, revision="c" * 40), *approvals[1:])
    elif mismatch == "approval_digest":
        approvals = (replace(first_approval, manifest_sha256=_sha("8")), *approvals[1:])
    elif mismatch == "duplicate_approval":
        approvals = (first_approval, first_approval, approvals[2])
    elif mismatch == "manifest_canonical":
        bad_manifest = replace(manifests[0], root_sha256=_sha("6"))
        manifests = (bad_manifest, *manifests[1:])
        candidates = (
            replace(first_candidate, expected_sha256=bad_manifest.root_sha256),
            *candidates[1:],
        )
        approvals = (
            replace(first_approval, manifest_sha256=manifest_sha256(bad_manifest)),
            *approvals[1:],
        )
    else:
        approvals = (
            *approvals,
            LicenseApproval(
                "extra",
                _REVISION,
                _sha("7"),
                "MIT",
                "https://licenses.example/extra",
            ),
        )

    with pytest.raises(DomainError):
        approved_production_registry(candidates, manifests, approvals)


def test_candidate_approved_status_without_independent_approvals_is_not_authorized() -> (
    None
):
    candidates, manifests, _approvals = _official_registry_inputs()

    with pytest.raises(DomainError, match="approval"):
        approved_production_registry(candidates, manifests, ())


def test_floating_revision_forbidden_in_candidates() -> None:
    from specstyle.generation.candidates import CandidateModel, LicenseEvidence

    with pytest.raises(DomainError, match="floating"):
        CandidateModel(
            "x",
            "base",
            "sdxl",
            "main",
            _sha("1"),
            "UNKNOWN",
            LicenseEvidence(
                "MIT",
                "https://example.com/lic",
                "allowed",
                "allowed",
                "allowed",
                "n",
            ),
            "x/main",
            "test",
        )


def test_resolve_weight_file_hash_and_mismatch(tmp_path: Path) -> None:
    payload = b"weight-bytes-v1"
    rel = "models/base.bin"
    path = tmp_path.joinpath(*rel.split("/"))
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    digest = hash_file(tmp_path, rel)
    desc = ModelDescriptor(
        "base1", "base", _REVISION, digest, "Apache-2.0", "APPROVED", "sdxl"
    )
    resolved = resolve_weight(tmp_path, desc, rel)
    assert resolved.kind == "legacy_single_file"
    assert resolved.content_sha256 == digest
    bad = ModelDescriptor(
        "base1", "base", _REVISION, _sha("9"), "Apache-2.0", "APPROVED", "sdxl"
    )
    with pytest.raises(InfrastructureError, match="hash mismatch"):
        resolve_weight(tmp_path, bad, rel)


def test_resolve_weight_directory_marker(tmp_path: Path) -> None:
    digest = hash_bytes(b"dir-marker")
    rel = "models/base-dir"
    d = tmp_path.joinpath(*rel.split("/"))
    d.mkdir(parents=True)
    (d / "WEIGHTS.sha256").write_text(digest.value + "\n", encoding="ascii")
    desc = ModelDescriptor(
        "base1", "base", _REVISION, digest, "Apache-2.0", "APPROVED", "sdxl"
    )
    with pytest.raises(InfrastructureError, match="directory marker.*disabled"):
        resolve_weight(tmp_path, desc, rel)


def test_resolve_weight_symlink_refused(tmp_path: Path) -> None:
    real = tmp_path / "real.bin"
    real.write_bytes(b"abc")
    link = tmp_path / "link.bin"
    link.symlink_to(real)
    desc = ModelDescriptor(
        "base1", "base", _REVISION, _sha("1"), "Apache-2.0", "APPROVED", "sdxl"
    )
    with pytest.raises(InfrastructureError, match="symlink"):
        resolve_weight(tmp_path, desc, "link.bin")


def test_legacy_plan_local_load_is_hard_disabled(tmp_path: Path) -> None:
    payload = b"w"
    paths = {}
    descs = []
    for mid, role, ch in (
        ("base1", "base", "1"),
        ("ip1", "ip_adapter", "2"),
        ("cn1", "controlnet", "3"),
    ):
        rel = f"{mid}.bin"
        p = tmp_path / rel
        p.write_bytes(payload + ch.encode())
        digest = hash_file(tmp_path, rel)
        descs.append(
            ModelDescriptor(
                mid, role, _REVISION, digest, "Apache-2.0", "APPROVED", "sdxl"
            )
        )
        paths[mid] = rel
    from specstyle.generation.model_registry import ModelRegistry

    reg = ModelRegistry(tuple(descs))
    graph = PipelineFactory(reg, tmp_path).build_production("base1", "ip1", "cn1")
    with pytest.raises(DomainError, match="legacy production loader disabled"):
        plan_local_load(graph, tmp_path, paths, require_gpu=True)


def test_legacy_plan_cannot_be_enabled_with_cpu_injection(tmp_path: Path) -> None:
    paths = {}
    descs = []
    for mid, role, ch in (
        ("base1", "base", "1"),
        ("ip1", "ip_adapter", "2"),
        ("cn1", "controlnet", "3"),
    ):
        rel = f"{mid}.bin"
        (tmp_path / rel).write_bytes(b"w" + ch.encode())
        digest = hash_file(tmp_path, rel)
        descs.append(
            ModelDescriptor(
                mid, role, _REVISION, digest, "Apache-2.0", "APPROVED", "sdxl"
            )
        )
        paths[mid] = rel
    from specstyle.generation.model_registry import ModelRegistry

    reg = ModelRegistry(tuple(descs))
    graph = PipelineFactory(reg, tmp_path).build_production("base1", "ip1", "cn1")
    with pytest.raises(DomainError, match="legacy production loader disabled"):
        plan_local_load(graph, tmp_path, paths, require_gpu=False)


def test_legacy_load_pipeline_is_disabled_before_builder_or_download_flags(
    tmp_path: Path,
) -> None:
    from specstyle.generation.diffusers_loader import LoadPlan
    from specstyle.generation.local_weights import ResolvedWeight
    from specstyle.generation.pipeline_factory import PipelineGraph
    from specstyle.generation.rocm_probe import RocmProbeResult

    desc = ModelDescriptor(
        "base1", "base", _REVISION, _sha("1"), "Apache-2.0", "APPROVED", "sdxl"
    )
    graph = PipelineGraph("production", desc, desc, desc, None, "cache")
    rw = ResolvedWeight("base1", tmp_path, _sha("1"), "file")
    plan = LoadPlan(
        graph,
        rw,
        rw,
        rw,
        None,
        RocmProbeResult(False, None, None, "x", "a" * 64),
    )
    called = False

    def builder(_graph, _weights):
        nonlocal called
        called = True
        return object()

    with pytest.raises(DomainError, match="legacy production loader disabled"):
        load_pipeline(plan, builder=builder, local_files_only=False)
    assert called is False
